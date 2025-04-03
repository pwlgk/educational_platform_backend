from rest_framework import generics, viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model # Получаем кастомную модель User
from .models import Profile, InvitationCode
from .serializers import (
    UserRegistrationSerializer, UserSerializer, ProfileSerializer,
    ChangePasswordSerializer, InvitationCodeSerializer
)
from .permissions import IsOwnerOrAdmin, IsAdmin, IsTeacherOrAdmin

User = get_user_model()

class RegisterView(generics.CreateAPIView):
    """Регистрация нового пользователя."""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny] # Разрешить всем

    def perform_create(self, serializer):
        # Сериализатор сам обрабатывает создание и отправку email (пока TODO)
        serializer.save()
        # Можно вернуть кастомный ответ
        # return Response({"message": "Регистрация успешна. Проверьте email для подтверждения."}, status=status.HTTP_201_CREATED)


class ConfirmEmailView(APIView):
    """Подтверждение email пользователя по токену."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, token, *args, **kwargs):
        try:
            user = User.objects.get(confirmation_token=token, is_active=False)
            user.is_active = True
            user.is_role_confirmed = True # Считаем, что email подтверждает и роль
            user.confirmation_token = None # Убираем токен после использования
            user.save()
            return Response({"message": "Email успешно подтвержден."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "Недействительный или истекший токен подтверждения."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Произошла ошибка: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """Просмотр и ОБНОВЛЕНИЕ данных ТЕКУЩЕГО пользователя (включая профиль)."""
    serializer_class = UserSerializer # Используем обновленный UserSerializer
    permission_classes = [permissions.IsAuthenticated] # Достаточно, т.к. get_object гарантирует работу только с request.user

    def get_queryset(self):
        # Возвращаем queryset для User, отфильтрованный по текущему пользователю
        return User.objects.filter(pk=self.request.user.pk)

    def get_object(self):
        # Всегда возвращаем объект ТЕКУЩЕГО пользователя (request.user)
        # Это гарантирует, что пользователь может редактировать только свой профиль
        user = self.request.user
        # Проверки прав на объект (вроде IsOwnerOrAdmin) здесь избыточны,
        # так как мы жестко привязаны к request.user.
        # self.check_object_permissions(self.request, user) # Можно раскомментировать, если есть специфичные проверки
        return user


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Просмотр списка пользователей (только для админов)."""
    queryset = User.objects.select_related('profile').all().order_by('id') # Оптимизация запроса
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin] # Только админы могут видеть всех


class ChangePasswordView(generics.UpdateAPIView):
    """Смена пароля для аутентифицированного пользователя."""
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        self.object = self.get_object()
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Пароль успешно изменен."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InvitationCodeViewSet(viewsets.ModelViewSet):
    """CRUD для кодов приглашения (только для Админов/Преподавателей)."""
    serializer_class = InvitationCodeSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin] # Создавать могут учителя и админы

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return InvitationCode.objects.all().order_by('-created_at')
        elif user.is_teacher:
            # Учитель видит только свои коды
            return InvitationCode.objects.filter(created_by=user).order_by('-created_at')
        return InvitationCode.objects.none() # Другие роли не видят

    def perform_create(self, serializer):
        # Создатель передается в сериализатор через context
        serializer.save(created_by=self.request.user)

    # Опционально: запретить учителям удалять/редактировать чужие коды (хотя queryset уже фильтрует)
    def get_permissions(self):
         if self.action in ['update', 'partial_update', 'destroy']:
             # Редактировать/удалять может только создатель или админ
             return [permissions.IsAuthenticated(), IsOwnerOrAdmin()] # IsOwnerOrAdmin проверит created_by
         return super().get_permissions()