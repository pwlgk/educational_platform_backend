from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from . import views

# Создается экземпляр DefaultRouter для управления URL-адресами,
# связанными с общими операциями над пользователями.
# ViewSet 'UserViewSet' регистрируется с префиксом 'users'.
# Это означает, что URL-адреса для этого ViewSet (например, список пользователей, детали пользователя)
# будут доступны по путям, начинающимся с 'users/' (относительно префикса,
# с которым этот роутер будет включен в главный urls.py, например, /api/users/users/).
# 'basename' используется для генерации имен URL-паттернов.
user_router = DefaultRouter()
user_router.register(r'users', views.UserViewSet, basename='user')

# Создается отдельный экземпляр DefaultRouter для URL-адресов,
# предназначенных для административных действий над пользователями и кодами приглашений.
# 'AdminUserViewSet' регистрируется с префиксом 'admin/users', что формирует URL-адреса
# вида 'admin/users/' для администрирования пользователей.
# 'InvitationCodeViewSet' регистрируется с префиксом 'admin/invitations',
# формируя URL-адреса вида 'admin/invitations/' для управления кодами приглашений.
# Эти префиксы также будут относительны главному префиксу приложения.
admin_router = DefaultRouter()
admin_router.register(r'admin/users', views.AdminUserViewSet, basename='admin-user')
admin_router.register(r'admin/invitations', views.InvitationCodeViewSet, basename='admin-invitation')

# Список urlpatterns определяет основные URL-маршруты для приложения 'users'.
# Префикс для всех этих маршрутов (например, '/api/users/') обычно задается
# в корневом файле urls.py проекта при включении данного urlpatterns.
urlpatterns = [
    # Маршруты для аутентификации с использованием JWT (JSON Web Tokens).
    # 'login/': Получение пары токенов (access и refresh) при успешном входе.
    # 'login/refresh/': Обновление access-токена с использованием refresh-токена.
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('login/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Маршруты для регистрации нового пользователя и подтверждения email.
    # 'register/': Регистрация нового пользователя.
    # 'confirm/<uuid:token>/': Подтверждение email пользователя с использованием уникального токена.
    path('register/', views.RegisterView.as_view(), name='register'),
    path('confirm/<uuid:token>/', views.ConfirmEmailView.as_view(), name='confirm-email'),

    # Маршруты для управления профилем пользователя и его паролем.
    # 'profile/': Просмотр и редактирование профиля текущего аутентифицированного пользователя.
    # 'change-password/': Смена пароля текущим аутентифицированным пользователем.
    # 'password-reset/': Запрос на сброс пароля (обычно отправка email с инструкциями).
    # 'password-reset/confirm/': Подтверждение сброса пароля с использованием токена и установка нового пароля.
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    
    # Включение URL-адресов, сгенерированных роутерами.
    # URL-адреса из 'user_router' (например, 'users/') будут доступны напрямую
    # относительно главного префикса приложения.
    path('', include(user_router.urls)),
    # URL-адреса из 'admin_router' (например, 'admin/users/', 'admin/invitations/') также
    # будут доступны напрямую относительно главного префикса приложения,
    # так как их префиксы 'admin/...' уже заданы при регистрации ViewSet'ов в роутере.
    path('', include(admin_router.urls)),
]