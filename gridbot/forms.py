from django import forms
from .models import BotConfig

class BotConfigForm(forms.ModelForm):
    class Meta:
        model = BotConfig
        fields = ["qty","avg","grid_step","levels_up","levels_down","stop_from_avg","interval","telegram_enabled"]
        widgets = {
            "qty": forms.NumberInput(attrs={"step":"0.0001"}),
            "avg": forms.NumberInput(attrs={"step":"0.0001"}),
            "grid_step": forms.NumberInput(attrs={"step":"0.1"}),
            "stop_from_avg": forms.NumberInput(attrs={"step":"0.1"}),
            "interval": forms.NumberInput(attrs={"min":"5"}),
        }
