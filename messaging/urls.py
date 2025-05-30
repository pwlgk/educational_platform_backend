from django.urls import path, include
from rest_framework_nested import routers # Импорт для вложенных роутеров
from . import views

# Создается основной экземпляр DefaultRouter из Django REST framework.
# Этот роутер будет управлять URL-адресами для объектов Chat.
# - router.register(r'chats', views.ChatViewSet, basename='chat'):
#   Регистрирует ChatViewSet с префиксом 'chats'. Это означает, что URL-адреса
#   для операций с чатами (например, список чатов, создание, получение деталей чата)
#   будут доступны по путям, начинающимся с 'chats/' (относительно главного префикса
#   приложения, например, /api/messaging/chats/).
#   'basename' используется для генерации имен URL-паттернов.
router = routers.DefaultRouter()
router.register(r'chats', views.ChatViewSet, basename='chat')

# Создается вложенный роутер NestedDefaultRouter из библиотеки rest_framework_nested.
# Этот роутер предназначен для управления URL-адресами, связанными с ресурсами,
# вложенными в чаты, такими как сообщения и медиафайлы.
# - chats_router = routers.NestedDefaultRouter(router, r'chats', lookup='chat'):
#   Инициализирует вложенный роутер.
#   - router: Родительский роутер (определенный выше).
#   - r'chats': Префикс URL родительского ресурса, к которому привязывается вложенный роутер.
#   - lookup='chat': Имя параметра в URL, который будет использоваться для идентификации
#     конкретного экземпляра родительского ресурса (Chat). Например, в URL
#     /api/messaging/chats/{chat_pk}/... , 'chat_pk' будет этим lookup-параметром.
#
# - chats_router.register(r'messages', views.MessageViewSet, basename='chat-messages'):
#   Регистрирует MessageViewSet внутри вложенного роутера с префиксом 'messages'.
#   URL-адреса для сообщений конкретного чата будут иметь вид:
#   /api/messaging/chats/{chat_pk}/messages/.
#
# - chats_router.register(r'media', views.ChatMediaViewSet, basename='chat-media'):
#   Регистрирует ChatMediaViewSet внутри вложенного роутера с префиксом 'media'.
#   URL-адреса для медиафайлов конкретного чата будут иметь вид:
#   /api/messaging/chats/{chat_pk}/media/.
chats_router = routers.NestedDefaultRouter(router, r'chats', lookup='chat')
chats_router.register(r'messages', views.MessageViewSet, basename='chat-messages')
chats_router.register(r'media', views.ChatMediaViewSet, basename='chat-media')

# Список urlpatterns определяет основные URL-маршруты для модуля 'messaging'.
# Префикс для всех этих маршрутов (например, '/api/messaging/') обычно задается
# в корневом файле urls.py проекта при включении данного urlpatterns.
urlpatterns = [
    # Включает URL-адреса, сгенерированные основным роутером 'router' (для 'chats').
    path('', include(router.urls)),
    # Включает URL-адреса, сгенерированные вложенным роутером 'chats_router'
    # (для 'messages' и 'media' внутри конкретного чата).
    path('', include(chats_router.urls)),
]