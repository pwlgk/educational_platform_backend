from django.contrib import admin
from .models import Subject, StudentGroup, Classroom, Lesson

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'curator', 'student_count')
    search_fields = ('name', 'curator__email', 'curator__last_name')
    filter_horizontal = ('students',) # Удобный виджет для ManyToMany

    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Кол-во студентов'

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'type', 'capacity')
    list_filter = ('type',)
    search_fields = ('identifier',)

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('subject', 'group', 'teacher', 'classroom', 'lesson_type', 'start_time', 'end_time')
    list_filter = ('lesson_type', 'start_time', 'group', 'teacher', 'classroom', 'subject')
    search_fields = ('subject__name', 'group__name', 'teacher__email', 'teacher__last_name', 'classroom__identifier')
    list_select_related = ('subject', 'group', 'teacher', 'classroom') # Оптимизация запросов в админке
    date_hierarchy = 'start_time' # Навигация по дате
    ordering = ('start_time',)
    # Поля для редактирования
    fields = ('subject', 'teacher', 'group', 'classroom', 'lesson_type', ('start_time', 'end_time'), 'created_by') # Группировка времени
    readonly_fields = ('created_at', 'updated_at') # 'created_by' заполняется во ViewSet

    def save_model(self, request, obj, form, change):
        # Автоматически устанавливаем created_by при создании из админки, если не задано
        if not obj.pk and not obj.created_by:
             if request.user.is_authenticated and (request.user.is_teacher or request.user.is_admin):
                obj.created_by = request.user
        super().save_model(request, obj, form, change)