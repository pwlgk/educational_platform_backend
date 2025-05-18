from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers as nested_routers # Для возможных вложенных маршрутов

from . import views

# --- 1. АДМИНИСТРАТИВНЫЕ ЭНДПОИНТЫ ---
admin_router = DefaultRouter()
admin_router.register(r'academic-years', views.AcademicYearViewSet, basename='academic-year')
admin_router.register(r'study-periods', views.StudyPeriodViewSet, basename='study-period')
admin_router.register(r'subject-types', views.SubjectTypeViewSet, basename='subject-type')
admin_router.register(r'subjects', views.SubjectViewSet, basename='subject')
admin_router.register(r'classrooms', views.ClassroomViewSet, basename='classroom')
admin_router.register(r'student-groups', views.StudentGroupViewSet, basename='student-group') # Админ управляет всеми группами
admin_router.register(r'curricula', views.CurriculumViewSet, basename='curriculum')
# CurriculumEntry лучше сделать вложенным в Curriculum
# admin_router.register(r'curriculum-entries', views.CurriculumEntryViewSet, basename='curriculum-entry')
admin_router.register(r'lessons', views.LessonViewSet, basename='lesson-admin') # Общий для админа, включает my_schedule action
admin_router.register(r'journal-entries', views.LessonJournalEntryViewSet, basename='journal-entry-admin')
admin_router.register(r'homework', views.HomeworkViewSet, basename='homework-admin')
admin_router.register(r'homework-attachments', views.HomeworkAttachmentViewSet, basename='homework-attachment-admin')
admin_router.register(r'homework-submissions', views.HomeworkSubmissionViewSet, basename='homework-submission-admin') # Админ видит все сдачи
admin_router.register(r'submission-attachments', views.SubmissionAttachmentViewSet, basename='submission-attachment-admin')
admin_router.register(r'attendances', views.AttendanceViewSet, basename='attendance-admin')
admin_router.register(r'grades', views.GradeViewSet, basename='grade-admin')
admin_router.register(r'subject-materials', views.SubjectMaterialViewSet, basename='subject-material-admin')

# Вложенные маршруты для администратора
admin_curricula_router = nested_routers.NestedDefaultRouter(admin_router, r'curricula', lookup='curriculum')
admin_curricula_router.register(r'entries', views.CurriculumEntryViewSet, basename='curriculum-entry')

admin_lessons_router = nested_routers.NestedDefaultRouter(admin_router, r'lessons', lookup='lesson')
admin_lessons_router.register(r'journal', views.LessonJournalEntryViewSet, basename='lesson-journal-entry') # Для CRUD журнала урока
admin_lessons_router.register(r'attendances', views.AttendanceViewSet, basename='lesson-attendance') # Для CRUD посещаемости урока
admin_lessons_router.register(r'grades', views.GradeViewSet, basename='lesson-grade') # Для CRUD оценок за урок

admin_journal_router = nested_routers.NestedDefaultRouter(admin_router, r'journal-entries', lookup='journal_entry')
admin_journal_router.register(r'homework', views.HomeworkViewSet, basename='journal-homework') # ДЗ для записи в журнале
admin_journal_router.register(r'attendances', views.AttendanceViewSet, basename='journal-attendance') # Посещаемость для записи в журнале

admin_homework_router = nested_routers.NestedDefaultRouter(admin_router, r'homework', lookup='homework')
admin_homework_router.register(r'attachments', views.HomeworkAttachmentViewSet, basename='homework-attachment')
admin_homework_router.register(r'submissions', views.HomeworkSubmissionViewSet, basename='homework-submission-list')

admin_submissions_router = nested_routers.NestedDefaultRouter(admin_router, r'homework-submissions', lookup='submission')
admin_submissions_router.register(r'attachments', views.SubmissionAttachmentViewSet, basename='submission-attachment')


# --- 2. ЭНДПОИНТЫ ДЛЯ ПРЕПОДАВАТЕЛЕЙ ---
teacher_router = DefaultRouter()
teacher_router.register(r'schedule', views.TeacherMyScheduleViewSet, basename='teacher-schedule') # Это ModelViewSet
teacher_router.register(r'journal-entries', views.TeacherLessonJournalViewSet, basename='teacher-journal-entry')
teacher_router.register(r'homework', views.TeacherHomeworkViewSet, basename='teacher-homework')
teacher_router.register(r'homework-submissions', views.TeacherHomeworkSubmissionViewSet, basename='teacher-homework-submission')
teacher_router.register(r'attendances', views.TeacherAttendanceViewSet, basename='teacher-attendance')
teacher_router.register(r'grades', views.TeacherGradeViewSet, basename='teacher-grade')
teacher_router.register(r'subject-materials', views.TeacherSubjectMaterialViewSet, basename='teacher-subject-material')

# Вложенные для преподавателя (аналогично админским, но с фильтрацией по преподавателю во ViewSet'ах)
teacher_schedule_router = nested_routers.NestedDefaultRouter(teacher_router, r'schedule', lookup='lesson')
teacher_schedule_router.register(r'journal', views.TeacherLessonJournalViewSet, basename='teacher-lesson-journal')
teacher_schedule_router.register(r'attendances', views.TeacherAttendanceViewSet, basename='teacher-lesson-attendance')
teacher_schedule_router.register(r'grades', views.TeacherGradeViewSet, basename='teacher-lesson-grade')

teacher_journal_router = nested_routers.NestedDefaultRouter(teacher_router, r'journal-entries', lookup='journal_entry')
teacher_journal_router.register(r'homework', views.TeacherHomeworkViewSet, basename='teacher-journal-homework')

teacher_homework_router = nested_routers.NestedDefaultRouter(teacher_router, r'homework', lookup='homework')
teacher_homework_router.register(r'attachments', views.HomeworkAttachmentViewSet, basename='teacher-homework-attachment')
teacher_homework_router.register(r'submissions', views.TeacherHomeworkSubmissionViewSet, basename='teacher-homework-submission-list')

teacher_submissions_router = nested_routers.NestedDefaultRouter(teacher_router, r'homework-submissions', lookup='submission')
teacher_submissions_router.register(r'attachments', views.SubmissionAttachmentViewSet, basename='teacher-submission-attachment-view') # Просмотр


# --- 3. ЭНДПОИНТЫ ДЛЯ КУРАТОРОВ ---
curator_router = DefaultRouter()
curator_router.register(r'managed-groups', views.CuratorManagedGroupsViewSet, basename='curator-managed-groups')
# Для статистики используем path()


# --- 4. ЭНДПОИНТЫ ДЛЯ СТУДЕНТОВ ---
student_router = DefaultRouter()
student_router.register(r'homework-submissions', views.StudentMyHomeworkSubmissionViewSet, basename='student-homework-submission')

# Вложенные для студента
student_submissions_router = nested_routers.NestedDefaultRouter(student_router, r'homework-submissions', lookup='submission')
student_submissions_router.register(r'attachments', views.SubmissionAttachmentViewSet, basename='student-submission-attachment')


# --- ОБЪЕДИНЕННЫЙ urlpatterns ---
urlpatterns = [
    # --- Административные эндпоинты ---
    path('management/', include(admin_router.urls)),
    path('management/', include(admin_curricula_router.urls)),
    path('management/', include(admin_lessons_router.urls)),
    path('management/', include(admin_journal_router.urls)),
    path('management/', include(admin_homework_router.urls)),
    path('management/', include(admin_submissions_router.urls)),
    path('management/import/<str:import_type>/', views.ImportDataView.as_view(), name='import-data'),
    path('management/export/journal/', views.ExportJournalView.as_view(), name='export-journal'),
    path('management/stats/teacher-load/', views.TeacherLoadStatsView.as_view(), name='stats-teacher-load'),
    path('management/stats/teacher-subject-performance/', views.TeacherSubjectPerformanceStatsView.as_view(), name='stats-teacher-subject-performance'),
    path('management/stats/group-performance/', views.GroupPerformanceView.as_view(), name='stats-group-performance-admin'),

    # --- Эндпоинты для Преподавателей ---
    path('teacher/', include(teacher_router.urls)),
    path('teacher/', include(teacher_schedule_router.urls)),
    path('teacher/', include(teacher_journal_router.urls)),
    path('teacher/', include(teacher_homework_router.urls)),
    path('teacher/', include(teacher_submissions_router.urls)),
    path('teacher/my-groups/', views.TeacherMyGroupsView.as_view(), name='teacher-my-groups-list'), # Это ListAPIView

    # --- Эндпоинты для Кураторов ---
    path('curator/', include(curator_router.urls)),
    path('curator/managed-groups/<int:group_pk>/performance/', views.CuratorGroupPerformanceView.as_view(), name='curator-group-performance'), # ListAPIView

    # --- Эндпоинты для Студентов ---
    path('student/', include(student_router.urls)), # Содержит StudentMyHomeworkSubmissionViewSet
    path('student/', include(student_submissions_router.urls)), # Вложенные аттачменты для сдачи
    path('student/schedule/', views.StudentMyScheduleListView.as_view(), name='student-my-schedule'),
    path('student/grades/', views.StudentMyGradesListView.as_view(), name='student-my-grades'),
    path('student/attendance/', views.StudentMyAttendanceListView.as_view(), name='student-my-attendance'),
    path('student/homework/', views.StudentMyHomeworkListView.as_view(), name='student-my-homework'),

    # --- Эндпоинты для Родителей (все ListAPIView) ---
    path('parent/child-schedule/', views.ParentChildScheduleListView.as_view(), name='parent-child-schedule'),
    path('parent/child-grades/', views.ParentChildGradesListView.as_view(), name='parent-child-grades'),
    path('parent/child-attendance/', views.ParentChildAttendanceListView.as_view(), name='parent-child-attendance'),
    path('parent/child-homework/', views.ParentChildHomeworkListView.as_view(), name='parent-child-homework'),
]