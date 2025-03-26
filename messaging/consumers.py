import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.contenttypes.models import ContentType
from .models import Chat, Message, ChatParticipant
from .serializers import MessageSerializer
from users.models import User # Для асинхронного получения пользователя

class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_id = None
        self.chat_group_name = None
        self.user = None

    async def connect(self):
        self.user = self.scope.get("user") # Получаем user из Auth Middleware (JWT или Session)

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001) # Или другой код для неавторизованных
            return

        # Получаем ID чата из URL
        self.chat_id = self.scope['url_route']['kwargs'].get('chat_id')
        if not self.chat_id:
             await self.close(code=4000) # Не указан ID чата
             return

        # Проверяем, имеет ли пользователь доступ к этому чату (асинхронно)
        has_access = await self.check_chat_access()
        if not has_access:
            await self.close(code=4003) # Доступ запрещен
            return

        # Имя группы Channels для данного чата
        self.chat_group_name = f'chat_{self.chat_id}'

        # Присоединяемся к группе чата
        await self.channel_layer.group_add(
            self.chat_group_name,
            self.channel_name
        )

        await self.accept()
        print(f"User {self.user.id} connected to chat {self.chat_id}")

        # Опционально: отправить предыдущие сообщения или статус подключения

    async def disconnect(self, close_code):
        print(f"User {self.user.id} disconnected from chat {self.chat_id}, code: {close_code}")
        # Покидаем группу чата
        if self.chat_group_name:
            await self.channel_layer.group_discard(
                self.chat_group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        """Прием сообщения от WebSocket клиента."""
        if not self.user or not self.user.is_authenticated:
             return # Игнорируем сообщения от неавторизованных

        try:
            data = json.loads(text_data)
            message_content = data.get('message')
            # TODO: Обработка загрузки файлов через WebSocket (сложнее)

            if not message_content:
                await self.send_error("Сообщение не может быть пустым.")
                return

            # Сохраняем сообщение в БД (асинхронно)
            message_instance = await self.save_message(message_content)
            if not message_instance:
                 await self.send_error("Не удалось сохранить сообщение.")
                 return

            # Сериализуем сообщение для отправки клиентам
            serializer = MessageSerializer(message_instance) # Контекст request здесь не нужен
            message_data = serializer.data

            # Отправляем сообщение всем в группе чата
            await self.channel_layer.group_send(
                self.chat_group_name,
                {
                    'type': 'chat_message', # Имя метода-обработчика
                    'message': message_data,
                    'sender_channel_name': self.channel_name # Чтобы не отправлять себе же (опционально)
                }
            )

        except json.JSONDecodeError:
            await self.send_error("Неверный формат JSON.")
        except Exception as e:
             print(f"Error processing message in chat {self.chat_id}: {e}")
             await self.send_error(f"Ошибка обработки сообщения: {e}")


    async def chat_message(self, event):
        """Отправка сообщения клиенту WebSocket."""
        message = event['message']
        # sender_channel = event.get('sender_channel_name')

        # # Не отправляем сообщение обратно отправителю (если необходимо)
        # if self.channel_name != sender_channel:
        await self.send(text_data=json.dumps({
             'type': 'message',
             'payload': message
        }))

    async def send_error(self, message):
         """Отправка ошибки клиенту."""
         await self.send(text_data=json.dumps({
             'type': 'error',
             'payload': {'message': message}
         }))

    # --- Вспомогательные асинхронные методы ---
    @database_sync_to_async
    def check_chat_access(self):
        """Проверяет, является ли пользователь участником чата."""
        try:
             # Проверяем участие через ChatParticipant или ManyToMany
             return Chat.objects.filter(pk=self.chat_id, participants=self.user).exists()
        except Exception as e:
             print(f"Error checking chat access for user {self.user.id} and chat {self.chat_id}: {e}")
             return False

    @database_sync_to_async
    def save_message(self, content, file=None):
        """Сохраняет сообщение в БД."""
        try:
            chat = Chat.objects.get(pk=self.chat_id)
            # Убедимся еще раз, что отправитель - участник
            if not chat.participants.filter(pk=self.user.pk).exists():
                 print(f"Attempt to save message from non-participant user {self.user.id} in chat {self.chat_id}")
                 return None # Не сохраняем

            message = Message.objects.create(
                chat=chat,
                sender=self.user,
                content=content
                # file=file # Добавить обработку файла, если нужно
            )
            return message
        except Chat.DoesNotExist:
             print(f"Chat {self.chat_id} not found for saving message.")
             return None
        except Exception as e:
             print(f"Error saving message for user {self.user.id} in chat {self.chat_id}: {e}")
             return None