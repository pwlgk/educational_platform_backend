from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Notification, UserNotificationSettings
from .serializers import NotificationSerializer, UserNotificationSettingsSerializer

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Просмотр уведомлений и управление статусом прочтения."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    # pagination_class = ... # Добавить пагинацию

    def get_queryset(self):
        # Только уведомления текущего пользователя
        return self.request.user.notifications.select_related('content_type').all()

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_as_read(self, request):
        """Пометить все непрочитанные уведомления пользователя как прочитанные."""
        updated_count = request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response({'status': 'Все уведомления помечены как прочитанные', 'updated_count': updated_count})

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_as_read(self, request, pk=None):
        """Пометить конкретное уведомление как прочитанное."""
        notification = self.get_object() # get_object сам проверит права, т.к. queryset отфильтрован
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
            return Response({'status': 'Уведомление помечено как прочитанное'})
        return Response({'status': 'Уведомление уже было прочитано'})

    @action(detail=True, methods=['post'], url_path='mark-unread')
    def mark_as_unread(self, request, pk=None):
        """Пометить конкретное уведомление как непрочитанное."""
        notification = self.get_object()
        if notification.is_read:
            notification.is_read = False
            notification.save(update_fields=['is_read'])
            return Response({'status': 'Уведомление помечено как непрочитанное'})
        return Response({'status': 'Уведомление уже было непрочитано'})

class UserNotificationSettingsView(generics.RetrieveUpdateAPIView):
    """Получение и обновление настроек уведомлений пользователя."""
    serializer_class = UserNotificationSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Возвращаем или создаем настройки для текущего пользователя
        settings, created = UserNotificationSettings.objects.get_or_create(user=self.request.user)
        return settings