from django.urls import re_path
from . import consumers

# Список websocket_urlpatterns определяет маршрутизацию для WebSocket-соединений,
# связанных с системой уведомлений, с использованием Django Channels.
# Каждый элемент списка сопоставляет URL-шаблон с соответствующим консьюмером,
# который будет обрабатывать WebSocket-соединения.
#
# В данном случае, определен один маршрут:
# - re_path(r'ws/notifications/$', consumers.NotificationConsumer.as_asgi()):
#   Этот маршрут связывает URL-шаблон 'ws/notifications/' с NotificationConsumer.
#   - r'ws/notifications/$': Регулярное выражение для URL.
#     - 'ws/notifications/': Префикс URL, указывающий на WebSocket-соединение
#       для получения уведомлений.
#     - '$': Означает конец строки, гарантируя, что URL точно соответствует шаблону.
#   - consumers.NotificationConsumer.as_asgi(): Указывает, что NotificationConsumer
#     будет обрабатывать WebSocket-соединения для данного маршрута. Метод .as_asgi()
#     преобразует класс консьюмера в ASGI-совместимое приложение.
#
# Когда клиент устанавливает WebSocket-соединение по адресу, соответствующему
# 'ws/notifications/', это соединение будет передано на обработку экземпляру
# NotificationConsumer.
websocket_urlpatterns = [
    re_path(r'ws/notifications/$', consumers.NotificationConsumer.as_asgi()),
]