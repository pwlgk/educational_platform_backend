from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers as nested_routers
from . import views

# --- 1. АДМИНИСТРАТИВНЫЕ ЭНДПОИНТЫ ---
# Создается основной роутер для административных ViewSet'ов.
# Каждый ViewSet регистрируется с префиксом URL и базовым именем для генерации имен паттернов.
# Например, AcademicYearViewSet будет доступен по URL .../management/academic-years/.
admin_router = DefaultRouter()
admin_router.register(r'academic-years', views.AcademicYearViewSet, basename='academic-year')
admin_router.register(r'study-periods', views.StudyPeriodViewSet, basename='study-period')
admin_router.register(r'subject-types', views.SubjectTypeViewSet, basename='subject-type')
admin_router.register(r'subjects', views.SubjectViewSet, basename='subject')
admin_router.register(r'classrooms', views.ClassroomViewSet, basename='classroom')
admin_router.register(r'student-groups', views.StudentGroupViewSet, basename='student-group')
admin_router.register(r'curricula', views.CurriculumViewSet, basename='curriculum')
admin_router.register(r'lessons', views.LessonViewSet, basename='lesson-admin')
admin_router.register(r'journal-entries', views.LessonJournalEntryViewSet, basename='journal-entry-admin')
admin_router.register(r'homework', views.HomeworkViewSet, basename='homework-admin')
admin_router.register(r'homework-attachments', views.HomeworkAttachmentViewSet, basename='homework-attachment-admin')
admin_router.register(r'homework-submissions', views.HomeworkSubmissionViewSet, basename='homework-submission-admin')
admin_router.register(r'submission-attachments', views.SubmissionAttachmentViewSet, basename='submission-attachment-admin')
admin_router.register(r'attendances', views.AttendanceViewSet, basename='attendance-admin')
admin_router.register(r'grades', views.GradeViewSet, basename='grade-admin')
admin_router.register(r'subject-materials', views.SubjectMaterialViewSet, basename='subject-material-admin')

# Вложенные роутеры для администратора:
# Эти роутеры создают URL-ы для ресурсов, вложенных в другие.
# Например, .../management/curricula/{curriculum_pk}/entries/ для записей учебного плана.
admin_curricula_router = nested_routers.NestedDefaultRouter(admin_router, r'curricula', lookup='curriculum')
admin_curricula_router.register(r'entries', views.CurriculumEntryViewSet, basename='curriculum-entry')

admin_lessons_router = nested_routers.NestedDefaultRouter(admin_router, r'lessons', lookup='lesson')
admin_lessons_router.register(r'journal', views.LessonJournalEntryViewSet, basename='lesson-journal-entry')
admin_lessons_router.register(r'attendances', views.AttendanceViewSet, basename='lesson-attendance')
admin_lessons_router.register(r'grades', views.GradeViewSet, basename='lesson-grade')

admin_journal_router = nested_routers.NestedDefaultRouter(admin_router, r'journal-entries', lookup='journal_entry')
admin_journal_router.register(r'homework', views.HomeworkViewSet, basename='journal-homework')
admin_journal_router.register(r'attendances', views.AttendanceViewSet, basename='journal-attendance')

admin_homework_router = nested_routers.NestedDefaultRouter(admin_router, r'homework', lookup='homework')
admin_homework_router.register(r'attachments', views.HomeworkAttachmentViewSet, basename='homework-attachment')
admin_homework_router.register(r'submissions', views.HomeworkSubmissionViewSet, basename='homework-submission-list')

admin_submissions_router = nested_routers.NestedDefaultRouter(admin_router, r'homework-submissions', lookup='submission')
admin_submissions_router.register(r'attachments', views.SubmissionAttachmentViewSet, basename='submission-attachment')


# --- 2. ЭНДПОИНТЫ ДЛЯ ПРЕПОДАВАТЕЛЕЙ ---
# Аналогично административным, создается роутер для ViewSet'ов, специфичных для преподавателей.
# ViewSet'ы для преподавателей обычно содержат логику фильтрации данных,
# чтобы преподаватель видел только свои занятия, группы, ДЗ и т.д.
teacher_router = DefaultRouter()
teacher_router.register(r'schedule', views.TeacherMyScheduleViewSet, basename='teacher-schedule')
teacher_router.register(r'journal-entries', views.TeacherLessonJournalViewSet, basename='teacher-journal-entry')
teacher_router.register(r'homework', views.TeacherHomeworkViewSet, basename='teacher-homework')
teacher_router.register(r'homework-submissions', views.TeacherHomeworkSubmissionViewSet, basename='teacher-homework-submission')
teacher_router.register(r'attendances', views.TeacherAttendanceViewSet, basename='teacher-attendance')
teacher_router.register(r'grades', views.TeacherGradeViewSet, basename='teacher-grade')
teacher_router.register(r'subject-materials', views.TeacherSubjectMaterialViewSet, basename='teacher-subject-material')

# Вложенные роутеры для преподавателей.
teacher_schedule_router = nested_routers.NestedDefaultRouter(teacher_router, r'schedule', lookup='lesson')
teacher_schedule_router.register(r'journal', views.TeacherLessonJournalViewSet, basename='teacher-lesson-journal')
teacher_schedule_router.register(r'attendances', views.TeacherAttendanceViewSet, basename='teacher-lesson-attendance')
teacher_schedule_router.register(r'grades', views.TeacherGradeViewSet, basename='teacher-lesson-grade')

teacher_journal_router = nested_routers.NestedDefaultRouter(teacher_router, r'journal-entries', lookup='journal_entry')
teacher_journal_router.register(r'homework', views.TeacherHomeworkViewSet, basename='teacher-journal-homework')

teacher_homework_router = nested_routers.NestedDefaultRouter(teacher_router, r'homework', lookup='homework')
teacher_homework_router.register(r'attachments', views.HomeworkAttachmentViewSet, basename='teacher-homework-attachment') # Может использовать общий ViewSet
teacher_homework_router.register(r'submissions', views.TeacherHomeworkSubmissionViewSet, basename='teacher-homework-submission-list')

teacher_submissions_router = nested_routers.NestedDefaultRouter(teacher_router, r'homework-submissions', lookup='submission')
teacher_submissions_router.register(r'attachments', views.SubmissionAttachmentViewSet, basename='teacher-submission-attachment-view') # Общий ViewSet


# --- 3. ЭНДПОИНТЫ ДЛЯ КУРАТОРОВ ---
# Роутер для функционала кураторов.
curator_router = DefaultRouter()
curator_router.register(r'managed-groups', views.CuratorManagedGroupsViewSet, basename='curator-managed-groups')


# --- 4. ЭНДПОИНТЫ ДЛЯ СТУДЕНТОВ ---
# Роутер для ViewSet'ов, предназначенных для студентов.
student_router = DefaultRouter()
student_router.register(r'homework-submissions', views.StudentMyHomeworkSubmissionViewSet, basename='student-homework-submission')

# Вложенные роутеры для студентов.
student_submissions_router = nested_routers.NestedDefaultRouter(student_router, r'homework-submissions', lookup='submission')
student_submissions_router.register(r'attachments', views.SubmissionAttachmentViewSet, basename='student-submission-attachment') # Общий ViewSet


# --- ОБЪЕДИНЕННЫЙ urlpatterns ---
# Собирает все определенные выше роутеры и отдельные пути в единый список urlpatterns.
# Каждый набор эндпоинтов (административные, преподавательские и т.д.)
# группируется под своим префиксом URL (например, 'management/', 'teacher/').
urlpatterns = [
    # Административные эндпоинты с префиксом 'management/'
    path('management/', include(admin_router.urls)),
    path('management/', include(admin_curricula_router.urls)),
    path('management/', include(admin_lessons_router.urls)),
    path('management/', include(admin_journal_router.urls)),
    path('management/', include(admin_homework_router.urls)),
    path('management/', include(admin_submissions_router.urls)),
    # Пути для импорта/экспорта данных и статистики (доступны администраторам)
    path('management/import/<str:import_type>/', views.ImportDataView.as_view(), name='import-data'),
    path('management/export/journal/', views.ExportJournalView.as_view(), name='export-journal'),
    path('management/stats/teacher-load/', views.TeacherLoadStatsView.as_view(), name='stats-teacher-load'),
    path('management/stats/teacher-subject-performance/', views.TeacherSubjectPerformanceStatsView.as_view(), name='stats-teacher-subject-performance'),
    path('management/stats/group-performance/', views.GroupPerformanceView.as_view(), name='stats-group-performance-admin'),

    # Эндпоинты для Преподавателей с префиксом 'teacher/'
    path('teacher/', include(teacher_router.urls)),
    path('teacher/', include(teacher_schedule_router.urls)),
    path('teacher/', include(teacher_journal_router.urls)),
    path('teacher/', include(teacher_homework_router.urls)),
    path('teacher/', include(teacher_submissions_router.urls)),
    path('teacher/my-groups/', views.TeacherMyGroupsView.as_view(), name='teacher-my-groups-list'),
    # Общий эндпоинт для получения комплексных данных журнала (для преподавателей)
    path('journal-data/', views.ComprehensiveJournalDataView.as_view(), name='comprehensive-journal-data'),


    # Эндпоинты для Кураторов с префиксом 'curator/'
    path('curator/', include(curator_router.urls)),
    path('curator/managed-groups/<int:group_pk>/performance/', views.CuratorGroupPerformanceView.as_view(), name='curator-group-performance'),

    # Эндпоинты для Студентов с префиксом 'student/'
    path('student/', include(student_router.urls)),
    path('student/', include(student_submissions_router.urls)),
    path('student/schedule/', views.StudentMyScheduleListView.as_view(), name='student-my-schedule'),
    path('student/grades/', views.StudentMyGradesListView.as_view(), name='student-my-grades'),
    path('student/attendance/', views.StudentMyAttendanceListView.as_view(), name='student-my-attendance'),
    path('student/homework/', views.StudentMyHomeworkListView.as_view(), name='student-my-homework'),
    path('student/homework/<int:homework_id>/', views.StudentMyHomeworkDetailView.as_view(), name='student-my-homework-detail'),

    # Эндпоинты для Родителей с префиксом 'parent/'
    path('parent/child-schedule/', views.ParentChildScheduleListView.as_view(), name='parent-child-schedule'),
    path('parent/child-grades/', views.ParentChildGradesListView.as_view(), name='parent-child-grades'),
    path('parent/child-attendance/', views.ParentChildAttendanceListView.as_view(), name='parent-child-attendance'),
    path('parent/child-homework/', views.ParentChildHomeworkListView.as_view(), name='parent-child-homework'),
]