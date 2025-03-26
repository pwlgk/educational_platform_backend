import json
from channels.generic.websocket import AsyncWebsocketConsumer

class NotificationConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.user_group_name = None

    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Каждый пользователь присоединяется к своей личной группе
        self.user_group_name = f'user_{self.user.id}'

        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        await self.accept()
        print(f"Notification WS connected for user {self.user.id}")

    async def disconnect(self, close_code):
        print(f"Notification WS disconnected for user {self.user.id}, code: {close_code}")
        if self.user_group_name:
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        # Этот консьюмер только отправляет, но можно добавить логику
        # для получения команд от клиента (например, "mark_read")
        pass

    # Метод для обработки сообщений из channel layer (вызывается из send_notification)
    async def notify(self, event):
        """Отправляет уведомление клиенту."""
        payload = event.get('payload')
        if payload:
            await self.send(text_data=json.dumps({
                'type': 'notification', # Тип сообщения для клиента
                'payload': payload
            }))