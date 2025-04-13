# messaging/views.py
from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db.models import Max, Q # Q импортирован, но не используется здесь
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied, ValidationError # Импортируем ValidationError
from .models import Chat, Message, ChatParticipant
# Убедитесь, что импортируете ВСЕ нужные сериализаторы
from .serializers import ChatSerializer, MessageSerializer, MarkReadSerializer
from users.permissions import IsAdmin # Используем пермишен

# Импорты для Channels (раскомментируйте, когда будете реализовывать WS)
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

User = get_user_model()

class ChatViewSet(viewsets.ModelViewSet):
    """Управление чатами (список, создание, детали)."""
    serializer_class = ChatSerializer
    permission_classes = [permissions.IsAuthenticated] # Доступ только для аутентифицированных

    def get_queryset(self):
        # Пользователь видит только те чаты, в которых он участвует
        # distinct() нужен при фильтрации по ManyToMany через prefetch_related
        # Убираем select_related для last_message, т.к. сериализатор может его подгрузить
        return self.request.user.chats.prefetch_related(
            'participants',
            'last_message__sender' # Подгружаем отправителя последнего сообщения
        ).distinct().order_by('-last_message__timestamp') # Сортируем по последнему сообщению

    # perform_create не нужен, если вся логика в сериализаторе
    # def perform_create(self, serializer):
    #     # Сериализатор должен сам обработать participants и добавить request.user
    #     serializer.save() # Возможно, нужно передать user: serializer.save(creator=self.request.user) если есть поле creator

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated]) # Разрешим участникам добавлять? Или оставить IsAdmin?
    def add_participant(self, request, pk=None):
        chat = self.get_object()
        # Дополнительная проверка прав: либо админ, либо создатель чата (если есть поле creator)
        # if not (request.user.is_staff or chat.creator == request.user):
        #     raise PermissionDenied("Только создатель или администратор могут добавлять участников.")

        if chat.chat_type == Chat.ChatType.PRIVATE:
            return Response({'error': 'Нельзя добавить участников в личный чат.'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_to_add = User.objects.get(pk=user_id)
            if chat.participants.filter(pk=user_to_add.pk).exists():
                 return Response({'detail': 'Пользователь уже в чате.'}, status=status.HTTP_400_BAD_REQUEST)

            chat.participants.add(user_to_add)
            # Если используется ChatParticipant модель:
            # ChatParticipant.objects.get_or_create(user=user_to_add, chat=chat)

            # TODO: Отправить уведомление через WebSocket
            # self.notify_participants(chat, f'User {user_to_add.username} joined the chat.')

            # Возвращаем обновленный чат
            serializer = self.get_serializer(chat)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'error': 'Пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             return Response({'error': f'Ошибка добавления участника: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated]) # Разрешить участникам удалять? Или только админ/создатель?
    def remove_participant(self, request, pk=None):
        chat = self.get_object()
        # Дополнительная проверка прав
        # if not (request.user.is_staff or chat.creator == request.user):
        #     raise PermissionDenied("Только создатель или администратор могут удалять участников.")

        user_id_to_remove = request.data.get('user_id')
        if not user_id_to_remove:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)

        # Запрет удаления самого себя через этот эндпоинт (пусть будет leave_chat)
        if str(request.user.id) == str(user_id_to_remove):
             return Response({'error': 'Вы не можете удалить себя этим методом.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_to_remove = User.objects.get(pk=user_id_to_remove)

            if not chat.participants.filter(pk=user_to_remove.pk).exists():
                 return Response({'error': 'Пользователь не найден в этом чате.'}, status=status.HTTP_404_NOT_FOUND)

            # Проверки на удаление создателя или последнего участника
            # if chat.creator == user_to_remove: ...
            if chat.participants.count() <= 1: # Нельзя удалить единственного участника
                 return Response({'error': 'Нельзя удалить единственного участника.'}, status=status.HTTP_400_BAD_REQUEST)

            chat.participants.remove(user_to_remove)
            # Если используется ChatParticipant:
            # ChatParticipant.objects.filter(chat=chat, user=user_to_remove).delete()

            # TODO: Отправить уведомление через WebSocket
            # self.notify_participants(chat, f'User {user_to_remove.username} left the chat.')

            serializer = self.get_serializer(chat)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except User.DoesNotExist:
             return Response({'error': 'Удаляемый пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             return Response({'error': f'Ошибка удаления участника: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        chat = get_object_or_404(self.get_queryset(), pk=pk) # Проверяем доступ через get_queryset

        # Используем сериализатор для валидации и сохранения (предполагается, что он есть и работает)
        serializer = MarkReadSerializer(data=request.data, context={'request': request, 'chat': chat})
        if serializer.is_valid():
            try:
                serializer.save() # Логика внутри сериализатора
                return Response({'status': 'Чат отмечен как прочитанный.'}, status=status.HTTP_200_OK)
            except ValidationError as e: # Ловим ошибки валидации из сериализатора
                 return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                 # Ловим другие возможные ошибки из serializer.save()
                 print(f"Error in mark_read save: {e}") # Логируем ошибку
                 return Response({'error': 'Не удалось обновить статус прочтения.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Вспомогательная функция для отправки WS уведомлений участникам чата (пример)
    # def notify_participants(self, chat, message_text):
    #     try:
    #         channel_layer = get_channel_layer()
    #         group_name = f"chat_{chat.pk}"
    #         async_to_sync(channel_layer.group_send)(
    #             group_name,
    #             {
    #                 "type": "chat.system_message", # Другой тип для системных сообщений
    #                 "message": message_text,
    #             },
    #         )
    #     except Exception as e:
    #         print(f"Failed to send WS notification for chat {chat.pk}: {e}")


class MessageViewSet(viewsets.ModelViewSet):
    """Просмотр и отправка сообщений в конкретном чате."""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # pagination_class = YourMessagePaginationClass # Раскомментируйте и настройте пагинацию

    def get_queryset(self):
        chat_pk = self.kwargs.get('chat_pk')
        if not chat_pk:
            return Message.objects.none()

        try:
            # Проверяем, что пользователь участник чата
            get_object_or_404(self.request.user.chats, pk=chat_pk)
        except Chat.DoesNotExist:
             raise PermissionDenied("Вы не являетесь участником этого чата или чат не существует.")

        # Возвращаем сообщения, старые сверху (для UI чата)
        return Message.objects.filter(chat_id=chat_pk).select_related('sender').order_by('timestamp')

    def perform_create(self, serializer):
        chat_pk = self.kwargs.get('chat_pk')
        # Получаем чат и проверяем участие
        chat = get_object_or_404(self.request.user.chats, pk=chat_pk)

        # Сохраняем сообщение
        try:
            instance = serializer.save(sender=self.request.user, chat=chat)
        except Exception as e:
            # Ловим возможные ошибки при сохранении сообщения
            print(f"Error saving message for chat {chat_pk}: {e}")
            raise ValidationError(f"Не удалось сохранить сообщение: {e}") # Возвращаем ошибку валидации

        # Обновляем last_message в чате
        # Используем update для атомарности и производительности
        Chat.objects.filter(pk=chat.pk).update(last_message=instance)
        print(f"[perform_create] Updated last_message for chat {chat.pk}")

        # --- ОТПРАВКА ЧЕРЕЗ WEBSOCKET ---
        try:
            channel_layer = get_channel_layer()
            group_name = f"chat_{chat.pk}" # Имя группы = chat_ID_чата
            # Пере-сериализуем сохраненный instance, чтобы получить все поля (особенно ID и timestamp)
            message_data = MessageSerializer(instance).data

            print(f"[perform_create] Sending message to WS group: {group_name}, Data: {message_data}")

            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "chat.message", # Этот тип должен обрабатываться в ChatConsumer
                    "message": message_data,
                },
            )
            print(f"[perform_create] Message sent to WS group: {group_name}")
        except Exception as e:
            # Логируем ошибку, но не прерываем HTTP ответ из-за ошибки WS
            print(f"!!! ERROR sending message via WebSocket for chat {chat.pk}: {e}")
            # В продакшене здесь должен быть более надежный логгер
        # --- КОНЕЦ ОТПРАВКИ ЧЕРЕЗ WEBSOCKET ---

        # TODO: Отправить уведомление (push/email) участникам (опционально)
        