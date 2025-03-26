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
    """
    Получение расписания для текущего пользователя (Студент, Преподаватель, Родитель).
    Поддерживает фильтрацию по дате (?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD).
    """
    serializer_class = ScheduleListSerializer # Используем компактный сериализатор
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    # Простые фильтры по дате
    filterset_fields = {
         'start_time': ['gte', 'lte', 'exact', 'date'],
         'end_time': ['gte', 'lte', 'exact', 'date'],
    }

    def get_queryset(self):
        user = self.request.user
        now = timezone.now()
        queryset = Lesson.objects.select_related(
            'subject', 'teacher', 'group', 'classroom'
        ).order_by('start_time') # Оптимизация

        # Фильтруем queryset в зависимости от роли пользователя
        if user.is_student:
            # Студент видит занятия своей группы
            queryset = queryset.filter(group__students=user)
        elif user.is_teacher:
            # Преподаватель видит свои занятия
            queryset = queryset.filter(teacher=user)
        elif user.is_parent and user.related_child:
            # Родитель видит занятия связанного ребенка
            queryset = queryset.filter(group__students=user.related_child)
        elif user.is_admin:
             # Админ видит все (или можно сделать отдельный эндпоинт для полного расписания)
             # return queryset # Показываем все админу
             return Lesson.objects.none() # Или ничего, если админ должен использовать LessonViewSet
        else:
            # Другие роли (или неполные данные) не видят расписание здесь
            return Lesson.objects.none()

        # Применяем фильтры даты из запроса (если их нет, можно показать текущий/следующий день)
        start_date_str = self.request.query_params.get('start_date')
        end_date_str = self.request.query_params.get('end_date')

        if not start_date_str and not end_date_str:
             # По умолчанию показываем занятия на сегодня
             today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
             today_end = today_start + timezone.timedelta(days=1)
             queryset = queryset.filter(start_time__gte=today_start, start_time__lt=today_end)
        else:
             # Применяем фильтры, если они есть
             # DjangoFilterBackend сделает это автоматически, если filterset_fields настроен
             pass

        return queryset

# TODO: Представление для генерации расписания (GenerateScheduleView)
# Это сложная задача, вероятно, требующая асинхронной обработки (Celery)
# и алгоритмов расстановки с учетом ограничений.