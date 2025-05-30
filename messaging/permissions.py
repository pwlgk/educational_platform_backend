from rest_framework import permissions

# Класс IsChatCreatorOrAdmin предоставляет разрешение на доступ к объекту (чату),
# если запрашивающий пользователь является создателем этого чата или администратором системы.
# Принцип работы:
# 1. Проверяется, является ли пользователь администратором (`request.user.is_admin`).
#    Если да, доступ разрешается.
# 2. Если пользователь не администратор, проверяется, совпадает ли поле `created_by`
#    объекта чата (`obj.created_by`) с запрашивающим пользователем (`request.user`).
#    Если они совпадают (т.е. пользователь является создателем чата), доступ разрешается.
# 3. Если ни одно из условий не выполнено, доступ запрещается.
# Предполагается, что объект `obj`, передаваемый в метод `has_object_permission`,
# является экземпляром модели `Chat` и имеет атрибут `created_by`.
class IsChatCreatorOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_authenticated and request.user.is_admin:
            return True
        return obj.created_by == request.user

# Класс IsChatParticipant предоставляет разрешение на доступ к объекту (чату),
# если запрашивающий пользователь является участником этого чата.
# Принцип работы:
# 1. Проверяется, аутентифицирован ли пользователь. Если нет, доступ запрещается.
# 2. Если пользователь аутентифицирован, выполняется проверка, присутствует ли
#    он в списке участников чата (`obj.participants`). Это делается путем фильтрации
#    участников чата по `pk` (первичному ключу) запрашивающего пользователя и проверки
#    существования такой записи (`.exists()`).
# 3. Если пользователь найден среди участников, доступ разрешается, иначе запрещается.
# Предполагается, что объект `obj`, передаваемый в метод `has_object_permission`,
# является экземпляром модели `Chat` и имеет M2M-поле `participants`,
# связывающее его с пользователями.
class IsChatParticipant(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_authenticated:
            return obj.participants.filter(pk=request.user.pk).exists()
        return False