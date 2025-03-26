from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db.models import Max # Для обновления last_read_message
from .models import Chat, Message, ChatParticipant
from .serializers import ChatSerializer, MessageSerializer, MarkReadSerializer
from users.permissions import IsAdmin # Импортируем права из users

class ChatViewSet(viewsets.ModelViewSet):
    """Управление чатами (список, создание, детали)."""
    serializer_class = ChatSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Пользователь видит только те чаты, в которых он участвует
        return self.request.user.chats.prefetch_related(
            'participants', 'messages', 'last_message__sender' # Оптимизация
        ).select_related('last_message').all() # Загружаем связанные объекты

    # Метод create обрабатывается логикой сериализатора ChatSerializer

    # Опционально: добавление/удаление участников (для админов или создателей групп)
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin]) # Пример: только админ
    def add_participant(self, request, pk=None):
        chat = self.get_object()
        if chat.chat_type == Chat.ChatType.PRIVATE:
            return Response({'error': 'Нельзя добавить участников в личный чат.'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_to_add = User.objects.get(pk=user_id)
            # Проверка, не является ли пользователь уже участником
            if chat.participants.filter(pk=user_to_add.pk).exists():
                 return Response({'status': 'Пользователь уже в чате.'}, status=status.HTTP_200_OK)

            ChatParticipant.objects.create(user=user_to_add, chat=chat)
            # TODO: Отправить уведомление новому участнику и остальным
            return Response({'status': 'Пользователь добавлен.'}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'error': 'Пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], permission_classes=[IsAdmin]) # Пример: только админ
    def remove_participant(self, request, pk=None):
        chat = self.get_object()
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'Необходимо указать "user_id".'}, status=status.HTTP_400_BAD_REQUEST)

        # Нельзя удалить создателя? Или последнего участника? Добавить логику если нужно.

        deleted_count, _ = ChatParticipant.objects.filter(chat=chat, user_id=user_id).delete()
        if deleted_count > 0:
            # TODO: Отправить уведомление удаленному участнику и остальным
            return Response({'status': 'Пользователь удален.'}, status=status.HTTP_204_NO_CONTENT)
        else:
            return Response({'error': 'Пользователь не найден в этом чате.'}, status=status.HTTP_404_NOT_FOUND)

    # Пометка сообщений прочитанными
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        chat = self.get_object() # Получаем чат
        serializer = MarkReadSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            try:
                serializer.save(chat_id=chat.id) # Передаем ID чата в save
                return Response({'status': 'Сообщения отмечены как прочитанные.'}, status=status.HTTP_200_OK)
            except serializers.ValidationError as e:
                 return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e: # Ловим другие возможные ошибки
                 return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MessageViewSet(viewsets.ModelViewSet):
    """Просмотр и отправка сообщений в конкретном чате."""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    # Пагинация для сообщений
    # pagination_class = ... # Добавить класс пагинации, если нужно

    def get_queryset(self):
        # Фильтруем сообщения по ID чата из URL
        chat_id = self.kwargs.get('chat_pk') # Получаем chat_pk из URL
        # Проверяем, является ли пользователь участником этого чата
        if not self.request.user.chats.filter(pk=chat_id).exists():
            return Message.objects.none() # Не показывать сообщения, если не участник

        return Message.objects.filter(chat_id=chat_id).select_related('sender').order_by('-timestamp') # Сначала новые для отображения

    def perform_create(self, serializer):
        chat_id = self.kwargs.get('chat_pk')
        chat = get_object_or_404(Chat, pk=chat_id)
        # Еще раз проверяем участие пользователя (на всякий случай)
        if not chat.participants.filter(pk=self.request.user.pk).exists():
             # Используем метод permission_denied для корректной ошибки
             self.permission_denied(self.request, message='Вы не являетесь участником этого чата.')

        instance = serializer.save(sender=self.request.user, chat=chat)

        # TODO: Отправить сообщение через WebSocket всем участникам чата, кроме отправителя
        # send_message_via_websocket(instance)
        # TODO: Отправить уведомление (push/email) участникам (опционально)
        # send_new_message_notification(instance)