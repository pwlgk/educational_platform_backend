# edu_core/management/commands/populate_db.py

import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from faker import Faker
from faker.providers import internet, person, company, lorem, date_time, file # Добавим file

# Импортируем все ваши модели
from users.models import Profile, InvitationCode # Предполагаем, что User уже импортирован
from edu_core.models import (
    AcademicYear, StudyPeriod, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)
from messaging.models import Chat, ChatParticipant, Message # Импортируем модели чата
# Импортируйте модели из других ваших приложений, если они нужны для связей

User = get_user_model()
fake = Faker('ru_RU') # Используем русскую локализацию для ФИО и т.п.
fake.add_provider(internet)
fake.add_provider(person)
fake.add_provider(company)
fake.add_provider(lorem)
fake.add_provider(date_time)
fake.add_provider(file) # Для генерации имен файлов

# --- Константы для количества создаваемых объектов ---
NUM_ADMINS = 2
NUM_TEACHERS = 15
NUM_STUDENTS_PER_GROUP = 20
NUM_PARENTS_RATIO = 0.7 # 70% студентов будут иметь родителя
NUM_ACADEMIC_YEARS = 3
NUM_STUDY_PERIODS_PER_YEAR = 4 # Четверти
NUM_SUBJECT_TYPES = 4
NUM_SUBJECTS = 20
NUM_CLASSROOMS = 10
NUM_STUDENT_GROUPS_PER_YEAR = 5 # Групп на каждый учебный год
NUM_CURRICULA_PER_GROUP = 1
NUM_CURRICULUM_ENTRIES_PER_CURRICULUM = 8
NUM_LESSONS_PER_CURRICULUM_ENTRY = 5 # Примерное количество уроков для "вычитки" части часов
MAX_HOMEWORKS_PER_JOURNAL_ENTRY = 1
MAX_GRADES_PER_LESSON_FOR_STUDENT = 2
MAX_MESSAGES_PER_CHAT = 15
MAX_SUBJECT_MATERIALS_PER_SUBJECT = 3


class Command(BaseCommand):
    help = 'Populates the database with fake data for testing and development. CLEARS EXISTING DATA FIRST!'

    @transaction.atomic # Выполняем все в одной транзакции
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Deleting existing data...'))
        self._clear_data()
        self.stdout.write(self.style.SUCCESS('Existing data deleted.'))

        self.stdout.write(self.style.HTTP_INFO('Populating database with fake data...'))

        # --- 1. Создание Пользователей ---
        self.stdout.write('Creating users...')
        admins = self._create_users(NUM_ADMINS, User.Role.ADMIN, is_active=True, is_role_confirmed=True)
        teachers = self._create_users(NUM_TEACHERS, User.Role.TEACHER, is_active=True, is_role_confirmed=True)
        
        # Списки для дальнейшего использования
        all_students = []
        all_parents = []

        # --- 2. Базовые Сущности Учебного Процесса ---
        self.stdout.write('Creating academic years and study periods...')
        academic_years = []
        for i in range(NUM_ACADEMIC_YEARS):
            year_start = 2022 + i
            year = AcademicYear.objects.create(
                name=f"{year_start}-{year_start + 1}",
                start_date=timezone.datetime(year_start, 9, 1).date(),
                end_date=timezone.datetime(year_start + 1, 6, 30).date(),
                is_current=(i == NUM_ACADEMIC_YEARS - 1) # Последний год - текущий
            )
            academic_years.append(year)
            for j in range(NUM_STUDY_PERIODS_PER_YEAR):
                period_name = f"{j+1}-я Четверть" if NUM_STUDY_PERIODS_PER_YEAR == 4 else f"{j+1}-й Семестр"
                # Примерное распределение дат
                ps_days = (year.end_date - year.start_date).days // NUM_STUDY_PERIODS_PER_YEAR
                period_start = year.start_date + timedelta(days=j * ps_days)
                period_end = period_start + timedelta(days=ps_days -1)
                if j == NUM_STUDY_PERIODS_PER_YEAR -1: # Последний период до конца года
                    period_end = year.end_date
                StudyPeriod.objects.create(
                    academic_year=year, name=period_name, start_date=period_start, end_date=period_end
                )
        study_periods = list(StudyPeriod.objects.all())

        self.stdout.write('Creating subject types and subjects...')
        subject_types = [SubjectType.objects.create(name=fake.bs().capitalize()) for _ in range(NUM_SUBJECT_TYPES)]
        subjects = []
        for _ in range(NUM_SUBJECTS):
            s = Subject.objects.create(
                name=fake.catch_phrase().capitalize(),
                code=fake.unique.bothify(text='??###').upper(),
                subject_type=random.choice(subject_types)
            )
            # Назначаем случайных ведущих преподавателей
            s.lead_teachers.set(random.sample(teachers, k=random.randint(1, min(3, len(teachers)))))
            subjects.append(s)

        self.stdout.write('Creating classrooms...')
        classrooms = [
            Classroom.objects.create(
                identifier=f"Каб. {fake.unique.building_number()}",
                capacity=random.randint(15, 50),
                type=random.choice(Classroom.ClassroomType.choices)[0],
                equipment=fake.sentence(nb_words=random.randint(3,7))
            ) for _ in range(NUM_CLASSROOMS)
        ]

        self.stdout.write('Creating student groups and populating them...')
        student_groups = []
        for year in academic_years:
            for i in range(NUM_STUDENT_GROUPS_PER_YEAR):
                cur = random.choice(teachers) if teachers else None
                group = StudentGroup.objects.create(
                    name=f"{random.randint(1,11)}-{chr(ord('А') + i)}-{year.name[:4]}", # Пример: 10-А-2023
                    academic_year=year,
                    curator=cur
                )
                group_students = self._create_users(NUM_STUDENTS_PER_GROUP, User.Role.STUDENT, is_active=True, is_role_confirmed=True)
                group.students.set(group_students)
                if group_students:
                    group.group_monitor = random.choice(group_students)
                    group.save()
                all_students.extend(group_students)
                student_groups.append(group)
                # Создаем родителей для части студентов
                for student in random.sample(group_students, k=int(len(group_students) * NUM_PARENTS_RATIO)):
                    parent = self._create_user(f"parent_{student.email.split('@')[0]}@example.com", User.Role.PARENT, is_active=True, is_role_confirmed=True)
                    # Связываем родителя с ребенком (в модели User)
                    student.parents.add(parent) # Используем M2M 'parents' на модели User
                    all_parents.append(parent)


        # --- 3. Учебные Планы и Нагрузка ---
        self.stdout.write('Creating curricula and entries...')
        curricula = []
        curriculum_entries = []
        for group in student_groups:
            for _ in range(NUM_CURRICULA_PER_GROUP): # Обычно 1 план на группу в год
                curriculum = Curriculum.objects.create(
                    name=f"УП для {group.name} ({group.academic_year.name})",
                    academic_year=group.academic_year,
                    student_group=group
                )
                curricula.append(curriculum)
                group_study_periods = StudyPeriod.objects.filter(academic_year=group.academic_year)
                available_subjects_for_plan = random.sample(subjects, k=min(len(subjects), NUM_CURRICULUM_ENTRIES_PER_CURRICULUM * 2)) # Берем с запасом

                for sp in group_study_periods:
                    # На каждый период плана добавим несколько предметов
                    num_subjects_in_period_plan = NUM_CURRICULUM_ENTRIES_PER_CURRICULUM // len(group_study_periods) or 1
                    subjects_for_this_period = random.sample(available_subjects_for_plan, k=min(len(available_subjects_for_plan), num_subjects_in_period_plan))
                    for subj in subjects_for_this_period:
                        entry = CurriculumEntry.objects.create(
                            curriculum=curriculum,
                            subject=subj,
                            teacher=random.choice(teachers) if teachers else None,
                            study_period=sp,
                            planned_hours=random.randint(20, 60)
                        )
                        curriculum_entries.append(entry)

        # --- 4. Расписание Занятий ---
        self.stdout.write('Creating lessons...')
        lessons = []
        for entry in curriculum_entries: # Создаем уроки на основе записей плана
            # Распределяем часы по урокам (упрощенно)
            hours_per_lesson = 2 # По 2 академических часа (90 мин)
            num_lessons = entry.planned_hours // hours_per_lesson
            # Ограничим количество генерируемых уроков для скорости
            num_lessons = min(num_lessons, NUM_LESSONS_PER_CURRICULUM_ENTRY)

            lesson_date = entry.study_period.start_date
            for _ in range(num_lessons):
                if lesson_date > entry.study_period.end_date: break # Не выходим за рамки периода
                
                start_hour = random.randint(8, 15) # Начало занятий
                start_time = timezone.make_aware(timezone.datetime.combine(lesson_date, timezone.datetime.min.time()) + timedelta(hours=start_hour, minutes=random.choice([0, 30])))
                end_time = start_time + timedelta(minutes=90) # Стандартный урок
                
                # Проверка, чтобы не выйти за конец дня (упрощенно)
                if end_time.time() > timezone.datetime.strptime("18:00", "%H:%M").time():
                    lesson_date += timedelta(days=1) # Переносим на след. день
                    if lesson_date.weekday() >= 5: lesson_date += timedelta(days=7-lesson_date.weekday()) # Пропускаем выходные
                    continue

                # Проверка пересечений (очень упрощенная, без аудиторий)
                if Lesson.objects.filter(teacher=entry.teacher, start_time__lt=end_time, end_time__gt=start_time).exists() or \
                   Lesson.objects.filter(student_group=entry.curriculum.student_group, start_time__lt=end_time, end_time__gt=start_time).exists():
                    lesson_date += timedelta(days=1)
                    if lesson_date.weekday() >= 5: lesson_date += timedelta(days=7-lesson_date.weekday())
                    continue
                
                lesson = Lesson.objects.create(
                    study_period=entry.study_period,
                    student_group=entry.curriculum.student_group,
                    subject=entry.subject,
                    teacher=entry.teacher,
                    classroom=random.choice(classrooms) if classrooms else None,
                    lesson_type=random.choice(Lesson.LessonType.choices)[0],
                    start_time=start_time,
                    end_time=end_time,
                    curriculum_entry=entry,
                    created_by=random.choice(admins) if admins else (entry.teacher or None)
                )
                lessons.append(lesson)
                
                lesson_date += timedelta(days=random.randint(1,3)) # Следующий урок через 1-3 дня
                if lesson_date.weekday() >= 5: # Пропускаем выходные
                    lesson_date += timedelta(days=7-lesson_date.weekday())


        # --- 5. Журнал, ДЗ, Посещаемость, Оценки ---
        self.stdout.write('Populating lesson journals, homework, attendance, and grades...')
        for lesson in random.sample(lessons, k=min(len(lessons), len(lessons) // 2)): # Заполняем для половины уроков
            journal_entry = LessonJournalEntry.objects.create(
                lesson=lesson,
                topic_covered=fake.sentence(nb_words=random.randint(4,8)).capitalize()[:-1],
                teacher_notes=fake.paragraph(nb_sentences=random.randint(1,2)) if random.random() < 0.3 else ""
            )
            
            # Домашнее задание (для некоторых уроков)
            if random.random() < 0.7: # 70% уроков с ДЗ
                for _ in range(random.randint(1, MAX_HOMEWORKS_PER_JOURNAL_ENTRY)):
                    hw = Homework.objects.create(
                        journal_entry=journal_entry,
                        title=f"ДЗ: {fake.catch_phrase()}",
                        description=fake.paragraph(nb_sentences=random.randint(2,4)),
                        due_date=lesson.start_time + timedelta(days=random.randint(2,7), hours=random.randint(9,18)),
                        author=lesson.teacher
                    )
                    # Прикрепляем файлы к ДЗ
                    if random.random() < 0.5:
                        for _ in range(random.randint(1,2)):
                            HomeworkAttachment.objects.create(
                                homework=hw,
                                #file=f"homework_attachments/temp/{fake.file_name(category='document')}", # Заглушка для пути
                                description=fake.sentence(nb_words=3)
                            )
            
            # Посещаемость и Оценки
            for student in lesson.student_group.students.all():
                # Посещаемость
                att_status = random.choices(
                    [s[0] for s in Attendance.Status.choices], 
                    weights=[0.85, 0.05, 0.05, 0.05, 0.00] # P, V, N, L, R
                )[0]
                Attendance.objects.create(
                    journal_entry=journal_entry,
                    student=student,
                    status=att_status,
                    comment=fake.sentence(nb_words=3) if att_status != Attendance.Status.PRESENT and random.random() < 0.5 else "",
                    marked_by=lesson.teacher
                )
                
                # Оценки (несколько случайных оценок за урок)
                if random.random() < 0.6: # 60% студентов получают оценки
                    for _ in range(random.randint(1, MAX_GRADES_PER_LESSON_FOR_STUDENT)):
                        grade_val = str(random.randint(3,5)) if random.random() > 0.1 else random.choice(["2", "Н/А"])
                        numeric_val = float(grade_val) if grade_val.isdigit() else (5.0 if grade_val=="Зач" else None)
                        Grade.objects.create(
                            student=student,
                            subject=lesson.subject,
                            study_period=lesson.study_period,
                            lesson=lesson,
                            grade_value=grade_val,
                            numeric_value=numeric_val,
                            grade_type=random.choice([gt[0] for gt in Grade.GradeType.choices if gt[0] not in [Grade.GradeType.PERIOD_AVERAGE, Grade.GradeType.PERIOD_FINAL, Grade.GradeType.YEAR_AVERAGE, Grade.GradeType.YEAR_FINAL]]),
                            date_given=lesson.start_time.date(),
                            graded_by=lesson.teacher,
                            weight=random.choice([1,1,1,2]) # Некоторые оценки весомее
                        )
        
        # --- 6. Библиотека Материалов ---
        self.stdout.write('Creating subject materials...')
        for subject_instance in subjects:
            for _ in range(random.randint(0, MAX_SUBJECT_MATERIALS_PER_SUBJECT)):
                # Материал для всех групп или для случайной группы
                target_group = random.choice(student_groups + [None]) if student_groups and random.random() < 0.5 else None
                SubjectMaterial.objects.create(
                    subject=subject_instance,
                    student_group=target_group,
                    title=f"Материал по {subject_instance.name}: {fake.bs()}",
                    description=fake.paragraph(nb_sentences=2),
                    #file=f"subject_materials/temp/{fake.file_name(category='presentation')}", # Заглушка
                    uploaded_by=random.choice(teachers) if teachers else None
                )

        # --- 7. Создание Чатов (на основе созданных групп) ---
        self.stdout.write('Creating group chats...')
        # Сигнал create_or_update_group_chat_on_save должен был уже сработать при создании/обновлении StudentGroup.
        # Если сигнал не используется или нужно создать чаты принудительно:
        for group in StudentGroup.objects.filter(curator__isnull=False).prefetch_related('students'):
            if group.curator:
                chat_name = f"Чат группы: {group.name}"
                # Проверяем, нет ли уже чата (упрощенная проверка)
                if not Chat.objects.filter(name=chat_name, chat_type=Chat.ChatType.GROUP, created_by=group.curator).exists():
                    chat = Chat.objects.create(
                        name=chat_name,
                        chat_type=Chat.ChatType.GROUP,
                        created_by=group.curator
                    )
                    participants_to_add = [group.curator] + list(group.students.all())
                    chat_participants_objs = [ChatParticipant(chat=chat, user=p) for p in set(participants_to_add)]
                    ChatParticipant.objects.bulk_create(chat_participants_objs, ignore_conflicts=True)
                    self.stdout.write(f"Created chat for group {group.name}")

                    # Добавим несколько сообщений в чат
                    chat_participants_users = list(chat.participants.all())
                    if chat_participants_users:
                        for _ in range(random.randint(3, MAX_MESSAGES_PER_CHAT)):
                            sender = random.choice(chat_participants_users)
                            Message.objects.create(
                                chat=chat,
                                sender=sender,
                                content=fake.sentence(nb_words=random.randint(5, 20))
                            )


        self.stdout.write(self.style.SUCCESS('Database populated successfully!'))

    def _clear_data(self):
        """Очищает все данные из моделей этого приложения и связанных."""
        # ВАЖНО: Соблюдать порядок удаления из-за ForeignKey constraints!
        # Сначала модели, на которые никто не ссылается или которые можно удалить каскадно.
        Grade.objects.all().delete()
        Attendance.objects.all().delete()
        SubmissionAttachment.objects.all().delete() # Перед HomeworkSubmission
        HomeworkSubmission.objects.all().delete()   # Перед HomeworkAttachment и Homework
        HomeworkAttachment.objects.all().delete()   # Перед Homework
        Homework.objects.all().delete()             # Перед LessonJournalEntry
        LessonJournalEntry.objects.all().delete()   # Перед Lesson
        SubjectMaterial.objects.all().delete()
        Lesson.objects.all().delete()               # Перед CurriculumEntry
        CurriculumEntry.objects.all().delete()      # Перед Curriculum
        Curriculum.objects.all().delete()
        # Чаты
        Message.objects.all().delete()              # Перед ChatParticipant и Chat
        ChatParticipant.objects.all().delete()      # Перед Chat
        Chat.objects.all().delete()                 # 
        # Базовые
        StudentGroup.objects.all().delete()         # Перед User (если есть связи M2M)
        Classroom.objects.all().delete()
        Subject.objects.all().delete()              # Перед SubjectType (если есть PROTECT)
        SubjectType.objects.all().delete()
        StudyPeriod.objects.all().delete()          # Перед AcademicYear
        AcademicYear.objects.all().delete()
        # Пользователи (удаляем всех, кроме суперпользователей, если нужно их оставить)
        User.objects.filter(is_superuser=False).delete()
        Profile.objects.all().delete() # Профили удалятся каскадно с User, но на всякий случай
        InvitationCode.objects.all().delete()
        # Если есть другие приложения, их модели тоже нужно очищать
        # Например, из notifications, forum, news

    def _create_user(self, email_prefix_or_email, role, is_active=False, is_role_confirmed=False, password="password123"):
        """Вспомогательная функция для создания пользователя."""
        if "@" in email_prefix_or_email:
            email = email_prefix_or_email
        else:
            email = f"{email_prefix_or_email}_{fake.unique.user_name()}@example.com"
        
        try:
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                patronymic=fake.middle_name() if random.random() < 0.7 else "",
                role=role,
                is_active=is_active,
                is_role_confirmed=is_role_confirmed
            )
            # Профиль создается автоматически в CustomUserManager.create_user
            # Настройки уведомлений создаются сигналом
            return user
        except Exception as e: # Ловим возможные ошибки уникальности email от Faker
            print(f"Could not create user {email}: {e}")
            # Попробуем еще раз с другим email
            email = f"{email_prefix_or_email}_{fake.unique.user_name()}_{random.randint(100,999)}@example.com"
            try:
                user = User.objects.create_user(
                    email=email, password=password, first_name=fake.first_name(), last_name=fake.last_name(),
                    patronymic=fake.middle_name() if random.random() < 0.7 else "", role=role,
                    is_active=is_active, is_role_confirmed=is_role_confirmed
                )
                return user
            except Exception as e2:
                print(f"Still could not create user {email}: {e2}")
                return None


    def _create_users(self, count, role, **kwargs):
        """Создает указанное количество пользователей с заданной ролью."""
        users = []
        for i in range(count):
            prefix = f"{role.lower()}{i+1}"
            user = self._create_user(prefix, role, **kwargs)
            if user:
                users.append(user)
        return users