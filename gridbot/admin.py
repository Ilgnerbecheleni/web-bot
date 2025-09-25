from django.contrib import admin
from .models import BotConfig, BotState

@admin.register(BotConfig)
class BotConfigAdmin(admin.ModelAdmin):
    list_display = ("id","qty","avg","grid_step","levels_up","levels_down","stop_from_avg","interval","telegram_enabled","created_at")

@admin.register(BotState)
class BotStateAdmin(admin.ModelAdmin):
    list_display = ("id","running","ref_price","trailing_high","last_level_idx","updated_at")
