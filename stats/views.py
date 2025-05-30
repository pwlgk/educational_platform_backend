# stats/views.py
import logging
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator # Если будете использовать кэширование
from django.views.decorators.cache import cache_page # Если будете использовать кэширование
from django.utils.translation import gettext_lazy as _
from django.conf import settings # Если нужны какие-то глобальные настройки

from edu_core.models import Lesson, StudentGroup, StudyPeriod # Нужен для получения периодов активного года
from .services import (
    PlatformStatsService, 
    TeacherLoadStatsService, 
    StudentPerformanceStatsService,
    AttendanceStatsService, 
    HomeworkStatsService,
    get_active_academic_year_service # Вспомогательная функция
)
from users.permissions import IsAdmin, IsTeacher, IsStudent, IsParent, IsTeacherOrAdmin
from users.models import User # Импортируем User для проверки child_id

logger = logging.getLogger(__name__)

# --- Вспомогательная функция для получения фильтров периода ---
def get_effective_period_filters(request, study_period_required=False, default_to_active_year=True):
    """
    Извлекает ID учебного года и периода из query-параметров.
    Если default_to_active_year=True и параметры не указаны,
    пытается использовать текущий активный учебный год.
    Если study_period_required=True и период не может быть определен, выбрасывает ValueError.
    """
    academic_year_id_str = request.query_params.get('academic_year_id')
    study_period_id_str = request.query_params.get('study_period_id')
    
    academic_year_id = None
    study_period_id = None

    parse_error_message = ""

    if study_period_id_str:
        try:
            study_period_id = int(study_period_id_str)
        except ValueError:
            parse_error_message += _(" Некорректный ID учебного периода.")
    
    if academic_year_id_str:
        try:
            academic_year_id = int(academic_year_id_str)
        except ValueError:
            parse_error_message += _(" НекорреКТНЫЙ ID учебного года.")

    if parse_error_message:
        raise ValueError(parse_error_message.strip())

    # Логика определения по умолчанию, если нужно
    if default_to_active_year and not academic_year_id and not study_period_id:
        active_year = get_active_academic_year_service()
        if active_year:
            academic_year_id = active_year.id
            logger.info(f"No period/year specified in request, using active academic year ID: {academic_year_id}")
            # Если учебный период обязателен и не был указан, пытаемся взять первый период активного года
            if study_period_required and not study_period_id:
                first_period = StudyPeriod.objects.filter(academic_year=active_year).order_by('start_date').first()
                if first_period:
                    study_period_id = first_period.id
                    logger.info(f"Study period required and not specified, using first period of active year: {study_period_id}")
                else:
                    logger.warning(f"Active academic year {active_year.name} (ID: {active_year.id}) has no study periods.")
                    # Ошибка будет выброшена ниже, если study_period_required=True
        else:
            logger.warning("No period/year specified and no active academic year found.")
            # Если активный год не найден, а период или год обязательны, то будет ошибка ниже

    # Проверка, если учебный период обязателен, но не был определен
    if study_period_required and not study_period_id:
        raise ValueError(_("Параметр 'study_period_id' обязателен для этого отчета и не был указан или определен по умолчанию."))
            
    return {
        'academic_year_id': academic_year_id,
        'study_period_id': study_period_id,
    }

# --- Эндпоинты для Администратора ---

class AdminPlatformSummaryStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    # @method_decorator(cache_page(60 * 15), name='dispatch')
    def get(self, request, *args, **kwargs):
        logger.info(f"Admin {request.user.email} requesting platform summary stats.")
        service = PlatformStatsService()
        days_ago_param = request.query_params.get('days_ago', '7')
        try:
            days_ago = int(days_ago_param)
            if days_ago <= 0: raise ValueError()
        except ValueError:
            return Response({"error": _("Параметр 'days_ago' должен быть положительным числом.")}, status=status.HTTP_400_BAD_REQUEST)

        data = {
            'user_counts_by_role': service.get_user_counts_by_role(),
            f'recent_registrations_{days_ago}_days': service.get_recent_registrations(days_ago=days_ago),
            'active_users_approx_15_min': service.get_active_users_approx(minutes_ago=15),
            'online_users_via_channels': service.get_online_users_via_channels(),
            'messaging_activity_summary': service.get_messaging_activity_summary(days_ago=days_ago),
            'notification_stats': service.get_notification_stats(days_ago=days_ago),
        }
        return Response(data)

class AdminAllTeachersLoadView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    # @method_decorator(cache_page(60 * 30), name='dispatch')
    def get(self, request, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
        logger.info(f"Admin {request.user.email} requesting all teachers load. Effective Filters: {filters}")
        service = TeacherLoadStatsService()
        data = service.get_all_teachers_summary_load(
            academic_year_id=filters.get('academic_year_id'),
            study_period_id=filters.get('study_period_id')
        )
        return Response(data)

class AdminTeacherLoadDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request, teacher_id, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"Admin {request.user.email} requesting load details for teacher ID {teacher_id}. Filters: {filters}")
        service = TeacherLoadStatsService()
        data = service.get_teacher_load_details(
            teacher_id=teacher_id,
            academic_year_id=filters.get('academic_year_id'),
            study_period_id=filters.get('study_period_id')
        )
        if "error" in data:
            status_code = status.HTTP_404_NOT_FOUND if "не найден" in str(data["error"]).lower() else status.HTTP_400_BAD_REQUEST
            return Response(data, status=status_code)
        return Response(data)

class AdminGroupPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]

    def get(self, request, group_id, *args, **kwargs):
        try:
            # study_period_id обязателен для этого отчета
            filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
        logger.info(f"Admin {request.user.email} requesting performance for group ID {group_id}. Period ID: {filters.get('study_period_id')}")
        service = StudentPerformanceStatsService()
        summary = service.get_group_performance_summary(
            student_group_id=group_id,
            study_period_id=filters.get('study_period_id')
        )
        if "error" in summary:
             return Response(summary, status=status.HTTP_404_NOT_FOUND)
        return Response(summary)

class AdminStudentsByPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        study_period_id = filters.get('study_period_id')
        # study_period_id уже проверен на None в get_effective_period_filters

        threshold_str = request.query_params.get('threshold', '3.0')
        above_str = request.query_params.get('above', 'false').lower()
        limit_str = request.query_params.get('limit', '20')

        try:
            threshold = float(threshold_str)
            above = above_str == 'true'
            limit = int(limit_str) if limit_str.isdigit() else None # Проверка, что это число
            if limit is not None and limit <= 0: limit = None # Лимит должен быть > 0
        except ValueError:
            return Response({"error": _("Параметры 'threshold', 'limit' имеют неверный формат.")}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"Admin {request.user.email} requesting students by performance. Period: {study_period_id}, Thr: {threshold}, Above: {above}, Limit: {limit}")
        service = StudentPerformanceStatsService()
        students_data = service.get_students_by_performance_threshold(
            study_period_id=study_period_id,
            threshold=threshold,
            above_threshold=above,
            limit=limit
        )
        return Response(students_data)

class AdminOverallAttendanceStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        limit_top_absent_str = request.query_params.get('limit_top_absent', '10')
        try:
            limit_top_absent = int(limit_top_absent_str)
            if limit_top_absent <=0: limit_top_absent = 10
        except ValueError:
            limit_top_absent = 10


        logger.info(f"Admin {request.user.email} requesting overall attendance stats. Filters: {filters}")
        service = AttendanceStatsService()
        percentage = service.get_overall_attendance_percentage(
            academic_year_id=filters.get('academic_year_id'),
            study_period_id=filters.get('study_period_id')
        )
        top_absent = service.get_top_absent_students(
            limit=limit_top_absent,
            academic_year_id=filters.get('academic_year_id'),
            study_period_id=filters.get('study_period_id')
        )
        return Response({
            'overall_attendance_percentage': percentage,
            'top_absent_students_invalid_reason': top_absent
        })

class AdminHomeworkOverallStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"Admin {request.user.email} requesting overall homework stats. Filters: {filters}")
        service = HomeworkStatsService()
        data = service.get_overall_submission_stats(
            academic_year_id=filters.get('academic_year_id'),
            study_period_id=filters.get('study_period_id')
        )
        return Response(data)

# --- Эндпоинты для Преподавателя ---

class TeacherMyOverallStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        study_period_id = filters.get('study_period_id')
        # study_period_id уже проверен на None в get_effective_period_filters

        logger.info(f"Teacher {request.user.email} requesting their overall stats. Effective Filters: {filters}")
        
        load_service = TeacherLoadStatsService()
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Запрашиваем полную детализацию ---
        my_load_data_details = load_service.get_teacher_load_details(
            teacher_id=request.user.id,
            academic_year_id=filters.get('academic_year_id'),
            study_period_id=study_period_id
        )
        
        homework_service = HomeworkStatsService()
        my_homework_data = homework_service.get_homework_submission_summary_for_teacher(
            teacher_id=request.user.id,
            study_period_id=study_period_id
        )
        
        performance_service = StudentPerformanceStatsService()
        curated_groups_performance = []
        if StudentGroup:
            active_year_id_for_curated = filters.get('academic_year_id')
            if not active_year_id_for_curated:
                 logger.warning(f"Teacher {request.user.email}: Cannot fetch curated group performance without an academic year for my-summary.")
            else:
                my_curated_groups_qs = StudentGroup.objects.filter(curator=request.user, academic_year_id=active_year_id_for_curated)
                for group in my_curated_groups_qs:
                    group_perf = performance_service.get_group_performance_summary(
                        student_group_id=group.id, 
                        study_period_id=study_period_id # Используем тот же study_period_id для консистентности
                    )
                    if "error" not in group_perf:
                        curated_groups_performance.append(group_perf)
        
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Формируем my_load_summary с детализацией ---
        data = {
            'my_load_summary': {
                'total_planned_hours': my_load_data_details.get('total_planned_hours'),
                'total_scheduled_lessons': my_load_data_details.get('total_scheduled_lessons'),
                'total_scheduled_hours': my_load_data_details.get('total_scheduled_hours'),
                'load_percentage': my_load_data_details.get('load_percentage'),
                # Добавляем детализацию запланированных часов
                'planned_details_by_subject_group': my_load_data_details.get('planned_details_by_subject_group', []) 
            },
            'my_homework_summary': my_homework_data,
            'curated_groups_performance_summary': curated_groups_performance
        }
        return Response(data)

class TeacherGroupStudentDetailsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request, group_id, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
        study_period_id = filters.get('study_period_id')
        # study_period_id уже проверен

        # Проверка, является ли учитель куратором этой группы ИЛИ ведет ли он занятия в этой группе в этом периоде
        is_curator = StudentGroup.objects.filter(pk=group_id, curator=request.user).exists()
        teaches_in_group_period = Lesson.objects.filter(
            teacher=request.user, 
            student_group_id=group_id,
            study_period_id=study_period_id # Проверяем по актуальному периоду
        ).exists()

        if not (is_curator or teaches_in_group_period):
            logger.warning(f"Teacher {request.user.email} permission denied for group {group_id} student details (not curator or teacher for this group/period).")
            return Response({"error": _("У вас нет доступа к детальной статистике этой группы в указанном периоде.")}, status=status.HTTP_403_FORBIDDEN)

        logger.info(f"Teacher {request.user.email} requesting student details for group ID {group_id}, Period ID: {study_period_id}")
        service = StudentPerformanceStatsService()
        # get_group_performance_summary возвращает и общую инфу, и детализацию по студентам
        data = service.get_group_performance_summary(
            student_group_id=group_id, 
            study_period_id=study_period_id
        )
        
        if "error" in data:
            return Response(data, status=status.HTTP_404_NOT_FOUND)
        
        # Возвращаем только список студентов с их детализацией
        return Response(data.get('students_details', []))

# --- Эндпоинты для Студента ---

class StudentMyPerformanceStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get(self, request, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
        study_period_id = filters.get('study_period_id')
        # study_period_id уже проверен
        
        logger.info(f"Student {request.user.email} requesting their performance stats. Period ID: {study_period_id}")
        
        performance_service = StudentPerformanceStatsService()
        attendance_service = AttendanceStatsService()
        homework_service = HomeworkStatsService()
        
        data = {
            'average_grades_by_subject': performance_service.get_student_performance_by_subject(request.user.id, study_period_id),
            'attendance_summary': attendance_service.get_student_attendance_summary(request.user.id, study_period_id),
            'homework_summary': homework_service.get_student_homework_summary(request.user.id, study_period_id),
        }
        return Response(data)

# --- Эндпоинты для Родителя ---

class ParentChildPerformanceStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsParent]

    def get(self, request, child_id, *args, **kwargs):
        try:
            filters = get_effective_period_filters(request, study_period_required=True, default_to_active_year=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
        study_period_id = filters.get('study_period_id')
        # study_period_id уже проверен

        try:
            child = request.user.children.get(pk=child_id, role=User.Role.STUDENT)
        except User.DoesNotExist:
            logger.warning(f"Parent {request.user.email} requested stats for non-child or non-student ID {child_id}")
            return Response({"error": _("Указанный ребенок не найден или не привязан к вашему аккаунту.")}, status=status.HTTP_404_NOT_FOUND)
        
        logger.info(f"Parent {request.user.email} requesting stats for child ID {child_id}. Period ID: {study_period_id}")
        
        performance_service = StudentPerformanceStatsService()
        attendance_service = AttendanceStatsService()
        homework_service = HomeworkStatsService()
        
        data = {
            'child_id': child.id,
            'child_name': child.get_full_name(),
            'average_grades_by_subject': performance_service.get_student_performance_by_subject(child.id, study_period_id),
            'attendance_summary': attendance_service.get_student_attendance_summary(child.id, study_period_id),
            'homework_summary': homework_service.get_student_homework_summary(child.id, study_period_id),
        }
        return Response(data)