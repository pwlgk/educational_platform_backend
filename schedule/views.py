from rest_framework import viewsets, permissions, generics
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from django.db.models import Q
from .models import Subject, StudentGroup, Classroom, Lesson
from .serializers import (
    SubjectSerializer, StudentGroupSerializer, ClassroomSerializer,
    LessonSerializer, ScheduleListSerializer
)

from users.permissions import IsAdmin, IsTeacher, IsTeacherOrAdmin # Импортируем права из users
from django_filters.rest_framework import DjangoFilterBackend # Для фильтрации
from rest_framework import filters # Для поиска и сортировки
from .filters import LessonDateRangeFilter
from rest_framework.pagination import PageNumberPagination

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10 # Количество по умолчанию
    page_size_query_param = 'page_size' # Позволяет клиенту менять размер страницы
    max_page_size = 100

class SubjectViewSet(viewsets.ModelViewSet):
    """CRUD для учебных предметов (только Админы)."""
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

class StudentGroupViewSet(viewsets.ModelViewSet):
    """CRUD для учебных групп (Админы)."""
    queryset = StudentGroup.objects.prefetch_related('students', 'curator').all() # Оптимизация
    serializer_class = StudentGroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'curator__last_name', 'curator__email'] # Поиск по имени группы, ФИО/email куратора

class ClassroomViewSet(viewsets.ModelViewSet):
    """CRUD для аудиторий (Админы)."""
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['type'] # Фильтр по типу
    search_fields = ['identifier', 'notes'] # Поиск по номеру/примечаниям

class LessonViewSet(viewsets.ModelViewSet):
    """CRUD для занятий (Админы/Преподаватели)."""
    queryset = Lesson.objects.select_related(
        'subject', 'teacher', 'group', 'classroom', 'created_by'
    ).all().order_by('start_time') # Оптимизация + сортировка по умолчанию
    serializer_class = LessonSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin] # Создавать/редактировать могут учителя и админы
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    # Фильтры
    filterset_fields = {
        'start_time': ['gte', 'lte', 'exact', 'date'], # Фильтры по дате/времени начала
        'end_time': ['gte', 'lte', 'exact', 'date'],   # Фильтры по дате/времени конца
        'subject': ['exact'],
        'teacher': ['exact'],
        'group': ['exact'],
        'classroom': ['exact'],
        'lesson_type': ['exact', 'in'],
    }
    # Поиск
    search_fields = ['subject__name', 'teacher__last_name', 'group__name', 'classroom__identifier']
    # Сортировка
    ordering_fields = ['start_time', 'end_time', 'subject__name', 'group__name']
    ordering = ['start_time'] # Сортировка по умолчанию

    def get_permissions(self):
        """Преподаватель может редактировать/удалять только свои занятия."""
        if self.action in ['update', 'partial_update', 'destroy']:
            # Возвращаем кастомный пермишен или проверяем вручную
            # Для простоты пока оставим IsTeacherOrAdmin, но добавим проверку в perform_update/destroy
             return [permissions.IsAuthenticated(), IsTeacherOrAdmin()] # Заменить на IsLessonOwnerOrAdmin позже
        return super().get_permissions()

    def perform_create(self, serializer):
        # Устанавливаем создателя из запроса (переопределяем метод сериализатора на всякий случай)
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        # Проверка прав для преподавателя
        if self.request.user.is_teacher and not self.request.user.is_admin:
            if serializer.instance.teacher != self.request.user and serializer.instance.created_by != self.request.user:
                 self.permission_denied(
                     self.request, message='Преподаватель может изменять только свои занятия.'
                 )
        serializer.save()

    def perform_destroy(self, instance):
        # Проверка прав для преподавателя
        if self.request.user.is_teacher and not self.request.user.is_admin:
            if instance.teacher != self.request.user and instance.created_by != self.request.user:
                 self.permission_denied(
                     self.request, message='Преподаватель может удалять только свои занятия.'
                 )
        # TODO: Отправить уведомление об удалении занятия
        # send_lesson_deletion_notification(instance)
        instance.delete()


class MyScheduleView(generics.ListAPIView):
    serializer_class = ScheduleListSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = LessonDateRangeFilter
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        print(f"DEBUG [MyScheduleView]: Checking user: {user.email}, Role: {getattr(user, 'role', 'N/A')}, is_staff={user.is_staff}") # Логируем роль из модели User

        queryset = Lesson.objects.none()

        # --- Фильтрация по роли пользователя ---
        try:
            # Используем поле role из модели User (если оно там есть)
            user_role = getattr(user, 'role', None)

            if user_role == 'STUDENT':
                print("DEBUG: User role is STUDENT.")
                # Получаем группы через related_name 'student_groups'
                student_groups_qs = user.student_groups.all()
                if student_groups_qs.exists():
                    print(f"DEBUG: Student groups found: {[g.name for g in student_groups_qs]}")
                    # Фильтруем занятия по этим группам
                    queryset = Lesson.objects.filter(group__in=student_groups_qs)
                else:
                    print("DEBUG: Student is not assigned to any group.")
            elif user_role == 'TEACHER':
                print("DEBUG: User role is TEACHER.")
                queryset = Lesson.objects.filter(teacher=user)
            elif user_role == 'PARENT':
                print("DEBUG: User role is PARENT.")
                 # Предполагаем, что у модели User есть поле/связь 'related_child' или 'parent_profile' со связью children
                 # ЗАМЕНИТЕ 'related_children' на ВАШЕ реальное поле/related_name
                children = getattr(user, 'related_children', None) # Пример, если M2M 'related_children' на User
                if children and children.exists():
                     children_qs = children.all()
                     print(f"DEBUG: Parent children found: {[c.email for c in children_qs]}")
                     # Получаем группы ВСЕХ детей родителя
                     queryset = Lesson.objects.filter(group__students__in=children_qs)
                else:
                     print("DEBUG: Parent has no linked children.")
            elif getattr(user, 'is_admin', False) or user.is_staff:
                 print(f"DEBUG: User is admin/staff. Returning none for MySchedule.")
                 queryset = Lesson.objects.none()
                 # return queryset # Важно вернуть сразу, чтобы не делать лишние запросы
            else:
                 print(f"DEBUG: User role ('{user_role}') not handled or invalid for MySchedule.")
                 queryset = Lesson.objects.none()
        except AttributeError as e:
             print(f"DEBUG: AttributeError accessing role/groups/children: {e}")
             queryset = Lesson.objects.none()

        # Оптимизация и distinct, если queryset не пустой
        if queryset.exists():
            queryset = queryset.select_related(
                'subject', 'teacher', 'group', 'classroom',
                'teacher__profile' # Оставляем, если UserSerializer использует профиль
            ).distinct()
        else:
            # Возвращаем пустой набор сразу, если базовая фильтрация не дала результатов
             print(f"DEBUG [MyScheduleView]: Base queryset is empty for user {user.email}. Returning.")
             return queryset

        # Фильтрация по дате будет применена DjangoFilterBackend
        print(f"DEBUG [MyScheduleView]: Returning base queryset for user {user.email} with {queryset.count()} potential lessons before date filtering.")
        return queryset.order_by('start_time')

# TODO: Представление для генерации расписания (GenerateScheduleView)
# Это сложная задача, вероятно, требующая асинхронной обработки (Celery)
# и алгоритмов расстановки с учетом ограничений.