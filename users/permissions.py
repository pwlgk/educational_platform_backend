from rest_framework import permissions
from .models import User

class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Разрешает доступ только владельцу объекта или администратору.
    Требует, чтобы у объекта был атрибут 'user'.
    """
    def has_object_permission(self, request, view, obj):
        # Разрешение администраторам
        if request.user and request.user.is_authenticated and request.user.is_admin:
            return True
        # Разрешение владельцу объекта
        # Проверяем наличие атрибута 'user' или '_user' (для Profile через user)
        owner = getattr(obj, 'user', getattr(obj, '_user', None))
        # Для модели User сам объект и есть владелец
        if isinstance(obj, User):
            owner = obj
        return owner == request.user

class IsAdmin(permissions.BasePermission):
    """Разрешает доступ только пользователям с ролью ADMIN."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)

class IsTeacher(permissions.BasePermission):
    """Разрешает доступ только пользователям с ролью TEACHER."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_teacher)

class IsStudent(permissions.BasePermission):
    """Разрешает доступ только пользователям с ролью STUDENT."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_student)

class IsParent(permissions.BasePermission):
    """Разрешает доступ только пользователям с ролью PARENT."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_parent)

class IsTeacherOrAdmin(permissions.BasePermission):
    """Разрешает доступ преподавателям или администраторам."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_teacher or request.user.is_admin))

# Добавьте другие комбинации по необходимости