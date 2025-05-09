from django.urls import path, include
from rest_framework_nested import routers # Используем вложенные роутеры для сообщений
from . import views

# Основной роутер для чатов
router = routers.DefaultRouter()
router.register(r'chats', views.ChatViewSet, basename='chat')

# Вложенный роутер для сообщений внутри чата
# URL будет /api/messaging/chats/{chat_pk}/messages/
chats_router = routers.NestedDefaultRouter(router, r'chats', lookup='chat')
chats_router.register(r'messages', views.MessageViewSet, basename='chat-messages')
chats_router.register(r'media', views.ChatMediaViewSet, basename='chat-media')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(chats_router.urls)), # Включаем вложенный роутер
]