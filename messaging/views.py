# messaging/views.py
from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db.models import Max, Q, Count # Добавляем Count
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied, ValidationError # Импортируем ValidationError
from .models import Chat, Message, ChatParticipant
# Убедитесь, что импортируете ВСЕ нужные сериализаторы
from .serializers import ChatSerializer, MediaMessageSerializer, MessageSerializer, MarkReadSerializer
from users.permissions import IsAdmin # Используем пермишен (если он нужен)
from .filters import ChatMediaFilter # Импортируем фильтр
from rest_framework.pagination import LimitOffsetPagination 
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
# Импорты для Channels
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
logger = logging.getLogger(__name__)

User = get_user_model()

class ChatMediaPagination(LimitOffsetPagination):
    default_limit = 30 # Количество медиа на странице по умолчанию
    max_limit = 100    # Максимальное количество

class ChatMediaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Предоставляет доступ к списку медиа и файлов для конкретного чата.
    URL: /api/messaging/chats/{chat_pk}/media/
    """
    serializer_class = MediaMessageSerializer # Используем урезанный сериализатор
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ChatMediaPagination # Включаем пагинацию
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = ChatMediaFilter # Используем наш фильтр по типу
    ordering_fields = ['timestamp']
    ordering = ['-timestamp'] # Сначала новые

    def get_queryset(self):
        """ Возвращает только сообщения с файлами для указанного чата. """
        chat_pk = self.kwargs.get('chat_pk')
        if not chat_pk: return Message.objects.none()

        # Проверяем доступ пользователя к чату
        try:
            if not ChatParticipant.objects.filter(chat_id=chat_pk, user=self.request.user).exists():
                raise PermissionDenied("Вы не являетесь участником этого чата.")
        except ValueError:
             raise ValidationError("Неверный ID чата.")

        # Фильтруем сообщения: должен быть файл и принадлежать чату
        return Message.objects.filter(
            chat_id=chat_pk,
            file__isnull=False # Убираем сообщения без файлов
        ).exclude(
            file='' # Исключаем записи с пустым путем к файлу (на всякий случай)
        ).select_related('sender__profile') # Подгружаем автора и профиль

    def get_serializer_context(self):
        # Передаем request в контекст для генерации file_url
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

class ChatViewSet(viewsets.ModelViewSet):
    """Управление чатами (список, создание, детали)."""
    serializer_class = ChatSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """ Пользователь видит только те чаты, в которых он участвует. """
        if not self.request.user.is_authenticated:
            return Chat.objects.none()
        # Оптимизация: prefetch_related для участников и select_related для автора последнего сообщения
        return self.request.user.chats.prefetch_related(
            'participants__profile', # Подгружаем профили участников
            'last_message__sender__profile' # Подгружаем профиль отправителя последнего сообщения
        ).annotate( # Аннотируем время последнего сообщения для сортировки
            last_message_ts=Max('messages__timestamp')
        ).distinct().order_by('-last_message_ts', '-created_at') # Сортируем по последнему сообщению, затем по дате создания

    # perform_create больше не нужен, логика перенесена в ChatSerializer.create
    # def perform_create(self, serializer):
    #     serializer.save(created_by=self.request.user) # Передаем создателя

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def add_participant(self, request, pk=None):
        """ Добавляет участника в групповой чат. """
        chat = self.get_object() # Получаем чат, get_queryset уже проверил участие текущего юзера

        # Проверка прав: Только админ может добавлять участников
        if not request.user.is_admin: # Используем ваш флаг is_admin
             raise PermissionDenied("Только администратор может добавлять участников.")

        if chat.chat_type == Chat.ChatType.PRIVATE:
            return Response({'error': 'Нельзя добавить участников в личный чат.'}, status=status.HTTP_400_BAD_REQUEST)

        # --- ИСПРАВЛЕНИЕ: Ожидаем user_id ---
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        try:
            user_to_add = User.objects.get(pk=user_id)

            # Используем модель ChatParticipant для добавления
            participant, created = ChatParticipant.objects.get_or_create(user=user_to_add, chat=chat)

            if not created:
                 return Response({'detail': 'Пользователь уже в чате.'}, status=status.HTTP_400_BAD_REQUEST)

            # TODO: Отправить уведомление через WebSocket
            self.notify_participants(chat, f'User {user_to_add.get_full_name() or user_to_add.email} joined the chat.', system=True)

            # Возвращаем обновленный чат
            # Пере-сериализуем, чтобы включить обновленный список участников
            serializer = self.get_serializer(chat)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'Пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             print(f"Error adding participant to chat {pk}: {e}") # Логируем ошибку
             return Response({'error': f'Ошибка добавления участника: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def remove_participant(self, request, pk=None):
        """ Удаляет участника из группового чата. """
        chat = self.get_object()

        # Проверка прав: Только админ может удалять
        if not request.user.is_admin:
            raise PermissionDenied("Только администратор может удалять участников.")

        if chat.chat_type == Chat.ChatType.PRIVATE:
             return Response({'error': 'Нельзя удалять участников из личного чата.'}, status=status.HTTP_400_BAD_REQUEST)

        # --- ИСПРАВЛЕНИЕ: Ожидаем user_id ---
        user_id_to_remove = request.data.get('user_id')
        if not user_id_to_remove:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        # Запрет удаления самого себя через этот эндпоинт
        if str(request.user.id) == str(user_id_to_remove):
             return Response({'error': 'Используйте действие "Покинуть чат".'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_to_remove = User.objects.get(pk=user_id_to_remove)

            # Используем ChatParticipant для удаления
            deleted_count, _ = ChatParticipant.objects.filter(chat=chat, user=user_to_remove).delete()

            if deleted_count == 0:
                 return Response({'error': 'Пользователь не найден в этом чате.'}, status=status.HTTP_404_NOT_FOUND)

            # Проверка на удаление последнего участника (не должна произойти, если есть админ)
            if chat.participants.count() == 0:
                 print(f"Warning: Last participant removed from chat {pk}. Consider deleting the chat.")
                 # Можно добавить логику удаления пустого чата здесь или в другом месте

            # TODO: Отправить уведомление через WebSocket
            self.notify_participants(chat, f'User {user_to_remove.get_full_name() or user_to_remove.email} left the chat.', system=True)

            # Возвращаем обновленный чат
            serializer = self.get_serializer(chat)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except User.DoesNotExist:
             return Response({'error': 'Удаляемый пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             print(f"Error removing participant from chat {pk}: {e}")
             return Response({'error': f'Ошибка удаления участника: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='mark-read', permission_classes=[permissions.IsAuthenticated])
    def mark_read(self, request, pk=None):
        """ Отмечает чат как прочитанный текущим пользователем до последнего сообщения. """
        # Получаем чат, проверяя участие пользователя через get_queryset
        chat = get_object_or_404(self.get_queryset(), pk=pk)
        logger.debug(f"MarkRead View: Attempting for chat {pk}, user {request.user.id}")

        # Используем сериализатор MarkReadSerializer
        serializer = MarkReadSerializer(data={}, context={'request': request, 'chat': chat})
        if serializer.is_valid():
            try:
                logger.debug(f"MarkRead View: Serializer is valid, calling save() for chat {pk}")
                participant_info = serializer.save() # Вызываем save и получаем результат
                logger.info(f"MarkRead View: Serializer save finished for chat {pk}. Participant updated/created: {participant_info is not None}. Last read message ID: {getattr(participant_info, 'last_read_message_id', 'N/A')}")

                # Отправляем WS уведомление об обновлении счетчика ТОЛЬКО ПОСЛЕ успешного save
                # Проверяем, что participant_info не None (на случай если save вернул None)
                if participant_info:
                    self.notify_user_unread_update(request.user, chat.pk)
                else:
                     logger.warning(f"MarkRead View: Serializer save returned None for chat {pk}, user {request.user.id}. Skipping WS notification.")


                return Response(status=status.HTTP_204_NO_CONTENT) # Успех без содержимого

            except Exception as e:
                 # Ловим исключения, проброшенные из serializer.save()
                 logger.error(f"MarkRead View: Error during serializer.save() for chat {pk}: {e}", exc_info=True)
                 # Возвращаем 500, так как это внутренняя ошибка сервера
                 return Response({'error': 'Failed to update read status due to internal error.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # Сюда не должны попасть при пустых data={}, но на всякий случай
            logger.error(f"MarkReadSerializer unexpected validation errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # --- Вспомогательные методы для WebSocket ---
    def notify_participants(self, chat: Chat, message_data: dict, system: bool = False, exclude_user: User | None = None):
        """ Отправляет сообщение или событие всем участникам чата через WebSocket. """
        try:
            channel_layer = get_channel_layer()
            group_name = f"chat_{chat.pk}"
            event_type = "chat.system_message" if system else "chat.message"
            event_content = {"message": message_data} if not system else {"text": message_data} # Разный формат для системных

            print(f"[WS Notify] Sending to group {group_name}: type={event_type}, content={event_content}")

            # Формируем список каналов для отправки, исключая exclude_user, если он указан
            # Это потребует хранения channel_name для каждого пользователя онлайн
            # Упрощенный вариант - просто отправляем в группу
            # TODO: Реализовать исключение пользователя, если нужно

            async_to_sync(channel_layer.group_send)(
                group_name,
                {"type": event_type, **event_content}, # Распаковываем event_content
            )
            print(f"[WS Notify] Sent to group {group_name}")
        except Exception as e:
            print(f"!!! ERROR sending WS notification for chat {chat.pk}: {e}")

    def notify_user_unread_update(self, user: User, chat_id: int):
         """ Отправляет событие обновления счетчика непрочитанных конкретному пользователю через NotificationConsumer. """
         try:
            channel_layer = get_channel_layer()
            user_channel_group = f"user_{user.id}"

            # --- РАССЧЕТ АКТУАЛЬНОГО СЧЕТЧИКА ДЛЯ ПОЛУЧАТЕЛЯ 'user' ---
            unread_count = 0
            try:
                 # Находим запись ИМЕННО ЭТОГО пользователя в чате
                 participant = ChatParticipant.objects.select_related('last_read_message').get(chat_id=chat_id, user=user)
                 last_read_msg = participant.last_read_message
                 if last_read_msg and last_read_msg.timestamp:
                     # Считаем сообщения ПОЗЖЕ времени прочтения ЭТИМ пользователем
                     unread_count = Message.objects.filter(chat_id=chat_id, timestamp__gt=last_read_msg.timestamp).count()
                 else:
                     # Если пользователь ничего не читал, считаем ВСЕ сообщения
                     unread_count = Message.objects.filter(chat_id=chat_id).count()
            except ChatParticipant.DoesNotExist:
                 # Если нет записи участника, считаем все сообщения непрочитанными ДЛЯ НЕГО
                 unread_count = Message.objects.filter(chat_id=chat_id).count()
                 logger.warning(f"notify_user_unread_update: ChatParticipant not found for user {user.id}, chat {chat_id}. Sending total count: {unread_count}")
            except Exception as e_count:
                 logger.error(f"notify_user_unread_update: Error calculating unread count for user {user.id}, chat {chat_id}: {e_count}", exc_info=True)
                 return # Не отправляем WS при ошибке подсчета

            # --- КОНЕЦ РАССЧЕТА ---

            event_data = {
                 "type": "chat.unread_update",
                 "chat_id": chat_id,
                 "unread_count": unread_count # Отправляем актуальный счетчик для ЭТОГО пользователя
             }
            logger.info(f"[WS Notify] Sending unread update to {user_channel_group}: {event_data}")
            async_to_sync(channel_layer.group_send)(
                user_channel_group,
                event_data,
            )
            logger.debug(f"[WS Notify] Sent unread update to {user_channel_group}")
         except Exception as e:
            logger.error(f"!!! ERROR sending WS unread update for user {user.id}, chat {chat_id}: {e}", exc_info=True)


class MessageViewSet(viewsets.ModelViewSet):
    """Просмотр и отправка сообщений в конкретном чате."""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # TODO: Добавить пагинацию для сообщений
    # pagination_class = YourMessagePaginationClass

    def get_queryset(self):
        """ Возвращает сообщения для конкретного чата, доступного пользователю. """
        chat_pk = self.kwargs.get('chat_pk')
        if not chat_pk:
            # Это не должно происходить из-за URL conf, но на всякий случай
            return Message.objects.none()

        # Проверяем доступ пользователя к чату ОДИН РАЗ
        try:
            # get_object_or_404 здесь не нужен, достаточно exists() или filter().exists()
            if not ChatParticipant.objects.filter(chat_id=chat_pk, user=self.request.user).exists():
                raise PermissionDenied("Вы не являетесь участником этого чата.")
        except ValueError: # Если chat_pk не число
             raise ValidationError("Неверный ID чата.")

        # Возвращаем сообщения, новые снизу (стандартно для чатов)
        return Message.objects.filter(chat_id=chat_pk).select_related('sender__profile').order_by('timestamp')

    def perform_create(self, serializer):
        """ Создает сообщение, обновляет last_message чата и отправляет WS уведомление. """
        chat_pk = self.kwargs.get('chat_pk')
        # Получаем чат еще раз (или берем из контекста, если передали при get_queryset)
        # Проверка доступа уже была в get_queryset, но повторим для надежности
        chat = get_object_or_404(Chat.objects.filter(participants=self.request.user), pk=chat_pk)

        # --- ИСПРАВЛЕНИЕ: Удаляем временные поля перед сохранением ---
        validated_data = serializer.validated_data
        validated_data.pop('_isSending', None)
        validated_data.pop('_tempId', None)
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        try:
            # Передаем очищенные validated_data
            instance = serializer.save(sender=self.request.user, chat=chat)
        except Exception as e:
            print(f"Error saving message for chat {chat_pk}: {e}")
            raise ValidationError(f"Failed to save message: {e}")

        # Обновляем last_message в чате (быстро и атомарно)
        updated_count = Chat.objects.filter(pk=chat.pk).update(last_message=instance)
        if updated_count > 0:
            print(f"[perform_create] Updated last_message for chat {chat.pk}")
        else:
            print(f"[perform_create] Warning: Failed to update last_message for chat {chat.pk}")


        # --- ОТПРАВКА ЧЕРЕЗ WEBSOCKET ---
        message_data = MessageSerializer(instance, context={'request': self.request}).data
        chat_viewset = ChatViewSet()

        # 1. Отправляем само сообщение всем участникам (кроме себя, если настроено в Consumer)
        chat_viewset.notify_participants(chat, message_data, system=False)

        # --- 2. Отправляем обновление счетчика КАЖДОМУ ПОЛУЧАТЕЛЮ ---
        # Получаем всех участников чата, КРОМЕ отправителя
        recipients = chat.participants.filter(is_active=True).exclude(id=self.request.user.id)
        for recipient in recipients:
             try:
                 # Вызываем обновление счетчика для КАЖДОГО получателя
                 chat_viewset.notify_user_unread_update(recipient, chat.pk)
                 print(recipient)
             except Exception as e_notify:
                 logger.error(f"Failed to send unread update notification to user {recipient.id} for chat {chat.pk}: {e_notify}", exc_info=True)

        # TODO: Отправить уведомление (push/email) - опционально