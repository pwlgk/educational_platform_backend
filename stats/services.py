from decimal import ROUND_HALF_UP, Decimal # Импорт для точного округления Decimal
import logging
from django.db.models import Avg, Count, Sum, F, ExpressionWrapper, fields, Q, Case, When, Value
from django.utils import timezone
from datetime import timedelta, date # date импортирован для использования в HomeworkStatsService
from django.conf import settings 

from users.models import User
from edu_core.models import (
    Lesson, StudentGroup, Subject, Grade, Attendance, Homework, HomeworkSubmission, 
    AcademicYear, StudyPeriod, CurriculumEntry
)
from messaging.models import Chat, Message # Модели из модуля messaging
from notifications.models import Notification # Модель из модуля notifications
from django.db.models import Prefetch # Prefetch для оптимизации запросов
from django.utils.translation import gettext_lazy as _ # Для интернационализации строк

logger = logging.getLogger(__name__)

# Сервисная функция для получения текущего активного учебного года.
# Возвращает первый найденный объект AcademicYear с флагом is_current=True.
def get_active_academic_year_service():
    return AcademicYear.objects.filter(is_current=True).first()

# Класс PlatformStatsService предоставляет методы для сбора общей статистики по платформе.
class PlatformStatsService:
    # Возвращает количество пользователей, сгруппированных по ролям.
    def get_user_counts_by_role(self):
        return list(User.objects.values('role').annotate(count=Count('id')).order_by('role'))

    # Возвращает количество пользователей, зарегистрированных за последние `days_ago` дней.
    def get_recent_registrations(self, days_ago=7):
        start_date = timezone.now() - timedelta(days=days_ago)
        return User.objects.filter(date_joined__gte=start_date).count()

    # Возвращает примерное количество активных пользователей (тех, кто логинился
    # за последние `minutes_ago` минут). Требует наличия поля `last_login` в модели User.
    def get_active_users_approx(self, minutes_ago=15):
        if not hasattr(User, 'last_login'):
            logger.warning("Поле 'last_login' отсутствует в модели User для статистики активности.")
            return {"error": "Механизм отслеживания последней активности через last_login не доступен."}
        threshold = timezone.now() - timedelta(minutes=minutes_ago)
        return User.objects.filter(is_active=True, last_login__gte=threshold).count()

    # Возвращает количество онлайн-пользователей, отслеживаемых через Redis (предполагается
    # интеграция с Django Channels и Redis для отслеживания онлайн-статуса).
    # Требует установленной библиотеки 'redis'.
    def get_online_users_via_channels(self):
        try:
            import redis # Попытка импорта redis
            r = redis.Redis(
                host=getattr(settings, 'REDIS_HOST', '127.0.0.1'),
                port=getattr(settings, 'REDIS_PORT', 6379),
                password=getattr(settings, 'REDIS_PASSWORD', None),
                db=getattr(settings, 'REDIS_DB', 0)
            )
            online_count = r.scard('online_users_platform') # 'online_users_platform' - ключ в Redis
            return online_count
        except ImportError:
            logger.warning("Библиотека 'redis' не установлена. Статистика онлайн пользователей через Channels недоступна.")
            return {"error": "Библиотека redis не установлена."}
        except Exception as e:
            logger.error(f"Ошибка получения онлайн пользователей из Redis: {e}")
            return {"error": "Не удалось получить данные об онлайн пользователях."}

    # Возвращает сводку по активности в мессенджере за последние `days_ago` дней:
    # количество созданных чатов, отправленных сообщений и активных чатов.
    def get_messaging_activity_summary(self, days_ago=7):
        start_date = timezone.now() - timedelta(days=days_ago)
        total_chats_created = Chat.objects.filter(created_at__gte=start_date).count()
        total_messages_sent = Message.objects.filter(timestamp__gte=start_date).count()
        active_chats_count = Chat.objects.filter(messages__timestamp__gte=start_date).distinct().count()
        return {
            "period_days": days_ago,
            "new_chats_created": total_chats_created,
            "messages_sent": total_messages_sent,
            "active_chats_count": active_chats_count,
        }

    # Возвращает статистику по уведомлениям за последние `days_ago` дней:
    # общее количество отправленных, прочитанных, процент прочитанных и распределение по типам.
    def get_notification_stats(self, days_ago=7):
        start_date = timezone.now() - timedelta(days=days_ago)
        notifications_sent = Notification.objects.filter(created_at__gte=start_date)
        total_sent = notifications_sent.count()
        total_read = notifications_sent.filter(is_read=True).count()
        by_type = list(notifications_sent.values('notification_type').annotate(count=Count('id')).order_by('-count'))
        return {
            "period_days": days_ago,
            "total_notifications_sent": total_sent,
            "total_notifications_read": total_read,
            "read_percentage": round((total_read / total_sent) * 100, 1) if total_sent > 0 else 0,
            "sent_by_type": by_type,
        }

# Класс TeacherLoadStatsService предоставляет методы для расчета и получения статистики
# по учебной нагрузке преподавателей.
class TeacherLoadStatsService:
    # Возвращает детализированную информацию о нагрузке конкретного преподавателя.
    # Фильтруется по ID учебного года и/или ID учебного периода.
    # Рассчитывает общие запланированные часы, детализацию по предметам/группам,
    # количество и общую продолжительность проведенных занятий, а также процент выполнения нагрузки.
    def get_teacher_load_details(self, teacher_id, academic_year_id=None, study_period_id=None):
        try: teacher = User.objects.get(pk=teacher_id, role=User.Role.TEACHER)
        except User.DoesNotExist: return {"error": _("Преподаватель не найден.")}
        
        planned_hours_filter = Q(teacher=teacher)
        scheduled_lessons_filter = Q(teacher=teacher)
        
        if study_period_id:
            target_study_period = StudyPeriod.objects.filter(pk=study_period_id).first()
            if not target_study_period: return {"error": _("Учебный период не найден.")}
            planned_hours_filter &= Q(study_period=target_study_period)
            scheduled_lessons_filter &= Q(study_period=target_study_period)
        elif academic_year_id:
            target_academic_year = AcademicYear.objects.filter(pk=academic_year_id).first()
            if not target_academic_year: return {"error": _("Учебный год не найден.")}
            planned_hours_filter &= Q(study_period__academic_year=target_academic_year)
            scheduled_lessons_filter &= Q(study_period__academic_year=target_academic_year)
        
        planned_entries = CurriculumEntry.objects.filter(planned_hours_filter).select_related('subject', 'study_period', 'curriculum__student_group')
        total_planned_hours = planned_entries.aggregate(total=Sum('planned_hours'))['total'] or 0.0
        planned_details = [{'subject_name': entry.subject.name, 'group_name': entry.curriculum.student_group.name, 'period_name': entry.study_period.name, 'hours': entry.planned_hours} for entry in planned_entries]
        
        duration_expression = ExpressionWrapper(F('end_time') - F('start_time'), output_field=fields.DurationField())
        scheduled_lessons_qs = Lesson.objects.filter(scheduled_lessons_filter).annotate(duration=duration_expression)
        scheduled_agg = scheduled_lessons_qs.aggregate(total_duration_agg=Sum('duration'), lesson_count_agg=Count('id'))
        total_scheduled_seconds = scheduled_agg.get('total_duration_agg').total_seconds() if scheduled_agg.get('total_duration_agg') else 0
        total_scheduled_hours = round(total_scheduled_seconds / 3600, 2)
        lesson_count = scheduled_agg.get('lesson_count_agg') or 0

        return {
            'teacher_id': teacher.id, 'teacher_name': teacher.get_full_name(),
            'filter_academic_year_id': academic_year_id, 'filter_study_period_id': study_period_id,
            'total_planned_hours': total_planned_hours, 'planned_details_by_subject_group': planned_details,
            'total_scheduled_lessons': lesson_count, 'total_scheduled_hours': total_scheduled_hours,
            'load_percentage': round((total_scheduled_hours / total_planned_hours) * 100, 1) if total_planned_hours > 0 else 0,
        }

    # Возвращает сводную информацию о нагрузке для всех преподавателей.
    # Фильтруется по ID учебного года и/или ID учебного периода.
    # Для каждого преподавателя агрегирует общие запланированные часы, количество проведенных занятий,
    # общую продолжительность проведенных занятий и процент выполнения нагрузки.
    def get_all_teachers_summary_load(self, academic_year_id=None, study_period_id=None):
        teachers = User.objects.filter(role=User.Role.TEACHER).order_by('last_name', 'first_name')
        results = []
        for teacher in teachers:
            details = self.get_teacher_load_details(teacher.id, academic_year_id, study_period_id)
            if "error" not in details:
                results.append({
                    'teacher_id': details['teacher_id'], 'teacher_name': details['teacher_name'],
                    'total_planned_hours': details['total_planned_hours'],
                    'total_scheduled_lessons': details['total_scheduled_lessons'],
                    'total_scheduled_hours': details['total_scheduled_hours'],
                    'load_percentage': details['load_percentage'],
                })
        return results

# Класс StudentPerformanceStatsService предоставляет методы для расчета и получения
# статистики по успеваемости студентов.
class StudentPerformanceStatsService:
    # Вспомогательный метод для расчета средневзвешенной оценки на основе QuerySet'а оценок.
    # Учитывает числовое значение оценки (`numeric_value`) и ее вес (`weight`).
    # Возвращает кортеж (средневзвешенная оценка Decimal, количество учтенных оценок).
    def _calculate_weighted_average(self, grades_queryset):
        if not grades_queryset.exists(): return None, 0
        aggregation = grades_queryset.filter(weight__gt=0).aggregate(
            weighted_sum=Sum(F('numeric_value') * F('weight')), total_weight=Sum('weight')
        )
        count_with_numeric = grades_queryset.filter(numeric_value__isnull=False).count()
        if aggregation['total_weight'] and aggregation['total_weight'] > 0:
            avg_decimal = (Decimal(str(aggregation['weighted_sum'])) / Decimal(str(aggregation['total_weight']))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return avg_decimal, count_with_numeric
        return None, count_with_numeric

    # Возвращает успеваемость конкретного студента по всем предметам в указанном учебном периоде.
    # Для каждого предмета рассчитывается средневзвешенная оценка и количество оценок.
    def get_student_performance_by_subject(self, student_id, study_period_id):
        try: student = User.objects.get(pk=student_id, role=User.Role.STUDENT)
        except User.DoesNotExist: return {"error": _("Студент не найден.")}
        subjects_with_activity = Subject.objects.filter(
            Q(grades_for_subject__student=student, grades_for_subject__study_period_id=study_period_id) |
            Q(lessons__student_group__students=student, lessons__study_period_id=study_period_id)
        ).distinct().order_by('name')
        results = []
        for subject in subjects_with_activity:
            grades_for_subject_period = Grade.objects.filter(student=student, subject=subject, study_period_id=study_period_id, numeric_value__isnull=False)
            avg_grade, num_grades = self._calculate_weighted_average(grades_for_subject_period)
            results.append({'subject_id': subject.id, 'subject_name': subject.name, 'average_grade': avg_grade, 'grades_count': num_grades})
        return results

    # Возвращает сводную информацию об успеваемости для указанной учебной группы в учебном периоде.
    # Включает общую среднюю оценку по группе, процент студентов, преодолевших порог успеваемости,
    # и детализацию успеваемости для каждого студента группы.
    def get_group_performance_summary(self, student_group_id, study_period_id, passing_threshold=3.0):
        try: group = StudentGroup.objects.get(pk=student_group_id)
        except StudentGroup.DoesNotExist: return {"error": _("Группа не найдена.")}
        students_in_group = group.students.filter(role=User.Role.STUDENT)
        if not students_in_group.exists(): return {'group_name': group.name, 'average_grade': None, 'passing_percentage': None, 'student_count': 0}
        
        passing_students_count = 0; total_average_grade_sum = Decimal('0.0'); students_with_grades_count = 0
        student_details_list = []; passing_threshold_decimal = Decimal(str(passing_threshold))

        for student in students_in_group:
            grades_for_student_period = Grade.objects.filter(student=student, study_period_id=study_period_id, numeric_value__isnull=False)
            student_avg_decimal, num_grades = self._calculate_weighted_average(grades_for_student_period) 
            student_details_list.append({'student_id': student.id, 'student_name': student.get_full_name(), 'average_grade': float(student_avg_decimal) if student_avg_decimal is not None else None, 'grades_count': num_grades})
            if student_avg_decimal is not None:
                total_average_grade_sum += student_avg_decimal; students_with_grades_count += 1
                if student_avg_decimal >= passing_threshold_decimal: passing_students_count += 1
        
        overall_group_avg_decimal = (total_average_grade_sum / Decimal(students_with_grades_count)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if students_with_grades_count > 0 else None
        passing_percentage = round((passing_students_count / students_in_group.count()) * 100, 1) if students_in_group.count() > 0 else 0.0

        return {
            'group_id': group.id, 'group_name': group.name, 'study_period_id': study_period_id,
            'overall_average_grade': float(overall_group_avg_decimal) if overall_group_avg_decimal is not None else None,
            'passing_students_percentage': passing_percentage, 'total_students_in_group': students_in_group.count(),
            'students_counted_for_average': students_with_grades_count, 'students_details': student_details_list
        }

    # Возвращает список студентов, чья средняя успеваемость в указанном учебном периоде
    # выше или ниже заданного порога (`threshold`).
    # `above_threshold=True` для студентов выше порога, `False` - ниже.
    # `limit` ограничивает количество возвращаемых студентов.
    def get_students_by_performance_threshold(self, study_period_id, threshold, above_threshold=False, limit=None):
        all_grades_in_period = Grade.objects.filter(study_period_id=study_period_id, numeric_value__isnull=False, weight__gt=0)\
            .values('student_id', 'student__first_name', 'student__last_name')\
            .annotate(student_avg_grade=Sum(F('numeric_value') * F('weight')) / Sum('weight'))\
            .filter(student_avg_grade__isnull=False)
        if above_threshold: filtered_students = all_grades_in_period.filter(student_avg_grade__gte=threshold).order_by('-student_avg_grade')
        else: filtered_students = all_grades_in_period.filter(student_avg_grade__lt=threshold).order_by('student_avg_grade')
        if limit: filtered_students = filtered_students[:limit]
        return list(filtered_students.values('student_id', 'student__first_name', 'student__last_name', 'student_avg_grade'))

# Класс AttendanceStatsService предоставляет методы для расчета и получения
# статистики по посещаемости.
class AttendanceStatsService:
    # Возвращает общий процент посещаемости по всем записям в указанном
    # учебном году или периоде.
    def get_overall_attendance_percentage(self, academic_year_id=None, study_period_id=None):
        base_qs = Attendance.objects.all()
        if study_period_id: base_qs = base_qs.filter(journal_entry__lesson__study_period_id=study_period_id)
        elif academic_year_id: base_qs = base_qs.filter(journal_entry__lesson__study_period__academic_year_id=academic_year_id)
        total_records = base_qs.count()
        if total_records == 0: return None
        present_count = base_qs.filter(status__in=[Attendance.Status.PRESENT, Attendance.Status.LATE, Attendance.Status.REMOTE]).count()
        return round((present_count / total_records) * 100, 1)

    # Возвращает топ `limit` студентов с наибольшим количеством пропусков по неуважительной причине
    # в указанном учебном году или периоде.
    def get_top_absent_students(self, limit=10, academic_year_id=None, study_period_id=None):
        base_qs = Attendance.objects.filter(status=Attendance.Status.ABSENT_INVALID)
        if study_period_id: base_qs = base_qs.filter(journal_entry__lesson__study_period_id=study_period_id)
        elif academic_year_id: base_qs = base_qs.filter(journal_entry__lesson__study_period__academic_year_id=academic_year_id)
        absences = base_qs.values('student', 'student__first_name', 'student__last_name')\
            .annotate(absent_count=Count('id')).order_by('-absent_count')[:limit]
        return list(absences)
    
    # Возвращает сводку по посещаемости для конкретного студента в указанном учебном периоде.
    # Включает количество посещенных занятий, процент посещаемости и распределение по статусам.
    def get_student_attendance_summary(self, student_id, study_period_id):
        try: student = User.objects.get(pk=student_id, role=User.Role.STUDENT)
        except User.DoesNotExist: return {"error": _("Студент не найден.")}
        records_qs = Attendance.objects.filter(student=student, journal_entry__lesson__study_period_id=study_period_id)
        summary_by_status = list(records_qs.values('status').annotate(count=Count('id')))
        total_recorded_lessons = records_qs.count()
        present_statuses = [Attendance.Status.PRESENT, Attendance.Status.LATE, Attendance.Status.REMOTE]
        present_count = records_qs.filter(status__in=present_statuses).count()
        return {
            'student_id': student.id, 'student_name': student.get_full_name(), 'study_period_id': study_period_id,
            'summary_by_status': summary_by_status, 'total_recorded_lessons': total_recorded_lessons,
            'present_lessons_count': present_count,
            'presence_percentage': round((present_count / total_recorded_lessons) * 100, 1) if total_recorded_lessons > 0 else None
        }

    # Возвращает сводку по посещаемости для указанной учебной группы в учебном периоде.
    # Включает общую статистику по статусам, средний процент посещаемости по группе.
    def get_group_attendance_summary(self, student_group_id, study_period_id):
        try: group = StudentGroup.objects.get(pk=student_group_id)
        except StudentGroup.DoesNotExist: return {"error": _("Группа не найдена.")}
        records_qs = Attendance.objects.filter(student__student_group_memberships=group, journal_entry__lesson__study_period_id=study_period_id)
        summary_by_status = list(records_qs.values('status').annotate(count=Count('id')))
        total_recorded_student_lessons = records_qs.count()
        present_statuses = [Attendance.Status.PRESENT, Attendance.Status.LATE, Attendance.Status.REMOTE]
        present_student_lessons_count = records_qs.filter(status__in=present_statuses).count()
        unique_lessons_with_attendance_count = records_qs.values('journal_entry__lesson_id').distinct().count()
        return {
            'group_id': group.id, 'group_name': group.name, 'study_period_id': study_period_id,
            'summary_by_status_for_group': summary_by_status,
            'total_student_lesson_records': total_recorded_student_lessons,
            'total_present_student_lessons': present_student_lessons_count,
            'average_presence_percentage_group': round((present_student_lessons_count / total_recorded_student_lessons) * 100, 1) if total_recorded_student_lessons > 0 else None,
            'unique_lessons_with_attendance_records': unique_lessons_with_attendance_count
        }

# Класс HomeworkStatsService предоставляет методы для расчета и получения
# статистики по домашним заданиям.
class HomeworkStatsService:
    # Возвращает общую статистику по сдаче домашних заданий в указанном
    # учебном году или периоде (количество выданных ДЗ, средний процент сдачи,
    # средний процент сдачи в срок).
    # Внимание: этот метод может быть ресурсоемким из-за необходимости итерации по ДЗ.
    def get_overall_submission_stats(self, academic_year_id=None, study_period_id=None):
        homework_qs = Homework.objects.all()
        if study_period_id: homework_qs = homework_qs.filter(journal_entry__lesson__study_period_id=study_period_id)
        elif academic_year_id: homework_qs = homework_qs.filter(journal_entry__lesson__study_period__academic_year_id=academic_year_id)
        total_homeworks = homework_qs.count()
        if total_homeworks == 0: return {"total_homeworks_issued": 0, "average_submission_rate_percent": None, "average_on_time_submission_rate_percent": None}
        
        total_possible_submissions, total_actual_submissions, total_on_time_submissions = 0, 0, 0
        for hw in homework_qs.select_related('journal_entry__lesson__student_group').prefetch_related('journal_entry__lesson__student_group__students', 'submissions'):
            num_students_in_group = hw.journal_entry.lesson.student_group.students.count()
            total_possible_submissions += num_students_in_group
            submissions_for_hw = hw.submissions.all()
            total_actual_submissions += submissions_for_hw.count()
            if hw.due_date: total_on_time_submissions += submissions_for_hw.filter(submitted_at__lte=hw.due_date).count()
            else: total_on_time_submissions += submissions_for_hw.count()
        
        avg_submission_rate = round((total_actual_submissions / total_possible_submissions) * 100, 1) if total_possible_submissions > 0 else None
        avg_on_time_rate = round((total_on_time_submissions / total_actual_submissions) * 100, 1) if total_actual_submissions > 0 else None
        
        return {
            "total_homeworks_issued": total_homeworks, "total_possible_submissions": total_possible_submissions,
            "total_actual_submissions": total_actual_submissions, "average_submission_rate_percent": avg_submission_rate,
            "average_on_time_submission_rate_percent": avg_on_time_rate,
        }

    # Возвращает сводку по сдаче домашних заданий для конкретного преподавателя
    # в указанном учебном периоде. Для каждого ДЗ преподавателя рассчитывается
    # количество ожидаемых сдач, полученных, сданных в срок, оцененных и средняя оценка.
    def get_homework_submission_summary_for_teacher(self, teacher_id, study_period_id):
        try: teacher = User.objects.get(pk=teacher_id, role=User.Role.TEACHER)
        except User.DoesNotExist: return {"error": _("Преподаватель не найден.")}
        homeworks_qs = Homework.objects.filter(Q(author=teacher) | Q(journal_entry__lesson__teacher=teacher), journal_entry__lesson__study_period_id=study_period_id)\
            .select_related('journal_entry__lesson__student_group', 'journal_entry__lesson__subject')\
            .prefetch_related('submissions__student', 'submissions__grade_for_submission').distinct()
        results = []
        for hw in homeworks_qs:
            students_in_group_count = hw.journal_entry.lesson.student_group.students.count()
            all_submissions_for_hw = hw.submissions.all(); submitted_count = all_submissions_for_hw.count()
            on_time_count = all_submissions_for_hw.filter(submitted_at__lte=hw.due_date).count() if hw.due_date else submitted_count
            grades = [s.grade_for_submission.numeric_value for s in all_submissions_for_hw if hasattr(s, 'grade_for_submission') and s.grade_for_submission and s.grade_for_submission.numeric_value is not None]
            avg_grade = round(sum(grades) / len(grades), 2) if grades else None
            graded_count = Grade.objects.filter(homework_submission__homework=hw).count()
            results.append({
                'homework_id': hw.id, 'homework_title': hw.title, 'subject_name': hw.journal_entry.lesson.subject.name,
                'group_name': hw.journal_entry.lesson.student_group.name, 'due_date': hw.due_date,
                'total_students_expected': students_in_group_count, 'submissions_received': submitted_count,
                'submissions_on_time': on_time_count, 'submissions_graded': graded_count,
                'submission_rate_percent': round((submitted_count / students_in_group_count) * 100, 1) if students_in_group_count > 0 else 0,
                'average_grade': avg_grade
            })
        return sorted(results, key=lambda x: (x['due_date'].date() if x['due_date'] else date.max, x['homework_title']), reverse=True)

    # Возвращает сводку по домашним заданиям для конкретного студента
    # в указанном учебном периоде. Для каждого ДЗ отображается статус сдачи и оценка (если есть).
    def get_student_homework_summary(self, student_id, study_period_id):
        try: student = User.objects.get(pk=student_id, role=User.Role.STUDENT)
        except User.DoesNotExist: return {"error": _("Студент не найден.")}
        student_groups_in_period = StudentGroup.objects.filter(students=student, lessons__study_period_id=study_period_id).distinct()
        if not student_groups_in_period.exists(): return {"info": _("Нет групп или ДЗ для этого студента в указанном периоде.")}
        homeworks_for_student = Homework.objects.filter(journal_entry__lesson__student_group__in=student_groups_in_period, journal_entry__lesson__study_period_id=study_period_id)\
            .select_related('journal_entry__lesson__subject', 'author')\
            .prefetch_related(Prefetch('submissions', queryset=HomeworkSubmission.objects.filter(student=student).select_related('grade_for_submission'), to_attr='my_submission_list'))\
            .distinct().order_by('-due_date', '-created_at')
        results = []
        for hw in homeworks_for_student:
            my_submission = hw.my_submission_list[0] if hw.my_submission_list else None
            status = ""; grade_value = None
            if my_submission:
                status = _("Сдано")
                if hasattr(my_submission, 'grade_for_submission') and my_submission.grade_for_submission:
                    grade = my_submission.grade_for_submission; grade_value = grade.grade_value; status += f" (Оценено: {grade_value})"
                else: status += _(" (Ожидает проверки)")
            elif hw.due_date and timezone.now().replace(tzinfo=None) > hw.due_date.replace(tzinfo=None): status = _("Не сдано (Срок истек)")
            else: status = _("Не сдано")
            results.append({
                'homework_id': hw.id, 'homework_title': hw.title, 'subject_name': hw.journal_entry.lesson.subject.name,
                'teacher_name': hw.author.get_full_name() if hw.author else "N/A", 'due_date': hw.due_date,
                'submission_status': status, 'my_grade': grade_value, 'submitted_at': my_submission.submitted_at if my_submission else None,
            })
        return results