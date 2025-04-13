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

from .models import Profile, InvitationCode
from .serializers import (
    UserRegistrationSerializer, UserSerializer, ProfileSerializer,
    ChangePasswordSerializer, InvitationCodeSerializer
)
# Импортируем все необходимые пермишены
from .permissions import IsOwnerOrAdmin, IsTeacherOrAdmin # Ваши кастомные
# permissions импортируется как permissions (из rest_framework)

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
    permission_classes = [permissions.IsAuthenticated] # Стандартный DRF пермишен
    def get_object(self):
        return self.request.user

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
class AdminUserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.select_related('profile').all().order_by('id')
    serializer_class = UserSerializer
    # --- ИСПРАВЛЕНИЕ: Используем стандартный IsAdminUser ---
    permission_classes = [permissions.IsAdminUser]
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['email', 'first_name', 'last_name']
    filterset_fields = ['role', 'is_active', 'is_role_confirmed']
    ordering_fields = ['id', 'email', 'last_name', 'first_name', 'date_joined', 'is_active', 'role']
    ordering = ['id']

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