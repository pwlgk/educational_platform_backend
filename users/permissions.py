from rest_framework import permissions
from .models import User

# Класс IsOwnerOrAdmin предоставляет разрешение на доступ к объекту,
# если запрашивающий пользователь является владельцем этого объекта или администратором системы.
# Принцип работы:
# 1. Проверяется, аутентифицирован ли пользователь. Если нет, доступ запрещается.
# 2. Если пользователь имеет атрибут 'is_admin' и он равен True, доступ разрешается.
# 3. Производится попытка определить владельца объекта для специфических моделей (QuizAttempt, QuizAppeal),
#    сравнивая поле 'student' объекта с запрашивающим пользователем.
# 4. Если специфические проверки не определили владельца, выполняется общая проверка по стандартным
#    именам полей-владельцев ('user', 'author', 'student'). Если такое поле найдено и его значение
#    совпадает с запрашивающим пользователем, доступ разрешается.
# 5. Если сам объект является экземпляром модели User, проверяется, совпадает ли объект с
#    запрашивающим пользователем.
# Если ни одно из условий не выполнено, доступ запрещается.
class IsOwnerOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        # Проверка, что пользователь аутентифицирован.
        if not request.user or not request.user.is_authenticated:
            return False

        # Разрешение для администраторов.
        if hasattr(request.user, 'is_admin') and request.user.is_admin:
            return True
        
        # Попытка определить владельца для специфических типов объектов.
        

        # Общая логика поиска поля, указывающего на владельца объекта.
        owner_field_candidates = ['user', 'author', 'student']
        owner = None
        for field_name in owner_field_candidates:
            if hasattr(obj, field_name):
                owner = getattr(obj, field_name)
                break
        
        if owner is not None:
            if owner == request.user:
                return True
        
        # Проверка, если сам объект является экземпляром User.
        # Это актуально, например, при запросе профиля пользователя или данных самого пользователя.
        if isinstance(obj, User):
            if obj == request.user:
                return True

        return False

# Класс IsAdmin предоставляет разрешение на доступ, если запрашивающий пользователь
# аутентифицирован и имеет роль администратора (атрибут is_admin равен True).
# Используется для ограничения доступа к определенным представлениям или действиям
# только для администраторов.
class IsAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)

# Класс IsTeacher предоставляет разрешение на доступ, если запрашивающий пользователь
# аутентифицирован и имеет роль преподавателя (атрибут is_teacher равен True).
# Используется для ограничения доступа к функционалу, предназначенному для преподавателей.
class IsTeacher(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_teacher)

# Класс IsStudent предоставляет разрешение на доступ, если запрашивающий пользователь
# аутентифицирован и имеет роль студента (атрибут is_student равен True).
# Используется для ограничения доступа к функционалу, предназначенному для студентов.
class IsStudent(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_student)

# Класс IsParent предоставляет разрешение на доступ, если запрашивающий пользователь
# аутентифицирован и имеет роль родителя (атрибут is_parent равен True).
# Используется для ограничения доступа к функционалу, предназначенному для родителей.
class IsParent(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_parent)

# Класс IsTeacherOrAdmin предоставляет разрешение на доступ, если запрашивающий пользователь
# аутентифицирован и имеет роль преподавателя (is_teacher) или администратора (is_admin).
# Позволяет объединить доступ для этих двух ролей.
class IsTeacherOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_teacher or request.user.is_admin))

# Класс IsStudentAndOwner предоставляет разрешение на доступ, если запрашивающий пользователь
# является студентом и одновременно владельцем запрашиваемого объекта.
# Принцип работы:
# 1. Метод has_permission проверяет, является ли пользователь студентом.
#    Эта проверка выполняется для представлений списка или перед has_object_permission.
# 2. Метод has_object_permission дополнительно проверяет, что студент является владельцем объекта.
#    Сначала убеждается, что пользователь студент. Затем пытается определить владельца объекта
#    (сначала для специфических моделей QuizAttempt, QuizAppeal, затем по общим полям 'user', 'author', 'student')
#    и сравнивает его с запрашивающим пользователем.
# Доступ разрешается только если обе проверки (студент и владелец) успешны.
class IsStudentAndOwner(permissions.BasePermission):
    def has_permission(self, request, view):
        # Проверка, что пользователь является студентом на уровне представления.
        is_student_check = IsStudent()
        if not is_student_check.has_permission(request, view):
            return False
        return True

    def has_object_permission(self, request, view, obj):
        # Повторная проверка, что пользователь является студентом (на случай, если has_permission не вызывался).
        is_student_check = IsStudent()
        if not is_student_check.has_permission(request, view):
            return False
        
        # Проверка, что студент является владельцем объекта.
        owner = None
        

        # Если владелец определен и совпадает с запрашивающим пользователем, доступ разрешен.
        if owner == request.user:
            return True
        
        return False

# Класс OrPermissions является композитным классом разрешений, который предоставляет доступ,
# если хотя бы одно из переданных ему в конструктор разрешений возвращает True.
# Принцип работы:
# 1. В конструкторе принимается список классов разрешений, из которых создаются экземпляры.
# 2. Метод has_permission итерируется по списку экземпляров разрешений и вызывает их метод
#    has_permission. Если хотя бы один из них возвращает True, доступ разрешается.
# 3. Метод has_object_permission также итерируется по списку. Для каждого разрешения сначала
#    проверяется его has_permission (так как общий has_permission для OrPermissions мог
#    сработать из-за другого разрешения), и если оно True, то вызывается has_object_permission.
#    Если хотя бы одно из вложенных разрешений дает доступ к объекту, общий доступ разрешается.
class OrPermissions(permissions.BasePermission):
    def __init__(self, *perms):
        # Инициализация списка экземпляров разрешений.
        self.perms = [p() if isinstance(p, type) and issubclass(p, permissions.BasePermission) else p for p in perms]

    def has_permission(self, request, view):
        # Проверка общего доступа на уровне представления.
        for perm_instance in self.perms:
            if perm_instance.has_permission(request, view):
                return True
        return False

    def has_object_permission(self, request, view, obj):
        # Проверка доступа к конкретному объекту.
        # Вызывается только если has_permission для OrPermissions вернул True.
        for perm_instance in self.perms:
            # Необходимо проверить has_permission для каждого внутреннего разрешения,
            # так как оно могло не быть причиной успешного прохождения общего has_permission.
            if perm_instance.has_permission(request, view):
                if perm_instance.has_object_permission(request, view, obj):
                    return True
        return False