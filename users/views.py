# users/views.py
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


from .models import Profile, InvitationCode
from .serializers import (
    UserRegistrationSerializer, UserSerializer, ProfileSerializer, AdminUserUpdateSerializer,
    ChangePasswordSerializer, InvitationCodeSerializer
)
# Импортируем все необходимые пермишены
from .permissions import IsOwnerOrAdmin, IsTeacherOrAdmin # Ваши кастомные
# permissions импортируется как permissions (из rest_framework)

logger = logging.getLogger(__name__)

User = get_user_model()

# --- RegisterView ---
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

# --- ConfirmEmailView ---
class ConfirmEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, token, *args, **kwargs):
        user = get_object_or_404(User, confirmation_token=token, is_active=False)
        # ... (логика активации) ...
        user.save(update_fields=['is_active', 'is_role_confirmed', 'confirmation_token', 'confirmation_token_expires_at'])
        return Response({"message": "Email успешно подтвержден."}, status=status.HTTP_200_OK)

# --- UserProfileView ---
class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    # Убедитесь, что парсеры включены для обработки и JSON, и FormData
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        # Возвращает текущего аутентифицированного пользователя
        return self.request.user

    # Переопределяем partial_update для логирования
    def partial_update(self, request, *args, **kwargs):
        logger.debug(f"--- [VIEW DEBUG] UserProfileView.partial_update ENTER ---")
        logger.debug(f"[VIEW DEBUG] Request Method: {request.method}")
        logger.debug(f"[VIEW DEBUG] Request User: {request.user}")
        logger.debug(f"[VIEW DEBUG] Request Content-Type: {request.content_type}")
        logger.debug(f"[VIEW DEBUG] Request Headers: {request.headers}") # Логируем все заголовки

        # Логируем данные в зависимости от типа контента
        if 'application/json' in request.content_type:
            try:
                 # request.data уже распарсенный JSON (или пустой dict, если тело пустое)
                 logger.debug(f"[VIEW DEBUG] Request Data (JSON parsed): {request.data}")
            except Exception as e:
                 logger.error(f"[VIEW DEBUG] Error reading/parsing JSON request body: {e}")
                 logger.debug(f"[VIEW DEBUG] Raw request body: {request.body}") # Логируем сырое тело
        elif 'multipart/form-data' in request.content_type:
             logger.debug(f"[VIEW DEBUG] Request POST data (form fields): {request.POST}") # Текстовые поля
             logger.debug(f"[VIEW DEBUG] Request FILES data (uploaded files): {request.FILES}") # Файлы
             # request.data в этом случае тоже будет содержать текстовые поля
             logger.debug(f"[VIEW DEBUG] Request Data (parsed form): {request.data}")
        else:
            logger.warning(f"[VIEW DEBUG] Unexpected Content-Type: {request.content_type}. Raw body: {request.body}")
            logger.debug(f"[VIEW DEBUG] Request Data (parsed by DRF): {request.data}")


        logger.debug(f"--- [VIEW DEBUG] Calling super().partial_update ---")
        try:
            # Вызываем стандартную логику RetrieveUpdateAPIView,
            # которая вызовет serializer.is_valid() и serializer.save() (-> serializer.update)
            response = super().partial_update(request, *args, **kwargs)
            logger.debug(f"[VIEW DEBUG] super().partial_update finished. Status: {response.status_code}, Response Data: {response.data}")
            return response
        except Exception as e:
            # Логируем исключение, которое могло возникнуть ВНУТРИ super().partial_update
            # (например, ошибка валидации сериализатора или ошибка в serializer.update)
            logger.error(f"[VIEW DEBUG] !!! EXCEPTION during super().partial_update: {e.__class__.__name__} - {e}", exc_info=True)
            raise # Пробрасываем исключение дальше для стандартной обработки ошибок DRF

# --- UserViewSet (для поиска) ---
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated] # Стандартный DRF пермишен
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['email', 'first_name', 'last_name']
    filterset_fields = ['role']
    ordering_fields = ['email', 'last_name', 'first_name', 'date_joined']
    ordering = ['last_name', 'first_name']
    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            # Админ ищет среди всех, кроме себя
             return User.objects.select_related('profile').exclude(pk=user.pk)
        # Обычный пользователь ищет среди активных, кроме себя
        return User.objects.select_related('profile').filter(is_active=True, is_role_confirmed=True).exclude(pk=user.pk)

# --- AdminUserViewSet (только для админов) ---
class AdminUserViewSet(viewsets.ModelViewSet): # <-- ИЗМЕНЕНО на ModelViewSet
    """
    CRUD для пользователей (только для Админов).
    Позволяет просматривать, редактировать (роль, статус, связи) пользователей.
    """
    queryset = User.objects.select_related('profile').prefetch_related('parents', 'children').all().order_by('id') # Добавил prefetch_related
    permission_classes = [IsAdminUser] # Только админ может управлять всеми пользователями
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['email', 'first_name', 'last_name']
    filterset_fields = ['role', 'is_active', 'is_role_confirmed']
    ordering_fields = ['id', 'email', 'last_name', 'first_name', 'date_joined', 'is_active', 'role', 'is_role_confirmed']
    ordering = ['id']
    # parser_classes = [JSONParser] # Оставляем только JSON, т.к. аватар меняется через профиль

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            # Используем AdminUserUpdateSerializer для PUT/PATCH админом
            return AdminUserUpdateSerializer
        # Для list, retrieve используем UserSerializer
        return UserSerializer


# --- ChangePasswordView ---
class ChangePasswordView(generics.UpdateAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated] # Стандартный DRF пермишен
    def get_object(self):
        return self.request.user

# --- InvitationCodeViewSet ---
class InvitationCodeViewSet(viewsets.ModelViewSet):
    serializer_class = InvitationCodeSerializer
    permission_classes = [permissions.IsAuthenticated] # Базовый

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return InvitationCode.objects.select_related('created_by', 'used_by').all().order_by('-created_at')
        # Используем property is_teacher из модели User
        elif user.is_teacher:
            return InvitationCode.objects.select_related('created_by', 'used_by').filter(created_by=user).order_by('-created_at')
        return InvitationCode.objects.none()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_permissions(self):
        if self.action == 'create':
            # Используем импортированный кастомный пермишен
            permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
        elif self.action in ['update', 'partial_update', 'destroy', 'retrieve']: # Добавил retrieve
            # Используем импортированный кастомный пермишен
            permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
        elif self.action == 'list':
             # Используем импортированный кастомный пермишен
             permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
        else:
            # Для неизвестных actions - только админ
            permission_classes = [permissions.IsAdminUser] # Используем стандартный
        return [permission() for permission in permission_classes]