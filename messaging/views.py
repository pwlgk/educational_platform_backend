from typing import Optional
from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db.models import Max, Q, Count
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied, ValidationError

from users.models import User
from .models import Chat, Message, ChatParticipant
from .serializers import ChatSerializer, MediaMessageSerializer, MessageSerializer, MarkReadSerializer
from .permissions import IsChatCreatorOrAdmin, IsChatParticipant
from .filters import ChatMediaFilter
from rest_framework.pagination import LimitOffsetPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from notifications.utils import notify_added_to_chat, notify_removed_from_chat
from notifications.models import Notification

logger = logging.getLogger(__name__)


# Класс ChatMediaPagination определяет кастомную пагинацию для списка медиафайлов в чате.
# Наследуется от LimitOffsetPagination.
# - default_limit: Количество элементов на странице по умолчанию (30).
# - max_limit: Максимальное количество элементов на странице, которое может запросить клиент (200).
class ChatMediaPagination(LimitOffsetPagination):
    default_limit = 30
    max_limit = 200

# Класс ChatMediaViewSet предоставляет эндпоинты только для чтения (ReadOnlyModelViewSet)
# для получения списка медиафайлов (сообщений с файлами) в конкретном чате.
# - serializer_class: Использует MediaMessageSerializer для отображения сообщений с медиа.
# - permission_classes: Требует аутентификации пользователя (IsAuthenticated).
# - pagination_class: Использует кастомную пагинацию ChatMediaPagination.
# - filter_backends: Включает DjangoFilterBackend для фильтрации по типу медиа и OrderingFilter для сортировки.
# - filterset_class: Использует ChatMediaFilter для определения доступных фильтров.
# - ordering_fields: Поля, по которым можно сортировать (только 'timestamp').
# - ordering: Сортировка по умолчанию (по убыванию 'timestamp', т.е. сначала новые).
# Метод get_queryset:
#   1. Получает 'chat_pk' из URL.
#   2. Проверяет, является ли запрашивающий пользователь участником данного чата. Если нет, выбрасывает PermissionDenied.
#   3. Возвращает QuerySet сообщений из указанного чата, у которых есть прикрепленный файл (file не null и не пустая строка),
#      с предзагрузкой профиля отправителя.
# Метод get_serializer_context добавляет объект request в контекст сериализатора,
# что необходимо для формирования полных URL для файлов.
class ChatMediaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MediaMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ChatMediaPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = ChatMediaFilter
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']

    def get_queryset(self):
        chat_pk = self.kwargs.get('chat_pk')
        if not chat_pk: return Message.objects.none()
        try:
            # Проверка, что пользователь является участником чата
            if not ChatParticipant.objects.filter(chat_id=chat_pk, user=self.request.user).exists():
                raise PermissionDenied("Вы не являетесь участником этого чата.")
        except ValueError: # Если chat_pk не может быть преобразован в int
             raise ValidationError("Неверный ID чата.")
        return Message.objects.filter(
            chat_id=chat_pk,
            file__isnull=False
        ).exclude(
            file=''
        ).select_related('sender__profile') # Оптимизация запроса

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request # Для build_absolute_uri в сериализаторе
        return context

# Класс ChatViewSet предоставляет полный CRUD-функционал (ModelViewSet) для управления чатами.
# - serializer_class: Использует ChatSerializer.
# - permission_classes (базовый): Требует аутентификации пользователя.
# Метод get_queryset:
#   - Возвращает QuerySet чатов, в которых участвует текущий аутентифицированный пользователь.
#   - Выполняет предзагрузку связанных данных (participants, last_message, created_by) для оптимизации.
#   - Аннотирует каждый чат временем последнего сообщения (`last_message_ts`) для сортировки.
#   - Сортирует чаты по времени последнего сообщения (сначала новые), затем по дате создания.
# Метод get_permissions динамически назначает разрешения в зависимости от действия:
#   - update, partial_update, destroy: IsChatCreatorOrAdmin (только создатель чата или админ).
#   - add_participant, remove_participant_by_admin: IsChatCreatorOrAdmin.
#   - leave_chat: IsChatParticipant (любой участник чата может его покинуть).
#   - mark_read, retrieve: IsChatParticipant (любой участник может прочитать и просмотреть чат).
# Кастомные действия (@action):
#   - add_participant: Позволяет создателю чата или админу добавлять нового участника в групповой чат.
#     Отправляет уведомление добавленному пользователю и системное сообщение в чат.
#   - remove_participant_by_admin: Позволяет создателю чата или админу удалять участника из группового чата.
#     Отправляет системное сообщение в чат и уведомление удаленному пользователю.
#   - leave_chat: Позволяет текущему пользователю покинуть групповой чат. Если пользователь был последним
#     участником, чат удаляется. Отправляет системное сообщение в чат.
#   - mark_read: Позволяет текущему пользователю отметить все сообщения в чате как прочитанные
#     (обновляет last_read_message). Отправляет WebSocket-уведомление `message.read_receipt`
#     в группу чата и `chat_unread_update` в личный канал пользователя для обновления счетчика непрочитанных.
# Вспомогательные методы:
#   - notify_participants: Отправляет WebSocket-уведомление (обычное или системное сообщение)
#     всем участникам указанного чата через Channels.
#   - notify_user_unread_update: Отправляет WebSocket-уведомление конкретному пользователю
#     об изменении количества непрочитанных сообщений в указанном чате.
class ChatViewSet(viewsets.ModelViewSet):
    serializer_class = ChatSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Chat.objects.none()
        # Получаем чаты, где пользователь является участником
        return self.request.user.chats.prefetch_related(
            'participants__profile', # Для отображения аватаров участников
            'last_message__sender__profile', # Для аватара отправителя последнего сообщения
            'created_by__profile'
        ).select_related(
            'last_message', # Для деталей последнего сообщения
            'created_by'    # Для информации о создателе чата
        ).annotate(
            last_message_ts=Max('messages__timestamp') # Для сортировки по последнему сообщению
        ).distinct().order_by('-last_message_ts', '-created_at')

    def get_permissions(self):
        # Динамическое назначение разрешений в зависимости от действия
        if self.action in ['update', 'partial_update', 'destroy']:
            self.permission_classes = [permissions.IsAuthenticated, IsChatCreatorOrAdmin]
        elif self.action in ['add_participant', 'remove_participant_by_admin']:
            self.permission_classes = [permissions.IsAuthenticated, IsChatCreatorOrAdmin]
        elif self.action == 'leave_chat':
            self.permission_classes = [permissions.IsAuthenticated, IsChatParticipant]
        elif self.action in ['mark_read', 'retrieve']: # retrieve - просмотр деталей чата
            self.permission_classes = [permissions.IsAuthenticated, IsChatParticipant]
        # Для 'create' и 'list' используются разрешения по умолчанию (IsAuthenticated)
        return super().get_permissions()

    @action(detail=True, methods=['post'], url_path='add_participant')
    def add_participant(self, request, pk=None):
        chat = self.get_object() # Проверка прав доступа уже выполнена get_permissions
        if chat.chat_type == Chat.ChatType.PRIVATE:
            return Response({'error': 'Нельзя добавить участников в личный чат.'}, status=status.HTTP_400_BAD_REQUEST)
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user_to_add = User.objects.get(pk=user_id)
            participant, created = ChatParticipant.objects.get_or_create(user=user_to_add, chat=chat)
            if not created:
                 return Response({'detail': 'Пользователь уже в чате.'}, status=status.HTTP_400_BAD_REQUEST)

            notify_added_to_chat(chat, user_to_add) # Уведомление через систему Notification
            notification_text_for_others = f'Пользователь {user_to_add.get_full_name() or user_to_add.email} присоединился к чату.'
            self.notify_participants(chat, notification_text_for_others, system=True, exclude_user=user_to_add) # WS уведомление в чат

            serializer = self.get_serializer(chat) # Возвращаем обновленные данные чата
            return Response(serializer.data, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'error': 'Пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error adding participant to chat {pk}: {e}", exc_info=True)
             return Response({'error': f'Ошибка добавления участника: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='remove_participant')
    def remove_participant_by_admin(self, request, pk=None):
        chat = self.get_object()
        if chat.chat_type == Chat.ChatType.PRIVATE:
             return Response({'error': 'Нельзя удалять участников из личного чата.'}, status=status.HTTP_400_BAD_REQUEST)
        user_id_to_remove_str = request.data.get('user_id')
        if not user_id_to_remove_str:
            return Response({'error': 'Необходимо указать "user_id" удаляемого участника.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user_id_to_remove = int(user_id_to_remove_str)
        except ValueError:
            return Response({'error': 'Неверный формат "user_id".'}, status=status.HTTP_400_BAD_REQUEST)
        current_user = request.user
        if current_user.id == user_id_to_remove: # Админ не может удалить сам себя этим методом
             return Response({'error': 'Чтобы покинуть чат, используйте действие "Покинуть чат".'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user_to_remove = User.objects.get(pk=user_id_to_remove)
            participant_to_remove = ChatParticipant.objects.filter(chat=chat, user=user_to_remove).first()
            if not participant_to_remove:
                return Response({'error': 'Указанный пользователь не является участником этого чата.'}, status=status.HTTP_404_NOT_FOUND)
            
            participant_to_remove.delete()

            notification_text_for_others = f'Пользователь {user_to_remove.get_full_name() or user_to_remove.email} был удален из чата администратором.'
            self.notify_participants(chat, notification_text_for_others, system=True, exclude_user=user_to_remove)
            notify_removed_from_chat(chat, user_to_remove, actor=current_user)

            return Response(status=status.HTTP_204_NO_CONTENT)
        except User.DoesNotExist:
            return Response({'error': 'Удаляемый пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error removing participant {user_id_to_remove} by admin from chat {pk}: {e}", exc_info=True)
             return Response({'error': f'Ошибка удаления участника: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='leave')
    def leave_chat(self, request, pk=None):
        chat = self.get_object()
        if chat.chat_type == Chat.ChatType.PRIVATE:
             return Response({'error': 'Нельзя покинуть личный чат таким образом.'}, status=status.HTTP_400_BAD_REQUEST)
        current_user = request.user
        try:
            participant_entry = ChatParticipant.objects.filter(chat=chat, user=current_user).first()
            if not participant_entry:
                return Response({'error': 'Вы не являетесь участником этого чата.'}, status=status.HTTP_404_NOT_FOUND)

            chat_name_for_notification = chat.name or "Групповой чат"
            is_last_participant = (chat.participants.count() == 1 and participant_entry.user == current_user)
            participant_entry.delete()

            if is_last_participant:
                logger.info(f"User {current_user.id} is the last participant leaving chat {pk}. Deleting chat.")
                chat.delete()
                return Response({'status': f'Вы покинули чат "{chat_name_for_notification}", и он был удален как пустой.'}, status=status.HTTP_204_NO_CONTENT)
            else:
                notification_text_for_others = f'Пользователь {current_user.get_full_name() or current_user.email} покинул(а) чат.'
                self.notify_participants(chat, notification_text_for_others, system=True, exclude_user=current_user)
                # notify_removed_from_chat(chat, current_user, actor=None) # Уведомление себе о выходе
                return Response({'status': 'Вы покинули чат.'}, status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
             logger.error(f"Error during user {current_user.id} leaving chat {pk}: {e}", exc_info=True)
             return Response({'error': f'Ошибка при выходе из чата: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        chat = self.get_object()
        serializer = MarkReadSerializer(data={}, context={'request': request, 'chat': chat})
        if serializer.is_valid():
            try:
                participant_info = serializer.save()
                if participant_info:
                    channel_layer = get_channel_layer()
                    chat_group_name = f'chat_{chat.pk}'
                    event_data = {
                        'type': 'message.read_receipt',
                        'chat_id': chat.pk,
                        'reader_id': request.user.id,
                        'last_read_message_id': participant_info.last_read_message.id if participant_info.last_read_message else None,
                    }
                    async_to_sync(channel_layer.group_send)(chat_group_name, event_data)
                    self.notify_user_unread_update(request.user, chat.pk) # Обновляем счетчик для себя
                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                 logger.error(f"MarkRead View: Error during serializer.save() for chat {pk}: {e}", exc_info=True)
                 return Response({'error': 'Failed to update read status due to internal error.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.error(f"MarkReadSerializer unexpected validation errors: {serializer.errors}") # Добавлено логирование
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Вспомогательный метод для отправки WS уведомлений в чат
    def notify_participants(self, chat: Chat, message_content_or_data, system: bool = False, exclude_user: Optional[User] = None):
        try:
            channel_layer = get_channel_layer()
            group_name = f"chat_{chat.pk}"
            event_type = "chat.system_message" if system else "chat.message"
            
            if system:
                event_content = {"text": message_content_or_data}
            else:
                event_content = {"message": message_content_or_data}

            sender_id_for_event = None
            if exclude_user:
                sender_id_for_event = exclude_user.id
            elif not system and isinstance(message_content_or_data, dict):
                sender_id_for_event = message_content_or_data.get('sender', {}).get('id')

            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": event_type,
                    **event_content,
                    "sender_id": sender_id_for_event, # ID пользователя, которого нужно исключить из получателей этого же сообщения (для системных) или ID отправителя (для обычных)
                }
            )
        except Exception as e:
            logger.error(f"!!! ERROR sending WS CHAT notification for chat {chat.pk}: {e}", exc_info=True)

    # Вспомогательный метод для отправки WS уведомления об обновлении счетчика непрочитанных
    def notify_user_unread_update(self, user: User, chat_id: int):
         try:
            channel_layer = get_channel_layer()
            user_channel_group = f"user_{user.id}" # Группа для NotificationConsumer
            unread_count = 0
            try: # Расчет непрочитанных
                 participant = ChatParticipant.objects.select_related('last_read_message').get(chat_id=chat_id, user=user)
                 last_read_msg = participant.last_read_message
                 if last_read_msg and last_read_msg.timestamp:
                     unread_count = Message.objects.filter(chat_id=chat_id, timestamp__gt=last_read_msg.timestamp).count()
                 else: # Если нет last_read_message, считаем все сообщения в чате
                     unread_count = Message.objects.filter(chat_id=chat_id).count()
            except ChatParticipant.DoesNotExist: # Если пользователь еще не читал ничего (или не участник)
                 unread_count = Message.objects.filter(chat_id=chat_id).count() # Считаем все
            except Exception as e_count: # Другие ошибки при подсчете
                 logger.error(f"notify_user_unread_update: Error calculating unread count for user {user.id}, chat {chat_id}: {e_count}", exc_info=True)
                 return # Не отправляем, если не смогли посчитать

            event_data = {
                 "type": "chat_unread_update", # Этот тип должен обрабатываться в NotificationConsumer
                 "chat_id": chat_id,
                 "unread_count": unread_count
             }
            async_to_sync(channel_layer.group_send)(user_channel_group, event_data)
         except Exception as e: # Ошибки отправки через Channels
            logger.error(f"!!! ERROR sending WS UNREAD update for user {user.id}, chat {chat_id}: {e}", exc_info=True)

# Класс MessageViewSet предоставляет полный CRUD-функционал (ModelViewSet) для управления сообщениями в чате.
# - serializer_class: Использует MessageSerializer.
# - permission_classes (базовый): Требует аутентификации пользователя.
# Метод get_queryset:
#   1. Получает 'chat_pk' из URL (этот ViewSet вложен в ChatViewSet).
#   2. Проверяет, является ли запрашивающий пользователь участником данного чата. Если нет, выбрасывает PermissionDenied.
#   3. Возвращает QuerySet сообщений из указанного чата, с предзагрузкой профиля отправителя,
#      отсортированных по времени отправки (сначала старые).
# Метод perform_create:
#   1. Получает объект чата, к которому относится создаваемое сообщение.
#   2. Удаляет временные поля `_isSending` и `_tempId` из валидированных данных.
#   3. Сохраняет сообщение, устанавливая текущего пользователя как отправителя и связывая с чатом.
#   4. Обновляет поле `last_message` у объекта Chat.
#   5. Отправляет WebSocket-уведомление о новом сообщении всем участникам чата через метод `notify_participants`.
#   6. Отправляет WebSocket-уведомления об обновлении счетчика непрочитанных сообщений всем получателям
#      (кроме отправителя) через метод `notify_user_unread_update`.
class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # TODO: Добавить пагинацию для сообщений
    # pagination_class = YourMessagePaginationClass

    def get_queryset(self):
        chat_pk = self.kwargs.get('chat_pk')
        if not chat_pk: # Если chat_pk не передан (маловероятно при вложенных роутерах)
            return Message.objects.none()
        try:
            # Проверка, что пользователь является участником чата
            if not ChatParticipant.objects.filter(chat_id=chat_pk, user=self.request.user).exists():
                raise PermissionDenied("Вы не являетесь участником этого чата.")
        except ValueError: # Если chat_pk не может быть преобразован в int
             raise ValidationError("Неверный ID чата.")
        return Message.objects.filter(chat_id=chat_pk).select_related('sender__profile').order_by('timestamp')

    def perform_create(self, serializer):
        chat_pk = self.kwargs.get('chat_pk')
        # Получаем чат, проверяя, что текущий пользователь является его участником
        chat = get_object_or_404(Chat.objects.filter(participants=self.request.user), pk=chat_pk)
        
        # Удаляем временные поля из validated_data перед сохранением
        validated_data = serializer.validated_data
        temp_id = validated_data.pop('_tempId', None) # Сохраняем temp_id, если он был
        validated_data.pop('_isSending', None)

        try:
            # Сохраняем сообщение с текущим пользователем как отправителем
            instance = serializer.save(sender=self.request.user, chat=chat)
        except Exception as e:
            logger.error(f"Error saving message for chat {chat_pk}: {e}", exc_info=True)
            raise ValidationError(f"Failed to save message: {e}") # Пробрасываем как ошибку валидации

        # Обновляем last_message в чате
        Chat.objects.filter(pk=chat.pk).update(last_message=instance)
        logger.info(f"[Message PerformCreate] Updated last_message for chat {chat.pk} to message {instance.id}")

        # --- Отправка через WebSocket ---
        # Сериализуем созданное сообщение для отправки через WS
        message_data = MessageSerializer(instance, context=self.get_serializer_context()).data
        
        # Добавляем temp_id обратно в данные для WS, если он был, чтобы клиент мог сопоставить
        if temp_id:
            message_data['_tempIdEcho'] = temp_id # Используем другое имя, чтобы не путать

        # Используем экземпляр ChatViewSet для вызова его метода (или выносим notify_participants в utils)
        chat_viewset_instance = ChatViewSet() # Создаем временный экземпляр
        chat_viewset_instance.request = self.request # Передаем request, если он нужен в notify_participants

        # Отправляем сообщение всем участникам чата, включая эхо отправителю (если temp_id был)
        chat_viewset_instance.notify_participants(
            chat,
            message_data, # Сериализованное сообщение
            system=False
        )

        # --- Обновление счетчиков непрочитанных для ПОЛУЧАТЕЛЕЙ ---
        # Получаем всех участников чата, КРОМЕ отправителя
        recipients_to_notify_unread = chat.participants.filter(is_active=True).exclude(id=self.request.user.id)
        for recipient in recipients_to_notify_unread:
             try:
                 chat_viewset_instance.notify_user_unread_update(recipient, chat.pk)
             except Exception as e_notify_unread:
                 logger.error(f"Failed to send unread update to user {recipient.id} for chat {chat.pk} after new message: {e_notify_unread}", exc_info=True)

        # Основное уведомление через систему Notification (вызывается через сигнал post_save для Message)
        # поэтому здесь его дублировать не нужно.