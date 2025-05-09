# notifications/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async # Если нужны запросы к БД
from users.models import User # Для типизации

class NotificationConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user: User | None = None # Типизация
        self.user_group_name: str | None = None

    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Личная группа пользователя
        self.user_group_name = f'user_{self.user.id}'

        # Присоединяемся к группе
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        await self.accept()
        print(f"Notification WS connected for user {self.user.id} (group: {self.user_group_name})")

        # Опционально: Отправить начальное состояние (например, кол-во непрочитанных)
        # initial_unread_count = await self.get_total_unread_count()
        # await self.send(text_data=json.dumps({
        #     'type': 'unread_count_update',
        #     'total_unread': initial_unread_count
        # }))

    async def disconnect(self, close_code):
        print(f"Notification WS disconnected for user {self.user.id}, code: {close_code}")
        if self.user_group_name:
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        """ Принимает сообщения от клиента (если нужно). Пока не используется. """
        # Можно использовать для команд типа "pong" для heartbeat
        pass

    # --- МЕТОДЫ-ОБРАБОТЧИКИ ДЛЯ group_send ---

    async def new_notification(self, event):
        """ Отправляет новое уведомление (из модели Notification) клиенту. """
        notification_data = event.get('notification')
        if notification_data:
            await self.send(text_data=json.dumps({
                'type': 'new_notification', # Этот тип ловит фронтенд
                'notification': notification_data # Сериализованные данные уведомления
            }))

    async def chat_unread_update(self, event):
        """ Отправляет обновление счетчика непрочитанных для КОНКРЕТНОГО чата. """
        chat_id = event.get('chat_id')
        unread_count = event.get('unread_count')
        if chat_id is not None and unread_count is not None:
            await self.send(text_data=json.dumps({
                'type': 'chat.unread_update', # Этот тип ловит фронтенд (и notifications, и messaging store)
                'chat_id': chat_id,
                'unread_count': unread_count
            }))

    async def total_unread_update(self, event):
         """ Отправляет ОБЩЕЕ количество непрочитанных уведомлений. """
         # Этот метод может вызываться, например, после mark_all_as_read
         total_unread = event.get('total_unread')
         if total_unread is not None:
             await self.send(text_data=json.dumps({
                 'type': 'unread_count_update', # Этот тип ловит фронтенд
                 'total_unread': total_unread
             }))

    # --- Вспомогательные методы (пример) ---
    # @database_sync_to_async
    # def get_total_unread_count(self):
    #     """ Асинхронно получает общее количество непрочитанных уведомлений для пользователя. """
    #     if self.user:
    #         # Ваша логика подсчета непрочитанных уведомлений из модели Notification
    #         # return Notification.objects.filter(recipient=self.user, is_read=False).count()
    #         return 0 # Заглушка
    #     return 0