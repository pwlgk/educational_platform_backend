from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from . import views

router = DefaultRouter()
router.register(r'admin/users', views.UserViewSet, basename='user-admin-list') # Список пользователей для админа
router.register(r'admin/invitations', views.InvitationCodeViewSet, basename='invitation-code') # Управление кодами

urlpatterns = [
    # Стандартные эндпоинты JWT
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('login/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Регистрация и подтверждение
    path('register/', views.RegisterView.as_view(), name='register'),
    path('confirm/<uuid:token>/', views.ConfirmEmailView.as_view(), name='confirm-email'), # Маршрут для подтверждения

    # Управление профилем и паролем
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),

    # Роутер для админских вьюсетов
    path('', include(router.urls)),
]