from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Маршрут для подключения к WebSocket мониторинга
    re_path(r'ws/monitor/$', consumers.MonitorConsumer.as_asgi()),
]