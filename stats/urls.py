# stats/urls.py
from django.urls import path, include

from .views import (
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

# --- Префиксы для URL ---
# /api/stats/admin/...
# /api/stats/teacher/...
# /api/stats/student/...
# /api/stats/parent/...

admin_urlpatterns = [
    path('platform-summary/', AdminPlatformSummaryStatsView.as_view(), name='admin-stats-platform-summary'),
    path('teachers-load/summary/', AdminAllTeachersLoadView.as_view(), name='admin-stats-teachers-load-summary'),
    path('teachers-load/detail/<int:teacher_id>/', AdminTeacherLoadDetailView.as_view(), name='admin-stats-teacher-load-detail'),
    path('groups/<int:group_id>/performance/', AdminGroupPerformanceView.as_view(), name='admin-stats-group-performance'),
    path('students-performance-filtered/', AdminStudentsByPerformanceView.as_view(), name='admin-stats-students-filtered'), # Например, группы риска/отличники
    path('attendance/overall/', AdminOverallAttendanceStatsView.as_view(), name='admin-stats-overall-attendance'),
    path('homework/overall/', AdminHomeworkOverallStatsView.as_view(), name='admin-stats-homework-overall'),
    # Добавьте другие эндпоинты для админа по мере необходимости
]

teacher_urlpatterns = [
    path('my-summary/', TeacherMyOverallStatsView.as_view(), name='teacher-stats-my-summary'),
    path('my-groups/<int:group_id>/student-details/', TeacherGroupStudentDetailsView.as_view(), name='teacher-stats-group-student-details'),
    # Эндпоинт для успеваемости по предмету/группе для преподавателя (если нужен отдельный от my-summary)
    # path('my-subjects/<int:subject_id>/groups/<int:group_id>/performance/', TeacherSubjectGroupPerformanceView.as_view(), name='teacher-subject-group-performance'),
]

student_urlpatterns = [
    path('my-performance/', StudentMyPerformanceStatsView.as_view(), name='student-stats-my-performance'),
]

parent_urlpatterns = [
    path('child/<int:child_id>/performance/', ParentChildPerformanceStatsView.as_view(), name='parent-stats-child-performance'),
]

urlpatterns = [
    path('admin/', include((admin_urlpatterns, 'admin_stats'))),
    path('teacher/', include((teacher_urlpatterns, 'teacher_stats'))),
    path('student/', include((student_urlpatterns, 'student_stats'))),
    path('parent/', include((parent_urlpatterns, 'parent_stats'))),
]