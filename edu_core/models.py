import os
import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q, F, Sum
from taggit.managers import TaggableManager # Если используется, оставить
import datetime

# Импорт кастомного хранилища, если используется.
# from edu_core.storages import OverwriteKeepOriginalNameStorage

# --- 1. Базовые Сущности Учебного Процесса ---

# Модель AcademicYear представляет учебный год.
# - name: Уникальное название (например, "2023-2024").
# - start_date, end_date: Даты начала и окончания учебного года.
# - is_current: Флаг, указывающий, является ли год текущим (только один может быть текущим).
# Валидация: дата начала должна быть раньше даты окончания; периоды учебных годов не должны пересекаться.
# При сохранении, если is_current=True, у других годов этот флаг снимается.
class AcademicYear(models.Model):
    name = models.CharField(_("название учебного года"), max_length=100, unique=True, help_text=_("Например, 2024-2025"))
    start_date = models.DateField(_("дата начала"))
    end_date = models.DateField(_("дата окончания"))
    is_current = models.BooleanField(_("текущий год"), default=False, help_text=_("Только один учебный год может быть помечен как текущий"))

    class Meta:
        verbose_name = _("учебный год")
        verbose_name_plural = _("учебные годы")
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_date >= self.end_date:
            raise ValidationError(_("Дата начала должна быть раньше даты окончания."))
        overlapping_years = AcademicYear.objects.filter(
            Q(start_date__lt=self.end_date) & Q(end_date__gt=self.start_date)
        ).exclude(pk=self.pk)
        if overlapping_years.exists():
            raise ValidationError(_("Период этого учебного года пересекается с существующим."))

    def save(self, *args, **kwargs):
        if self.is_current:
            AcademicYear.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)

# Модель StudyPeriod представляет учебный период внутри учебного года (например, четверть, семестр).
# - academic_year: Связь с учебным годом.
# - name: Название периода.
# - start_date, end_date: Даты начала и окончания периода.
# Валидация: даты периода должны быть в пределах дат учебного года и не пересекаться с другими периодами этого же года.
class StudyPeriod(models.Model):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='study_periods', verbose_name=_("учебный год"))
    name = models.CharField(_("название периода"), max_length=100, help_text=_("Например, 1-я Четверть, Осенний семестр"))
    start_date = models.DateField(_("дата начала"))
    end_date = models.DateField(_("дата окончания"))

    class Meta:
        verbose_name = _("учебный период")
        verbose_name_plural = _("учебные периоды")
        ordering = ['academic_year', 'start_date']
        unique_together = ('academic_year', 'name')

    def __str__(self):
        return f"{self.name} ({self.academic_year.name})"

    def clean(self):
        if self.start_date >= self.end_date:
            raise ValidationError(_("Дата начала периода должна быть раньше даты окончания."))
        if self.academic_year:
            if not (self.academic_year.start_date <= self.start_date <= self.academic_year.end_date and
                    self.academic_year.start_date <= self.end_date <= self.academic_year.end_date):
                raise ValidationError(_("Даты учебного периода должны находиться в пределах дат учебного года."))
        overlapping_periods = StudyPeriod.objects.filter(
            academic_year=self.academic_year
        ).filter(
            Q(start_date__lt=self.end_date) & Q(end_date__gt=self.start_date)
        ).exclude(pk=self.pk)
        if overlapping_periods.exists():
            raise ValidationError(_("Этот учебный период пересекается с другим периодом в этом же учебном году."))

# Модель SubjectType представляет тип учебного предмета (например, "Общеобразовательный", "Специальный").
# - name: Уникальное название типа.
# - description: Описание типа.
class SubjectType(models.Model):
    name = models.CharField(_("название типа предмета"), max_length=100, unique=True)
    description = models.TextField(_("описание"), blank=True)

    class Meta:
        verbose_name = _("тип предмета")
        verbose_name_plural = _("типы предметов")
        ordering = ['name']

    def __str__(self):
        return self.name

# Модель Subject представляет учебный предмет.
# - name, code: Название и уникальный код предмета.
# - description: Описание.
# - subject_type: Связь с типом предмета.
# - lead_teachers: ManyToMany-связь с пользователями (преподавателями), которые являются ведущими по этому предмету.
class Subject(models.Model):
    name = models.CharField(_('название предмета'), max_length=200, unique=True)
    code = models.CharField(_('код предмета'), max_length=20, unique=True, blank=True, null=True)
    description = models.TextField(_('описание'), blank=True)
    subject_type = models.ForeignKey(
        SubjectType,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='subjects',
        verbose_name=_("тип предмета")
    )
    lead_teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='lead_subjects',
        limit_choices_to={'role': 'TEACHER'},
        blank=True,
        verbose_name=_("основные преподаватели предмета")
    )

    class Meta:
        verbose_name = _("предмет")
        verbose_name_plural = _("предметы")
        ordering = ['name']

    def __str__(self):
        return self.name

# Модель Classroom представляет аудиторию или учебное помещение.
# - ClassroomType: Перечисление типов аудиторий (лекционная, лаборатория и т.д.).
# - identifier: Уникальный номер или название аудитории.
# - capacity: Вместимость.
# - type: Тип аудитории.
# - equipment: Описание оборудования.
class Classroom(models.Model):
    class ClassroomType(models.TextChoices):
        LECTURE = 'LECTURE', _('Лекционная')
        PRACTICE = 'PRACTICE', _('Практическая')
        LAB = 'LAB', _('Лаборатория')
        COMPUTER = 'COMPUTER', _('Компьютерный класс')
        SPORTS = 'SPORTS', _('Спортивный зал')
        ART = 'ART', _('Творческая мастерская')
        LIBRARY = 'LIBRARY', _('Библиотека')
        MEETING = 'MEETING', _('Переговорная/Зал собраний')
        OTHER = 'OTHER', _('Другое')

    identifier = models.CharField(_('номер/название'), max_length=50, unique=True)
    capacity = models.PositiveIntegerField(_('вместимость'), default=0)
    type = models.CharField(_('тип аудитории'), max_length=20, choices=ClassroomType.choices, default=ClassroomType.OTHER)
    equipment = models.TextField(_('оборудование и примечания'), blank=True)

    class Meta:
        verbose_name = _("аудитория")
        verbose_name_plural = _("аудитории")
        ordering = ['identifier']

    def __str__(self):
        return self.identifier

# Модель StudentGroup представляет учебную группу студентов.
# - name: Название группы.
# - academic_year: Связь с учебным годом.
# - curator: Преподаватель-куратор группы.
# - students: ManyToMany-связь со студентами, входящими в группу.
# - group_monitor: Староста группы (один из студентов группы).
# Валидация: староста должен быть студентом этой группы.
class StudentGroup(models.Model):
    name = models.CharField(_('название группы'), max_length=100)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name='student_groups', verbose_name=_("учебный год"))
    curator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='curated_groups',
        limit_choices_to={'role': 'TEACHER'},
        verbose_name=_("куратор")
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='student_group_memberships',
        limit_choices_to={'role': 'STUDENT'},
        blank=True,
        verbose_name=_('студенты в группе')
    )
    group_monitor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='monitored_group',
        limit_choices_to={'role': 'STUDENT'},
        verbose_name=_("староста группы")
    )

    class Meta:
        verbose_name = _("учебная группа")
        verbose_name_plural = _("учебные группы")
        ordering = ['academic_year', 'name']
        unique_together = ('name', 'academic_year')

    def __str__(self):
        return f"{self.name} ({self.academic_year.name})"

    def clean(self):
        super().clean()
        if self.group_monitor and self.pk: # Проверяем только для существующих групп
            if self.students.exists() and not self.students.filter(pk=self.group_monitor.pk).exists():
                raise ValidationError({'group_monitor': _("Староста должен быть студентом этой группы.")})

# --- 2. Учебные Планы и Нагрузка ---

# Модель Curriculum представляет учебный план для конкретной группы в учебном году.
# - name: Название учебного плана.
# - academic_year, student_group: Связи с учебным годом и группой.
# - description: Описание плана.
# - is_active: Флаг активности плана.
class Curriculum(models.Model):
    name = models.CharField(_("название учебного плана"), max_length=255)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name='curricula', verbose_name=_("учебный год"))
    student_group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, related_name='curricula', verbose_name=_("учебная группа"))
    description = models.TextField(_("описание"), blank=True)
    is_active = models.BooleanField(_("активен"), default=True)

    class Meta:
        verbose_name = _("учебный план")
        verbose_name_plural = _("учебные планы")
        unique_together = ('name', 'academic_year', 'student_group')
        ordering = ['academic_year', 'student_group', 'name']

    def __str__(self):
        return f"{self.name} для {self.student_group.name} ({self.academic_year.name})"

# Модель CurriculumEntry представляет запись в учебном плане (конкретный предмет, преподаватель, часы).
# - curriculum: Связь с учебным планом.
# - subject, teacher, study_period: Связи с предметом, преподавателем и учебным периодом.
# - planned_hours: Количество запланированных часов по предмету в данном периоде.
# Свойства scheduled_hours и remaining_hours вычисляют количество часов, уже запланированных
# в расписании, и оставшееся количество часов соответственно.
class CurriculumEntry(models.Model):
    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name='entries', verbose_name=_("учебный план"))
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='curriculum_entries', verbose_name=_("предмет"))
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='curriculum_entries_taught',
        limit_choices_to={'role': 'TEACHER'},
        verbose_name=_("преподаватель")
    )
    study_period = models.ForeignKey(StudyPeriod, on_delete=models.CASCADE, related_name='curriculum_entries', verbose_name=_("учебный период"))
    planned_hours = models.PositiveIntegerField(_("запланировано часов в периоде"))

    class Meta:
        verbose_name = _("запись учебного плана")
        verbose_name_plural = _("записи учебного плана")
        unique_together = ('curriculum', 'subject', 'teacher', 'study_period')
        ordering = ['study_period', 'subject']

    def __str__(self):
        teacher_name = self.teacher.get_full_name() if self.teacher else _("Не назначен")
        return f"{self.subject.name} ({teacher_name}) - {self.planned_hours} ч. в {self.study_period.name} (План: {self.curriculum.name})"

    @property
    def scheduled_hours(self):
        total_duration = Lesson.objects.filter(
            curriculum_entry=self
        ).aggregate(
            total_duration=Sum(F('end_time') - F('start_time'))
        )['total_duration']
        return total_duration.total_seconds() / 3600 if total_duration else 0.0 # Возвращаем float

    @property
    def remaining_hours(self):
        return float(self.planned_hours) - self.scheduled_hours # Преобразуем planned_hours к float

# --- 3. Расписание Занятий ---

# Модель Lesson представляет занятие (урок) в расписании.
# - LessonType: Перечисление типов занятий (лекция, практика и т.д.).
# - study_period, student_group, subject, teacher, classroom: Связи с соответствующими сущностями.
# - lesson_type: Тип занятия.
# - start_time, end_time: Время начала и окончания.
# - curriculum_entry: (Опционально) Связь с записью учебного плана.
# - created_by: Пользователь, создавший занятие.
# Свойство duration_hours вычисляет продолжительность занятия в часах.
# Валидация (clean): проверяет корректность времени, нахождение в пределах периода,
# отсутствие конфликтов (преподаватель, группа, аудитория заняты), соответствие вместимости аудитории.
class Lesson(models.Model):
    class LessonType(models.TextChoices):
        LECTURE = 'LECTURE', _('Лекция')
        PRACTICE = 'PRACTICE', _('Практическое занятие')
        LAB = 'LAB', _('Лабораторная работа')
        SEMINAR = 'SEMINAR', _('Семинар')
        CONSULTATION = 'CONSULTATION', _('Консультация')
        EXAM = 'EXAM', _('Экзамен/Зачет')
        EVENT = 'EVENT', _('Мероприятие/Событие')
        OTHER = 'OTHER', _('Другое')

    study_period = models.ForeignKey(StudyPeriod, on_delete=models.PROTECT, related_name='lessons', verbose_name=_("учебный период"))
    student_group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, related_name='lessons', verbose_name=_("учебная группа"))
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='lessons', verbose_name=_("предмет"))
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, # Или SET_NULL, если преподавателя могут удалить, а занятия остаются
        related_name='lessons_taught_in_core',
        limit_choices_to={'role': 'TEACHER'},
        verbose_name=_("преподаватель")
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name='lessons_in_core', verbose_name=_("аудитория"))
    lesson_type = models.CharField(_('тип занятия'), max_length=20, choices=LessonType.choices, default=LessonType.LECTURE)
    start_time = models.DateTimeField(_('время начала'))
    end_time = models.DateTimeField(_('время окончания'))
    curriculum_entry = models.ForeignKey(
        CurriculumEntry,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scheduled_lessons',
        verbose_name=_("связанная запись учебного плана")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_core_lessons'
    )

    class Meta:
        verbose_name = _("занятие")
        verbose_name_plural = _("занятия")
        ordering = ['start_time', 'student_group']
        indexes = [
            models.Index(fields=['study_period', 'start_time']),
            models.Index(fields=['teacher', 'start_time']),
            models.Index(fields=['student_group', 'start_time']),
            models.Index(fields=['classroom', 'start_time']),
        ]

    def __str__(self):
        return f"{self.subject.name} - {self.student_group.name} ({self.start_time.strftime('%d.%m %H:%M')})"

    @property
    def duration_hours(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() / 3600
        return 0

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError(_('Время окончания должно быть позже времени начала.'))
        if not (self.study_period.start_date <= self.start_time.date() <= self.study_period.end_date and
                self.study_period.start_date <= self.end_time.date() <= self.study_period.end_date):
            raise ValidationError({'start_time': _("Даты занятия должны находиться в пределах дат учебного периода."),
                                 'end_time': _("Даты занятия должны находиться в пределах дат учебного периода.")})
        
        # Проверка на конфликты
        conflicting_lessons_query = Q(start_time__lt=self.end_time) & Q(end_time__gt=self.start_time)
        conflicting_lessons = Lesson.objects.filter(conflicting_lessons_query).exclude(pk=self.pk)
        
        errors = {}
        if self.teacher and conflicting_lessons.filter(teacher=self.teacher).exists():
            errors['teacher'] = _("Преподаватель занят в это время на другом занятии.")
        if conflicting_lessons.filter(student_group=self.student_group).exists():
            errors['student_group'] = _("Группа занята в это время на другом занятии.")
        if self.classroom and conflicting_lessons.filter(classroom=self.classroom).exists():
            errors['classroom'] = _("Аудитория занята в это время на другом занятии.")
        if errors:
            raise ValidationError(errors)

        if self.classroom and self.student_group:
            if self.student_group.pk and self.student_group.students.exists(): # Убеждаемся, что группа сохранена и имеет студентов
                if self.student_group.students.count() > self.classroom.capacity:
                    raise ValidationError({'classroom': _(f'Вместимость аудитории {self.classroom} ({self.classroom.capacity}) меньше, чем студентов в группе {self.student_group} ({self.student_group.students.count()}).')})


# --- 4. Журнал Занятий, Оценки, Посещаемость, ДЗ и Библиотека Файлов ---

# Модель LessonJournalEntry представляет запись в журнале для конкретного занятия.
# - lesson: OneToOne-связь с занятием.
# - topic_covered: Пройденная тема.
# - teacher_notes: Заметки преподавателя.
# - date_filled: Дата заполнения (автоматически).
class LessonJournalEntry(models.Model):
    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='journal_entry', verbose_name=_("занятие"))
    topic_covered = models.CharField(_("пройденная тема на занятии"), max_length=500, blank=True)
    teacher_notes = models.TextField(_("заметки преподавателя о занятии"), blank=True)
    date_filled = models.DateTimeField(_("дата заполнения журнала"), auto_now=True)

    class Meta:
        verbose_name = _("запись в журнале занятия")
        verbose_name_plural = _("записи в журнале занятий")

    def __str__(self):
        return f"Журнал для: {self.lesson}"

# Функции для генерации путей сохранения файлов (учебные материалы, ДЗ, сдачи ДЗ).
# Используют UUID для уникальности имен файлов.
def subject_material_upload_path(instance, filename): # Не используется напрямую для SubjectMaterial, но может для Attachment
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    group_folder = f"group_{instance.student_group.id}" if instance.student_group else "all_groups"
    subject_folder = f"subject_{instance.subject.id}"
    return os.path.join('subject_materials', subject_folder, group_folder, unique_filename)

def material_attachment_upload_path(instance, filename):
    material_id_folder = f'material_{instance.subject_material.id}' if instance.subject_material_id else 'temp_material_unknown'
    return os.path.join('subject_material_files', material_id_folder, filename)

# Модель SubjectMaterialAttachment представляет файл, прикрепленный к учебному материалу.
# - subject_material: Связь с учебным материалом.
# - file: Сам файл (использует кастомное хранилище OverwriteKeepOriginalNameStorage, если оно определено).
# - description: Описание файла.
class SubjectMaterialAttachment(models.Model):
    subject_material = models.ForeignKey(
        'SubjectMaterial',
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name=_("учебный материал")
    )
    file = models.FileField(
        _("файл"),
        upload_to=material_attachment_upload_path,
        # storage=OverwriteKeepOriginalNameStorage() # Если используется
    )
    description = models.CharField(_("описание файла"), max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("прикрепленный файл к учебному материалу")
        verbose_name_plural = _("прикрепленные файлы к учебным материалам")
        ordering = ['uploaded_at']

    def __str__(self):
        return os.path.basename(self.file.name) if self.file else _("Нет файла")

# Модель SubjectMaterial представляет учебный материал (например, лекция, методичка).
# - subject, student_group: Связи с предметом и (опционально) группой.
# - title, description: Название и описание.
# - uploaded_by: Пользователь (преподаватель/админ), загрузивший материал.
# Свойство files_count возвращает количество прикрепленных файлов (через SubjectMaterialAttachment).
class SubjectMaterial(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='materials', verbose_name=_("предмет"))
    student_group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, null=True, blank=True, related_name='subject_materials', verbose_name=_("учебная группа (если применимо)"))
    title = models.CharField(_("название материала"), max_length=255)
    description = models.TextField(_("описание"), blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='uploaded_materials',
        limit_choices_to=models.Q(role='TEACHER') | models.Q(role='ADMIN')
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("учебный материал")
        verbose_name_plural = _("учебные материалы (библиотека)")
        ordering = ['subject', 'student_group', '-uploaded_at']

    def __str__(self):
        group_name = f" ({self.student_group.name})" if self.student_group else " (для всех групп)"
        return f"{self.title} по '{self.subject.name}'{group_name}"

    @property
    def files_count(self):
        return self.attachments.count()

# Модель Homework представляет домашнее задание.
# - journal_entry: Связь с записью в журнале (т.е. с конкретным занятием).
# - title, description: Тема и описание.
# - due_date: Срок сдачи.
# - author: Преподаватель, выдавший ДЗ.
# - related_materials: Связь с учебными материалами.
# Метод save автоматически устанавливает автора ДЗ, если он не указан, на основе преподавателя занятия.
def homework_attachment_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    homework_id_folder = f'homework_{instance.homework.id}' if instance.homework_id else 'temp_homework'
    return os.path.join('homework_attachments', homework_id_folder, unique_filename)

class Homework(models.Model):
    journal_entry = models.ForeignKey(LessonJournalEntry, on_delete=models.CASCADE, related_name='homework_assignments', verbose_name=_("запись в журнале"))
    title = models.CharField(_("заголовок/тема ДЗ"), max_length=255, default=_("Домашнее задание"))
    description = models.TextField(_("описание задания"))
    due_date = models.DateTimeField(_("срок сдачи"), null=True, blank=True)
    created_at = models.DateTimeField(_('выдано'), auto_now_add=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='authored_homeworks',
        verbose_name=_("автор задания (преподаватель)")
    )
    related_materials = models.ManyToManyField(SubjectMaterial, blank=True, related_name='homeworks_using_material', verbose_name=_("связанные материалы"))

    class Meta:
        verbose_name = _("домашнее задание")
        verbose_name_plural = _("домашние задания")
        ordering = ['-due_date', '-created_at']

    def __str__(self):
        title_str = str(self.title)
        lesson_str = str(self.journal_entry.lesson) if self.journal_entry and self.journal_entry.lesson else _("Неизвестное занятие")
        due_date_str = str(self.due_date.strftime('%d.%m.%Y')) if self.due_date else _("бессрочно")
        return f"{_('ДЗ')} '{title_str}' {_('к')} {lesson_str} ({_('до')} {due_date_str})"

    def save(self, *args, **kwargs):
        if not self.author_id and self.journal_entry_id and hasattr(self.journal_entry, 'lesson') and self.journal_entry.lesson.teacher_id:
            self.author_id = self.journal_entry.lesson.teacher_id
        super().save(*args, **kwargs)

# Модель HomeworkAttachment представляет файл, прикрепленный преподавателем к домашнему заданию.
class HomeworkAttachment(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='attachments', verbose_name=_("домашнее задание"))
    file = models.FileField(_("файл"), upload_to=homework_attachment_upload_path)
    description = models.CharField(_("описание файла"), max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("прикрепленный файл к ДЗ")
        verbose_name_plural = _("прикрепленные файлы к ДЗ")

    def __str__(self):
        return os.path.basename(self.file.name) if self.file else "No file"

# Модель HomeworkSubmission представляет сдачу домашнего задания студентом.
# - homework, student: Связи с ДЗ и студентом.
# - submitted_at: Время сдачи.
# - content: Ответ/комментарий студента.
def submission_attachment_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    submission_id_folder = f'submission_{instance.submission.id}' if instance.submission_id else 'temp_submission'
    homework_id_folder = f'homework_{instance.submission.homework.id}' if instance.submission_id and instance.submission.homework_id else 'temp_homework'
    student_id_folder = f'student_{instance.submission.student.id}' if instance.submission_id and instance.submission.student_id else 'temp_student'
    return os.path.join('submission_attachments', homework_id_folder, student_id_folder, submission_id_folder, unique_filename)

class HomeworkSubmission(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='submissions', verbose_name=_("домашнее задание"))
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='homework_submissions',
        limit_choices_to={'role': 'STUDENT'},
        verbose_name=_("студент")
    )
    submitted_at = models.DateTimeField(_("время сдачи"), auto_now_add=True)
    content = models.TextField(_("ответ/комментарий студента"), blank=True)

    class Meta:
        verbose_name = _("сдача ДЗ")
        verbose_name_plural = _("сдачи ДЗ")
        unique_together = ('homework', 'student') # Студент может сдать одно ДЗ только один раз
        ordering = ['homework', '-submitted_at']

    def __str__(self):
        hw_title = str(self.homework.title) if self.homework else _("Неизвестное ДЗ")
        student_name = str(self.student.get_full_name()) if self.student else _("Неизвестный студент")
        return f"{_('Сдача ДЗ')} '{hw_title}' {_('от')} {student_name}"

# Модель SubmissionAttachment представляет файл, прикрепленный студентом к своей сданной работе.
class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(HomeworkSubmission, on_delete=models.CASCADE, related_name='attachments', verbose_name=_("сдача ДЗ"))
    file = models.FileField(_("файл"), upload_to=submission_attachment_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("файл сдачи ДЗ")
        verbose_name_plural = _("файлы сдачи ДЗ")

    def __str__(self):
        return os.path.basename(self.file.name) if self.file else "No file"

# Модель Attendance представляет запись о посещаемости студента на занятии.
# - Status: Перечисление статусов посещаемости.
# - journal_entry, student: Связи с записью в журнале и студентом.
# - status: Статус посещаемости.
# - comment: Комментарий.
# - marked_by, marked_at: Кто и когда отметил.
# Метод save автоматически устанавливает marked_by, если не указан.
class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'P', _('Присутствовал (П)')
        ABSENT_VALID = 'V', _('Отсутствовал по ув. причине (УП)')
        ABSENT_INVALID = 'N', _('Отсутствовал по неув. причине (Н)')
        LATE = 'L', _('Опоздал (О)')
        REMOTE = 'R', _('Дистанционно (Д)')

    journal_entry = models.ForeignKey(LessonJournalEntry, on_delete=models.CASCADE, related_name='attendances', verbose_name=_("запись в журнале"))
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'STUDENT'},
        related_name='attendance_records',
        verbose_name=_("студент")
    )
    status = models.CharField(_("статус посещаемости"), max_length=10, choices=Status.choices, default=Status.PRESENT)
    comment = models.CharField(_("комментарий"), max_length=255, blank=True)
    marked_at = models.DateTimeField(_("когда отмечено"), auto_now_add=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='marked_attendances',
        limit_choices_to={'role': 'TEACHER'}
    )

    class Meta:
        verbose_name = _("запись о посещаемости")
        verbose_name_plural = _("записи о посещаемости")
        unique_together = ('journal_entry', 'student')
        ordering = ['journal_entry__lesson__start_time', 'student__last_name']

    def __str__(self):
        student_name = self.student.get_full_name() if self.student else _("Неизвестный студент")
        lesson_info = str(self.journal_entry.lesson) if self.journal_entry and self.journal_entry.lesson else _("Неизвестное занятие")
        return f"{student_name} - {self.get_status_display()} на {lesson_info}"


    def save(self, *args, **kwargs):
        if not self.marked_by_id and self.journal_entry_id and hasattr(self.journal_entry, 'lesson') and self.journal_entry.lesson.teacher_id:
            self.marked_by_id = self.journal_entry.lesson.teacher_id
        super().save(*args, **kwargs)

# Модель Grade представляет оценку студента.
# - GradeType: Перечисление типов оценок (за работу на занятии, ДЗ, итоговые и т.д.).
# - student, subject, study_period, academic_year: Связи с соответствующими сущностями.
#   `study_period` и `academic_year` сделаны опциональными (null=True, blank=True),
#   так как для текущих оценок они могут выводиться из `lesson` или `homework_submission`.
# - lesson, homework_submission: (Опционально) Связь с занятием или сданным ДЗ.
# - grade_value: Значение оценки (строковое, например "5", "Зачтено").
# - numeric_value: Числовой эквивалент оценки (для расчетов).
# - grade_type: Тип оценки.
# - date_given: Дата выставления.
# - comment: Комментарий.
# - graded_by: Преподаватель, выставивший оценку.
# - weight: Вес оценки (для расчета средних).
# Валидация (clean): Проверяет согласованность полей (например, годовые оценки не должны быть привязаны к занятию,
# тип оценки должен соответствовать наличию/отсутствию study_period/academic_year).
# Метод save автоматически устанавливает graded_by, если не указан.
class Grade(models.Model):
    class GradeType(models.TextChoices):
        LESSON_WORK = 'LESSON_WORK', _('Работа на занятии')
        HOMEWORK_GRADE = 'HOMEWORK_GRADE', _('Оценка за ДЗ')
        TEST = 'TEST', _('Контрольная/Тест') # Добавил, т.к. было в GradeAdmin
        PROJECT = 'PROJECT', _('Проект')     # Добавил, т.к. было в GradeAdmin
        QUIZ = 'QUIZ', _('Опрос/Летучка')   # Добавил, т.к. было в GradeAdmin
        EXAM = 'EXAM', _('Экзамен/Зачет')
        PERIOD_AVERAGE = 'PERIOD_AVG', _('Средняя за период (расчетная)')
        PERIOD_FINAL = 'PERIOD_FINAL', _('Итог за период (выставленная)')
        YEAR_AVERAGE = 'YEAR_AVG', _('Средняя за год (расчетная)')
        YEAR_FINAL = 'YEAR_FINAL', _('Итог за год (выставленная)')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'STUDENT'},
        related_name='grades_received',
        verbose_name=_("студент")
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='grades_for_subject',
        verbose_name=_("предмет")
    )
    study_period = models.ForeignKey(
        StudyPeriod,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='grades_in_period',
        verbose_name=_("учебный период (для текущих и итоговых за период)")
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='annual_grades_in_core',
        verbose_name=_("учебный год (для годовых итоговых)")
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grades_for_lesson_instance',
        verbose_name=_("занятие (если применимо)")
    )
    homework_submission = models.OneToOneField(
        HomeworkSubmission,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grade_for_submission',
        verbose_name=_("сдача ДЗ (если применимо)")
    )
    grade_value = models.CharField(_("значение оценки"), max_length=10)
    numeric_value = models.DecimalField(_("числовой эквивалент"), max_digits=4, decimal_places=2, null=True, blank=True)
    grade_type = models.CharField(_("тип оценки"), max_length=20, choices=GradeType.choices)
    date_given = models.DateField(_("дата выставления"), default=datetime.date.today)
    comment = models.TextField(_("комментарий к оценке"), blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grades_given_by_teacher',
        limit_choices_to={'role': 'TEACHER'}
    )
    weight = models.PositiveSmallIntegerField(_("вес оценки"), default=1)

    class Meta:
        verbose_name = _("оценка")
        verbose_name_plural = _("оценки")
        ordering = ['-date_given', 'student__last_name', 'subject']
        indexes = [
            models.Index(fields=['student', 'subject', 'study_period', 'date_given']),
            models.Index(fields=['student', 'subject', 'academic_year', 'date_given']),
            models.Index(fields=['lesson', 'student']),
            models.Index(fields=['homework_submission']),
        ]

    def __str__(self):
        period_or_year = ""
        student_name = self.student.get_full_name() if self.student else _("Неизвестный студент")
        subject_name = self.subject.name if self.subject else _("Неизвестный предмет")

        if self.grade_type in [self.GradeType.YEAR_FINAL, self.GradeType.YEAR_AVERAGE] and self.academic_year:
            period_or_year = f" за {self.academic_year.name} год"
        elif self.study_period:
            period_or_year = f" за {self.study_period.name}"
        return f"{student_name}: {self.grade_value} по '{subject_name}' ({self.get_grade_type_display()}{period_or_year})"


    def clean(self):
        super().clean()
        if self.lesson:
            if self.study_period and self.lesson.study_period != self.study_period:
                raise ValidationError({'study_period': _("Учебный период оценки должен совпадать с периодом занятия.")})
            elif not self.study_period:
                self.study_period = self.lesson.study_period
            if self.academic_year and self.lesson.study_period.academic_year != self.academic_year:
                raise ValidationError({'academic_year': _("Учебный год оценки должен совпадать с годом периода занятия.")})
            elif not self.academic_year and self.study_period:
                self.academic_year = self.study_period.academic_year
        if self.study_period and not self.academic_year:
            self.academic_year = self.study_period.academic_year
        if self.grade_type in [self.GradeType.YEAR_FINAL, self.GradeType.YEAR_AVERAGE]:
            if self.study_period:
                raise ValidationError({'study_period': _("Для годовых оценок учебный период не указывается.")})
            if not self.academic_year:
                raise ValidationError({'academic_year': _("Для годовых оценок необходимо указать учебный год.")})
            if self.lesson or self.homework_submission:
                raise ValidationError(_("Годовые оценки не должны быть привязаны к конкретному занятию или ДЗ."))
        elif self.grade_type in [self.GradeType.PERIOD_FINAL, self.GradeType.PERIOD_AVERAGE]:
            if not self.study_period:
                raise ValidationError({'study_period': _("Для итоговых оценок за период необходимо указать учебный период.")})
            if self.lesson or self.homework_submission:
                raise ValidationError(_("Итоговые оценки за период не должны быть привязаны к конкретному занятию или ДЗ."))
        else:
            if not self.study_period:
                # Если это не оценка за ДЗ или занятие, то study_period должен быть
                if not (self.lesson or self.homework_submission):
                    raise ValidationError({'study_period': _("Для текущих оценок необходимо указать учебный период (или занятие/ДЗ, из которого он будет взят).")})
            if self.grade_type == self.GradeType.LESSON_WORK and not self.lesson:
                raise ValidationError({'lesson': _("Для оценки за работу на занятии необходимо указать занятие.")})
            if self.grade_type == self.GradeType.HOMEWORK_GRADE and not self.homework_submission:
                raise ValidationError({'homework_submission': _("Для оценки за ДЗ необходимо указать сданную работу.")})
        if self.academic_year and self.study_period:
            if self.study_period.academic_year != self.academic_year:
                raise ValidationError(
                    _("Указанный учебный период (%(period)s) не принадлежит указанному учебному году (%(year)s).") %
                    {'period': self.study_period, 'year': self.academic_year}
                )

    def save(self, *args, **kwargs):
        if not self.graded_by_id:
            if self.lesson_id and hasattr(self.lesson, 'teacher_id') and self.lesson.teacher_id:
                self.graded_by_id = self.lesson.teacher_id
            elif self.homework_submission_id and \
                 hasattr(self.homework_submission, 'homework') and \
                 self.homework_submission.homework and \
                 hasattr(self.homework_submission.homework, 'author_id') and \
                 self.homework_submission.homework.author_id:
                     self.graded_by_id = self.homework_submission.homework.author_id
        
        # Установка study_period и academic_year из lesson, если они не заданы
        if self.lesson and not self.study_period:
            self.study_period = self.lesson.study_period
        if self.study_period and not self.academic_year:
            self.academic_year = self.study_period.academic_year
        
        # self.full_clean() # Вызов полной валидации перед сохранением
        super().save(*args, **kwargs)