from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ping/", views.ping, name="ping"),
    path("start/", views.start_bot, name="start_bot"),
    path("stop/", views.stop_bot, name="stop_bot"),
    # APIs
    path("api/state/", views.state_json, name="state_json"),
    path("api/signals/", views.signals_json, name="signals_json"),
    path("api/klines/", views.klines_proxy, name="klines_proxy"),
]
