from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Создается экземпляр DefaultRouter из Django REST framework.
# Роутеры используются для автоматической генерации URL-паттернов для ViewSet'ов.
router = DefaultRouter()

# Регистрируется NotificationViewSet с префиксом 'list' и базовым именем 'notification-list'.
# - r'list': Префикс URL для эндпоинтов, связанных с NotificationViewSet.
#   Например, список уведомлений будет доступен по URL, оканчивающемуся на 'list/'.
# - views.NotificationViewSet: ViewSet, который будет обрабатывать запросы для этих эндпоинтов.
# - basename='notification-list': Базовое имя, используемое для генерации имен URL-паттернов.
#   Это полезно, если ViewSet не имеет атрибута `queryset` или если нужно переопределить
#   автоматически генерируемое имя.
router.register(r'list', views.NotificationViewSet, basename='notification-list')

# Список urlpatterns определяет URL-маршруты для модуля 'notifications'.
# Префикс для всех этих маршрутов (например, '/api/notifications/') обычно задается
# в корневом файле urls.py проекта при включении данного urlpatterns.
urlpatterns = [
    # Маршрут для управления настройками уведомлений пользователя.
    # - 'settings/': URL-путь для доступа к настройкам.
    # - views.UserNotificationSettingsView.as_view(): Представление (APIView или GenericView),
    #   которое обрабатывает запросы на просмотр и изменение настроек уведомлений.
    # - name='notification-settings': Имя URL-паттерна, которое можно использовать для
    #   обратного разрешения URL (например, в шаблонах или тестах).
    path('settings/', views.UserNotificationSettingsView.as_view(), name='notification-settings'),

    # Включение URL-адресов, сгенерированных роутером 'router'.
    # Это добавит в urlpatterns все URL-адреса, определенные NotificationViewSet
    # (например, для получения списка уведомлений, отметки уведомлений как прочитанных).
    path('', include(router.urls)),
]