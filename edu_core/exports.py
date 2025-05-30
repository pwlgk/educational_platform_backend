import datetime
import logging
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
from django.utils import timezone
from django.db.models import Prefetch, Q, OuterRef, Subquery
from django.http import HttpResponse
from users.models import User
from .models import (
    Lesson, LessonJournalEntry, StudentGroup, Subject, StudyPeriod, AcademicYear,
    Attendance, Grade, Homework, HomeworkSubmission
)

logger = logging.getLogger(__name__)

# Класс JournalExporter отвечает за формирование и экспорт данных электронного журнала
# в формат Excel (.xlsx). Он поддерживает экспорт для преподавателей и администраторов
# с учетом различных фильтров.
#
# Атрибуты:
# - user: Пользователь, запрашивающий экспорт. Используется для определения прав доступа и фильтрации.
# - filters: Словарь с параметрами фильтрации (например, ID учебного года, периода, группы, предмета, даты).
# - workbook: Экземпляр openpyxl.Workbook, представляющий Excel-книгу.
#
# Основные методы:
# - _apply_common_styles(ws): Применяет общие стили (шрифты, заливка, границы, выравнивание, автоподбор ширины)
#   к указанному листу (ws) Excel-книги. Закрепляет первую строку (заголовки).
# - _get_base_lesson_queryset(): Формирует базовый QuerySet для модели Lesson с необходимой
#   оптимизацией (select_related, prefetch_related) для эффективного извлечения связанных данных
#   (журнал, посещаемость, ДЗ, оценки).
# - _filter_queryset_by_params(queryset): Применяет фильтры, переданные в self.filters,
#   к предоставленному QuerySet'у.
# - export_teacher_journal(): Генерирует Excel-файл с журналом для преподавателя.
#   - Фильтрует занятия так, чтобы преподаватель видел только те, которые он ведет,
#     или занятия групп, где он является куратором.
#   - Группирует отфильтрованные занятия по "Предмет - Группа", создавая для каждой такой комбинации
#     отдельный лист в Excel-книге.
#   - Для каждого листа формирует заголовки и строки данных, включая ФИО студентов,
#     дату/время/тему занятия, статус присутствия, оценку за урок, информацию о ДЗ и оценку за него.
#   - Если данных нет, создает лист с сообщением "Нет данных".
#   - Формирует имя файла на основе примененных фильтров и возвращает HttpResponse с Excel-файлом.
# - export_admin_journal(): Генерирует Excel-файл с полным журналом для администратора.
#   - Применяет фильтры к базовому QuerySet'у занятий.
#   - Создает один лист "Общий журнал" со всеми отфильтрованными данными.
#   - Включает более подробную информацию по каждому занятию и студенту, чем в учительском журнале
#     (ID занятия, уч. год/период, тип занятия, аудитория и т.д.).
#   - Если данных нет, создает лист с сообщением "Нет данных".
#   - Формирует имя файла и возвращает HttpResponse с Excel-файлом.
# - _save_workbook_to_response(filename): Сохраняет текущую Excel-книгу (self.workbook)
#   в байтовый поток и формирует HttpResponse с соответствующим content_type и
#   Content-Disposition для скачивания файла клиентом.
class JournalExporter:
    def __init__(self, request_user, filters=None):
        self.user = request_user
        self.filters = filters if filters else {}
        self.workbook = Workbook()
        self.workbook.remove(self.workbook.active) # Удаление листа по умолчанию

    # Применяет общие стили к листу Excel.
    def _apply_common_styles(self, ws):
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        for row in ws.iter_rows():
            for cell in row:
                cell.border = thin_border
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        for col_idx, column_cells in enumerate(ws.columns):
            max_length = 0
            column_letter = get_column_letter(col_idx + 1) # Исправлено имя переменной
            for cell in column_cells:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column_letter].width = min(adjusted_width, 50)

        ws.freeze_panes = 'A2'

    # Формирует базовый QuerySet для занятий с предзагрузкой связанных данных.
    def _get_base_lesson_queryset(self):
        return Lesson.objects.select_related(
            'study_period__academic_year', 
            'student_group__curator', 
            'subject', 
            'teacher', 
            'classroom'
        ).prefetch_related(
            Prefetch('journal_entry', queryset=LessonJournalEntry.objects.prefetch_related(
                Prefetch('attendances', queryset=Attendance.objects.select_related('student')),
                Prefetch('homework_assignments', queryset=Homework.objects.prefetch_related(
                    Prefetch('submissions', queryset=HomeworkSubmission.objects.select_related('student', 'grade_for_submission'))
                ))
            )),
            Prefetch('grades_for_lesson_instance', queryset=Grade.objects.filter(grade_type=Grade.GradeType.LESSON_WORK).select_related('student'))
        ).order_by('start_time', 'student_group__name')

    # Применяет фильтры к QuerySet'у на основе параметров, переданных в self.filters.
    def _filter_queryset_by_params(self, queryset):
        if self.filters.get('academic_year_id'):
            queryset = queryset.filter(study_period__academic_year_id=self.filters['academic_year_id'])
        if self.filters.get('study_period_id'):
            queryset = queryset.filter(study_period_id=self.filters['study_period_id'])
        if self.filters.get('student_group_id'):
            queryset = queryset.filter(student_group_id=self.filters['student_group_id'])
        if self.filters.get('subject_id'):
            queryset = queryset.filter(subject_id=self.filters['subject_id'])
        if self.filters.get('teacher_id'):
            queryset = queryset.filter(teacher_id=self.filters['teacher_id'])
        
        date_from = self.filters.get('date_from')
        date_to = self.filters.get('date_to')
        if date_from:
            queryset = queryset.filter(start_time__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(start_time__date__lte=date_to)
            
        return queryset.distinct()

    # Генерирует Excel-файл с журналом для преподавателя.
    def export_teacher_journal(self):
        logger.info(f"Teacher {self.user.email} requested journal export with filters: {self.filters}")
        base_queryset = self._get_base_lesson_queryset()
        
        teacher_lessons_qs = base_queryset.filter(teacher=self.user)
        curated_group_ids = StudentGroup.objects.filter(curator=self.user).values_list('id', flat=True)
        curator_lessons_qs = base_queryset.filter(student_group_id__in=list(curated_group_ids))
        
        final_queryset = (teacher_lessons_qs | curator_lessons_qs).distinct()
        final_queryset = self._filter_queryset_by_params(final_queryset)

        lessons_by_subject_group = {}
        for lesson in final_queryset:
            # Используем ID для уникальности ключа, если имена могут совпадать
            key = (lesson.subject.name, lesson.student_group.name, lesson.student_group_id, lesson.subject_id)
            if key not in lessons_by_subject_group:
                lessons_by_subject_group[key] = []
            lessons_by_subject_group[key].append(lesson)

        if not lessons_by_subject_group:
            ws = self.workbook.create_sheet(title="Нет данных")
            ws.append(["Нет данных для экспорта по указанным фильтрам."])
            self._apply_common_styles(ws)
            logger.warning(f"No data found for teacher {self.user.email} export with filters: {self.filters}")
            return self._save_workbook_to_response("Teacher_Journal_NoData.xlsx")

        for (subject_name, group_name, group_id, subject_id_unused), lessons_in_group_subject in lessons_by_subject_group.items():
            sheet_title = f"{subject_name[:15]}_{group_name[:15]}"[:31] # Сокращаем для имени листа
            ws = self.workbook.create_sheet(title=sheet_title)
            
            headers = [
                '№', 'ФИО студента', 'Дата занятия', 'Время', 'Тема урока', 
                'Присутствие', 'Комм. к присут.', 'Оценка за урок', 'Комм. к оценке',
                'Домашнее задание', 'Статус ДЗ', 'Оценка за ДЗ', 'Комм. к оценке ДЗ'
            ]
            ws.append(headers)

            students_in_group = StudentGroup.objects.get(id=group_id).students.order_by('last_name', 'first_name')
            
            lesson_row_start_index = 2 # Начинаем данные со второй строки
            for lesson in sorted(lessons_in_group_subject, key=lambda l: l.start_time):
                journal_entry = getattr(lesson, 'journal_entry', None)
                homework = None
                if journal_entry and hasattr(journal_entry, 'homework_assignments') and journal_entry.homework_assignments.exists():
                    homework = journal_entry.homework_assignments.first()

                for student_idx, student in enumerate(students_in_group):
                    current_excel_row = lesson_row_start_index + student_idx
                    
                    attendance_obj = None
                    if journal_entry and hasattr(journal_entry, 'attendances'):
                        for att in journal_entry.attendances.all():
                            if att.student_id == student.id: attendance_obj = att; break
                    
                    lesson_grade_obj = None
                    if hasattr(lesson, 'grades_for_lesson_instance'):
                        for grade in lesson.grades_for_lesson_instance.all():
                             if grade.student_id == student.id: lesson_grade_obj = grade; break
                    
                    hw_submission_obj = None
                    hw_grade_obj = None
                    status_dz = "Нет ДЗ"
                    if homework:
                        status_dz = "Не сдано"
                        if hasattr(homework, 'submissions'):
                            for sub in homework.submissions.all():
                                if sub.student_id == student.id:
                                    hw_submission_obj = sub
                                    status_dz = "Сдано (ожидает)" # По умолчанию
                                    if hasattr(sub, 'grade_for_submission') and sub.grade_for_submission:
                                        hw_grade_obj = sub.grade_for_submission
                                        status_dz = f"Оценено: {hw_grade_obj.grade_value}"
                                    break
                        if not hw_submission_obj and homework.due_date and timezone.now().date() > homework.due_date.date():
                             status_dz = "Не сдано (просрочено)"

                    row_data = [
                        student_idx + 1, # № п/п студента внутри занятия
                        student.get_full_name(),
                        lesson.start_time.strftime('%d.%m.%Y'),
                        f"{lesson.start_time.strftime('%H:%M')}-{lesson.end_time.strftime('%H:%M')}",
                        getattr(journal_entry, 'topic_covered', '-'),
                        attendance_obj.get_status_display() if attendance_obj else '-',
                        attendance_obj.comment if attendance_obj and attendance_obj.comment else '-', # Добавлена проверка на None
                        lesson_grade_obj.grade_value if lesson_grade_obj else '-',
                        lesson_grade_obj.comment if lesson_grade_obj and lesson_grade_obj.comment else '-', # Добавлена проверка на None
                        homework.description if homework and homework.description else '-', # Добавлена проверка на None
                        status_dz,
                        hw_grade_obj.grade_value if hw_grade_obj else '-',
                        hw_grade_obj.comment if hw_grade_obj and hw_grade_obj.comment else '-', # Добавлена проверка на None
                    ]
                    ws.append(row_data)
                lesson_row_start_index += students_in_group.count() # Сдвигаем начальный индекс для следующего занятия
            
            self._apply_common_styles(ws)
            logger.info(f"Generated sheet '{sheet_title}' for teacher {self.user.email}")

        filename_parts = ["Teacher_Journal"]
        # Добавляем фильтры в имя файла, если они были применены
        if self.filters.get('academic_year_id'):
            try: filename_parts.append(AcademicYear.objects.get(id=self.filters['academic_year_id']).name.replace(" ", "_"))
            except AcademicYear.DoesNotExist: pass
        if self.filters.get('study_period_id'):
            try: filename_parts.append(StudyPeriod.objects.get(id=self.filters['study_period_id']).name.replace(" ", "_"))
            except StudyPeriod.DoesNotExist: pass

        filename = "_".join(filename_parts) + ".xlsx"
        return self._save_workbook_to_response(filename)

    # Генерирует Excel-файл с общим журналом для администратора.
    def export_admin_journal(self):
        logger.info(f"Admin {self.user.email} requested journal export with filters: {self.filters}")
        base_queryset = self._get_base_lesson_queryset()
        final_queryset = self._filter_queryset_by_params(base_queryset)

        if not final_queryset.exists():
            ws = self.workbook.create_sheet(title="Нет данных")
            ws.append(["Нет данных для экспорта по указанным фильтрам."])
            self._apply_common_styles(ws)
            logger.warning(f"No data found for admin export with filters: {self.filters}")
            return self._save_workbook_to_response("Admin_Journal_NoData.xlsx")

        ws = self.workbook.create_sheet(title="Общий журнал")
        headers = [
            'ID Занятия', 'Дата', 'Время начала', 'Время окончания', 'Уч. Год', 'Уч. Период',
            'Группа', 'Предмет', 'Тип занятия', 'Преподаватель', 'Аудитория', 'Тема урока',
            'ФИО студента', 'ID Студента', 'Статус присутствия', 'Комм. к присут.', 
            'Оценка за урок', 'Комм. к оценке (урок)', 'ДЗ (ID)', 'ДЗ (описание)', 
            'Статус ДЗ', 'Оценка за ДЗ', 'Комм. к оценке (ДЗ)'
        ]
        ws.append(headers)

        for lesson in final_queryset: # Итерация по отфильтрованным занятиям
            journal_entry = getattr(lesson, 'journal_entry', None)
            homework = None
            if journal_entry and hasattr(journal_entry, 'homework_assignments') and journal_entry.homework_assignments.exists():
                 homework = journal_entry.homework_assignments.first()

            # Получаем студентов группы для текущего занятия
            students_in_lesson_group = lesson.student_group.students.order_by('last_name', 'first_name')

            for student in students_in_lesson_group:
                attendance_obj = None
                if journal_entry and hasattr(journal_entry, 'attendances'):
                    for att in journal_entry.attendances.all(): # Итерируем по предзагруженным
                        if att.student_id == student.id: attendance_obj = att; break
                
                lesson_grade_obj = None
                if hasattr(lesson, 'grades_for_lesson_instance'):
                    for grade in lesson.grades_for_lesson_instance.all(): # Итерируем по предзагруженным
                         if grade.student_id == student.id: lesson_grade_obj = grade; break
                
                hw_submission_obj = None
                hw_grade_obj = None
                status_dz = "Нет ДЗ"
                if homework:
                    status_dz = "Не сдано"
                    if hasattr(homework, 'submissions'):
                        for sub in homework.submissions.all(): # Итерируем по предзагруженным
                            if sub.student_id == student.id:
                                hw_submission_obj = sub
                                status_dz = "Сдано (ожидает)"
                                if hasattr(sub, 'grade_for_submission') and sub.grade_for_submission:
                                    hw_grade_obj = sub.grade_for_submission
                                    status_dz = f"Оценено: {hw_grade_obj.grade_value}"
                                break
                    if not hw_submission_obj and homework.due_date and timezone.now().date() > homework.due_date.date():
                         status_dz = "Не сдано (просрочено)"

                row_data = [
                    lesson.id, lesson.start_time.strftime('%d.%m.%Y'), lesson.start_time.strftime('%H:%M'), lesson.end_time.strftime('%H:%M'),
                    lesson.study_period.academic_year.name, lesson.study_period.name,
                    lesson.student_group.name, lesson.subject.name, lesson.get_lesson_type_display(),
                    lesson.teacher.get_full_name() if lesson.teacher else '-', # Добавлена проверка на None
                    lesson.classroom.identifier if lesson.classroom else '-',
                    getattr(journal_entry, 'topic_covered', '-'),
                    student.get_full_name(), student.id,
                    attendance_obj.get_status_display() if attendance_obj else '-',
                    attendance_obj.comment if attendance_obj and attendance_obj.comment else '-',
                    lesson_grade_obj.grade_value if lesson_grade_obj else '-',
                    lesson_grade_obj.comment if lesson_grade_obj and lesson_grade_obj.comment else '-',
                    homework.id if homework else '-',
                    homework.description if homework and homework.description else '-',
                    status_dz,
                    hw_grade_obj.grade_value if hw_grade_obj else '-',
                    hw_grade_obj.comment if hw_grade_obj and hw_grade_obj.comment else '-',
                ]
                ws.append(row_data)
        
        self._apply_common_styles(ws)
        logger.info(f"Generated admin journal sheet for user {self.user.email}")

        filename_parts = ["Admin_Full_Journal"]
        # Формирование имени файла с учетом фильтров
        try:
            if self.filters.get('academic_year_id'): filename_parts.append(AcademicYear.objects.get(id=self.filters['academic_year_id']).name.replace(" ","_"))
            if self.filters.get('study_period_id'): filename_parts.append(StudyPeriod.objects.get(id=self.filters['study_period_id']).name.replace(" ","_"))
            if self.filters.get('student_group_id'): filename_parts.append(StudentGroup.objects.get(id=self.filters['student_group_id']).name.replace(" ","_"))
            if self.filters.get('subject_id'): filename_parts.append(Subject.objects.get(id=self.filters['subject_id']).name.replace(" ","_"))
            if self.filters.get('date_from'): filename_parts.append(f"from_{self.filters['date_from'].strftime('%Y%m%d')}")
            if self.filters.get('date_to'): filename_parts.append(f"to_{self.filters['date_to'].strftime('%Y%m%d')}")
        except Exception as e: # Обработка возможных DoesNotExist
            logger.warning(f"Could not retrieve some filter names for filename generation: {e}")

        filename = "_".join(filename_parts) + ".xlsx"
        return self._save_workbook_to_response(filename)

    # Сохраняет Excel-книгу в байтовый поток и возвращает HttpResponse.
    def _save_workbook_to_response(self, filename="journal_export.xlsx"):
        excel_io = BytesIO()
        self.workbook.save(excel_io)
        excel_io.seek(0)

        response = HttpResponse(
            excel_io.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        logger.info(f"Prepared HttpResponse with Excel file: {filename}")
        return response