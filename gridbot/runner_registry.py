from typing import Optional
from .models import BotConfig, BotState
from .bot_runner import GridBotThread

class BotRegistry:
    _thread: Optional[GridBotThread] = None

    @classmethod
    def start(cls):
        if cls._thread and cls._thread.is_alive():
            return False
        cfg = BotConfig.objects.order_by("-id").first() or BotConfig.objects.create()
        state, _ = BotState.objects.get_or_create(pk=1)
        t = GridBotThread(cfg, state)
        t.start()
        cls._thread = t
        return True

    @classmethod
    def stop(cls):
        if cls._thread and cls._thread.is_alive():
            cls._thread.stop()
            cls._thread.join(timeout=5)
            cls._thread = None
            return True
        return False

    @classmethod
    def running(cls):
        return bool(cls._thread and cls._thread.is_alive())
