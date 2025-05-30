import os
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.urls import reverse # Импортировано для reverse
from django.utils.html import format_html # Импортировано для format_html
from .models import (
    AcademicYear, StudyPeriod, SubjectMaterialAttachment, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)

# --- Настройки для базовых сущностей образовательного процесса ---

# Класс AcademicYearAdmin настраивает отображение модели AcademicYear (Учебный год).
# - list_display: Поля для отображения в списке (название, даты начала/окончания, текущий ли год).
# - list_filter: Фильтры по текущему году.
# - search_fields: Поиск по названию.
# - ordering: Сортировка по дате начала (сначала новые).
@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current')
    list_filter = ('is_current',)
    search_fields = ('name',)
    ordering = ('-start_date',)

# Класс StudyPeriodAdmin настраивает отображение модели StudyPeriod (Учебный период).
# - list_display: Поля для отображения (название, учебный год, даты начала/окончания).
# - list_filter: Фильтры по учебному году.
# - search_fields: Поиск по названию периода и названию учебного года.
# - ordering: Сортировка по дате начала учебного года, затем по дате начала периода.
# - list_select_related: Оптимизация запросов для поля 'academic_year'.
@admin.register(StudyPeriod)
class StudyPeriodAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'start_date', 'end_date')
    list_filter = ('academic_year',)
    search_fields = ('name', 'academic_year__name')
    ordering = ('academic_year__start_date', 'start_date')
    list_select_related = ('academic_year',)

# Класс SubjectTypeAdmin настраивает отображение модели SubjectType (Тип предмета).
# - list_display: Поля для отображения (название, описание).
# - search_fields: Поиск по названию.
@admin.register(SubjectType)
class SubjectTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

# Класс SubjectAdmin настраивает отображение модели Subject (Учебный предмет).
# - list_display: Поля для отображения (название, код, тип, ведущие преподаватели).
# - list_filter: Фильтры по типу предмета.
# - search_fields: Поиск по названию и коду.
# - filter_horizontal: Удобный виджет для выбора ведущих преподавателей (M2M).
# - list_select_related: Оптимизация для поля 'subject_type'.
# - get_lead_teachers: Кастомный метод для отображения списка ведущих преподавателей.
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

# Класс ClassroomAdmin настраивает отображение модели Classroom (Аудитория).
# - list_display: Поля для отображения (идентификатор, тип, вместимость, краткое описание оборудования).
# - list_filter: Фильтры по типу аудитории.
# - search_fields: Поиск по идентификатору и оборудованию.
# - ordering: Сортировка по идентификатору.
# - equipment_short: Кастомный метод для краткого отображения оборудования.
@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'type', 'capacity', 'equipment_short')
    list_filter = ('type',)
    search_fields = ('identifier', 'equipment')
    ordering = ('identifier',)

    def equipment_short(self, obj):
        return obj.equipment[:70] + '...' if len(obj.equipment) > 70 else obj.equipment
    equipment_short.short_description = _('Оборудование (кратко)')

# Класс StudentGroupAdmin настраивает отображение модели StudentGroup (Учебная группа).
# - list_display: Поля (название, учебный год, куратор, староста, количество студентов).
# - list_filter: Фильтры по учебному году и куратору.
# - search_fields: Поиск по названию группы, учебному году, ФИО/email куратора.
# - filter_horizontal: Удобный виджет для выбора студентов (M2M).
# - list_select_related: Оптимизация для полей 'academic_year', 'curator', 'group_monitor'.
# - ordering: Сортировка по учебному году, затем по названию группы.
# - Кастомные методы: curator_name, group_monitor_name, student_count.
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

# --- Настройки для Учебных Планов ---

# Класс CurriculumEntryInline для встроенного редактирования записей учебного плана.
# - model: Модель CurriculumEntry.
# - extra: Количество пустых форм для добавления.
# - autocomplete_fields: Поля с автодополнением для удобного выбора связанных объектов.
# - ordering: Сортировка записей.
# - fields: Явно указанные поля для отображения/редактирования в инлайне.
class CurriculumEntryInline(admin.TabularInline):
    model = CurriculumEntry
    extra = 1
    autocomplete_fields = ['subject', 'teacher', 'study_period']
    ordering = ['study_period__start_date', 'subject__name']
    fields = ('subject', 'teacher', 'study_period', 'planned_hours')

# Класс CurriculumAdmin настраивает отображение модели Curriculum (Учебный план).
# - list_display: Поля (название, учебный год, группа, активен ли, количество записей).
# - list_filter: Фильтры по учебному году, группе, активности.
# - search_fields: Поиск по названию, описанию, группе, учебному году.
# - list_select_related: Оптимизация для 'academic_year', 'student_group'.
# - inlines: Включение CurriculumEntryInline.
# - ordering: Сортировка.
# - entry_count: Кастомный метод для отображения количества записей в плане.
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

# Класс CurriculumEntryAdmin настраивает отображение модели CurriculumEntry (Запись учебного плана).
# - list_display: Поля (инфо о плане, предмет, преподаватель, период, часы).
# - list_filter: Фильтры по году, периоду, предмету, преподавателю, группе.
# - search_fields: Поиск по предмету, преподавателю, названию плана, группе.
# - list_select_related: Оптимизация запросов.
# - ordering: Сортировка.
# - fields: Поля для страницы редактирования.
# - readonly_fields: Поля, вычисляемые как property в модели (запланированные/оставшиеся часы).
# - Кастомные методы: curriculum_info, teacher_name, study_period_name, scheduled_hours_display, remaining_hours_display.
@admin.register(CurriculumEntry)
class CurriculumEntryAdmin(admin.ModelAdmin):
    list_display = ('curriculum_info', 'subject', 'teacher_name', 'study_period_name', 'planned_hours', 'scheduled_hours_display', 'remaining_hours_display')
    list_filter = ('curriculum__academic_year', 'study_period', 'subject', 'teacher', 'curriculum__student_group')
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
    readonly_fields = ('scheduled_hours', 'remaining_hours')

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

# --- Настройки для Расписания и Журнала ---

# Инлайны для модели Lesson:
# - LessonJournalEntryInline: Для ввода данных журнала (тема, заметки преподавателя).
# - AttendanceInline: Для отметки посещаемости студентов.
# - HomeworkInline: Для добавления домашних заданий к занятию.
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
    readonly_fields = ('author',) # Автор ДЗ обычно текущий преподаватель
    show_change_link = True

# Класс LessonAdmin настраивает отображение модели Lesson (Занятие/Урок).
# - list_display: Поля (предмет, группа, преподаватель, тип, время, аудитория, заполнен ли журнал).
# - list_filter: Фильтры по году, периоду, группе, преподавателю, предмету, аудитории, типу.
# - search_fields: Поиск.
# - date_hierarchy: Навигация по датам.
# - ordering: Сортировка.
# - list_select_related: Оптимизация.
# - autocomplete_fields: Поля с автодополнением.
# - fieldsets: Группировка полей на странице редактирования.
# - readonly_fields: Поля только для чтения (даты создания/обновления).
# - Кастомные методы: teacher_name, start_time_display, end_time_display, has_journal_entry.
# - save_model: Устанавливает 'created_by' при создании нового занятия.
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
    readonly_fields = ('created_at', 'updated_at') # Даты создания и обновления

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
        if not obj.pk and not obj.created_by: # Если объект создается и created_by не задан
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

# Класс LessonJournalEntryAdmin настраивает отображение модели LessonJournalEntry (Запись в журнале занятия).
# - list_display: Поля (инфо о занятии, краткая тема, дата заполнения).
# - list_filter: Фильтры.
# - search_fields: Поиск.
# - list_select_related: Оптимизация.
# - autocomplete_fields: Поля с автодополнением.
# - inlines: Включение HomeworkInline и AttendanceInline.
# - ordering: Сортировка.
# - readonly_fields: 'date_filled' (устанавливается автоматически).
# - Кастомные методы: lesson_info, topic_covered_short.
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

# --- Настройки для Домашних Заданий ---

# Инлайны для модели Homework:
# - HomeworkAttachmentInline: Для прикрепления файлов к домашнему заданию.
# - HomeworkSubmissionInline: Для просмотра списка сданных работ.
class HomeworkAttachmentInline(admin.TabularInline):
    model = HomeworkAttachment
    extra = 1
    fields = ('file', 'description')

class HomeworkSubmissionInline(admin.TabularInline):
    model = HomeworkSubmission
    extra = 0
    fields = ('student', 'submitted_at', 'get_attachments_count') # Убран content_short
    readonly_fields = ('submitted_at', 'get_attachments_count')
    autocomplete_fields = ['student']
    show_change_link = True # Позволяет перейти к редактированию сданной работы

    # content_short не нужен, если хотим только список
    # def content_short(self, obj):
    #    return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    # content_short.short_description = _('Ответ студента')

    def get_attachments_count(self, obj):
        return obj.attachments.count()
    get_attachments_count.short_description = _('Файлов сдано')

# Класс HomeworkAdmin настраивает отображение модели Homework (Домашнее задание).
# - list_display: Поля (название, инфо о занятии, автор, срок, количество сдач).
# - list_filter: Фильтры.
# - search_fields: Поиск.
# - list_select_related: Оптимизация.
# - autocomplete_fields: Поля с автодополнением.
# - inlines: Включение HomeworkAttachmentInline и HomeworkSubmissionInline.
# - ordering: Сортировка.
# - readonly_fields: 'created_at'.
# - Кастомные методы: lesson_info, author_name, submission_count.
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
        # Проверка, что journal_entry и lesson существуют
        if obj.journal_entry and obj.journal_entry.lesson:
            return str(obj.journal_entry.lesson)
        return "-"
    lesson_info.short_description = _('Занятие')

    def author_name(self, obj):
        return obj.author.get_full_name() if obj.author else '-'
    author_name.short_description = _('Автор ДЗ')

    def submission_count(self, obj):
        return obj.submissions.count()
    submission_count.short_description = _('Сдач')

# Инлайн для модели HomeworkSubmission:
# - SubmissionAttachmentInline: Для прикрепления файлов к сданной работе.
class SubmissionAttachmentInline(admin.TabularInline):
    model = SubmissionAttachment
    extra = 1

# Класс HomeworkSubmissionAdmin настраивает отображение модели HomeworkSubmission (Сданная работа).
# - list_display: Поля (название ДЗ, студент, дата сдачи, оценено ли).
# - list_filter: Фильтры.
# - search_fields: Поиск.
# - list_select_related: Оптимизация.
# - autocomplete_fields: Поля с автодополнением.
# - inlines: Включение SubmissionAttachmentInline.
# - readonly_fields: 'submitted_at'.
# - ordering: Сортировка.
# - Кастомные методы: homework_title, student_name, has_grade.
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

# --- Настройки для Посещаемости и Оценок ---

# Класс AttendanceAdmin настраивает отображение модели Attendance (Посещаемость).
# - list_display: Поля (инфо о занятии, студент, статус, комментарий, кем отмечено, время отметки).
# - list_filter: Фильтры.
# - search_fields: Поиск.
# - list_select_related: Оптимизация.
# - autocomplete_fields: Поля с автодополнением.
# - readonly_fields: 'marked_at'.
# - list_editable: Поля, которые можно редактировать прямо в списке.
# - ordering: Сортировка.
# - Кастомные методы: lesson_info, student_name, comment_short, marked_by_name, marked_at_display.
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('lesson_info', 'student_name', 'status', 'comment_short', 'marked_by_name', 'marked_at_display')
    list_filter = ('status', 'journal_entry__lesson__study_period__academic_year', 'journal_entry__lesson__subject', 'journal_entry__lesson__student_group', 'marked_by')
    search_fields = ('student__last_name', 'student__email', 'comment', 'journal_entry__lesson__subject__name')
    list_select_related = ('journal_entry__lesson__subject', 'journal_entry__lesson__student_group', 'student', 'marked_by')
    autocomplete_fields = ['journal_entry', 'student', 'marked_by']
    readonly_fields = ('marked_at',)
    list_editable = ('status',) # Убрали comment, его лучше редактировать отдельно
    ordering = ('-journal_entry__lesson__start_time', 'student__last_name')

    def lesson_info(self, obj):
        # Проверка, что journal_entry и lesson существуют
        if obj.journal_entry and obj.journal_entry.lesson:
            return str(obj.journal_entry.lesson)
        return "-"
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

# Класс GradeAdmin настраивает отображение модели Grade (Оценка).
# - list_display: Поля (студент, предмет, оценка, тип, период, инфо о занятии, дата, кем выставлена).
# - list_filter: Фильтры.
# - search_fields: Поиск.
# - list_select_related: Оптимизация.
# - autocomplete_fields: Поля с автодополнением.
# - ordering: Сортировка.
# - readonly_fields: 'date_given'.
# - fieldsets: Группировка полей на странице редактирования.
# - Кастомные методы: student_name, subject_name, grade_value_display, study_period_name, lesson_info_short, graded_by_name.
# - save_model: Автоматически устанавливает 'graded_by' (кем выставлена оценка), если не указано.
@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student_name', 'subject_name', 'grade_value_display', 'grade_type', 'study_period_name', 'lesson_info_short', 'date_given', 'graded_by_name')
    list_filter = ('grade_type', 'study_period__academic_year', 'study_period', 'subject', 'graded_by', 'date_given')
    search_fields = ('student__last_name', 'student__email', 'subject__name', 'grade_value', 'comment')
    list_select_related = ('student', 'subject', 'study_period', 'lesson', 'homework_submission', 'graded_by')
    autocomplete_fields = ['student', 'subject', 'study_period', 'lesson', 'homework_submission', 'graded_by']
    ordering = ('-date_given', 'student__last_name', 'subject__name')
    readonly_fields = ('date_given',) # date_given часто auto_now_add

    fieldsets = (
        (None, {'fields': ('student', 'subject', 'study_period')}),
        (_('Детали оценки'), {'fields': ('grade_type', 'grade_value', 'numeric_value', 'weight', 'comment')}), # Убрали date_given, если auto_now_add
        (_('Связи (опционально)'), {'fields': ('lesson', 'homework_submission')}),
        (_('Автор оценки'), {'fields': ('graded_by',)}),
    )
    # Если date_given не auto_now_add, его можно вернуть в fieldsets

    def student_name(self, obj):
        return obj.student.get_full_name()
    student_name.short_description = _('Студент')
    student_name.admin_order_field = 'student__last_name'

    def subject_name(self, obj):
        return obj.subject.name
    subject_name.short_description = _('Предмет')
    subject_name.admin_order_field = 'subject__name'

    def grade_value_display(self, obj):
        return f"{obj.grade_value} ({obj.numeric_value})" if obj.numeric_value is not None else obj.grade_value
    grade_value_display.short_description = _('Оценка (число)')

    def study_period_name(self, obj):
        return str(obj.study_period) if obj.study_period else '-'
    study_period_name.short_description = _('Учебный период')

    def lesson_info_short(self, obj):
        return str(obj.lesson) if obj.lesson else '-'
    lesson_info_short.short_description = _('Занятие (если есть)')

    def graded_by_name(self, obj):
        return obj.graded_by.get_full_name() if obj.graded_by else '-'
    graded_by_name.short_description = _('Кем выставлена')

    def save_model(self, request, obj, form, change):
        if not obj.graded_by_id : # Проверяем, что graded_by еще не установлен
            if obj.lesson and obj.lesson.teacher:
                obj.graded_by = obj.lesson.teacher
            elif obj.homework_submission and obj.homework_submission.homework and obj.homework_submission.homework.author:
                obj.graded_by = obj.homework_submission.homework.author
            elif request.user.is_authenticated and hasattr(request.user, 'is_teacher') and request.user.is_teacher :
                 obj.graded_by = request.user
        super().save_model(request, obj, form, change)

# --- Настройки для Библиотеки Материалов ---

# Класс SubjectMaterialAttachmentAdmin настраивает отображение модели SubjectMaterialAttachment (Вложение к учебному материалу).
# - list_display: Поля (ID, ссылка на материал, имя файла, описание, дата загрузки).
# - list_select_related: Оптимизация.
# - search_fields: Поиск.
# - list_filter: Фильтры.
# - readonly_fields: 'uploaded_at'.
# - Кастомные методы: subject_material_link, file_name_display.
@admin.register(SubjectMaterialAttachment)
class SubjectMaterialAttachmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject_material_link', 'file_name_display', 'description', 'uploaded_at')
    list_select_related = ('subject_material', 'subject_material__subject')
    search_fields = ('file', 'description', 'subject_material__title')
    list_filter = ('uploaded_at', 'subject_material__subject')
    readonly_fields = ('uploaded_at',)

    def subject_material_link(self, obj):
        if obj.subject_material:
            link = reverse(f"admin:{obj.subject_material._meta.app_label}_{obj.subject_material._meta.model_name}_change", args=[obj.subject_material.id])
            return format_html('<a href="{}">{}</a>', link, obj.subject_material.title or obj.subject_material.id) # Используем title или id
        return "-"
    subject_material_link.short_description = 'Учебный материал'

    def file_name_display(self, obj):
        return os.path.basename(obj.file.name) if obj.file else "-"
    file_name_display.short_description = 'Имя файла'

# Инлайн для SubjectMaterial:
# - SubjectMaterialAttachmentInline: Для управления вложениями на странице учебного материала.
class SubjectMaterialAttachmentInline(admin.TabularInline):
    model = SubjectMaterialAttachment
    fields = ('file', 'description')
    extra = 1

# Класс SubjectMaterialAdmin настраивает отображение модели SubjectMaterial (Учебный материал).
# - list_display: Поля (название, предмет, группа, кем загружено, дата загрузки, количество файлов).
# - list_filter: Фильтры.
# - search_fields: Поиск.
# - list_select_related: Оптимизация.
# - readonly_fields: 'uploaded_at'.
# - fields: Поля для страницы редактирования.
# - inlines: Включение SubjectMaterialAttachmentInline.
# - Кастомные методы: student_group_display, files_count_display.
# - save_model: Устанавливает 'uploaded_by' при создании, если не указано.
@admin.register(SubjectMaterial)
class SubjectMaterialAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'student_group_display', 'uploaded_by', 'uploaded_at', 'files_count_display')
    list_filter = ('subject', 'student_group', 'uploaded_by', 'uploaded_at')
    search_fields = ('title', 'description', 'subject__name', 'student_group__name')
    list_select_related = ('subject', 'student_group', 'uploaded_by')
    readonly_fields = ('uploaded_at',)
    fields = ('title', 'description', 'subject', 'student_group', 'uploaded_by')
    inlines = [SubjectMaterialAttachmentInline]

    def student_group_display(self, obj):
        return obj.student_group.name if obj.student_group else _("Для всех групп")
    student_group_display.short_description = 'Группа'
    student_group_display.admin_order_field = 'student_group__name'

    def files_count_display(self, obj):
        return obj.attachments.count()
    files_count_display.short_description = 'Файлов'

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id and request.user.is_authenticated:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)