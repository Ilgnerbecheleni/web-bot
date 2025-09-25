import os, time, json, threading, requests
from datetime import datetime, timezone
from django.conf import settings
from django.db import close_old_connections
from .models import BotSignal, BotState, BotConfig

BINANCE_HOSTS = ["https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com"]
DEFAULT_SYMBOL = "POLUSDT"
STATE_JSON = os.path.join(os.path.dirname(__file__), "grid_state.json")

def now_iso():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

def human(v):
    return f"{v:,.6f}".replace(",", "X").replace(".", ",").replace("X", ".")

def pct(a, b):
    if b == 0: return 0.0
    return (a - b) / b * 100.0

def tg_send(text):
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        print(f"[{now_iso()}] (SEM TELEGRAM) {text}")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"[{now_iso()}] Telegram falhou: {e}")

def get_price(symbol=DEFAULT_SYMBOL):
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f"{host}/api/v3/ticker/price", params={"symbol": symbol}, timeout=8)
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception:
            continue
    raise RuntimeError("Falha ao obter preço (rede bloqueada?)")

def get_klines(symbol=DEFAULT_SYMBOL, interval="1m", limit=300):
    limit = max(5, min(limit, 1000))
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f"{host}/api/v3/klines",
                             params={"symbol": symbol, "interval": interval, "limit": limit},
                             timeout=8)
            r.raise_for_status()
            data = r.json()
            return [{"t": k[0], "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])} for k in data]
        except Exception:
            continue
    raise RuntimeError("Falha ao obter klines (rede bloqueada?)")

def calc_atr(ohlc, length=14):
    # ATR clássico: TR com SMA inicial e depois EMA(TR)
    if len(ohlc) < length + 2:
        return None
    tr_list = []
    prev_close = ohlc[0]["c"]
    for i in range(1, len(ohlc)):
        h = ohlc[i]["h"]; l = ohlc[i]["l"]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        tr_list.append(tr)
        prev_close = ohlc[i]["c"]
    if len(tr_list) < length:
        return None
    sma0 = sum(tr_list[:length]) / length
    k = 2 / (length + 1)
    atr_val = sma0
    for tr in tr_list[length:]:
        atr_val = tr * k + atr_val * (1 - k)
    return atr_val

def build_grid(ref_price, step_pct, up, down):
    levels = [ref_price * (1 + (i * step_pct / 100.0)) for i in range(-down, up + 1)]
    levels.sort()
    def idx_for(price):
        for i in range(len(levels)-1):
            if levels[i] <= price < levels[i+1]:
                return i
        return max(0, len(levels)-2)
    return levels, idx_for

class GridBotThread(threading.Thread):
    def __init__(self, cfg: BotConfig, state_model: BotState):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.state_model = state_model
        self._stop_evt = threading.Event()
        self.cooldowns = {}
        self.eff_grid_step = None
        self.atr_value = None
        self.atr_next_ts = 0
        self.atr_trailing_stop = None
        self.levels = None
        self.idx_for = None

    def stop(self): self._stop_evt.set()
    def stopped(self): return self._stop_evt.is_set()

    def maybe_alert(self, key, msg, cooldown=120):
        now = time.time()
        last = self.cooldowns.get(key, 0)
        if now - last >= cooldown and self.cfg.telegram_enabled:
            tg_send(msg)
            self.cooldowns[key] = now

    def _post_signal(self, kind, msg, price=None, pnl_pct=None):
        try:
            close_old_connections()
            BotSignal.objects.create(kind=kind, message=msg, price=price, pnl_pct=pnl_pct)
            type(self.state_model).objects.filter(pk=self.state_model.pk).update(
                last_kind=kind, last_message=msg, last_price=price, last_pnl_pct=pnl_pct
            )
        except Exception as e:
            print(f"[{now_iso()}] Falha ao salvar sinal: {e}")

    def _rebuild_grid(self, ref_price):
        self.levels, self.idx_for = build_grid(ref_price, self.eff_grid_step, self.cfg.levels_up, self.cfg.levels_down)

    def _update_atr_and_effective_params(self, price, trailing_high):
        # Sem ATR → usa step fixo
        if not self.cfg.use_atr:
            self.atr_value = None
            self.eff_grid_step = self.cfg.grid_step
            self.atr_trailing_stop = None
            return

        # Refresh por janela
        now = time.time()
        if now < self.atr_next_ts and self.atr_value is not None and self.eff_grid_step is not None:
            return
        try:
            ohlc = get_klines(DEFAULT_SYMBOL, self.cfg.atr_interval, limit=max(100, self.cfg.atr_len + 30))
            atr = calc_atr(ohlc, self.cfg.atr_len)
            if atr:
                self.atr_value = atr
                eff = self.cfg.atr_k_grid * (atr / price) * 100.0   # %
                eff = max(0.15, min(eff, 2.5))                      # clamp
                self.eff_grid_step = eff
                self.atr_trailing_stop = trailing_high - self.cfg.atr_n_stop * atr
            else:
                self.eff_grid_step = self.cfg.grid_step
                self.atr_trailing_stop = None
        except Exception as e:
            print(f"[{now_iso()}] ATR falhou: {e}")
            self.eff_grid_step = self.cfg.grid_step
            self.atr_trailing_stop = None

        self.atr_next_ts = now + max(10, self.cfg.atr_refresh_sec)

        # grava diagnóstico
        try:
            close_old_connections()
            type(self.state_model).objects.filter(pk=self.state_model.pk).update(
                atr=self.atr_value, eff_grid_step=self.eff_grid_step, atr_trailing_stop=self.atr_trailing_stop
            )
        except Exception:
            pass

    def run(self):
        close_old_connections()

        # estado leve
        try:
            j = json.load(open(STATE_JSON,"r",encoding="utf-8")) if os.path.exists(STATE_JSON) else {}
        except Exception:
            j = {}

        # preço inicial
        try:
            price = get_price()
        except Exception as e:
            print(f"[{now_iso()}] Falha preço inicial: {e}")
            return

        ref = j.get("ref_price") or price
        trailing_high = j.get("trailing_high", ref)

        # ATR / step efetivo / grade
        self._update_atr_and_effective_params(price, trailing_high)
        if self.eff_grid_step is None:
            self.eff_grid_step = self.cfg.grid_step
        self._rebuild_grid(ref)
        last_idx = j.get("last_level_idx", self.idx_for(price))

        # stop por PM e por ATR
        stop_pm = self.cfg.avg * (1 - self.cfg.stop_from_avg/100.0)
        stop_line = max(stop_pm, self.atr_trailing_stop) if self.atr_trailing_stop is not None else stop_pm

        # state inicial
        close_old_connections()
        type(self.state_model).objects.filter(pk=self.state_model.pk).update(
            running=True, ref_price=ref, trailing_high=trailing_high, last_level_idx=last_idx,
            atr=self.atr_value, eff_grid_step=self.eff_grid_step, atr_trailing_stop=self.atr_trailing_stop
        )

        # startup
        txt_start = (
            f"PM {human(self.cfg.avg)} | Qtd {self.cfg.qty}\n"
            f"Ref {human(ref)} | Grade efetiva @ {self.eff_grid_step:.2f}% (modo {'ATR' if self.cfg.use_atr else 'fixo'})\n"
        )
        if self.cfg.use_atr and self.atr_value:
            txt_start += f"ATR({self.cfg.atr_len},{self.cfg.atr_interval}) ~ {human(self.atr_value)} | Stop ATR≈ {human(self.atr_trailing_stop)}\n"
        txt_start += f"Stop mínimo por PM ({self.cfg.stop_from_avg:.1f}%): {human(stop_pm)}"
        self.maybe_alert("startup", f"🚀 GRID+STOP ON (POLUSDT)\n{txt_start}", cooldown=3)
        self._post_signal("startup", txt_start)

        # loop
        while not self.stopped():
            try:
                close_old_connections()

                price = get_price()
                if price > trailing_high:
                    trailing_high = price

                # ATR update por janela + trail stop
                self._update_atr_and_effective_params(price, trailing_high)
                stop_pm = self.cfg.avg * (1 - self.cfg.stop_from_avg/100.0)
                if self.atr_trailing_stop is not None and self.atr_value is not None:
                    self.atr_trailing_stop = trailing_high - self.cfg.atr_n_stop * self.atr_value
                    stop_line = max(stop_pm, self.atr_trailing_stop)
                else:
                    stop_line = stop_pm

                pnl_pct = pct(price, self.cfg.avg)
                pnl_val = (price - self.cfg.avg) * self.cfg.qty

                # STOP
                if price <= stop_line:
                    txt = (f"🛑 STOP! {human(price)} <= {human(stop_line)} "
                           f"(PM {human(self.cfg.avg)} | {pnl_pct:.2f}% | ~{human(pnl_val)} USDT).")
                    self.maybe_alert("stop", txt)
                    self._post_signal("stop", txt, price=price, pnl_pct=pnl_pct)

                # GRID cross
                idx = self.idx_for(price)
                if idx != last_idx:
                    lower, upper = self.levels[idx], self.levels[idx+1]
                    direction = "⬆️" if idx > last_idx else "⬇️"
                    sug = "venda parcial" if idx > last_idx else "compra parcial"
                    txt = (f"📊 {direction} Cruzou nível @ step {self.eff_grid_step:.2f}%\n"
                           f"Faixa {human(lower)} – {human(upper)}\n"
                           f"Preço {human(price)} | PM {human(self.cfg.avg)} | PnL {pnl_pct:.2f}%\n"
                           f"Sugestão: {sug}.")
                    self.maybe_alert("grid", txt)
                    self._post_signal("grid", txt, price=price, pnl_pct=pnl_pct)
                    last_idx = idx

                # persistência leve
                j.update({"ref_price": ref, "last_level_idx": last_idx, "trailing_high": trailing_high})
                with open(STATE_JSON,"w",encoding="utf-8") as f:
                    json.dump(j, f, ensure_ascii=False, indent=2)

                # atualizar DB state
                close_old_connections()
                type(self.state_model).objects.filter(pk=self.state_model.pk).update(
                    ref_price=ref, trailing_high=trailing_high, last_level_idx=last_idx,
                    atr=self.atr_value, eff_grid_step=self.eff_grid_step, atr_trailing_stop=stop_line
                )

            except Exception as e:
                print(f"[{now_iso()}] Loop erro: {e}")

            time.sleep(self.cfg.interval)

        close_old_connections()
        type(self.state_model).objects.filter(pk=self.state_model.pk).update(running=False)
