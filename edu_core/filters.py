import django_filters
from django.db.models import Q
from users.models import User
from .models import Homework, HomeworkSubmission, Lesson, LessonJournalEntry, StudyPeriod, StudentGroup, Subject, Classroom

# Класс LessonFilter определяет набор фильтров для модели Lesson,
# используемый в Django REST framework для фильтрации списка занятий.
# Наследуется от django_filters.FilterSet.
# - Фильтры по дате и времени:
#   - `start_time__date__gte`, `start_time__date__lte`, `start_time__date`:
#     Фильтруют занятия по дате начала (больше или равно, меньше или равно, точно).
#   - `end_time__date__gte`, `end_time__date__lte`, `end_time__date`:
#     Аналогичные фильтры для даты окончания занятия.
# - Фильтры по связанным моделям:
#   - `study_period`, `student_group`, `subject`, `classroom`, `teacher`:
#     ModelChoiceFilter'ы, позволяющие фильтровать по ID связанных объектов.
#     Для `teacher` queryset ограничен пользователями с ролью `TEACHER`.
# - Фильтр по типу занятия:
#   - `lesson_type__in`: BaseInFilter, позволяющий передавать несколько значений для типа занятия
#     (например, `?lesson_type__in=LECTURE,PRACTICE`).
# - Фильтр для текстового поиска:
#   - `search`: CharFilter, использующий кастомный метод `filter_by_search_term`.
# Метод `filter_by_search_term` реализует регистронезависимый поиск по вхождению строки
# в названии предмета, имени/фамилии преподавателя или идентификаторе аудитории.
# Использует Q-объекты для объединения условий поиска через OR и `distinct()` для
# исключения дубликатов при поиске через связанные модели.
# В Meta-классе указывается модель (`Lesson`) и список полей для стандартной фильтрации.
class LessonFilter(django_filters.FilterSet):
    start_time__date__gte = django_filters.DateFilter(field_name='start_time__date', lookup_expr='gte')
    start_time__date__lte = django_filters.DateFilter(field_name='start_time__date', lookup_expr='lte')
    start_time__date = django_filters.DateFilter(field_name='start_time__date', lookup_expr='exact')

    end_time__date__gte = django_filters.DateFilter(field_name='end_time__date', lookup_expr='gte')
    end_time__date__lte = django_filters.DateFilter(field_name='end_time__date', lookup_expr='lte')
    end_time__date = django_filters.DateFilter(field_name='end_time__date', lookup_expr='exact')

    study_period = django_filters.ModelChoiceFilter(queryset=StudyPeriod.objects.all())
    student_group = django_filters.ModelChoiceFilter(queryset=StudentGroup.objects.all())
    subject = django_filters.ModelChoiceFilter(queryset=Subject.objects.all())
    classroom = django_filters.ModelChoiceFilter(queryset=Classroom.objects.all())
    teacher = django_filters.ModelChoiceFilter(
            queryset=User.objects.filter(role=User.Role.TEACHER)
        )
    lesson_type__in = django_filters.BaseInFilter(field_name='lesson_type', lookup_expr='in')
    search = django_filters.CharFilter(method='filter_by_search_term', label='Search')

    class Meta:
        model = Lesson
        fields = [
            'study_period', 'student_group', 'teacher', 'subject', 'classroom',
            'lesson_type',
        ]

    def filter_by_search_term(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(subject__name__icontains=value) |
                Q(teacher__first_name__icontains=value) |
                Q(teacher__last_name__icontains=value) |
                Q(classroom__identifier__icontains=value)
            ).distinct()
        return queryset
    
# Класс HomeworkFilter определяет набор фильтров для модели Homework.
# - Фильтры по связанным объектам через LessonJournalEntry и Lesson:
#   - `lesson` (устаревший, но оставлен для обратной совместимости, если использовался ранее):
#     Фильтрует ДЗ по ID урока, к которому оно привязано через запись в журнале.
#   - `journal_entry__lesson__student_group`: Фильтрует ДЗ по ID студенческой группы урока.
#   - `journal_entry__lesson__subject`: Фильтрует ДЗ по ID предмета урока.
#   - `journal_entry__lesson`: Фильтрует ДЗ по ID урока (более явный путь).
# - Прямые фильтры:
#   - `journal_entry`: Фильтрует ДЗ по ID записи в журнале.
#   - `author`: Фильтрует ДЗ по ID автора (преподавателя).
# - Фильтры по дате сдачи (`due_date`):
#   - `due_date`: DateFromToRangeFilter, позволяющий фильтровать по диапазону дат
#     (например, `?due_date_after=YYYY-MM-DD&due_date_before=YYYY-MM-DD`).
#   - `due_date__gte`, `due_date__lte`, `due_date__exact`: Фильтры для точной даты сдачи или
#     дат "больше или равно" / "меньше или равно".
# В Meta-классе указана модель (`Homework`) и список полей для фильтрации.
class HomeworkFilter(django_filters.FilterSet):
    lesson = django_filters.ModelChoiceFilter( # Устаревший, оставлен для примера
        field_name='journal_entry__lesson',
        queryset=Lesson.objects.all(),
        label='Фильтр по ID урока (связанного с ДЗ через запись в журнале)'
    )
    
    journal_entry__lesson__student_group = django_filters.ModelChoiceFilter(
        queryset=StudentGroup.objects.all(),
        label='Фильтр по ID студенческой группы урока'
    )
    journal_entry__lesson__subject = django_filters.ModelChoiceFilter(
        queryset=Subject.objects.all(),
        label='Фильтр по ID предмета урока'
    )
    journal_entry__lesson = django_filters.ModelChoiceFilter(
        field_name='journal_entry__lesson',
        queryset=Lesson.objects.all(),
        label='Фильтр по ID урока (связанного с ДЗ через запись в журнале)'
    )
    journal_entry = django_filters.ModelChoiceFilter(
        queryset=LessonJournalEntry.objects.all(),
        label='Фильтр по ID записи в журнале'
    )
    author = django_filters.ModelChoiceFilter(
        queryset=User.objects.filter(role=User.Role.TEACHER),
        label='Фильтр по ID автора ДЗ'
    )
    due_date = django_filters.DateFromToRangeFilter(
        label='Фильтр по сроку сдачи (диапазон дат)'
    )
    due_date__gte = django_filters.DateFilter(field_name='due_date', lookup_expr='gte')
    due_date__lte = django_filters.DateFilter(field_name='due_date', lookup_expr='lte')
    due_date__exact = django_filters.DateFilter(field_name='due_date', lookup_expr='exact')

    class Meta:
        model = Homework
        fields = [
            'lesson',
            'journal_entry__lesson',
            'journal_entry__lesson__student_group',
            'journal_entry__lesson__subject',
            'journal_entry',
            'author',
            'due_date',
            'due_date__gte', 'due_date__lte', 'due_date__exact'
        ]

# Класс HomeworkSubmissionFilter определяет набор фильтров для модели HomeworkSubmission.
# - `homework`: ModelChoiceFilter для фильтрации сданных работ по ID домашнего задания.
# - `student`: ModelChoiceFilter для фильтрации сданных работ по ID студента
#   (queryset ограничен пользователями с ролью `STUDENT`).
# (Закомментировано) Примеры фильтров по дате сдачи, если потребуются.
# В Meta-классе указана модель (`HomeworkSubmission`) и поля для фильтрации.
class HomeworkSubmissionFilter(django_filters.FilterSet):
    homework = django_filters.ModelChoiceFilter(
        queryset=Homework.objects.all(),
        label='Фильтр по ID домашнего задания'
    )
    student = django_filters.ModelChoiceFilter(
        queryset=User.objects.filter(role=User.Role.STUDENT),
        label='Фильтр по ID студента'
    )
    # submitted_at__date__gte = django_filters.DateFilter(field_name='submitted_at__date', lookup_expr='gte')
    # submitted_at__date__lte = django_filters.DateFilter(field_name='submitted_at__date', lookup_expr='lte')

    class Meta:
        model = HomeworkSubmission
        fields = [
            'homework',
            'student',
        ]