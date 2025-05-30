from django.urls import re_path
from . import consumers

# Список websocket_urlpatterns определяет маршрутизацию для WebSocket-соединений
# в приложении Django Channels. Каждый элемент списка сопоставляет URL-шаблон
# с соответствующим консьюмером (consumer), который будет обрабатывать
# WebSocket-соединения, установленные по этому URL.
#
# В данном случае, определен один маршрут:
# - re_path(r'ws/chat/(?P<chat_id>\d+)/$', consumers.ChatConsumer.as_asgi()):
#   Этот маршрут связывает URL-шаблоны, начинающиеся с 'ws/chat/',
#   за которыми следует числовой идентификатор чата (chat_id), с ChatConsumer.
#   - r'ws/chat/(?P<chat_id>\d+)/$': Регулярное выражение для URL.
#     - 'ws/chat/': Префикс URL для WebSocket-соединений чата.
#     - '(?P<chat_id>\d+)': Именованная группа захвата 'chat_id', которая соответствует
#       одному или нескольким цифровым символам. Этот chat_id будет доступен
#       в консьюмере через self.scope['url_route']['kwargs']['chat_id'].
#     - '/': Завершающий слеш.
#     - '$': Означает конец строки, гарантируя, что URL точно соответствует шаблону.
#   - consumers.ChatConsumer.as_asgi(): Указывает, что ChatConsumer будет
#     обрабатывать WebSocket-соединения для данного маршрута. Метод .as_asgi()
#     преобразует класс консьюмера в ASGI-совместимое приложение.
websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<chat_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
]