from django.urls import path, include
from .views import ( # Импорт всех необходимых представлений (views)
    AdminPlatformSummaryStatsView,
    AdminAllTeachersLoadView,
    AdminTeacherLoadDetailView,
    AdminGroupPerformanceView,
    AdminStudentsByPerformanceView,
    AdminOverallAttendanceStatsView,
    AdminHomeworkOverallStatsView,
    TeacherMyOverallStatsView,
    TeacherGroupStudentDetailsView,
    StudentMyPerformanceStatsView,
    ParentChildPerformanceStatsView
)

# --- URL-маршруты для Администратора ---
# Этот список определяет URL-пути для эндпоинтов статистики, доступных администраторам.
# Каждый путь сопоставляется с соответствующим классом View и получает уникальное имя.
# Префикс для этих URL (например, /api/stats/admin/) будет задан в основном файле urls.py проекта.
admin_urlpatterns = [
    # Общая сводная статистика по платформе
    path('platform-summary/', AdminPlatformSummaryStatsView.as_view(), name='admin-stats-platform-summary'),
    # Сводная статистика по нагрузке всех преподавателей
    path('teachers-load/summary/', AdminAllTeachersLoadView.as_view(), name='admin-stats-teachers-load-summary'),
    # Детализированная статистика по нагрузке конкретного преподавателя
    path('teachers-load/detail/<int:teacher_id>/', AdminTeacherLoadDetailView.as_view(), name='admin-stats-teacher-load-detail'),
    # Статистика успеваемости по конкретной группе
    path('groups/<int:group_id>/performance/', AdminGroupPerformanceView.as_view(), name='admin-stats-group-performance'),
    # Список студентов, отфильтрованных по успеваемости (например, группы риска/отличники)
    path('students-performance-filtered/', AdminStudentsByPerformanceView.as_view(), name='admin-stats-students-filtered'),
    # Общая статистика по посещаемости
    path('attendance/overall/', AdminOverallAttendanceStatsView.as_view(), name='admin-stats-overall-attendance'),
    # Общая статистика по домашним заданиям
    path('homework/overall/', AdminHomeworkOverallStatsView.as_view(), name='admin-stats-homework-overall'),
]

# --- URL-маршруты для Преподавателя ---
# Определяет URL-пути для эндпоинтов статистики, доступных преподавателям.
# Префикс (например, /api/stats/teacher/) задается в основном urls.py.
teacher_urlpatterns = [
    # Сводная статистика для текущего преподавателя (нагрузка, ДЗ, успеваемость курируемых групп)
    path('my-summary/', TeacherMyOverallStatsView.as_view(), name='teacher-stats-my-summary'),
    # Детализированная успеваемость студентов в конкретной группе (для преподавателя/куратора)
    path('my-groups/<int:group_id>/student-details/', TeacherGroupStudentDetailsView.as_view(), name='teacher-stats-group-student-details'),
]

# --- URL-маршруты для Студента ---
# Определяет URL-пути для эндпоинтов статистики, доступных студентам.
# Префикс (например, /api/stats/student/) задается в основном urls.py.
student_urlpatterns = [
    # Сводная статистика успеваемости и посещаемости для текущего студента
    path('my-performance/', StudentMyPerformanceStatsView.as_view(), name='student-stats-my-performance'),
]

# --- URL-маршруты для Родителя ---
# Определяет URL-пути для эндпоинтов статистики, доступных родителям.
# Префикс (например, /api/stats/parent/) задается в основном urls.py.
parent_urlpatterns = [
    # Сводная статистика успеваемости и посещаемости для конкретного ребенка родителя
    path('child/<int:child_id>/performance/', ParentChildPerformanceStatsView.as_view(), name='parent-stats-child-performance'),
]

# --- Общий список urlpatterns для модуля 'stats' ---
# Объединяет все вышеопределенные списки URL-маршрутов, группируя их по ролям
# с использованием соответствующего префикса и пространства имен (namespace).
# Например, все административные URL-ы будут доступны через /admin/...
# относительно основного префикса модуля 'stats'.
urlpatterns = [
    path('admin/', include((admin_urlpatterns, 'admin_stats'))),
    path('teacher/', include((teacher_urlpatterns, 'teacher_stats'))),
    path('student/', include((student_urlpatterns, 'student_stats'))),
    path('parent/', include((parent_urlpatterns, 'parent_stats'))),
]