# messaging/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.contenttypes.models import ContentType
from .models import Chat, Message, ChatParticipant
# Используем сериализатор, чтобы получить готовые данные для отправки
from .serializers import MessageSerializer, LimitedUserSerializer
from users.models import User # Для асинхронного получения пользователя

class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_id = None
        self.chat_group_name = None
        self.user: User | None = None # Явно типизируем

    async def connect(self):
        self.user = self.scope.get("user")

        # --- Проверка аутентификации ---
        if not self.user or not self.user.is_authenticated:
            print("WS Connect REJECTED: User not authenticated.")
            await self.close(code=4001)
            return

        # --- Получение и проверка chat_id ---
        self.chat_id = self.scope['url_route']['kwargs'].get('chat_id')
        if not self.chat_id:
             print("WS Connect REJECTED: chat_id missing in URL.")
             await self.close(code=4000)
             return
        # Пробуем преобразовать в int для проверки
        try:
            chat_pk = int(self.chat_id)
        except ValueError:
             print(f"WS Connect REJECTED: Invalid chat_id format: {self.chat_id}")
             await self.close(code=4000)
             return

        # --- Проверка доступа к чату (асинхронно) ---
        has_access = await self.check_chat_access(chat_pk)
        if not has_access:
            print(f"WS Connect REJECTED: User {self.user.id} has no access to chat {chat_pk}")
            await self.close(code=4003)
            return

        # --- Присоединение к группе ---
        self.chat_group_name = f'chat_{self.chat_id}'
        await self.channel_layer.group_add(
            self.chat_group_name,
            self.channel_name
        )

        # --- Принимаем соединение ---
        await self.accept()
        print(f"WS Connect ACCEPTED: User {self.user.id} connected to chat {self.chat_id} (channel: {self.channel_name})")

        # --- Опционально: Отправка события "пользователь онлайн" другим участникам ---
        # user_serializer = LimitedUserSerializer(self.user) # Используем урезанный
        # await self.channel_layer.group_send(
        #     self.chat_group_name,
        #     {
        #         "type": "chat.user_status",
        #         "user": user_serializer.data,
        #         "status": "online",
        #         "sender_channel_name": self.channel_name # Исключаем себя
        #     }
        # )

    async def disconnect(self, close_code):
        print(f"WS Disconnect: User {self.user.id if self.user else 'Unknown'} from chat {self.chat_id}, code: {close_code}")
        # --- Опционально: Отправка события "пользователь оффлайн" ---
        # if self.user and self.chat_group_name:
        #     user_serializer = LimitedUserSerializer(self.user)
        #     await self.channel_layer.group_send(
        #         self.chat_group_name,
        #         {
        #             "type": "chat.user_status",
        #             "user": user_serializer.data,
        #             "status": "offline",
        #             "sender_channel_name": self.channel_name
        #         }
        #     )

        # Покидаем группу чата
        if self.chat_group_name:
            await self.channel_layer.group_discard(
                self.chat_group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        """ Прием сообщения от клиента (для событий typing и, возможно, read). """
        if not self.user or not self.user.is_authenticated: return

        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            print(f"[WS Receive] Chat {self.chat_id}, User {self.user.id}: Received type '{message_type}' data: {data}")

            if message_type == 'typing':
                is_typing = data.get('is_typing', False)
                # Рассылаем событие "typing" всем остальным в группе
                user_serializer = LimitedUserSerializer(self.user) # Отправляем базовую инфу
                await self.channel_layer.group_send(
                    self.chat_group_name,
                    {
                        "type": "chat.typing", # Метод-обработчик ниже
                        "user_id": self.user.id,
                        "user_name": user_serializer.data.get('first_name', self.user.get_username()), # Используем имя или username/email
                        "is_typing": is_typing,
                        "sender_channel_name": self.channel_name # Исключаем себя
                    }
                )
            # elif message_type == 'mark_read':
                # Обработка отметки прочтения через WS (если нужно)
                # message_id = data.get('message_id')
                # await self.mark_message_as_read(message_id)
                # await self.channel_layer.group_send(...) # Уведомляем остальных
            else:
                print(f"[WS Receive] Chat {self.chat_id}, User {self.user.id}: Unknown message type '{message_type}'")
                # await self.send_error(f"Unknown message type: {message_type}") # Не шлем ошибку на неизвестный тип

        except json.JSONDecodeError:
            print(f"[WS Receive] Chat {self.chat_id}, User {self.user.id}: Invalid JSON")
            # await self.send_error("Invalid JSON format.")
        except Exception as e:
             print(f"[WS Receive] Chat {self.chat_id}, User {self.user.id}: Error processing received message: {e}")
             # await self.send_error(f"Error processing message: {e}")

    # --- Методы-Обработчики для group_send ---

    async def chat_message(self, event):
        """ Обработчик для отправки НОВОГО сообщения клиенту. """
        message_data = event['message']
        sender_channel = event.get('sender_channel_name')

        # НЕ отправляем сообщение обратно тому же клиенту, который его отправил через REST API
        await self.send(text_data=json.dumps({
                'type': 'chat.message', # Используем префикс chat. для ясности
                'message': message_data
            }))
        # if self.channel_name != sender_channel:
        #     await self.send(text_data=json.dumps({
        #         'type': 'chat.message', # Используем префикс chat. для ясности
        #         'message': message_data
        #     }))

    async def chat_typing(self, event):
        """ Обработчик для отправки статуса набора текста клиенту. """
        sender_channel = event.get('sender_channel_name')
        # Не отправляем событие typing себе же
        if self.channel_name != sender_channel:
            await self.send(text_data=json.dumps({
                'type': 'chat.typing',
                'user_id': event['user_id'],
                'user_name': event['user_name'],
                'is_typing': event['is_typing']
            }))

    async def chat_message_read(self, event):
         """ Обработчик для отправки события прочтения сообщения клиенту. """
         sender_channel = event.get('sender_channel_name')
         # Не отправляем себе же уведомление о прочтении
         if self.channel_name != sender_channel:
             await self.send(text_data=json.dumps({
                 'type': 'chat.message_read',
                 'message_id': event['message_id'],
                 'user_id': event['user_id'] # ID того, КТО прочитал
             }))

    async def chat_participant_update(self, event):
         """ Обработчик для отправки обновленной информации о чате (участниках). """
         # Отправляем всем, включая того, кто инициировал изменение
         await self.send(text_data=json.dumps({
             'type': 'chat.participant_update',
             'chat': event['chat'] # Сериализованные данные чата
         }))

    async def chat_system_message(self, event):
         """ Обработчик для отправки системного сообщения (вошел/вышел). """
         await self.send(text_data=json.dumps({
             'type': 'chat.system_message',
             'text': event['text']
         }))


    # --- Метод для отправки ошибки клиенту (если нужно) ---
    # async def send_error(self, message):
    #      await self.send(text_data=json.dumps({'type': 'error', 'message': message}))

    # --- Вспомогательные асинхронные методы ---
    @database_sync_to_async
    def check_chat_access(self, chat_pk: int):
        """ Проверяет, является ли self.user участником чата. """
        if not self.user: return False
        try:
             # Проверяем через промежуточную модель
             return ChatParticipant.objects.filter(chat_id=chat_pk, user=self.user).exists()
             # Или через M2M поле:
             # return Chat.objects.filter(pk=chat_pk, participants=self.user).exists()
        except Exception as e:
             print(f"Error checking chat access for user {self.user.id} and chat {chat_pk}: {e}")
             return False

    # save_message больше не нужен здесь, сохранение идет через REST API
    # @database_sync_to_async
    # def save_message(self, content, file=None): ...