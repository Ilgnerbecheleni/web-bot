from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ping/", views.ping, name="ping"),
    path("test-telegram/", views.test_telegram, name="test_telegram"),
    # APIs
    path("api/state/", views.state_json, name="state_json"),
    path("api/signals/", views.signals_json, name="signals_json"),
    path("api/klines/", views.klines_proxy, name="klines_proxy"),
]
