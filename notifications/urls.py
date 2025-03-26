from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'list', views.NotificationViewSet, basename='notification-list')

urlpatterns = [
    path('settings/', views.UserNotificationSettingsView.as_view(), name='notification-settings'),
    path('', include(router.urls)),
]