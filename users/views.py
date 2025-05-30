from rest_framework import generics, viewsets, permissions, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser 
import logging
from rest_framework.permissions import IsAdminUser
import uuid
from datetime import timedelta
from django.conf import settings
from .utils import send_password_reset_email, send_confirmation_email
from django.utils.translation import gettext_lazy as _

from .models import Profile, InvitationCode
from .serializers import (
    PasswordResetConfirmSerializer, PasswordResetRequestSerializer, UserRegistrationSerializer, UserSerializer, ProfileSerializer, AdminUserUpdateSerializer,
    ChangePasswordSerializer, InvitationCodeSerializer
)
from .permissions import IsAdmin, IsOwnerOrAdmin, IsTeacherOrAdmin


logger = logging.getLogger(__name__)
User = get_user_model()

# Класс RegisterView обрабатывает запросы на регистрацию новых пользователей.
# Наследуется от generics.CreateAPIView, что обеспечивает базовый функционал для создания объектов.
# - queryset: Определяет набор данных, с которым работает представление (все пользователи).
# - serializer_class: Указывает сериализатор UserRegistrationSerializer для валидации и создания пользователя.
# - permission_classes: Разрешает доступ к этому эндпоинту всем пользователям (AllowAny).
# Метод create переопределен для формирования кастомного ответа после успешной регистрации,
# который включает сообщение о необходимости подтверждения email или об успешной активации по инвайт-коду,
# а также данные созданного пользователя.
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer) 
        
        user_data = serializer.data 
        headers = self.get_success_headers(user_data)
        
        if user_data.get('used_invitation_code', False):
            message = "Регистрация успешна! Ваш аккаунт активирован с помощью кода приглашения. Теперь вы можете войти."
        else:
            message = "Регистрация успешна. Пожалуйста, проверьте ваш email для подтверждения аккаунта."
            
        response_data = {
            "message": message,
            "user": user_data
        }
        
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

# Класс ConfirmEmailView обрабатывает запросы на подтверждение email пользователя.
# Наследуется от APIView для более гибкой обработки GET-запроса.
# - permission_classes: Разрешает доступ всем пользователям (AllowAny).
# Метод get вызывается при переходе по ссылке подтверждения с токеном.
# Он ищет пользователя по токену, проверяет срок действия токена, активирует пользователя,
# подтверждает его роль и очищает токен. Возвращает сообщение об успехе или ошибке.
class ConfirmEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, token, *args, **kwargs):
        try:
            user = User.objects.get(confirmation_token=token, is_active=False)
            
            if user.confirmation_token_expires_at and user.confirmation_token_expires_at < timezone.now():
                logger.warning(f"Attempt to confirm email with expired token for user {user.email}. Token: {token}")
                return Response({"error": "Срок действия токена подтверждения истек. Пожалуйста, запросите новый."}, status=status.HTTP_400_BAD_REQUEST)

            user.is_active = True
            user.is_role_confirmed = True
            user.confirmation_token = None
            user.confirmation_token_expires_at = None
            user.save(update_fields=['is_active', 'is_role_confirmed', 'confirmation_token', 'confirmation_token_expires_at'])
            logger.info(f"User {user.email} successfully confirmed email with token {token}")
            
            return Response({"message": "Email успешно подтвержден. Теперь вы можете войти."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            logger.warning(f"Invalid or already used confirmation token received: {token}")
            return Response({"error": "Недействительный токен подтверждения или email уже подтвержден."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error during email confirmation for token {token}: {e}", exc_info=True)
            return Response({"error": "Произошла ошибка при подтверждении email."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
# Класс UserProfileView предоставляет эндпоинт для просмотра и обновления профиля
# текущего аутентифицированного пользователя.
# Наследуется от generics.RetrieveUpdateAPIView.
# - serializer_class: Использует UserSerializer для отображения и обновления данных.
# - permission_classes: Требует, чтобы пользователь был аутентифицирован (IsAuthenticated).
# - parser_classes: Поддерживает парсинг JSON и multipart/form-data (для загрузки аватара).
# Метод get_object возвращает объект текущего пользователя.
# Метод partial_update переопределен для добавления логирования входящего запроса.
class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return self.request.user

    def partial_update(self, request, *args, **kwargs):
        logger.debug(f"--- [VIEW DEBUG] UserProfileView.partial_update ENTER ---")
        logger.debug(f"[VIEW DEBUG] Request Method: {request.method}")
        logger.debug(f"[VIEW DEBUG] Request User: {request.user}")
        logger.debug(f"[VIEW DEBUG] Request Content-Type: {request.content_type}")
        logger.debug(f"[VIEW DEBUG] Request Headers: {request.headers}")

        if 'application/json' in request.content_type:
            try:
                 logger.debug(f"[VIEW DEBUG] Request Data (JSON parsed): {request.data}")
            except Exception as e:
                 logger.error(f"[VIEW DEBUG] Error reading/parsing JSON request body: {e}")
                 logger.debug(f"[VIEW DEBUG] Raw request body: {request.body}")
        elif 'multipart/form-data' in request.content_type:
             logger.debug(f"[VIEW DEBUG] Request POST data (form fields): {request.POST}")
             logger.debug(f"[VIEW DEBUG] Request FILES data (uploaded files): {request.FILES}")
             logger.debug(f"[VIEW DEBUG] Request Data (parsed form): {request.data}")
        else:
            logger.warning(f"[VIEW DEBUG] Unexpected Content-Type: {request.content_type}. Raw body: {request.body}")
            logger.debug(f"[VIEW DEBUG] Request Data (parsed by DRF): {request.data}")

        logger.debug(f"--- [VIEW DEBUG] Calling super().partial_update ---")
        try:
            response = super().partial_update(request, *args, **kwargs)
            logger.debug(f"[VIEW DEBUG] super().partial_update finished. Status: {response.status_code}, Response Data: {response.data}")
            return response
        except Exception as e:
            logger.error(f"[VIEW DEBUG] !!! EXCEPTION during super().partial_update: {e.__class__.__name__} - {e}", exc_info=True)
            raise

# Класс UserViewSet предоставляет эндпоинты только для чтения (поиск, список) пользователей.
# Наследуется от viewsets.ReadOnlyModelViewSet.
# - serializer_class: Использует UserSerializer.
# - permission_classes: Требует аутентификации пользователя.
# - filter_backends, search_fields, filterset_fields, ordering_fields, ordering:
#   Настраивают возможности фильтрации, поиска и сортировки списка пользователей.
# Метод get_queryset определяет, каких пользователей может видеть запрашивающий:
# администраторы видят всех (кроме себя), обычные пользователи видят активных и подтвержденных (кроме себя).
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['email', 'first_name', 'last_name']
    filterset_fields = ['role']
    ordering_fields = ['email', 'last_name', 'first_name', 'date_joined']
    ordering = ['last_name', 'first_name']
    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
             return User.objects.select_related('profile').exclude(pk=user.pk)
        return User.objects.select_related('profile').filter(is_active=True, is_role_confirmed=True).exclude(pk=user.pk)

# Класс AdminUserViewSet предоставляет полный CRUD-функционал для управления пользователями,
# доступный только администраторам. Наследуется от viewsets.ModelViewSet.
# - queryset: Все пользователи с предзагрузкой профилей и связей (parents, children).
# - permission_classes: Требует аутентификации и прав администратора (IsAdmin).
# - Настройки фильтрации, поиска и сортировки аналогичны UserViewSet.
# Метод get_serializer_class выбирает сериализатор в зависимости от действия:
# AdminUserUpdateSerializer для обновления, UserSerializer для остальных.
# Дополнительное действие (action) 'initiate_password_reset' позволяет администратору
# инициировать сброс пароля для указанного пользователя. При этом генерируется токен,
# сохраняется в БД и пользователю отправляется email со ссылкой для сброса.
class AdminUserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.select_related('profile').prefetch_related('parents', 'children').all().order_by('id')
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['email', 'first_name', 'last_name']
    filterset_fields = ['role', 'is_active', 'is_role_confirmed']
    ordering_fields = ['id', 'email', 'last_name', 'first_name', 'date_joined', 'is_active', 'role', 'is_role_confirmed']
    ordering = ['id']

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        return UserSerializer

    @action(detail=True, methods=['post'], url_path='initiate-password-reset')
    def initiate_password_reset(self, request, pk=None):
        logger.info(f"Admin {request.user.email} initiating password reset for user ID: {pk}")
        target_user = self.get_object()

        if not target_user.is_active:
            logger.warning(f"Attempt to reset password for inactive user {target_user.email} (ID: {pk}) by admin {request.user.email}")
            return Response(
                {"error": _("Нельзя сбросить пароль для неактивного пользователя.")},
                status=status.HTTP_400_BAD_REQUEST
            )

        target_user.password_reset_token = uuid.uuid4()
        timeout_hours = getattr(settings, 'PASSWORD_RESET_TIMEOUT_HOURS', 24)
        target_user.password_reset_token_expires_at = timezone.now() + timedelta(hours=timeout_hours)
        
        try:
            target_user.save(update_fields=['password_reset_token', 'password_reset_token_expires_at'])
            logger.info(f"Password reset token generated for user {target_user.email} (ID: {pk}). Expires at: {target_user.password_reset_token_expires_at}")
        except Exception as e:
            logger.error(f"Error saving password reset token for user {target_user.email} (ID: {pk}): {e}", exc_info=True)
            return Response(
                {"error": _("Произошла ошибка при генерации токена сброса пароля.")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            send_password_reset_email(target_user)
            logger.info(f"Password reset email initiated for user {target_user.email} (ID: {pk}) by admin {request.user.email}")
        except Exception as e:
            logger.error(f"Failed to send password reset email to {target_user.email} (ID: {pk}) after token generation: {e}", exc_info=True)

        return Response(
            {"message": _(f"Письмо для сброса пароля было отправлено пользователю {target_user.email}.")},
            status=status.HTTP_200_OK
        )

# Класс ChangePasswordView обрабатывает запросы на смену пароля текущим
# аутентифицированным пользователем. Наследуется от generics.UpdateAPIView.
# - serializer_class: Использует ChangePasswordSerializer для валидации и смены пароля.
# - permission_classes: Требует аутентификации пользователя.
# Метод get_object возвращает объект текущего пользователя.
class ChangePasswordView(generics.UpdateAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_object(self):
        return self.request.user

# Класс InvitationCodeViewSet предоставляет CRUD-функционал для управления кодами приглашений.
# Наследуется от viewsets.ModelViewSet.
# - serializer_class: Использует InvitationCodeSerializer.
# - permission_classes (базовый): Требует аутентификации пользователя.
# Метод get_queryset определяет, какие коды видит пользователь: администраторы видят все,
# преподаватели видят только свои созданные коды, остальные не видят ничего.
# Метод perform_create устанавливает текущего пользователя как создателя кода.
# Метод get_permissions динамически назначает разрешения в зависимости от действия:
#   - create: IsTeacherOrAdmin (преподаватели или админы могут создавать).
#   - update, partial_update, destroy, retrieve: IsOwnerOrAdmin (владелец кода или админ).
#   - list: IsTeacherOrAdmin (преподаватели или админы могут просматривать списки кодов).
#   - другие действия: IsAdminUser (только админ).
class InvitationCodeViewSet(viewsets.ModelViewSet):
    serializer_class = InvitationCodeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return InvitationCode.objects.select_related('created_by', 'used_by').all().order_by('-created_at')
        elif user.is_teacher:
            return InvitationCode.objects.select_related('created_by', 'used_by').filter(created_by=user).order_by('-created_at')
        return InvitationCode.objects.none()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_permissions(self):
        if self.action == 'create':
            permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
        elif self.action in ['update', 'partial_update', 'destroy', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
        elif self.action == 'list':
             permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]
    
# Класс PasswordResetRequestView обрабатывает запросы на сброс пароля от неаутентифицированных пользователей.
# Наследуется от generics.GenericAPIView.
# - serializer_class: Использует PasswordResetRequestSerializer для валидации email.
# - permission_classes: Разрешает доступ всем пользователям (AllowAny).
# Метод post принимает email, ищет активного пользователя с таким email, генерирует для него
# токен сброса пароля и отправляет email с инструкциями. В целях безопасности,
# возвращает одинаковый успешный ответ независимо от того, найден ли email в системе.
class PasswordResetRequestView(generics.GenericAPIView):
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        try:
            user = User.objects.get(email=email, is_active=True)
            user.password_reset_token = uuid.uuid4()
            user.password_reset_token_expires_at = timezone.now() + timedelta(hours=settings.PASSWORD_RESET_TIMEOUT_HOURS or 1)
            user.save(update_fields=['password_reset_token', 'password_reset_token_expires_at'])
            send_password_reset_email(user)
        except User.DoesNotExist:
            pass
        return Response({"message": _("Если ваш email зарегистрирован, вы получите письмо с инструкциями по сбросу пароля.")}, status=status.HTTP_200_OK)

# Класс PasswordResetConfirmView обрабатывает подтверждение сброса пароля.
# Наследуется от generics.GenericAPIView.
# - serializer_class: Использует PasswordResetConfirmSerializer для валидации токена и нового пароля.
# - permission_classes: Разрешает доступ всем пользователям (AllowAny).
# Метод post принимает токен и новые пароли. Сериализатор проверяет токен,
# и если он валиден, метод save сериализатора устанавливает новый пароль для пользователя.
# Возвращает сообщение об успешной смене пароля.
class PasswordResetConfirmView(generics.GenericAPIView):
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": _("Пароль успешно изменен.")}, status=status.HTTP_200_OK)