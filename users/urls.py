# users/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
# Импортируем ВСЕ нужные views
from . import views

# --- Роутер для ОБЩИХ пользовательских эндпоинтов ---
# (поиск пользователей, возможно, другие действия в будущем)
user_router = DefaultRouter()
# Регистрируем UserViewSet на пустой префикс '' внутри этого роутера
# Итоговый путь будет /api/users/ (из главного urls.py)
user_router.register(r'users', views.UserViewSet, basename='user') # Изменил basename для ясности

# --- Роутер для АДМИНСКИХ эндпоинтов ---
admin_router = DefaultRouter()
# Регистрируем AdminUserViewSet на префикс 'admin/users'
# Итоговый путь будет /api/users/admin/users/
admin_router.register(r'admin/users', views.AdminUserViewSet, basename='admin-user')
# Регистрируем InvitationCodeViewSet на префикс 'admin/invitations'
# Итоговый путь будет /api/users/admin/invitations/
admin_router.register(r'admin/invitations', views.InvitationCodeViewSet, basename='admin-invitation')

urlpatterns = [
    # Эндпоинты JWT (оставляем здесь, если они специфичны для users)
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('login/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Регистрация и подтверждение
    path('register/', views.RegisterView.as_view(), name='register'),
    path('confirm/<uuid:token>/', views.ConfirmEmailView.as_view(), name='confirm-email'),

    # Управление профилем и паролем
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),

    # Включаем ОБА роутера
    # Общий роутер будет доступен по /api/users/ (из главного urls.py)
    path('', include(user_router.urls)),
    # Админский роутер будет доступен по /api/users/admin/users/ и /api/users/admin/invitations/
    # (префикс /api/users/ берется из главного urls.py)
    path('', include(admin_router.urls)), # Префикс админских путей уже задан в router.register
]