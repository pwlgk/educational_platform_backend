from django.db import models
from django.conf import settings # Для ссылки на кастомную модель User
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
# Для правил повторения можно использовать django-recurrence,
# но для простоты пока сделаем базовую логику
# from recurrence.fields import RecurrenceField

class Subject(models.Model):
    """Модель учебного предмета."""
    name = models.CharField(_('название предмета'), max_length=200, unique=True)
    description = models.TextField(_('описание'), blank=True)

    class Meta:
        verbose_name = _('предмет')
        verbose_name_plural = _('предметы')
        ordering = ['name']

    def __str__(self):
        return self.name

class StudentGroup(models.Model):
    """Модель учебной группы."""
    name = models.CharField(_('название группы'), max_length=100, unique=True)
    # Куратор - необязательно, но полезно
    curator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='curated_groups',
        limit_choices_to={'role': "TEACHER"}, # Ограничиваем выбор преподавателями
        verbose_name=_('куратор')
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='student_groups',
        limit_choices_to={'role': "STUDENT"}, # Ограничиваем выбор студентами
        blank=True, # Группа может быть создана без студентов
        verbose_name=_('студенты')
    )

    class Meta:
        verbose_name = _('учебная группа')
        verbose_name_plural = _('учебные группы')
        ordering = ['name']

    def __str__(self):
        return self.name

class Classroom(models.Model):
    """Модель аудитории/кабинета."""
    class ClassroomType(models.TextChoices):
        LECTURE = 'LECTURE', _('Лекционная')
        PRACTICE = 'PRACTICE', _('Практическая')
        LAB = 'LAB', _('Лаборатория')
        COMPUTER = 'COMPUTER', _('Компьютерный класс')
        OTHER = 'OTHER', _('Другое')

    identifier = models.CharField(_('номер/название'), max_length=50, unique=True) # Напр., "305", "Лекц. А"
    capacity = models.PositiveIntegerField(_('вместимость'), default=0)
    type = models.CharField(_('тип аудитории'), max_length=20, choices=ClassroomType.choices, default=ClassroomType.OTHER)
    notes = models.TextField(_('примечания'), blank=True) # Оборудование и т.п.

    class Meta:
        verbose_name = _('аудитория')
        verbose_name_plural = _('аудитории')
        ordering = ['identifier']

    def __str__(self):
        return self.identifier

class Lesson(models.Model):
    """Модель занятия в расписании."""
    class LessonType(models.TextChoices):
        LECTURE = 'LECTURE', _('Лекция')
        PRACTICE = 'PRACTICE', _('Практика')
        SEMINAR = 'SEMINAR', _('Семинар')
        LAB = 'LAB', _('Лабораторная работа')
        EXAM = 'EXAM', _('Экзамен/Зачет')
        CONSULTATION = 'CONSULTATION', _('Консультация')
        OTHER = 'OTHER', _('Другое')

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='lessons', verbose_name=_('предмет'))
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, # Или SET_NULL, если занятие может остаться без преподавателя
        related_name='lessons_taught',
        limit_choices_to={'role': 'TEACHER'},
        verbose_name=_('преподаватель')
    )
    group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, related_name='lessons', verbose_name=_('группа'))
    classroom = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name='lessons', verbose_name=_('аудитория'))
    lesson_type = models.CharField(_('тип занятия'), max_length=20, choices=LessonType.choices, default=LessonType.LECTURE)

    start_time = models.DateTimeField(_('время начала'))
    end_time = models.DateTimeField(_('время окончания'))

    # Повторяющиеся занятия (упрощенная реализация)
    # Для сложной логики используйте `django-recurrence`
    # is_recurring = models.BooleanField(_('повторяющееся'), default=False)
    # recurrence_rule = RecurrenceField(null=True, blank=True) # Пример с django-recurrence
    # Или простой вариант:
    # recurrence_end_date = models.DateField(_('дата окончания повторений'), null=True, blank=True)
    # recurrence_frequency = models.CharField(_('частота'), max_length=10, choices=[('WEEKLY', 'Еженедельно'), ('BIWEEKLY', 'Раз в 2 недели')], null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Кто создал/изменил занятие
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_lessons',
        limit_choices_to={'role__in': ["TEACHER", "ADMIN"]},
        verbose_name=_('кем создано')
    )

    class Meta:
        verbose_name = _('занятие')
        verbose_name_plural = _('занятия')
        ordering = ['start_time', 'group']
        # Индексы для ускорения запросов по расписанию
        indexes = [
            models.Index(fields=['start_time', 'end_time']),
            models.Index(fields=['teacher', 'start_time']),
            models.Index(fields=['group', 'start_time']),
            models.Index(fields=['classroom', 'start_time']),
        ]

    def __str__(self):
        return f"{self.subject} - {self.group} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"

    def clean(self):
        """Валидация модели."""
        # Проверка времени
        if self.start_time >= self.end_time:
            raise ValidationError(_('Время окончания должно быть позже времени начала.'))

        # Проверка пересечений (упрощенная, для одного занятия)
        # Более сложная логика нужна для повторяющихся и учета вместимости
        overlapping_lessons = Lesson.objects.filter(
            models.Q(classroom=self.classroom) | models.Q(teacher=self.teacher) | models.Q(group=self.group),
            start_time__lt=self.end_time,
            end_time__gt=self.start_time
        ).exclude(pk=self.pk) # Исключаем себя при обновлении

        if overlapping_lessons.exists():
             conflicts = []
             for lesson in overlapping_lessons:
                 if lesson.classroom == self.classroom: conflicts.append(f"Аудитория ({self.classroom})")
                 if lesson.teacher == self.teacher: conflicts.append(f"Преподаватель ({self.teacher.get_full_name()})")
                 if lesson.group == self.group: conflicts.append(f"Группа ({self.group})")
             if conflicts:
                 unique_conflicts = ", ".join(sorted(list(set(conflicts))))
                 raise ValidationError(_(f'Обнаружено пересечение занятий по времени для: {unique_conflicts}.'))

        # Проверка вместимости аудитории
        if self.classroom and self.group and self.group.students.count() > self.classroom.capacity:
             raise ValidationError(_(f'Вместимость аудитории {self.classroom} ({self.classroom.capacity}) меньше, чем количество студентов в группе {self.group} ({self.group.students.count()}).'))


    # def save(self, *args, **kwargs):
    #     self.full_clean() # Вызываем валидацию перед сохранением
    #     super().save(*args, **kwargs)
    # Раскомментируйте save, если хотите включить валидацию при сохранении, но
    # лучше вызывать clean() в формах/сериализаторах.