# edu_core/models.py
import os
import uuid
from django.db import models
from django.conf import settings # Для AUTH_USER_MODEL
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q, F, Sum # Убрал Avg, Count, т.к. не использовались явно здесь
from taggit.managers import TaggableManager
import datetime

# --- 1. Базовые Сущности Учебного Процесса ---

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

class SubjectType(models.Model):
    name = models.CharField(_("название типа предмета"), max_length=100, unique=True)
    description = models.TextField(_("описание"), blank=True)

    class Meta:
        verbose_name = _("тип предмета")
        verbose_name_plural = _("типы предметов")
        ordering = ['name']

    def __str__(self):
        return self.name

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
        limit_choices_to={'role': 'TEACHER'}, # Используем строковое значение роли
        blank=True,
        verbose_name=_("основные преподаватели предмета")
    )

    class Meta:
        verbose_name = _("предмет")
        verbose_name_plural = _("предметы")
        ordering = ['name']

    def __str__(self):
        return self.name

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

class StudentGroup(models.Model):
    name = models.CharField(_('название группы'), max_length=100)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name='student_groups', verbose_name=_("учебный год"))
    curator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='curated_groups',
        limit_choices_to={'role': 'TEACHER'}, # Строковое значение
        verbose_name=_("куратор")
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='student_group_memberships',
        limit_choices_to={'role': 'STUDENT'}, # Строковое значение
        blank=True,
        verbose_name=_('студенты в группе')
    )
    group_monitor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='monitored_group',
        limit_choices_to={'role': 'STUDENT'}, # Строковое значение
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
        if self.group_monitor and self.pk:
            if self.students.exists() and not self.students.filter(pk=self.group_monitor.pk).exists():
                raise ValidationError({'group_monitor': _("Староста должен быть студентом этой группы.")})

# --- 2. Учебные Планы и Нагрузка ---

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

class CurriculumEntry(models.Model):
    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name='entries', verbose_name=_("учебный план"))
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='curriculum_entries', verbose_name=_("предмет"))
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='curriculum_entries_taught',
        limit_choices_to={'role': 'TEACHER'}, # Строковое значение
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
        return total_duration.total_seconds() / 3600 if total_duration else 0

    @property
    def remaining_hours(self):
        return self.planned_hours - self.scheduled_hours

# --- 3. Расписание Занятий ---

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
        on_delete=models.CASCADE,
        related_name='lessons_taught_in_core',
        limit_choices_to={'role': 'TEACHER'}, # Строковое значение
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
        query = Q(start_time__lt=self.end_time) & Q(end_time__gt=self.start_time)
        conflicting_lessons = Lesson.objects.filter(query).exclude(pk=self.pk)
        errors = {}
        if conflicting_lessons.filter(teacher=self.teacher).exists():
            errors['teacher'] = _("Преподаватель занят в это время на другом занятии.")
        if conflicting_lessons.filter(student_group=self.student_group).exists():
            errors['student_group'] = _("Группа занята в это время на другом занятии.")
        if self.classroom and conflicting_lessons.filter(classroom=self.classroom).exists():
            errors['classroom'] = _("Аудитория занята в это время на другом занятии.")
        if errors:
            raise ValidationError(errors)
        if self.classroom and self.student_group:
            # Проверяем количество студентов только если группа уже сохранена и имеет студентов
            if self.student_group.pk and self.student_group.students.exists():
                if self.student_group.students.count() > self.classroom.capacity:
                    raise ValidationError({'classroom': _(f'Вместимость аудитории {self.classroom} ({self.classroom.capacity}) меньше, чем студентов в группе {self.student_group} ({self.student_group.students.count()}).')})


# --- 4. Журнал Занятий, Оценки, Посещаемость, ДЗ и Библиотека Файлов ---

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

def subject_material_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    group_folder = f"group_{instance.student_group.id}" if instance.student_group else "all_groups"
    subject_folder = f"subject_{instance.subject.id}"
    return os.path.join('subject_materials', subject_folder, group_folder, unique_filename)

class SubjectMaterial(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='materials', verbose_name=_("предмет"))
    student_group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, null=True, blank=True, related_name='subject_materials', verbose_name=_("учебная группа (если применимо)"))
    title = models.CharField(_("название материала"), max_length=255)
    description = models.TextField(_("описание"), blank=True)
    file = models.FileField(_("файл материала"), upload_to=subject_material_upload_path)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='uploaded_materials',
        limit_choices_to=Q(role='TEACHER') | Q(role='ADMIN') # Используем Q-объект для OR
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("учебный материал")
        verbose_name_plural = _("учебные материалы (библиотека)")
        ordering = ['subject', 'student_group', '-uploaded_at']

    def __str__(self):
        group_name = f" ({self.student_group.name})" if self.student_group else " (для всех групп)"
        return f"{self.title} по '{self.subject.name}'{group_name}"

def homework_attachment_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    # Проверяем, что homework существует, прежде чем получить его id
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
        return f"ДЗ '{self.title}' к {self.journal_entry.lesson} (до {self.due_date or 'бессрочно'})"

    def save(self, *args, **kwargs):
        if not self.author_id and self.journal_entry_id and self.journal_entry.lesson.teacher_id:
            self.author_id = self.journal_entry.lesson.teacher_id
        super().save(*args, **kwargs)

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
        limit_choices_to={'role': 'STUDENT'}, # Строковое значение
        verbose_name=_("студент")
    )
    submitted_at = models.DateTimeField(_("время сдачи"), auto_now_add=True)
    content = models.TextField(_("ответ/комментарий студента"), blank=True)

    class Meta:
        verbose_name = _("сдача ДЗ")
        verbose_name_plural = _("сдачи ДЗ")
        unique_together = ('homework', 'student')
        ordering = ['homework', '-submitted_at']

    def __str__(self):
        return f"Сдача ДЗ '{self.homework.title}' от {self.student.get_full_name()}"

class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(HomeworkSubmission, on_delete=models.CASCADE, related_name='attachments', verbose_name=_("сдача ДЗ"))
    file = models.FileField(_("файл"), upload_to=submission_attachment_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("файл сдачи ДЗ")
        verbose_name_plural = _("файлы сдачи ДЗ")

    def __str__(self):
        return os.path.basename(self.file.name) if self.file else "No file"

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
        limit_choices_to={'role': 'STUDENT'}, # Строковое значение
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
        limit_choices_to={'role': 'TEACHER'} # Строковое значение
    )

    class Meta:
        verbose_name = _("запись о посещаемости")
        verbose_name_plural = _("записи о посещаемости")
        unique_together = ('journal_entry', 'student')
        ordering = ['journal_entry__lesson__start_time', 'student__last_name']

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.get_status_display()} на {self.journal_entry.lesson}"

    def save(self, *args, **kwargs):
        if not self.marked_by_id and self.journal_entry_id and self.journal_entry.lesson.teacher_id:
            self.marked_by_id = self.journal_entry.lesson.teacher_id
        super().save(*args, **kwargs)

class Grade(models.Model):
    class GradeType(models.TextChoices):
        LESSON_WORK = 'LESSON_WORK', _('Работа на занятии')
        HOMEWORK_GRADE = 'HOMEWORK_GRADE', _('Оценка за ДЗ')
        TEST = 'TEST', _('Контрольная/Тест')
        PROJECT = 'PROJECT', _('Проект')
        QUIZ = 'QUIZ', _('Опрос/Летучка')
        EXAM = 'EXAM', _('Экзамен/Зачет')
        PERIOD_AVERAGE = 'PERIOD_AVG', _('Средняя за период (расчетная)')
        PERIOD_FINAL = 'PERIOD_FINAL', _('Итог за период (выставленная)')
        YEAR_AVERAGE = 'YEAR_AVG', _('Средняя за год (расчетная)')
        YEAR_FINAL = 'YEAR_FINAL', _('Итог за год (выставленная)')

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'STUDENT'}, # Строковое значение
        related_name='grades_received',
        verbose_name=_("студент")
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='grades_for_subject', verbose_name=_("предмет"))
    study_period = models.ForeignKey(StudyPeriod, on_delete=models.CASCADE, related_name='grades_in_period', verbose_name=_("учебный период"))
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name='grades_for_lesson_instance', verbose_name=_("занятие (если применимо)"))
    homework_submission = models.OneToOneField(HomeworkSubmission, on_delete=models.SET_NULL, null=True, blank=True, related_name='grade_for_submission', verbose_name=_("сдача ДЗ (если применимо)"))

    grade_value = models.CharField(_("значение оценки"), max_length=10)
    numeric_value = models.DecimalField(_("числовой эквивалент"), max_digits=4, decimal_places=2, null=True, blank=True)
    grade_type = models.CharField(_("тип оценки"), max_length=20, choices=GradeType.choices)
    date_given = models.DateField(_("дата выставления"), default=datetime.date.today)    
    comment = models.TextField(_("комментарий к оценке"), blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grades_given_by_teacher',
        limit_choices_to={'role': 'TEACHER'} # Строковое значение
    )
    weight = models.PositiveSmallIntegerField(_("вес оценки"), default=1)

    class Meta:
        verbose_name = _("оценка")
        verbose_name_plural = _("оценки")
        ordering = ['-date_given', 'student__last_name', 'subject']
        indexes = [
            models.Index(fields=['student', 'subject', 'study_period', 'date_given']),
            models.Index(fields=['lesson', 'student']),
            models.Index(fields=['homework_submission']),
        ]

    def __str__(self):
        return f"{self.student.get_full_name()}: {self.grade_value} по '{self.subject.name}' ({self.get_grade_type_display()})"

    def save(self, *args, **kwargs):
        if not self.graded_by_id:
            if self.lesson_id and self.lesson.teacher_id:
                self.graded_by_id = self.lesson.teacher_id
            elif self.homework_submission_id and self.homework_submission.homework.author_id:
                self.graded_by_id = self.homework_submission.homework.author_id
        super().save(*args, **kwargs)