from django.db import models

class BotConfig(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    qty = models.FloatField(default=0.0)
    avg = models.FloatField(default=0.0)
    grid_step = models.FloatField(default=0.6)
    levels_up = models.IntegerField(default=8)
    levels_down = models.IntegerField(default=8)
    stop_from_avg = models.FloatField(default=8.0)
    interval = models.IntegerField(default=15)
    telegram_enabled = models.BooleanField(default=True)

    # ATR (se você já adicionou antes, mantenha)
    use_atr = models.BooleanField(default=True)
    atr_len = models.IntegerField(default=14)
    atr_k_grid = models.FloatField(default=0.60)
    atr_n_stop = models.FloatField(default=3.0)
    atr_refresh_sec = models.IntegerField(default=30)
    atr_interval = models.CharField(default="1m", max_length=8)

    def __str__(self): return f"Config #{self.pk} (qty={self.qty}, avg={self.avg})"


class BotState(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    running = models.BooleanField(default=False)
    ref_price = models.FloatField(null=True, blank=True)
    trailing_high = models.FloatField(null=True, blank=True)
    last_level_idx = models.IntegerField(null=True, blank=True)

    last_kind = models.CharField(max_length=32, null=True, blank=True)
    last_message = models.TextField(null=True, blank=True)
    last_price = models.FloatField(null=True, blank=True)
    last_pnl_pct = models.FloatField(null=True, blank=True)

    atr = models.FloatField(null=True, blank=True)
    eff_grid_step = models.FloatField(null=True, blank=True)
    atr_trailing_stop = models.FloatField(null=True, blank=True)

    def __str__(self): return f"State running={self.running}"


class BotSignal(models.Model):  # <<< ESTA É A CLASSE QUE FALTAVA
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=32)      # "grid" | "stop" | "ddX" | "startup"
    message = models.TextField()
    price = models.FloatField(null=True, blank=True)
    pnl_pct = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"[{self.created_at:%H:%M:%S}] {self.kind}"
