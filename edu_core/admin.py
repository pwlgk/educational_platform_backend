import os
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import (
    AcademicYear, StudyPeriod, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)

# --- Базовые Сущности ---

@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current')
    list_filter = ('is_current',)
    search_fields = ('name',)
    ordering = ('-start_date',)

@admin.register(StudyPeriod)
class StudyPeriodAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'start_date', 'end_date')
    list_filter = ('academic_year',)
    search_fields = ('name', 'academic_year__name')
    ordering = ('academic_year__start_date', 'start_date')
    list_select_related = ('academic_year',)

@admin.register(SubjectType)
class SubjectTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'subject_type', 'get_lead_teachers')
    list_filter = ('subject_type',)
    search_fields = ('name', 'code')
    filter_horizontal = ('lead_teachers',)
    list_select_related = ('subject_type',)

    def get_lead_teachers(self, obj):
        return ", ".join([t.get_full_name() for t in obj.lead_teachers.all()])
    get_lead_teachers.short_description = _('Основные преподаватели')

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'type', 'capacity', 'equipment_short')
    list_filter = ('type',)
    search_fields = ('identifier', 'equipment')
    ordering = ('identifier',)

    def equipment_short(self, obj):
        return obj.equipment[:70] + '...' if len(obj.equipment) > 70 else obj.equipment
    equipment_short.short_description = _('Оборудование (кратко)')


@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'curator_name', 'group_monitor_name', 'student_count')
    list_filter = ('academic_year', 'curator')
    search_fields = ('name', 'academic_year__name', 'curator__last_name', 'curator__email')
    filter_horizontal = ('students',)
    list_select_related = ('academic_year', 'curator', 'group_monitor')
    ordering = ('academic_year__start_date', 'name')

    def curator_name(self, obj):
        return obj.curator.get_full_name() if obj.curator else '-'
    curator_name.short_description = _('Куратор')
    curator_name.admin_order_field = 'curator__last_name'

    def group_monitor_name(self, obj):
        return obj.group_monitor.get_full_name() if obj.group_monitor else '-'
    group_monitor_name.short_description = _('Староста')
    group_monitor_name.admin_order_field = 'group_monitor__last_name'

    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = _('Студентов')

# --- Учебные Планы ---

class CurriculumEntryInline(admin.TabularInline):
    model = CurriculumEntry
    extra = 1
    autocomplete_fields = ['subject', 'teacher', 'study_period']
    ordering = ['study_period__start_date', 'subject__name']
    # Указываем поля явно, чтобы избежать проблем с readonly полями, если они есть
    fields = ('subject', 'teacher', 'study_period', 'planned_hours')

@admin.register(Curriculum)
class CurriculumAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'student_group', 'is_active', 'entry_count')
    list_filter = ('academic_year', 'student_group', 'is_active')
    search_fields = ('name', 'description', 'student_group__name', 'academic_year__name')
    list_select_related = ('academic_year', 'student_group')
    inlines = [CurriculumEntryInline]
    ordering = ('academic_year__start_date', 'student_group__name', 'name')

    def entry_count(self, obj):
        return obj.entries.count()
    entry_count.short_description = _('Записей в плане')


# СНАЧАЛА регистрируем CurriculumEntryAdmin
@admin.register(CurriculumEntry)
class CurriculumEntryAdmin(admin.ModelAdmin):
    list_display = ('curriculum_info', 'subject', 'teacher_name', 'study_period_name', 'planned_hours', 'scheduled_hours_display', 'remaining_hours_display')
    list_filter = ('curriculum__academic_year', 'study_period', 'subject', 'teacher', 'curriculum__student_group') # Добавил фильтр по группе
    search_fields = (
        'subject__name',
        'teacher__last_name',
        'teacher__email',
        'curriculum__name',
        'curriculum__student_group__name'
    )
    list_select_related = ('curriculum__academic_year', 'curriculum__student_group', 'subject', 'teacher', 'study_period')
    ordering = ('curriculum', 'study_period__start_date', 'subject__name')
    fields = ('curriculum', 'subject', 'teacher', 'study_period', 'planned_hours')
    readonly_fields = ('scheduled_hours', 'remaining_hours') # Если это property

    def curriculum_info(self, obj):
        return str(obj.curriculum)
    curriculum_info.short_description = _("Учебный план")
    curriculum_info.admin_order_field = 'curriculum__name'

    def teacher_name(self, obj):
        return obj.teacher.get_full_name() if obj.teacher else '-'
    teacher_name.short_description = _('Преподаватель')
    teacher_name.admin_order_field = 'teacher__last_name'

    def study_period_name(self, obj):
        return str(obj.study_period)
    study_period_name.short_description = _("Учебный период")
    study_period_name.admin_order_field = 'study_period__start_date'

    def scheduled_hours_display(self, obj):
        return f"{obj.scheduled_hours:.2f}"
    scheduled_hours_display.short_description = _("Запланировано (расп.) ч.")

    def remaining_hours_display(self, obj):
        return f"{obj.remaining_hours:.2f}"
    remaining_hours_display.short_description = _("Осталось (план) ч.")


# --- Расписание и Журнал ---

class LessonJournalEntryInline(admin.StackedInline):
    model = LessonJournalEntry
    extra = 0
    fields = ('topic_covered', 'teacher_notes')
    can_delete = False

class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0
    fields = ('student', 'status', 'comment')
    autocomplete_fields = ['student']
    ordering = ['student__last_name', 'student__first_name']

class HomeworkInline(admin.StackedInline):
    model = Homework
    extra = 0
    fields = ('title', 'description', 'due_date', 'author', 'related_materials')
    autocomplete_fields = ['author', 'related_materials']
    readonly_fields = ('author',)
    show_change_link = True

# ЗАТЕМ регистрируем LessonAdmin
@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('subject', 'student_group', 'teacher_name', 'lesson_type', 'start_time_display', 'end_time_display', 'classroom', 'has_journal_entry')
    list_filter = ('study_period__academic_year', 'study_period', 'student_group', 'teacher', 'subject', 'classroom', 'lesson_type')
    search_fields = ('subject__name', 'teacher__last_name', 'teacher__email', 'student_group__name', 'classroom__identifier')
    date_hierarchy = 'start_time'
    ordering = ('-start_time', 'student_group__name')
    list_select_related = ('study_period', 'student_group', 'subject', 'teacher', 'classroom', 'journal_entry')
    autocomplete_fields = ['study_period', 'student_group', 'subject', 'teacher', 'classroom', 'curriculum_entry', 'created_by']

    fieldsets = (
        (None, {'fields': ('study_period', 'student_group', 'subject', 'teacher', 'classroom', 'lesson_type')}),
        (_('Время проведения'), {'fields': (('start_time', 'end_time'),)}),
        (_('Связь с планом и создание'), {'fields': ('curriculum_entry', 'created_by')}),
    )
    readonly_fields = ('created_at', 'updated_at')

    def teacher_name(self, obj):
        return obj.teacher.get_full_name() if obj.teacher else '-'
    teacher_name.short_description = _('Преподаватель')
    teacher_name.admin_order_field = 'teacher__last_name'

    def start_time_display(self, obj):
        return obj.start_time.strftime('%d.%m.%Y %H:%M')
    start_time_display.short_description = _('Начало')
    start_time_display.admin_order_field = 'start_time'

    def end_time_display(self, obj):
        return obj.end_time.strftime('%H:%M')
    end_time_display.short_description = _('Окончание')
    end_time_display.admin_order_field = 'end_time'

    def has_journal_entry(self, obj):
        return hasattr(obj, 'journal_entry') and obj.journal_entry is not None
    has_journal_entry.short_description = _('Журнал заполнен')
    has_journal_entry.boolean = True

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(LessonJournalEntry)
class LessonJournalEntryAdmin(admin.ModelAdmin):
    list_display = ('lesson_info', 'topic_covered_short', 'date_filled')
    list_filter = ('lesson__study_period__academic_year', 'lesson__study_period', 'lesson__teacher', 'lesson__student_group')
    search_fields = ('lesson__subject__name', 'topic_covered', 'teacher_notes')
    list_select_related = ('lesson__subject', 'lesson__student_group', 'lesson__teacher')
    autocomplete_fields = ['lesson']
    inlines = [HomeworkInline, AttendanceInline]
    ordering = ('-lesson__start_time',)
    readonly_fields = ('date_filled',)

    def lesson_info(self, obj):
        return str(obj.lesson)
    lesson_info.short_description = _('Занятие')

    def topic_covered_short(self, obj):
        return obj.topic_covered[:70] + '...' if len(obj.topic_covered) > 70 else obj.topic_covered
    topic_covered_short.short_description = _('Пройденная тема')

# --- Домашние Задания ---

class HomeworkAttachmentInline(admin.TabularInline):
    model = HomeworkAttachment
    extra = 1
    fields = ('file', 'description')

class HomeworkSubmissionInline(admin.TabularInline):
    model = HomeworkSubmission
    extra = 0
    fields = ('student', 'submitted_at', 'content_short', 'get_attachments_count')
    readonly_fields = ('submitted_at', 'get_attachments_count')
    autocomplete_fields = ['student']
    show_change_link = True

    def content_short(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_short.short_description = _('Ответ студента')

    def get_attachments_count(self, obj):
        return obj.attachments.count()
    get_attachments_count.short_description = _('Файлов сдано')

@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ('title', 'lesson_info', 'author_name', 'due_date', 'submission_count')
    list_filter = ('journal_entry__lesson__study_period__academic_year', 'journal_entry__lesson__subject', 'author', 'due_date')
    search_fields = ('title', 'description', 'author__last_name', 'journal_entry__lesson__subject__name')
    list_select_related = ('journal_entry__lesson__subject', 'journal_entry__lesson__student_group', 'author')
    autocomplete_fields = ['journal_entry', 'author', 'related_materials']
    inlines = [HomeworkAttachmentInline, HomeworkSubmissionInline]
    ordering = ('-due_date', '-created_at')
    readonly_fields = ('created_at',)

    def lesson_info(self, obj):
        return str(obj.journal_entry.lesson)
    lesson_info.short_description = _('Занятие')

    def author_name(self, obj):
        return obj.author.get_full_name() if obj.author else '-'
    author_name.short_description = _('Автор ДЗ')

    def submission_count(self, obj):
        return obj.submissions.count()
    submission_count.short_description = _('Сдач')

class SubmissionAttachmentInline(admin.TabularInline):
    model = SubmissionAttachment
    extra = 1

@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = ('homework_title', 'student_name', 'submitted_at', 'has_grade')
    list_filter = ('homework__journal_entry__lesson__study_period__academic_year', 'homework__journal_entry__lesson__subject', 'student')
    search_fields = ('homework__title', 'student__last_name', 'student__email', 'content')
    list_select_related = ('homework__journal_entry__lesson__subject', 'student', 'grade_for_submission')
    autocomplete_fields = ['homework', 'student']
    inlines = [SubmissionAttachmentInline]
    readonly_fields = ('submitted_at',)
    ordering = ('-submitted_at',)

    def homework_title(self, obj):
        return obj.homework.title
    homework_title.short_description = _('Домашнее задание')

    def student_name(self, obj):
        return obj.student.get_full_name()
    student_name.short_description = _('Студент')

    def has_grade(self, obj):
        return hasattr(obj, 'grade_for_submission') and obj.grade_for_submission is not None
    has_grade.short_description = _('Оценено')
    has_grade.boolean = True

# --- Посещаемость и Оценки ---

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('lesson_info', 'student_name', 'status', 'comment_short', 'marked_by_name', 'marked_at_display')
    list_filter = ('status', 'journal_entry__lesson__study_period__academic_year', 'journal_entry__lesson__subject', 'journal_entry__lesson__student_group', 'marked_by')
    search_fields = ('student__last_name', 'student__email', 'comment', 'journal_entry__lesson__subject__name')
    list_select_related = ('journal_entry__lesson__subject', 'journal_entry__lesson__student_group', 'student', 'marked_by')
    autocomplete_fields = ['journal_entry', 'student', 'marked_by']
    readonly_fields = ('marked_at',)
    list_editable = ('status',) # Убрали 'comment_short'
    ordering = ('-journal_entry__lesson__start_time', 'student__last_name')

    def lesson_info(self, obj):
        return str(obj.journal_entry.lesson)
    lesson_info.short_description = _('Занятие')

    def student_name(self, obj):
        return obj.student.get_full_name()
    student_name.short_description = _('Студент')

    def comment_short(self, obj):
        return obj.comment[:50] + '...' if len(obj.comment) > 50 else obj.comment
    comment_short.short_description = _('Комментарий')

    def marked_by_name(self, obj):
        return obj.marked_by.get_full_name() if obj.marked_by else '-'
    marked_by_name.short_description = _('Кем отмечено')

    def marked_at_display(self, obj):
        return obj.marked_at.strftime('%d.%m.%Y %H:%M')
    marked_at_display.short_description = _('Время отметки')

@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student_name', 'subject_name', 'grade_value_display', 'grade_type', 'study_period_name', 'lesson_info_short', 'date_given', 'graded_by_name')
    list_filter = ('grade_type', 'study_period__academic_year', 'study_period', 'subject', 'graded_by', 'date_given')
    search_fields = ('student__last_name', 'student__email', 'subject__name', 'grade_value', 'comment')
    list_select_related = ('student', 'subject', 'study_period', 'lesson', 'homework_submission', 'graded_by')
    autocomplete_fields = ['student', 'subject', 'study_period', 'lesson', 'homework_submission', 'graded_by']
    ordering = ('-date_given', 'student__last_name', 'subject__name')
    readonly_fields = ('date_given',)

    fieldsets = (
        (None, {'fields': ('student', 'subject', 'study_period')}),
        (_('Детали оценки'), {'fields': ('grade_type', 'grade_value', 'numeric_value', 'weight', 'comment', 'date_given')}),
        (_('Связи (опционально)'), {'fields': ('lesson', 'homework_submission')}),
        (_('Автор оценки'), {'fields': ('graded_by',)}),
    )

    def student_name(self, obj):
        return obj.student.get_full_name()
    student_name.short_description = _('Студент')
    student_name.admin_order_field = 'student__last_name'

    def subject_name(self, obj):
        return obj.subject.name
    subject_name.short_description = _('Предмет')
    subject_name.admin_order_field = 'subject__name'

    def grade_value_display(self, obj):
        return f"{obj.grade_value} ({obj.numeric_value})" if obj.numeric_value else obj.grade_value
    grade_value_display.short_description = _('Оценка (число)')

    def study_period_name(self, obj):
        return str(obj.study_period)
    study_period_name.short_description = _('Учебный период')

    def lesson_info_short(self, obj):
        return str(obj.lesson) if obj.lesson else '-'
    lesson_info_short.short_description = _('Занятие (если есть)')

    def graded_by_name(self, obj):
        return obj.graded_by.get_full_name() if obj.graded_by else '-'
    graded_by_name.short_description = _('Кем выставлена')

    def save_model(self, request, obj, form, change):
        if not obj.graded_by_id :
            if obj.lesson and obj.lesson.teacher:
                obj.graded_by = obj.lesson.teacher
            elif obj.homework_submission and obj.homework_submission.homework.author:
                obj.graded_by = obj.homework_submission.homework.author
            elif request.user.is_authenticated and hasattr(request.user, 'is_teacher') and request.user.is_teacher :
                 obj.graded_by = request.user
        super().save_model(request, obj, form, change)

# --- Библиотека Материалов ---

@admin.register(SubjectMaterial)
class SubjectMaterialAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'student_group_name', 'file_name', 'uploaded_by_name', 'uploaded_at_display')
    list_filter = ('subject', 'student_group', 'uploaded_by', 'uploaded_at')
    search_fields = ('title', 'description', 'subject__name', 'student_group__name', 'uploaded_by__last_name')
    list_select_related = ('subject', 'student_group', 'uploaded_by')
    autocomplete_fields = ['subject', 'student_group', 'uploaded_by']
    ordering = ('-uploaded_at',)
    readonly_fields = ('uploaded_at',)

    fieldsets = (
        (None, {'fields': ('subject', 'student_group', 'title', 'description', 'file')}),
        (_('Метаданные'), {'fields': ('uploaded_by', 'uploaded_at')}),
    )

    def student_group_name(self, obj):
        return obj.student_group.name if obj.student_group else _("(для всех групп)")
    student_group_name.short_description = _('Группа')

    def file_name(self, obj):
        return os.path.basename(obj.file.name) if obj.file else '-'
    file_name.short_description = _('Имя файла')

    def uploaded_by_name(self, obj):
        return obj.uploaded_by.get_full_name() if obj.uploaded_by else '-'
    uploaded_by_name.short_description = _('Кем загружено')

    def uploaded_at_display(self, obj):
        return obj.uploaded_at.strftime('%d.%m.%Y %H:%M')
    uploaded_at_display.short_description = _('Дата загрузки')

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)