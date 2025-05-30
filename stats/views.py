import logging
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator # Для декораторов кэширования
from django.views.decorators.cache import cache_page # Для кэширования на уровне view
from django.utils.translation import gettext_lazy as _
from django.conf import settings # Для глобальных настроек, если нужны

from edu_core.models import Lesson, StudentGroup, StudyPeriod # Модели из edu_core
from .services import ( # Сервисы для получения статистических данных
    PlatformStatsService, 
    TeacherLoadStatsService, 
    StudentPerformanceStatsService,
    AttendanceStatsService, 
    HomeworkStatsService,
    get_active_academic_year_service # Вспомогательная сервисная функция
)
from users.permissions import IsAdmin, IsTeacher, IsStudent, IsParent, IsTeacherOrAdmin # Кастомные пермишены
from users.models import User # Модель пользователя

logger = logging.getLogger(__name__)

# Вспомогательная функция для извлечения и валидации ID учебного года и периода из параметров запроса.
# - request: Объект HTTP-запроса.
# - study_period_required: Флаг, указывающий, обязателен ли ID учебного периода.
# - default_to_active_year: Флаг, указывающий, использовать ли текущий активный учебный год по умолчанию,
#   если параметры года/периода не переданы.
# Возвращает словарь с 'academic_year_id' и 'study_period_id' или выбрасывает ValueError.
def get_effective_period_filters(request, study_period_required=False, default_to_active_year=True):
    academic_year_id_str = request.query_params.get('academic_year_id')
    study_period_id_str = request.query_params.get('study_period_id')
    academic_year_id, study_period_id = None, None
    parse_error_message = ""

    if study_period_id_str:
        try: study_period_id = int(study_period_id_str)
        except ValueError: parse_error_message += _(" Некорректный ID учебного периода.")
    if academic_year_id_str:
        try: academic_year_id = int(academic_year_id_str)
        except ValueError: parse_error_message += _(" Некорректный ID учебного года.") # Исправлена опечатка
    if parse_error_message: raise ValueError(parse_error_message.strip())

    if default_to_active_year and not academic_year_id and not study_period_id:
        active_year = get_active_academic_year_service()
        if active_year:
            academic_year_id = active_year.id
            if study_period_required: # Если период обязателен, пытаемся взять первый период активного года
                first_period = StudyPeriod.objects.filter(academic_year=active_year).order_by('start_date').first()
                if first_period: study_period_id = first_period.id
                else: logger.warning(f"Активный учебный год {active_year.name} не имеет учебных периодов.")
        else: logger.warning("Активный учебный год не найден.")
    
    if study_period_required and not study_period_id:
        raise ValueError(_("Параметр 'study_period_id' обязателен и не был определен."))
            
    return {'academic_year_id': academic_year_id, 'study_period_id': study_period_id}

# --- Эндпоинты для Администратора ---

# View для получения общей сводной статистики по платформе.
# Доступно только администраторам.
# - get_user_counts_by_role: Количество пользователей по ролям.
# - get_recent_registrations: Количество недавних регистраций.
# - get_active_users_approx: Примерное количество активных пользователей.
# - get_online_users_via_channels: Количество онлайн-пользователей (через Redis/Channels).
# - get_messaging_activity_summary: Сводка по активности в мессенджере.
# - get_notification_stats: Статистика по уведомлениям.
# Параметр `days_ago` (по умолчанию 7) определяет период для статистики.
# (Закомментировано) `@method_decorator(cache_page(60 * 15), name='dispatch')` - пример кэширования ответа.
class AdminPlatformSummaryStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get(self, request, *args, **kwargs):
        logger.info(f"Admin {request.user.email} requesting platform summary stats.")
        service = PlatformStatsService()
        days_ago_param = request.query_params.get('days_ago', '7')
        try:
            days_ago = int(days_ago_param)
            if days_ago <= 0: raise ValueError()
        except ValueError: return Response({"error": _("Параметр 'days_ago' должен быть положительным числом.")}, status=status.HTTP_400_BAD_REQUEST)
        data = {
            'user_counts_by_role': service.get_user_counts_by_role(),
            f'recent_registrations_{days_ago}_days': service.get_recent_registrations(days_ago=days_ago),
            'active_users_approx_15_min': service.get_active_users_approx(minutes_ago=15),
            'online_users_via_channels': service.get_online_users_via_channels(),
            'messaging_activity_summary': service.get_messaging_activity_summary(days_ago=days_ago),
            'notification_stats': service.get_notification_stats(days_ago=days_ago),
        }
        return Response(data)

# View для получения сводной статистики по нагрузке всех преподавателей.
# Доступно только администраторам.
# Использует `get_effective_period_filters` для определения учебного года/периода.
class AdminAllTeachersLoadView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get(self, request, *args, **kwargs):
        try: filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        logger.info(f"Admin {request.user.email} requesting all teachers load. Filters: {filters}")
        service = TeacherLoadStatsService()
        data = service.get_all_teachers_summary_load(academic_year_id=filters.get('academic_year_id'), study_period_id=filters.get('study_period_id'))
        return Response(data)

# View для получения детализированной статистики по нагрузке конкретного преподавателя.
# Доступно только администраторам. `teacher_id` передается в URL.
class AdminTeacherLoadDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get(self, request, teacher_id, *args, **kwargs):
        try: filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        logger.info(f"Admin {request.user.email} requesting load details for teacher ID {teacher_id}. Filters: {filters}")
        service = TeacherLoadStatsService()
        data = service.get_teacher_load_details(teacher_id=teacher_id, academic_year_id=filters.get('academic_year_id'), study_period_id=filters.get('study_period_id'))
        if "error" in data:
            status_code = status.HTTP_404_NOT_FOUND if "не найден" in str(data["error"]).lower() else status.HTTP_400_BAD_REQUEST
            return Response(data, status=status_code)
        return Response(data)

# View для получения статистики успеваемости по конкретной группе.
# Доступно администраторам и преподавателям (кураторам этой группы).
# `group_id` передается в URL. `study_period_id` обязателен в query-параметрах.
class AdminGroupPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin] # Доступ для админов и учителей
    def get(self, request, group_id, *args, **kwargs):
        try: filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # Дополнительная проверка прав для учителя (должен быть куратором, если не админ)
        if request.user.is_teacher and not request.user.is_admin:
            if not StudentGroup.objects.filter(pk=group_id, curator=request.user).exists():
                return Response({"error": _("Вы не являетесь куратором этой группы.")}, status=status.HTTP_403_FORBIDDEN)
        logger.info(f"User {request.user.email} requesting performance for group ID {group_id}. Period ID: {filters.get('study_period_id')}")
        service = StudentPerformanceStatsService()
        summary = service.get_group_performance_summary(student_group_id=group_id, study_period_id=filters.get('study_period_id'))
        if "error" in summary: return Response(summary, status=status.HTTP_404_NOT_FOUND)
        return Response(summary)

# View для получения списка студентов по успеваемости (выше/ниже порога).
# Доступно только администраторам.
# Параметры: `study_period_id` (обязателен), `threshold` (порог, по умолчанию 3.0),
# `above` (true/false, по умолчанию false - ниже порога), `limit` (количество, по умолчанию 20).
class AdminStudentsByPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get(self, request, *args, **kwargs):
        try: filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        study_period_id = filters.get('study_period_id')
        threshold_str = request.query_params.get('threshold', '3.0'); above_str = request.query_params.get('above', 'false').lower(); limit_str = request.query_params.get('limit', '20')
        try:
            threshold = float(threshold_str); above = above_str == 'true'; limit = int(limit_str) if limit_str.isdigit() else None
            if limit is not None and limit <= 0: limit = None
        except ValueError: return Response({"error": _("Параметры 'threshold', 'limit' имеют неверный формат.")}, status=status.HTTP_400_BAD_REQUEST)
        logger.info(f"Admin {request.user.email} requesting students by performance. Period: {study_period_id}, Thr: {threshold}, Above: {above}, Limit: {limit}")
        service = StudentPerformanceStatsService()
        students_data = service.get_students_by_performance_threshold(study_period_id=study_period_id, threshold=threshold, above_threshold=above, limit=limit)
        return Response(students_data)

# View для получения общей статистики по посещаемости.
# Доступно только администраторам.
# Включает общий процент посещаемости и топ студентов по пропускам.
class AdminOverallAttendanceStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get(self, request, *args, **kwargs):
        try: filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        limit_top_absent_str = request.query_params.get('limit_top_absent', '10')
        try: limit_top_absent = int(limit_top_absent_str);
        except ValueError: limit_top_absent = 10
        if limit_top_absent <=0: limit_top_absent = 10 # Коррекция лимита
        logger.info(f"Admin {request.user.email} requesting overall attendance stats. Filters: {filters}")
        service = AttendanceStatsService()
        percentage = service.get_overall_attendance_percentage(academic_year_id=filters.get('academic_year_id'), study_period_id=filters.get('study_period_id'))
        top_absent = service.get_top_absent_students(limit=limit_top_absent, academic_year_id=filters.get('academic_year_id'), study_period_id=filters.get('study_period_id'))
        return Response({'overall_attendance_percentage': percentage, 'top_absent_students_invalid_reason': top_absent})

# View для получения общей статистики по сдаче домашних заданий.
# Доступно только администраторам.
class AdminHomeworkOverallStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get(self, request, *args, **kwargs):
        try: filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        logger.info(f"Admin {request.user.email} requesting overall homework stats. Filters: {filters}")
        service = HomeworkStatsService()
        data = service.get_overall_submission_stats(academic_year_id=filters.get('academic_year_id'), study_period_id=filters.get('study_period_id'))
        return Response(data)

# --- Эндпоинты для Преподавателя ---

# View для получения сводной статистики для преподавателя (нагрузка, ДЗ, успеваемость курируемых групп).
# Доступно только преподавателям. `study_period_id` обязателен.
class TeacherMyOverallStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    def get(self, request, *args, **kwargs):
        try: filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        study_period_id = filters.get('study_period_id')
        logger.info(f"Teacher {request.user.email} requesting their overall stats. Filters: {filters}")
        load_service = TeacherLoadStatsService(); homework_service = HomeworkStatsService(); performance_service = StudentPerformanceStatsService()
        my_load_data_details = load_service.get_teacher_load_details(teacher_id=request.user.id, academic_year_id=filters.get('academic_year_id'), study_period_id=study_period_id)
        my_homework_data = homework_service.get_homework_submission_summary_for_teacher(teacher_id=request.user.id, study_period_id=study_period_id)
        curated_groups_performance = []
        if StudentGroup: # Проверка, что модель StudentGroup импортирована
            active_year_id_for_curated = filters.get('academic_year_id')
            if active_year_id_for_curated:
                my_curated_groups_qs = StudentGroup.objects.filter(curator=request.user, academic_year_id=active_year_id_for_curated)
                for group in my_curated_groups_qs:
                    group_perf = performance_service.get_group_performance_summary(student_group_id=group.id, study_period_id=study_period_id)
                    if "error" not in group_perf: curated_groups_performance.append(group_perf)
            else: logger.warning(f"Teacher {request.user.email}: Cannot fetch curated group performance without an academic year.")
        data = {
            'my_load_summary': {
                'total_planned_hours': my_load_data_details.get('total_planned_hours'),
                'total_scheduled_lessons': my_load_data_details.get('total_scheduled_lessons'),
                'total_scheduled_hours': my_load_data_details.get('total_scheduled_hours'),
                'load_percentage': my_load_data_details.get('load_percentage'),
                'planned_details_by_subject_group': my_load_data_details.get('planned_details_by_subject_group', []) 
            },
            'my_homework_summary': my_homework_data,
            'curated_groups_performance_summary': curated_groups_performance
        }
        return Response(data)

# View для получения детализированной успеваемости студентов в группе (для преподавателя).
# `group_id` передается в URL. `study_period_id` обязателен.
# Преподаватель должен быть куратором группы или вести занятия в ней в указанном периоде.
class TeacherGroupStudentDetailsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    def get(self, request, group_id, *args, **kwargs):
        try: filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        study_period_id = filters.get('study_period_id')
        is_curator = StudentGroup.objects.filter(pk=group_id, curator=request.user).exists()
        teaches_in_group_period = Lesson.objects.filter(teacher=request.user, student_group_id=group_id, study_period_id=study_period_id).exists()
        if not (is_curator or teaches_in_group_period): return Response({"error": _("Нет доступа к статистике этой группы.")}, status=status.HTTP_403_FORBIDDEN)
        logger.info(f"Teacher {request.user.email} requesting student details for group ID {group_id}, Period ID: {study_period_id}")
        service = StudentPerformanceStatsService()
        data = service.get_group_performance_summary(student_group_id=group_id, study_period_id=study_period_id)
        if "error" in data: return Response(data, status=status.HTTP_404_NOT_FOUND)
        return Response(data.get('students_details', []))

# --- Эндпоинты для Студента ---

# View для получения сводной статистики успеваемости и посещаемости для студента.
# Доступно только аутентифицированному студенту для своих данных. `study_period_id` обязателен.
class StudentMyPerformanceStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStudent]
    def get(self, request, *args, **kwargs):
        try: filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        study_period_id = filters.get('study_period_id')
        logger.info(f"Student {request.user.email} requesting their performance stats. Period ID: {study_period_id}")
        performance_service = StudentPerformanceStatsService(); attendance_service = AttendanceStatsService(); homework_service = HomeworkStatsService()
        data = {
            'average_grades_by_subject': performance_service.get_student_performance_by_subject(request.user.id, study_period_id),
            'attendance_summary': attendance_service.get_student_attendance_summary(request.user.id, study_period_id),
            'homework_summary': homework_service.get_student_homework_summary(request.user.id, study_period_id),
        }
        return Response(data)

# --- Эндпоинты для Родителя ---

# View для получения сводной статистики успеваемости и посещаемости для ребенка родителя.
# Доступно только аутентифицированному родителю. `child_id` передается в URL. `study_period_id` обязателен.
class ParentChildPerformanceStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsParent]
    def get(self, request, child_id, *args, **kwargs):
        try: filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e: return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        study_period_id = filters.get('study_period_id')
        try: child = request.user.children.get(pk=child_id, role=User.Role.STUDENT)
        except User.DoesNotExist: return Response({"error": _("Ребенок не найден или не привязан к вашему аккаунту.")}, status=status.HTTP_404_NOT_FOUND)
        logger.info(f"Parent {request.user.email} requesting stats for child ID {child_id}. Period ID: {study_period_id}")
        performance_service = StudentPerformanceStatsService(); attendance_service = AttendanceStatsService(); homework_service = HomeworkStatsService()
        data = {
            'child_id': child.id, 'child_name': child.get_full_name(),
            'average_grades_by_subject': performance_service.get_student_performance_by_subject(child.id, study_period_id),
            'attendance_summary': attendance_service.get_student_attendance_summary(child.id, study_period_id),
            'homework_summary': homework_service.get_student_homework_summary(child.id, study_period_id),
        }
        return Response(data)