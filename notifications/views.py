from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Notification, UserNotificationSettings
from .serializers import NotificationSerializer, UserNotificationSettingsSerializer
from rest_framework.pagination import LimitOffsetPagination

# Класс StandardNotificationsPagination определяет кастомную пагинацию для списка уведомлений.
# Наследуется от LimitOffsetPagination, которая позволяет клиенту контролировать
# количество элементов на странице (limit) и смещение (offset).
# - default_limit: Количество уведомлений, отображаемых на странице по умолчанию (20).
# - max_limit: Максимальное количество уведомлений, которое клиент может запросить на одной странице (100).
class StandardNotificationsPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100

# Класс NotificationViewSet предоставляет API-эндпоинты для управления уведомлениями.
# Наследуется от viewsets.ModelViewSet, что обеспечивает CRUD-операции, но в данном
# случае основное внимание уделяется чтению и изменению статуса прочтения.
# - serializer_class: Использует NotificationSerializer для преобразования данных уведомлений.
# - permission_classes: Требует, чтобы пользователь был аутентифицирован (IsAuthenticated).
# - pagination_class: Использует кастомную пагинацию StandardNotificationsPagination.
# Метод get_queryset:
#   - Возвращает QuerySet уведомлений, принадлежащих текущему аутентифицированному пользователю.
#   - Выполняет `select_related('content_type')` для оптимизации запросов к базе данных
#     при доступе к связанным объектам ContentType (используется для GenericForeignKey).
# Кастомные действия (@action):
#   - mark_all_as_read:
#     - URL: `notifications/list/mark-all-read/` (POST-запрос)
#     - Позволяет пользователю пометить все свои непрочитанные уведомления как прочитанные.
#     - Обновляет поле `is_read` для соответствующих уведомлений и возвращает количество обновленных записей.
#   - mark_as_read:
#     - URL: `notifications/list/{pk}/mark-read/` (POST-запрос)
#     - Позволяет пользователю пометить конкретное уведомление (по его `pk`) как прочитанное.
#     - Если уведомление уже прочитано, возвращает соответствующий статус.
#   - mark_as_unread:
#     - URL: `notifications/list/{pk}/mark-unread/` (POST-запрос)
#     - Позволяет пользователю пометить конкретное уведомление как непрочитанное.
#     - Если уведомление уже не прочитано, возвращает соответствующий статус.
class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardNotificationsPagination 

    def get_queryset(self):
        return self.request.user.notifications.select_related('content_type').all()

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_as_read(self, request):
        updated_count = request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response({'status': 'Все уведомления помечены как прочитанные', 'updated_count': updated_count})

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
            return Response({'status': 'Уведомление помечено как прочитанное'})
        return Response({'status': 'Уведомление уже было прочитано'})

    @action(detail=True, methods=['post'], url_path='mark-unread')
    def mark_as_unread(self, request, pk=None):
        notification = self.get_object()
        if notification.is_read:
            notification.is_read = False
            notification.save(update_fields=['is_read'])
            return Response({'status': 'Уведомление помечено как непрочитанное'})
        return Response({'status': 'Уведомление уже было непрочитано'})

# Класс UserNotificationSettingsView предоставляет API-эндпоинт для получения
# и обновления настроек уведомлений текущего аутентифицированного пользователя.
# Наследуется от generics.RetrieveUpdateAPIView, что обеспечивает функционал
# для просмотра (GET) и обновления (PUT/PATCH) одного объекта.
# - serializer_class: Использует UserNotificationSettingsSerializer для преобразования данных настроек.
# - permission_classes: Требует, чтобы пользователь был аутентифицирован (IsAuthenticated).
# Метод get_object:
#   - Возвращает объект UserNotificationSettings, связанный с текущим пользователем.
#   - Если настройки для пользователя еще не существуют, они автоматически создаются
#     с использованием метода `get_or_create`.
class UserNotificationSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = UserNotificationSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        settings, created = UserNotificationSettings.objects.get_or_create(user=self.request.user)
        return settings