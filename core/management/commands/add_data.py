# edu_core/management/commands/seed_edu_data.py
import random
from datetime import date, time, timedelta, datetime as dt_datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction, IntegrityError
from faker import Faker
from django.contrib.auth import get_user_model
from django.db.models import Avg # Импортируем Avg
from django.db.models import Q
# Импорт моделей
from users.models import User # Уже импортирован get_user_model
from edu_core.models import (
    AcademicYear, StudyPeriod, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial, SubjectMaterialAttachment
)

fake = Faker('ru_RU')
User = get_user_model()

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
NUM_STUDENTS = 100
NUM_PARENTS = 100 # по одному на студента
# NUM_TEACHERS_TARGET будет определен длиной TEACHER_ASSIGNMENTS
GRADES_RANGE = range(1, 12) # Классы с 1 по 11

SUBJECTS_CONFIG = {
    "Русский язык (1-4)": {"type_name": "Гуманитарный", "code": "RU-N", "grades": range(1, 5)},
    "Литературное чтение (1-4)": {"type_name": "Гуманитарный", "code": "LIT-N", "grades": range(1, 5)},
    "Математика (1-4)": {"type_name": "Естественно-математический", "code": "MATH-N", "grades": range(1, 5)},
    "Окружающий мир (1-4)": {"type_name": "Естественно-математический", "code": "WORLD-N", "grades": range(1, 5)},
    "Английский язык (2-4)": {"type_name": "Иностранные языки", "code": "EN-N", "grades": range(2, 5)},
    "ИЗО (1-4)": {"type_name": "Искусство и Технология", "code": "ART-N", "grades": range(1, 5)},
    "Музыка (1-4)": {"type_name": "Искусство и Технология", "code": "MUS-N", "grades": range(1, 5)},
    "Технология (1-4)": {"type_name": "Искусство и Технология", "code": "TECH-N", "grades": range(1, 5)},
    "Физкультура (1-4)": {"type_name": "Физическая культура и ОБЖ", "code": "PE-N", "grades": range(1, 5)},
    "Информатика (2-4)": {"type_name": "Информационные технологии", "code": "IT-N", "grades": range(2, 5)},
    "Русский язык (5-11)": {"type_name": "Гуманитарный", "code": "RU-M", "grades": range(5, 12)},
    "Литература (5-11)": {"type_name": "Гуманитарный", "code": "LIT-M", "grades": range(5, 12)},
    "Английский язык (5-11)": {"type_name": "Иностранные языки", "code": "EN-M", "grades": range(5, 12)},
    "Математика (5-6)": {"type_name": "Естественно-математический", "code": "MATH-56", "grades": range(5, 7)},
    "Алгебра (7-11)": {"type_name": "Естественно-математический", "code": "ALG", "grades": range(7, 12)},
    "Геометрия (7-11)": {"type_name": "Естественно-математический", "code": "GEOM", "grades": range(7, 12)},
    "История (5-11)": {"type_name": "Гуманитарный", "code": "HIST", "grades": range(5, 12)},
    "Обществознание (8-11)": {"type_name": "Гуманитарный", "code": "SOC", "grades": range(8, 12)},
    "География (5-11)": {"type_name": "Естественно-математический", "code": "GEO", "grades": range(5, 11)},
    "Биология (5-11)": {"type_name": "Естественно-математический", "code": "BIO", "grades": range(5, 12)},
    "Физика (7-11)": {"type_name": "Естественно-математический", "code": "PHYS", "grades": range(7, 12)},
    "Химия (8-11)": {"type_name": "Естественно-математический", "code": "CHEM", "grades": range(8, 12)},
    "Информатика (5-11)": {"type_name": "Информационные технологии", "code": "IT-M", "grades": range(5, 12)},
    "Технология (5-9)": {"type_name": "Искусство и Технология", "code": "TECH-M", "grades": range(5, 10)},
    "ИЗО (5-7)": {"type_name": "Искусство и Технология", "code": "ART-M", "grades": range(5, 8)},
    "Музыка (5-7)": {"type_name": "Искусство и Технология", "code": "MUS-M", "grades": range(5, 8)},
    "Физкультура (5-11)": {"type_name": "Физическая культура и ОБЖ", "code": "PE-M", "grades": range(5, 12)},
    "ОБЖ (8-11)": {"type_name": "Физическая культура и ОБЖ", "code": "OBZH", "grades": range(8, 12)},
    "Астрономия (11)": {"type_name": "Естественно-математический", "code": "ASTR", "grades": range(11, 12)},
}

TEACHER_ASSIGNMENTS = [
    {"name_prefix": "Учитель РусЛит НШ", "subjects": ["Русский язык (1-4)", "Литературное чтение (1-4)"]},
    {"name_prefix": "Учитель РусЛит СШ", "subjects": ["Русский язык (5-11)", "Литература (5-11)"]},
    {"name_prefix": "Учитель Англ 1-7", "subjects": ["Английский язык (2-4)", "Английский язык (5-11)"]}, # Ведет до 7, потом другой
    {"name_prefix": "Учитель Англ 8-11", "subjects": ["Английский язык (5-11)"]}, # Ведет с 8
    {"name_prefix": "Учитель Мат 1-6", "subjects": ["Математика (1-4)", "Математика (5-6)"]},
    {"name_prefix": "Учитель АлгГеом 7-11", "subjects": ["Алгебра (7-11)", "Геометрия (7-11)"]},
    {"name_prefix": "Учитель ИстОбщ", "subjects": ["История (5-11)", "Обществознание (8-11)"]},
    {"name_prefix": "Учитель Геогр", "subjects": ["География (5-11)"]},
    {"name_prefix": "Учитель Биолог", "subjects": ["Биология (5-11)"]},
    {"name_prefix": "Учитель ФизАстр", "subjects": ["Физика (7-11)", "Астрономия (11)"]},
    {"name_prefix": "Учитель Химик", "subjects": ["Химия (8-11)"]},
    {"name_prefix": "Учитель Информ", "subjects": ["Информатика (2-4)", "Информатика (5-11)"]},
    {"name_prefix": "Учитель НачКласс1", "subjects": ["Русский язык (1-4)", "Литературное чтение (1-4)", "Математика (1-4)", "Окружающий мир (1-4)", "ИЗО (1-4)", "Музыка (1-4)", "Технология (1-4)"]}, # Для 1-2 классов
    {"name_prefix": "Учитель НачКласс2", "subjects": ["Русский язык (1-4)", "Литературное чтение (1-4)", "Математика (1-4)", "Окружающий мир (1-4)", "ИЗО (1-4)", "Музыка (1-4)", "Технология (1-4)"]}, # Для 3-4 классов
    {"name_prefix": "Учитель ИЗОМузОбщ", "subjects": ["ИЗО (1-4)", "Музыка (1-4)", "ИЗО (5-7)", "Музыка (5-7)"]},
    {"name_prefix": "Учитель Технолог", "subjects": ["Технология (1-4)", "Технология (5-9)"]},
    {"name_prefix": "Учитель ФизКульт", "subjects": ["Физкультура (1-4)", "Физкультура (5-11)"]},
    {"name_prefix": "Учитель ОБЖ", "subjects": ["ОБЖ (8-11)"]},
]
NUM_TEACHERS_ACTUAL = len(TEACHER_ASSIGNMENTS)

LESSON_TIMES = [
    (time(8, 30), time(9, 15)), (time(9, 25), time(10, 10)), (time(10, 20), time(11, 05)),
    (time(11, 25), time(12, 10)), (time(12, 20), time(13, 05)), (time(13, 15), time(14, 00)),
    (time(14, 10), time(14, 55)), (time(15, 05), time(15, 50))
]
LESSONS_PER_DAY_MAP = {
    range(1, 5): (3, 4), range(5, 10): (4, 6), range(10, 12): (5, 7)
}
ATTENDANCE_STATUS_WEIGHTS = {
    Attendance.Status.PRESENT: 0.85, Attendance.Status.ABSENT_VALID: 0.05,
    Attendance.Status.ABSENT_INVALID: 0.05, Attendance.Status.LATE: 0.03,
    Attendance.Status.REMOTE: 0.02,
}
GRADE_VALUES_NUMERIC = ["5", "4", "3", "2"]
NUMERIC_MAP = {"5": 5.0, "4": 4.0, "3": 3.0, "2": 2.0, "Зачтено": 5.0, "Незачтено": 2.0}


class Command(BaseCommand):
    help = 'Seeds the database with initial data for the educational platform.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_academic_year = None
        self.quarters = []
        self.semesters = []
        self.subject_types_db = {}
        self.subjects_db = {}
        self.classrooms = []
        self.teachers = []
        self.students = []
        self.parents = []
        self.student_groups = []

    def _split_fio(self, full_name):
        parts = full_name.split()
        if len(parts) >= 2:
            last_name, first_name = parts[0], parts[1]
            patronymic = parts[2] if len(parts) > 2 else ""
        else:
            last_name, first_name, patronymic = parts[0] if parts else "Фамилия", "Имя", ""
        return first_name, last_name, patronymic

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")
        self._create_academic_year_and_periods()
        self._create_subject_types_and_subjects()
        self._create_classrooms()
        self._create_teachers()
        self._create_students_and_parents()
        self._create_student_groups()
        self._create_curricula_and_entries()
        all_lessons = self._generate_schedules()
        self._fill_lesson_journals_attendance_homework(all_lessons)
        self._generate_grades()
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))

    def _create_academic_year_and_periods(self):
        self.stdout.write("Creating academic year and study periods...")
        year, _ = AcademicYear.objects.update_or_create(
            name="2024-2025",
            defaults={'start_date': date(2024, 9, 2), 'end_date': date(2025, 5, 31), 'is_current': True}
        )
        AcademicYear.objects.exclude(pk=year.pk).update(is_current=False) # Снимаем флаг с других
        self.current_academic_year = year

        q_dates = [("1 четверть", date(2024, 9, 2), date(2024, 10, 26)), ("2 четверть", date(2024, 11, 5), date(2024, 12, 28)), ("3 четверть", date(2025, 1, 9), date(2025, 3, 22)), ("4 четверть", date(2025, 4, 1), date(2025, 5, 31))]
        self.quarters = [StudyPeriod.objects.get_or_create(academic_year=year, name=n, defaults={'start_date': s, 'end_date': e})[0] for n, s, e in q_dates]
        sem_dates = [("1 полугодие (10-11 кл)", date(2024, 9, 2), date(2024, 12, 28)), ("2 полугодие (10-11 кл)", date(2025, 1, 9), date(2025, 5, 31))]
        self.semesters = [StudyPeriod.objects.get_or_create(academic_year=year, name=n, defaults={'start_date': s, 'end_date': e})[0] for n, s, e in sem_dates]
        self.stdout.write("Academic year and study periods created.")

    def _create_subject_types_and_subjects(self):
        self.stdout.write("Creating subject types and subjects...")
        for type_name in set(d["type_name"] for d in SUBJECTS_CONFIG.values()):
            st, _ = SubjectType.objects.get_or_create(name=type_name)
            self.subject_types_db[type_name] = st
        for subj_name, data in SUBJECTS_CONFIG.items():
            s, _ = Subject.objects.get_or_create(name=subj_name, defaults={'subject_type': self.subject_types_db.get(data["type_name"]), 'code': data["code"]})
            self.subjects_db[subj_name] = s
        self.stdout.write("Subject types and subjects created.")

    def _create_classrooms(self):
        self.stdout.write("Creating classrooms...")
        for i in range(1, 21):
            room, _ = Classroom.objects.get_or_create(identifier=f"Каб. {100+i}", defaults={'type': random.choice(Classroom.ClassroomType.choices)[0], 'capacity': random.randint(20, 35), 'equipment': fake.bs()})
            self.classrooms.append(room)
        self.stdout.write("Classrooms created.")

    def _create_teachers(self):
        self.stdout.write("Creating teachers...")
        for i, assignment in enumerate(TEACHER_ASSIGNMENTS):
            first_name, last_name, patronymic = self._split_fio(fake.name())
            email = f"{assignment['name_prefix'].lower().replace(' ', '').replace('-', '')}{i+1}@example.com"
            teacher, created = User.objects.get_or_create(email=email, defaults={'first_name': first_name, 'last_name': last_name, 'patronymic': patronymic, 'role': User.Role.TEACHER, 'is_active': True, 'is_role_confirmed': True})
            if created: teacher.set_password("teacherpass"); teacher.save()
            teacher.lead_subjects.set([self.subjects_db[subj_name] for subj_name in assignment["subjects"] if subj_name in self.subjects_db])
            self.teachers.append(teacher)
        self.stdout.write(f"{len(self.teachers)} teachers created.")

    def _create_students_and_parents(self):
        self.stdout.write("Creating students and parents...")
        for i in range(NUM_STUDENTS):
            s_first_name, s_last_name, s_patronymic = self._split_fio(fake.name_male() if random.choice([True, False]) else fake.name_female())
            s_email = f"student{i+1}@example.com"
            student, created = User.objects.get_or_create(email=s_email, defaults={'first_name': s_first_name, 'last_name': s_last_name, 'patronymic': s_patronymic, 'role': User.Role.STUDENT, 'is_active': True, 'is_role_confirmed': True})
            if created: student.set_password("studentpass"); student.save()
            student.temp_grade_level = random.choice(GRADES_RANGE)
            self.students.append(student)

            p_first_name, p_last_name, p_patronymic = self._split_fio(fake.name())
            p_email = f"parent{i+1}@example.com"
            parent, created = User.objects.get_or_create(email=p_email, defaults={'first_name': p_first_name, 'last_name': p_last_name, 'patronymic': p_patronymic, 'role': User.Role.PARENT, 'is_active': True, 'is_role_confirmed': True})
            if created: parent.set_password("parentpass"); parent.save()
            student.parents.add(parent)
            self.parents.append(parent)
        self.stdout.write(f"{len(self.students)} students and {len(self.parents)} parents created.")

    def _create_student_groups(self):
        self.stdout.write("Creating student groups...")
        available_curators = list(self.teachers); random.shuffle(available_curators)
        for grade_num in GRADES_RANGE:
            group, _ = StudentGroup.objects.get_or_create(name=f"{grade_num}А", academic_year=self.current_academic_year)
            if available_curators and len(self.student_groups) < 11: group.curator = available_curators.pop(0)
            students_for_grade = [s for s in self.students if s.temp_grade_level == grade_num]
            if students_for_grade:
                group.students.set(students_for_grade)
                if not group.group_monitor: group.group_monitor = random.choice(students_for_grade)
            group.save(); self.student_groups.append(group)
        self.stdout.write(f"{len(self.student_groups)} student groups created.")

    def _create_curricula_and_entries(self):
        self.stdout.write("Creating curricula and entries...")
        for group in self.student_groups:
            grade_level = int(group.name[:-1])
            curriculum, _ = Curriculum.objects.get_or_create(name=f"УП {group.name} {self.current_academic_year.name}", academic_year=self.current_academic_year, student_group=group, defaults={'is_active': True})
            current_study_periods = self.quarters if grade_level < 10 else self.semesters
            for period in current_study_periods:
                for subj_name_cfg, subj_data_cfg in SUBJECTS_CONFIG.items():
                    if grade_level in subj_data_cfg["grades"]:
                        subject_obj = self.subjects_db[subj_name_cfg]
                        possible_teachers = [t for t in self.teachers if subject_obj in t.lead_subjects.all()] or self.teachers
                        teacher_obj = random.choice(possible_teachers) if possible_teachers else None
                        if not teacher_obj: continue
                        hours = random.randint(20, 50) // len(current_study_periods) + 10
                        CurriculumEntry.objects.get_or_create(curriculum=curriculum, subject=subject_obj, teacher=teacher_obj, study_period=period, defaults={'planned_hours': hours})
        self.stdout.write("Curricula and entries created.")

    def _generate_schedules(self):
        self.stdout.write("Generating lesson schedules...")
        all_lessons_created = []
        for group in self.student_groups:
            grade_level = int(group.name[:-1])
            current_study_periods = self.quarters if grade_level < 10 else self.semesters
            lessons_per_day_range = LESSONS_PER_DAY_MAP.get(next(r for r in LESSONS_PER_DAY_MAP if grade_level in r), (3,4))
            try: curriculum = Curriculum.objects.get(student_group=group, academic_year=self.current_academic_year)
            except Curriculum.DoesNotExist: continue
            for period in current_study_periods:
                entries_for_period = list(CurriculumEntry.objects.filter(curriculum=curriculum, study_period=period).select_related('subject', 'teacher'))
                if not entries_for_period: continue
                current_date = period.start_date
                while current_date <= period.end_date:
                    day_of_week = current_date.weekday()
                    if day_of_week >= 5: current_date += timedelta(days=1); continue
                    num_lessons_today = random.randint(*lessons_per_day_range)
                    daily_entries_sample = random.sample(entries_for_period, min(len(entries_for_period), num_lessons_today))
                    for slot_idx, entry in enumerate(daily_entries_sample):
                        if slot_idx >= len(LESSON_TIMES): break
                        start_t, end_t = LESSON_TIMES[slot_idx]
                        start_dt, end_dt = timezone.make_aware(dt_datetime.combine(current_date, start_t)), timezone.make_aware(dt_datetime.combine(current_date, end_t))
                        classroom = random.choice(self.classrooms) if self.classrooms else None
                        conflict_q = Q(start_time__lt=end_dt) & Q(end_time__gt=start_dt)
                        if Lesson.objects.filter(conflict_q, teacher=entry.teacher).exists() or \
                           Lesson.objects.filter(conflict_q, student_group=group).exists() or \
                           (classroom and Lesson.objects.filter(conflict_q, classroom=classroom).exists()):
                            continue # Пропускаем при конфликте
                        lesson = Lesson.objects.create(study_period=period, student_group=group, subject=entry.subject, teacher=entry.teacher, classroom=classroom, lesson_type=random.choice(Lesson.LessonType.choices)[0], start_time=start_dt, end_time=end_dt, curriculum_entry=entry, created_by=entry.teacher)
                        all_lessons_created.append(lesson)
                    current_date += timedelta(days=1)
        self.stdout.write(f"{len(all_lessons_created)} lessons generated.")
        return all_lessons_created

    def _fill_lesson_journals_attendance_homework(self, all_lessons):
        self.stdout.write("Filling lesson journals, attendance, and homework...")
        for lesson in all_lessons:
            journal_entry, _ = LessonJournalEntry.objects.get_or_create(lesson=lesson, defaults={'topic_covered': fake.catch_phrase()[:200], 'teacher_notes': fake.text(max_nb_chars=150)})
            for student in lesson.student_group.students.all():
                status_choice = random.choices(list(ATTENDANCE_STATUS_WEIGHTS.keys()), weights=list(ATTENDANCE_STATUS_WEIGHTS.values()), k=1)[0]
                Attendance.objects.get_or_create(journal_entry=journal_entry, student=student, defaults={'status': status_choice, 'marked_by': lesson.teacher, 'comment': fake.sentence() if random.random() < 0.05 else ""})
            if random.random() < 0.4:
                hw = Homework.objects.create(journal_entry=journal_entry, title=f"ДЗ: {lesson.subject.name} {lesson.start_time.strftime('%d.%m')}", description=fake.paragraph(nb_sentences=2), due_date=lesson.start_time + timedelta(days=random.randint(2,5)), author=lesson.teacher)
                for student in lesson.student_group.students.all():
                    if random.random() < 0.6: HomeworkSubmission.objects.create(homework=hw, student=student, content=fake.text(max_nb_chars=100))
        self.stdout.write("Lesson journals, attendance, and homework filled.")

    def _generate_grades(self):
        self.stdout.write("Generating grades...")
        for student in self.students:
            for sub in HomeworkSubmission.objects.filter(student=student):
                if random.random() < 0.7:
                    grade_val = random.choice(GRADE_VALUES_NUMERIC)
                    Grade.objects.get_or_create(homework_submission=sub, student=student, subject=sub.homework.journal_entry.lesson.subject, grade_type=Grade.GradeType.HOMEWORK_GRADE, defaults={'study_period':sub.homework.journal_entry.lesson.study_period, 'academic_year':sub.homework.journal_entry.lesson.study_period.academic_year, 'grade_value':grade_val, 'numeric_value':NUMERIC_MAP.get(grade_val), 'graded_by':sub.homework.author, 'date_given':fake.date_between_dates(date_start=sub.submitted_at.date(), date_end=sub.submitted_at.date() + timedelta(days=2))})
            for att in Attendance.objects.filter(student=student, status__in=[Attendance.Status.PRESENT, Attendance.Status.LATE, Attendance.Status.REMOTE]):
                if random.random() < 0.1:
                    grade_val = random.choice(GRADE_VALUES_NUMERIC)
                    Grade.objects.get_or_create(lesson=att.journal_entry.lesson, student=student, subject=att.journal_entry.lesson.subject, grade_type=Grade.GradeType.LESSON_WORK, defaults={'study_period':att.journal_entry.lesson.study_period, 'academic_year':att.journal_entry.lesson.study_period.academic_year, 'grade_value':grade_val, 'numeric_value':NUMERIC_MAP.get(grade_val), 'graded_by':att.journal_entry.lesson.teacher, 'date_given':att.journal_entry.lesson.start_time.date()})
            
            student_grade_level = student.temp_grade_level
            current_study_periods = self.quarters if student_grade_level < 10 else self.semesters
            subjects_for_student = Subject.objects.filter(curriculum_entries__curriculum__student_group__students=student, curriculum_entries__curriculum__academic_year=self.current_academic_year).distinct()
            for subject_obj in subjects_for_student:
                for period in current_study_periods:
                    if not CurriculumEntry.objects.filter(curriculum__student_group__students=student, subject=subject_obj, study_period=period).exists(): continue
                    period_grades = Grade.objects.filter(student=student, subject=subject_obj, study_period=period, numeric_value__isnull=False)
                    if period_grades.exists():
                        avg_val = period_grades.aggregate(avg=Avg('numeric_value'))['avg']
                        if avg_val:
                            final_grade_str = str(max(2, min(5, int(round(avg_val))))) # Оценка от 2 до 5
                            Grade.objects.get_or_create(student=student, subject=subject_obj, study_period=period, grade_type=Grade.GradeType.PERIOD_FINAL, defaults={'academic_year': self.current_academic_year, 'grade_value': final_grade_str, 'numeric_value': float(final_grade_str), 'graded_by': random.choice(self.teachers) if self.teachers else None, 'date_given': period.end_date})
                year_final_grades = Grade.objects.filter(student=student, subject=subject_obj, academic_year=self.current_academic_year, grade_type=Grade.GradeType.PERIOD_FINAL, numeric_value__isnull=False)
                if year_final_grades.exists():
                    avg_val = year_final_grades.aggregate(avg=Avg('numeric_value'))['avg']
                    if avg_val:
                        final_grade_str = str(max(2, min(5, int(round(avg_val)))))
                        Grade.objects.get_or_create(student=student, subject=subject_obj, academic_year=self.current_academic_year, grade_type=Grade.GradeType.YEAR_FINAL, defaults={'grade_value': final_grade_str, 'numeric_value': float(final_grade_str), 'graded_by': random.choice(self.teachers) if self.teachers else None, 'date_given': self.current_academic_year.end_date})
        self.stdout.write("Grades generated.")