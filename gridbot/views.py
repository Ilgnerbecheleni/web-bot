import random, time, requests
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages
from django.core.cache import cache
from django.conf import settings

from .models import BotConfig, BotState, BotSignal
from .forms import BotConfigForm

def ping(request): 
    return HttpResponse("pong gridbot")

def dashboard(request):
    cfg = BotConfig.objects.order_by("-id").first() or BotConfig.objects.create()
    state, _ = BotState.objects.get_or_create(pk=1)

    if request.method == "POST" and "save_config" in request.POST:
        form = BotConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuração salva.")
            return redirect("dashboard")
    else:
        form = BotConfigForm(instance=cfg)

    return render(request, "gridbot/dashboard.html", {
        "form": form,
        "state": state,
        # sem threads no web: status é o que o processo runbot gravar
        "is_running": bool(state.running),
        "service_mode": True,  # para o template mostrar aviso "rodando via Supervisor"
    })

# --- Telegram teste ---
def _send_telegram(text: str):
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes do .env")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
    r.raise_for_status()
    return r.json()

@require_POST
def test_telegram(request):
    try:
        _send_telegram("🔔 Teste OK do painel POL Grid+Stop.")
        messages.success(request, "Mensagem de teste enviada ao Telegram.")
    except Exception as e:
        messages.error(request, f"Falha no teste do Telegram: {e}")
    return redirect("dashboard")

# --- APIs para painel ---
def state_json(request):
    st, _ = BotState.objects.get_or_create(pk=1)
    return JsonResponse({
        "running": st.running,
        "ref_price": st.ref_price,
        "trailing_high": st.trailing_high,
        "last_level_idx": st.last_level_idx,
        "last_kind": st.last_kind,
        "last_message": st.last_message,
        "last_price": st.last_price,
        "last_pnl_pct": st.last_pnl_pct,
        "atr": st.atr,
        "eff_grid_step": st.eff_grid_step,
        "atr_trailing_stop": st.atr_trailing_stop,
    })

def signals_json(request):
    qs = BotSignal.objects.order_by("-id")[:20]
    data = [{
        "t": s.created_at.strftime("%H:%M:%S"),
        "kind": s.kind,
        "message": s.message,
        "price": s.price,
        "pnl_pct": s.pnl_pct,
    } for s in qs]
    return JsonResponse(data, safe=False)

# --- Proxy de klines (evita bloqueios/CORS) ---
BINANCE_HOSTS = ["https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com"]
ALLOWED_SYMBOLS = {"POLUSDT"}
ALLOWED_INTERVALS = {"1m","5m","15m","1h"}

@require_GET
def klines_proxy(request):
    symbol = (request.GET.get("symbol") or "POLUSDT").upper()
    interval = request.GET.get("interval","1m")
    try:
        limit = max(1, min(int(request.GET.get("limit","200")), 500))
    except ValueError:
        return HttpResponseBadRequest("limit inválido")

    if symbol not in ALLOWED_SYMBOLS or interval not in ALLOWED_INTERVALS:
        return HttpResponseBadRequest("parâmetros não permitidos")

    ck = f"kl_{symbol}_{interval}_{limit}"
    if (cached := cache.get(ck)):
        return JsonResponse(cached, safe=False)

    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f"{host}/api/v3/klines",
                             params={"symbol": symbol, "interval": interval, "limit": limit},
                             timeout=8, headers={"User-Agent": "polgrid-bot/1.0"})
            r.raise_for_status()
            data = [{"t": k[0], "close": float(k[4])} for k in r.json()]
            cache.set(ck, data, 8)
            return JsonResponse(data, safe=False)
        except Exception:
            continue

    # fallback offline simples
    rows = []
    base = 0.25
    t0 = int(time.time() - limit*60) * 1000
    price = base
    for i in range(limit):
        price += random.uniform(-0.002, 0.002)
        rows.append({"t": t0 + i*60_000, "close": round(max(price, 0.01), 6)})
    return JsonResponse(rows, safe=False)
