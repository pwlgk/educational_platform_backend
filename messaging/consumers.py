from django.utils import timezone
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.contenttypes.models import ContentType
from .models import Chat, Message, ChatParticipant
from .serializers import MessageSerializer, LimitedUserSerializer
from users.models import User
import logging

logger = logging.getLogger(__name__)

# Класс ChatConsumer обрабатывает WebSocket-соединения для обмена сообщениями в реальном времени
# в рамках конкретного чата. Он наследуется от AsyncWebsocketConsumer для асинхронной работы.
#
# Жизненный цикл и основные методы:
# - __init__: Инициализирует переменные экземпляра, такие как `chat_id`, `chat_group_name` и `user`.
# - connect: Вызывается при установлении WebSocket-соединения.
#   1. Получает пользователя из `scope` (аутентификация должна быть настроена в ASGI-приложении).
#   2. Проверяет аутентификацию пользователя. Если не аутентифицирован, соединение отклоняется.
#   3. Извлекает `chat_id` из URL-маршрута. Если `chat_id` отсутствует или имеет неверный формат, соединение отклоняется.
#   4. Асинхронно проверяет, имеет ли пользователь доступ к указанному чату (`check_chat_access`). Если нет, соединение отклоняется.
#   5. Формирует имя группы Channels (`chat_group_name`) на основе `chat_id`.
#   6. Добавляет текущий канал WebSocket в группу Channels, чтобы он мог получать сообщения, отправленные в эту группу.
#   7. Принимает WebSocket-соединение.
#   8. Отправляет событие `user_status_update` с информацией о том, что пользователь стал "online", всем участникам группы (кроме себя).
# - disconnect: Вызывается при закрытии WebSocket-соединения.
#   1. Отправляет событие `user_status_update` с информацией о том, что пользователь стал "offline" и временем последнего визита, всем участникам группы.
#   2. Удаляет текущий канал WebSocket из группы Channels.
# - receive: Вызывается при получении сообщения от клиента через WebSocket.
#   1. Проверяет аутентификацию пользователя.
#   2. Пытается разобрать полученные данные как JSON.
#   3. В зависимости от типа сообщения (`type` в JSON-данных):
#      - Если тип 'typing': Рассылает событие `chat.typing` остальным участникам группы, указывая, начал или закончил пользователь набирать текст.
#      - (Закомментировано) Возможна обработка других типов, например, 'mark_read'.
# - Методы-обработчики событий (например, `chat_message`, `chat_typing`, `user_status_update` и др.):
#   Эти методы вызываются, когда в группу Channels, на которую подписан консьюмер, приходит событие
#   соответствующего типа (например, `type="chat.message"`). Они отвечают за отправку данных
#   подключенному клиенту через WebSocket.
#   - `chat_message`: Отправляет новое сообщение клиенту. Реализовано подавление эха для сообщений, отправленных самим пользователем через REST API (если используется `temp_id_echo`).
#   - `chat_typing`: Отправляет информацию о статусе набора текста.
#   - `user_status_update`: Отправляет обновление статуса пользователя (online/offline).
#   - `chat_message_read`: Отправляет информацию о прочтении сообщения.
#   - `message_read_receipt`: Отправляет квитанцию о прочтении сообщения (обновление статуса последнего прочитанного сообщения).
#   - `chat_participant_update`: Отправляет обновленную информацию об участниках чата.
#   - `chat_system_message`: Отправляет системное сообщение (например, "пользователь вошел/вышел").
# - Вспомогательные методы:
#   - `get_limited_user_data`: Асинхронный метод для получения сериализованных данных пользователя (использует `LimitedUserSerializer`).
#   - `check_chat_access`: Асинхронный метод для проверки, является ли текущий пользователь участником указанного чата.
class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_id = None
        self.chat_group_name = None
        self.user: User | None = None

    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        self.chat_id = self.scope['url_route']['kwargs'].get('chat_id')
        if not self.chat_id:
             await self.close(code=4000)
             return
        try:
            chat_pk = int(self.chat_id)
        except ValueError:
             await self.close(code=4000)
             return

        has_access = await self.check_chat_access(chat_pk)
        if not has_access:
            await self.close(code=4003)
            return

        self.chat_group_name = f'chat_{self.chat_id}'
        await self.channel_layer.group_add(
            self.chat_group_name,
            self.channel_name
        )

        await self.accept()

        user_serializer_data = await self.get_limited_user_data(self.user)
        await self.channel_layer.group_send(
            self.chat_group_name,
            {
                "type": "user_status_update",
                "data": {
                    "user_id": self.user.id,
                    "status": "online",
                    "user_details": user_serializer_data
                },
                "sender_channel_name": self.channel_name
            }
        )

    async def disconnect(self, close_code):
        if self.user: # Пользователь может быть None, если connect не завершился успешно
            user_serializer_data = await self.get_limited_user_data(self.user)

            await self.channel_layer.group_send(
                    self.chat_group_name,
                    {
                        "type": "user_status_update",
                        "data": {
                            "user_id": self.user.id,
                            "status": "offline",
                            "last_seen": timezone.now().isoformat(),
                            "user_details": user_serializer_data
                        },
                        "sender_channel_name": self.channel_name
                    }
                )

        if self.chat_group_name:
            await self.channel_layer.group_discard(
                self.chat_group_name,
                self.channel_name
            )

    # Обработчик для события обновления статуса пользователя (online/offline).
    # Отправляет данные клиенту, если событие не было инициировано этим же каналом.
    async def user_status_update(self, event):
        sender_channel = event.get('sender_channel_name')
        if self.channel_name != sender_channel:
            await self.send(text_data=json.dumps({
                'type': 'user_status_update',
                'data': event['data']
            }))

    # Обрабатывает сообщения, полученные от клиента через WebSocket (например, 'typing').
    async def receive(self, text_data=None, bytes_data=None):
        if not self.user or not self.user.is_authenticated: return

        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'typing':
                is_typing = data.get('is_typing', False)
                user_serializer = LimitedUserSerializer(self.user)
                await self.channel_layer.group_send(
                    self.chat_group_name,
                    {
                        "type": "chat.typing",
                        "user_id": self.user.id,
                        "user_name": user_serializer.data.get('first_name', self.user.get_username()),
                        "is_typing": is_typing,
                        "sender_channel_name": self.channel_name
                    }
                )
            # Другие типы сообщений от клиента могут быть обработаны здесь
        except json.JSONDecodeError:
            logger.error(f"[WS Receive] Chat {self.chat_id}, User {self.user.id}: Invalid JSON")
        except Exception as e:
             logger.error(f"[WS Receive] Chat {self.chat_id}, User {self.user.id}: Error processing received message: {e}")

    # Обработчик для события нового сообщения в чате.
    # Отправляет сообщение клиенту, если оно не является эхом собственного сообщения пользователя.
    # Для эхо-сообщений (с temp_id_echo) отправляется специальный тип 'chat_message_echo'.
    async def chat_message(self, event):
      message_data = event['message']
      sender_id_from_event = message_data.get('sender', {}).get('id')
      temp_id_echo = event.get('temp_id_echo')

      if self.user and sender_id_from_event == self.user.id:
          if temp_id_echo:
              await self.send(text_data=json.dumps({
                  'type': 'chat_message_echo',
                  'message': message_data,
                  'temp_id_echo': temp_id_echo
              }))
          return

      await self.send(text_data=json.dumps({
              'type': 'chat.message',
              'message': message_data
          }))

    # Обработчик для события набора текста в чате.
    # Отправляет статус набора текста клиенту, если событие не было инициировано этим же каналом.
    async def chat_typing(self, event):
        sender_channel = event.get('sender_channel_name')
        if self.channel_name != sender_channel:
            await self.send(text_data=json.dumps({
                'type': 'chat.typing',
                'user_id': event['user_id'],
                'user_name': event['user_name'],
                'is_typing': event['is_typing']
            }))

    # Обработчик для события прочтения сообщения.
    # Отправляет информацию о прочтении клиенту, если событие не было инициировано этим же каналом.
    async def chat_message_read(self, event):
         sender_channel = event.get('sender_channel_name')
         if self.channel_name != sender_channel:
             await self.send(text_data=json.dumps({
                 'type': 'chat.message_read',
                 'message_id': event['message_id'],
                 'user_id': event['user_id']
             }))

    # Обработчик для квитанции о прочтении (обновление последнего прочитанного сообщения).
    # Отправляет данные клиенту для обновления интерфейса.
    async def message_read_receipt(self, event):
        chat_id = event.get('chat_id')
        reader_id = event.get('reader_id')
        last_read_message_id = event.get('last_read_message_id')

        if chat_id is not None and reader_id is not None:
            await self.send(text_data=json.dumps({
                'type': 'message_read_update',
                'payload': {
                    'chat_id': chat_id,
                    'reader_id': reader_id,
                    'last_read_message_id': last_read_message_id,
                }
            }))
        else:
            logger.warning(f"[WS Consumer] Received incomplete message.read_receipt event: {event}")

    # Обработчик для события обновления участников чата.
    # Отправляет клиенту обновленную информацию о чате.
    async def chat_participant_update(self, event):
         await self.send(text_data=json.dumps({
             'type': 'chat.participant_update',
             'chat': event['chat']
         }))

    # Обработчик для системных сообщений в чате.
    # Отправляет текст системного сообщения клиенту.
    async def chat_system_message(self, event):
         await self.send(text_data=json.dumps({
             'type': 'chat.system_message',
             'text': event['text']
         }))

    # Асинхронный вспомогательный метод для получения ограниченного набора данных пользователя.
    @database_sync_to_async
    def get_limited_user_data(self, user_instance):
        if not user_instance: # Добавлена проверка на None
            return {}
        return LimitedUserSerializer(user_instance).data

    # Асинхронный вспомогательный метод для проверки доступа пользователя к чату.
    @database_sync_to_async
    def check_chat_access(self, chat_pk: int):
        if not self.user: return False
        try:
             return ChatParticipant.objects.filter(chat_id=chat_pk, user=self.user).exists()
        except Exception as e:
             logger.error(f"Error checking chat access for user {self.user.id} and chat {chat_pk}: {e}")
             return False