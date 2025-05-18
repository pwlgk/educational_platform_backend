import random
from datetime import timedelta, time, date as py_date # Переименуем, чтобы не конфликтовать с models.date
import logging

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError, models
from django.utils import timezone
from django.utils.text import slugify
from faker import Faker
from django.core.exceptions import ValidationError as DjangoValidationError

# Импортируем модели
from users.models import Profile
from schedule.models import Subject, StudentGroup, Classroom, Lesson
from news.models import NewsCategory, NewsArticle, NewsComment, Reaction as NewsReaction
from messaging.models import Chat, Message, ChatParticipant
from forum.models import ForumCategory, ForumTopic, ForumPost, ForumReaction as ForumForumReaction
from notifications.models import Notification # Если будем генерировать
from academics.models import AcademicYear, AcademicPeriod, StudyPlan, StudyPlanItem, Grade, Attendance
# Модели тестирования УДАЛЕНЫ

User = get_user_model()
fake = Faker('ru_RU')
logger = logging.getLogger(__name__) # Используем стандартный логгер

# Константы для генерации
MAX_COMMENTS_PER_NEWS = 3
MAX_POSTS_PER_TOPIC = 8
MAX_MESSAGES_PER_CHAT = 15
LIKES_RATIO = 0.2
REPLIES_RATIO = 0.3
WORK_START_HOUR = 8
WORK_END_HOUR = 18
MAX_REPLIES_PER_COMMENT = 5

class Command(BaseCommand):
    help = 'Заполняет базу данных тестовыми данными (без модуля Тестирования).'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Удалить существующие данные (кроме суперпользователей) перед заполнением.')
        parser.add_argument('--password', type=str, default='testpass123', help='Пароль для всех созданных пользователей.')
        parser.add_argument('--num-students', type=int, default=30, help='Количество студентов.')
        parser.add_argument('--num-teachers', type=int, default=8, help='Количество преподавателей.')
        parser.add_argument('--num-parents', type=int, default=20, help='Количество родителей.')
        parser.add_argument('--num-subjects', type=int, default=10, help='Количество предметов.')
        parser.add_argument('--num-groups', type=int, default=3, help='Количество групп.')
        parser.add_argument('--num-classrooms', type=int, default=5, help='Количество аудиторий.')
        parser.add_argument('--days-range', type=int, default=30, help='Диапазон дней (+/-) для генерации расписания.')
        parser.add_argument('--lessons-per-group-day', type=int, default=2, help='Среднее кол-во уроков у группы в день.')
        parser.add_argument('--num-news-categories', type=int, default=3, help='Количество категорий новостей.')
        parser.add_argument('--num-news-articles', type=int, default=15, help='Количество новостей.')
        parser.add_argument('--num-forum-categories', type=int, default=3, help='Количество категорий форума.')
        parser.add_argument('--num-forum-topics', type=int, default=10, help='Количество тем форума.')
        parser.add_argument('--num-private-chats', type=int, default=20, help='Количество личных чатов.')
        parser.add_argument('--num-academic-years', type=int, default=2, help='Количество учебных годов.')
        parser.add_argument('--study-plans-per-group', type=int, default=1, help='Кол-во планов на группу за УЧЕБНЫЙ ГОД.')
        parser.add_argument('--items-per-study-plan', type=int, default=5, help='Предметов в учебном плане.')
        parser.add_argument('--grades-per-lesson-student', type=int, default=1, help='Макс. текущих оценок за урок.')

    @transaction.atomic
    def handle(self, *args, **options):
        s = self.style.SUCCESS
        w = self.style.WARNING
        e = self.style.ERROR
        start_time_total = timezone.now()

        if options['clear']:
            self.clear_database()
        password = options['password']

        self.stdout.write(s('--- 1. Пользователи и Профили ---'))
        st_time = timezone.now()
        students, teachers, parents, admins = self.create_users(options['num_students'], options['num_teachers'], options['num_parents'], password)
        all_users = students + teachers + parents + admins
        creators = teachers + admins
        self.fill_profiles(all_users)
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        if not creators and (options['num_news_articles'] > 0 or options['num_forum_topics'] > 0):
             self.stderr.write(e('! Нет создателей контента (учителей/админов).'))

        self.stdout.write(s('\n--- 2. База Расписания (Предметы, Аудитории, Группы) ---'))
        st_time = timezone.now()
        subjects, classrooms, groups = self.create_schedule_base(options['num_subjects'], options['num_classrooms'], options['num_groups'], teachers, students)
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s('\n--- 3. Учебные Годы и Периоды (Academics) ---'))
        st_time = timezone.now()
        academic_years = self.create_academic_years(options['num_academic_years'])
        academic_periods = []
        if academic_years:
            academic_periods = self.create_academic_periods_for_years(academic_years)
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s('\n--- 4. Учебные Планы и Элементы (Academics) ---'))
        st_time = timezone.now()
        study_plans, study_plan_items = [], []
        if groups and subjects and academic_years and creators and academic_periods : # Нужны academic_periods для StudyPlanItem.control_period
            study_plans, study_plan_items = self.create_study_plans_and_items(
                groups, academic_years, subjects, teachers, # Передаем teachers для StudyPlanItem.teacher
                options['study_plans_per_group'],
                options['items_per_study_plan'],
                academic_periods # Для StudyPlanItem.control_period
            )
        else: self.stdout.write(w('! Пропуск учебных планов: нет групп, предметов, учебных годов, создателей или периодов.'))
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s('\n--- 5. Занятия (Schedule) ---'))
        st_time = timezone.now()
        lessons = []
        if groups and classrooms and subjects and teachers and creators:
            lessons = self.create_lessons(
                options['lessons_per_group_day'], options['days_range'],
                groups, teachers, classrooms, subjects, creators, study_plan_items
            )
        else: self.stdout.write(w('! Пропуск занятий: нет полной базы расписания или создателей.'))
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s('\n--- 6. Оценки и Посещаемость (Academics) ---'))
        st_time = timezone.now()
        if lessons and students and teachers and academic_periods and (subjects or study_plan_items):
            self.create_grades_and_attendance(
                lessons, students, teachers, study_plan_items, academic_periods, subjects, options['grades_per_lesson_student']
            )
        else: self.stdout.write(w('! Пропуск оценок/посещаемости: нет уроков, студентов, учителей или периодов/предметов.'))
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        # --- Модуль Тестирования УДАЛЕН ---

        self.stdout.write(s('\n--- 7. Новости ---'))
        st_time = timezone.now()
        news_categories, news_articles = self.create_news(options['num_news_categories'], options['num_news_articles'], creators)
        if news_articles and all_users: self.create_news_comments_and_reactions(news_articles, all_users)
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s('\n--- 8. Форум ---'))
        st_time = timezone.now()
        forum_categories, forum_topics, forum_posts = self.create_forum(options['num_forum_categories'], options['num_forum_topics'], all_users, creators)
        if forum_posts and all_users: self.create_forum_reactions(forum_posts, all_users)
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s('\n--- 9. Чаты и Сообщения (Messaging) ---'))
        st_time = timezone.now()
        self.create_chats_and_messages(options['num_private_chats'], groups, all_users)
        self.stdout.write(f"Время: {timezone.now() - st_time}")

        self.stdout.write(s(f'\n--- Генерация тестовых данных завершена! Общее время: {timezone.now() - start_time_total} ---'))

    def clear_database(self):
        self.stdout.write(self.style.WARNING('Очистка существующих данных (кроме суперпользователей)...'))
        # Порядок важен из-за ForeignKey constraints

        # Testing - УДАЛЕНО
        # StudentAnswer.objects.all().delete()
        # TestAttempt.objects.all().delete()
        # TestAssignment.objects.all().delete()
        # AnswerOption.objects.all().delete()
        # Question.objects.all().delete()
        # Test.objects.all().delete()

        # Academics
        Grade.objects.all().delete()
        Attendance.objects.all().delete()
        StudyPlanItem.objects.all().delete()
        StudyPlan.objects.all().delete()
        AcademicPeriod.objects.all().delete()
        AcademicYear.objects.all().delete()

        # Notifications
        Notification.objects.all().delete()

        # Messaging
        Message.objects.all().delete()
        ChatParticipant.objects.all().delete()
        Chat.objects.all().delete()

        # Forum
        ForumForumReaction.objects.all().delete()
        ForumPost.objects.all().delete()
        ForumTopic.objects.all().delete()
        ForumCategory.objects.all().delete()

        # News
        NewsReaction.objects.all().delete()
        NewsComment.objects.all().delete()
        NewsArticle.objects.all().delete()
        NewsCategory.objects.all().delete()

        # Schedule
        Lesson.objects.all().delete()
        StudentGroup.objects.all().delete() # Зависит от User, удаляем до User, если есть M2M
        Classroom.objects.all().delete()
        Subject.objects.all().delete()

        # Users (Profile удалится каскадно при удалении User)
        # InvitationCode удалится каскадно при удалении User (created_by) или установит used_by=NULL
        # Проверяем, что UserNotificationSettings удалится каскадно (OneToOne)
        users_to_delete = User.objects.filter(is_superuser=False)
        deleted_users_count = users_to_delete.count()
        # Сначала удаляем связи ManyToMany, если они не каскадные
        for user_obj_del in users_to_delete:
            user_obj_del.student_groups.clear() # M2M в StudentGroup
            user_obj_del.parents.clear()        # M2M в User (если Student)
            user_obj_del.children.clear()       # M2M в User (если Parent, обратная связь)
        users_to_delete.delete() # Теперь можно удалять самих пользователей
        self.stdout.write(f'  - Удалено {deleted_users_count} пользователей (не суперпользователей).')

        self.stdout.write(self.style.SUCCESS('Данные очищены (кроме суперпользователей).'))


    def _get_fake_name(self):
        # ... (код без изменений) ...
        if random.random() < 0.5:
            return fake.first_name_male(), fake.last_name_male(), fake.middle_name_male()
        else:
            return fake.first_name_female(), fake.last_name_female(), fake.middle_name_female()

    def create_users(self, num_students, num_teachers, num_parents, password):
        # ... (логика создания s, t, p_list, a без изменений) ...
        students_list, teachers_list, parents_list, admins_list = [], [], [], list(User.objects.filter(is_superuser=True))
        roles_map = {
            User.Role.TEACHER: (teachers_list, num_teachers, "учителя"),
            User.Role.STUDENT: (students_list, num_students, "студента"),
            User.Role.PARENT: (parents_list, num_parents, "родителя"),
        }
        all_created_users = []

        for role_value, (target_list, num_to_create, role_name_gen) in roles_map.items():
            for i in range(num_to_create):
                email_prefix = role_value.lower().replace('_', '')
                email = f'{email_prefix}{i+1}@example.test'
                user_obj = User.objects.filter(email=email).first()
                if user_obj:
                    if user_obj.role != role_value: # Обновляем роль, если отличается
                        user_obj.role = role_value
                        user_obj.set_password(password) # Сбрасываем пароль
                        user_obj.is_active = True
                        user_obj.is_role_confirmed = True
                        # Обновляем ФИО, если нужно
                        first_name, last_name, patronymic = self._get_fake_name()
                        user_obj.first_name = first_name
                        user_obj.last_name = last_name
                        user_obj.patronymic = patronymic
                        user_obj.save()
                    target_list.append(user_obj)
                    all_created_users.append(user_obj)
                    self.stdout.write(f'  * Найден/Обновлен {role_value.label}: {email}')
                    continue

                first_name, last_name, patronymic = self._get_fake_name()
                try:
                    user_obj = User.objects.create_user(
                        email=email, password=password, first_name=first_name, last_name=last_name, patronymic=patronymic,
                        role=role_value, is_active=True, is_role_confirmed=True # Активируем сразу
                    )
                    target_list.append(user_obj)
                    all_created_users.append(user_obj)
                    self.stdout.write(f'  + {role_value.label}: {email}')
                except Exception as e_user:
                    self.stderr.write(self.style.WARNING(f'  ! Не удалось создать {role_name_gen} {email}: {e_user}'))

        # Связываем родителей и детей
        if students_list and parents_list:
            for student_obj_rel in students_list:
                # У студента может быть 0, 1 или 2 родителя из списка
                num_student_parents = random.choices([0, 1, 2], weights=[0.3, 0.5, 0.2], k=1)[0]
                if num_student_parents > 0 and not student_obj_rel.parents.exists():
                    # Выбираем родителей, у которых еще не максимальное кол-во детей (упрощенно - не более 2)
                    available_parents = [p for p in parents_list if p.children.count() < 2]
                    if available_parents:
                        chosen_parents_rel = random.sample(available_parents, k=min(num_student_parents, len(available_parents)))
                        student_obj_rel.parents.set(chosen_parents_rel)
                        self.stdout.write(f'    Студенту {student_obj_rel.email} назначены родители: {[p.email for p in chosen_parents_rel]}')

        return students_list, teachers_list, parents_list, admins_list


    def fill_profiles(self, all_users):
        # ... (код без изменений) ...
        self.stdout.write('  Заполнение профилей пользователей...')
        count = 0
        for user_obj in all_users:
            try:
                # Profile создается автоматически сигналом или в create_user
                profile, created = Profile.objects.get_or_create(user=user_obj)
                # Заполняем только если поля пустые или для только что созданного
                if created or not profile.phone_number:
                    profile.phone_number = fake.phone_number() if random.random() < 0.8 else ""
                    profile.bio = fake.paragraph(nb_sentences=random.randint(1,3)) if random.random() < 0.5 else ""
                    min_age = 7 if user_obj.role == User.Role.STUDENT else 22
                    max_age = 17 if user_obj.role == User.Role.STUDENT else 65
                    profile.date_of_birth = fake.date_of_birth(minimum_age=min_age, maximum_age=max_age) if random.random() < 0.7 else None
                    profile.save()
                    count +=1
            except Exception as e_profile:
                 self.stderr.write(self.style.WARNING(f'   ! Ошибка сохранения профиля для {user_obj.email}: {e_profile}'))
        self.stdout.write(f'  + Профили заполнены/обновлены для {count} пользователей.')


    def create_schedule_base(self, num_subjects, num_classrooms, num_groups, teachers, students):
        # ... (код для subjects и classrooms без изменений) ...
        subjects_list = []
        # ... (код генерации subjects_list)
        subject_names_pool = ["Алгебра", "Геометрия", "Русский язык", "Литература", "История России", "Всеобщая история", "Обществознание", "География мира", "Биология общая", "Химия неорганическая", "Физика механика", "Информатика и ИКТ", "Английский язык (базовый)", "Немецкий язык (начальный)", "Физическая культура", "Музыкальная грамота", "Основы ИЗО", "Технология (труд)", "Основы Безопасности Жизнедеятельности", "Введение в экономику"]
        random.shuffle(subject_names_pool)
        for i in range(num_subjects):
            name = subject_names_pool[i % len(subject_names_pool)]
            if num_subjects > len(subject_names_pool) and i >= len(subject_names_pool): name += f" (Уровень {i // len(subject_names_pool) + 1})"
            try:
                s_obj, _ = Subject.objects.get_or_create(name=name, defaults={'description': fake.bs()})
                subjects_list.append(s_obj)
            except IntegrityError: pass
        self.stdout.write(f'  + Создано/найдено {len(subjects_list)} предметов.')

        classrooms_list = []
        for i in range(num_classrooms):
             identifier_cr=f"{random.randint(1, 4)}{str(i+1).zfill(2)}{random.choice(['', 'каб', ' ауд'])}"
             try:
                 c_obj, _ = Classroom.objects.get_or_create(
                     identifier=identifier_cr,
                     defaults={'capacity': random.choice([15, 20, 25, 30]), 'type': random.choice(Classroom.ClassroomType.values)}
                 )
                 classrooms_list.append(c_obj)
             except IntegrityError: pass
        self.stdout.write(f'  + Создано/найдено {len(classrooms_list)} аудиторий.')


        groups_list = []
        if not students or num_groups <= 0 or not teachers:
            self.stdout.write(self.style.WARNING('  ! Недостаточно данных для создания групп (нет студентов, учителей или num_groups=0).'))
            return subjects_list, classrooms_list, groups_list

        students_per_group_approx = len(students) // num_groups if num_groups > 0 else len(students)
        student_list_copy_grp = list(students) # Копируем список для извлечения
        random.shuffle(student_list_copy_grp)

        for i in range(num_groups):
            current_year_digit = timezone.now().year % 100 # 23 для 2023
            group_name_str = f"{random.randint(1,11)}-{chr(ord('А') + i)}-{current_year_digit}" # Пример: 9-А-23
            curator_grp = random.choice(teachers) if teachers else None
            try:
                group_obj, created_grp = StudentGroup.objects.get_or_create(name=group_name_str, defaults={'curator': curator_grp})
                groups_list.append(group_obj)

                if created_grp or not group_obj.students.exists(): # Заполняем студентов только для новых или пустых групп
                    assigned_students_for_this_group = []
                    # Распределяем студентов по группам
                    num_to_assign_grp = students_per_group_approx
                    if i == num_groups - 1: # Последней группе достаются все оставшиеся
                        num_to_assign_grp = len(student_list_copy_grp)

                    for _ in range(min(num_to_assign_grp, len(student_list_copy_grp))):
                        if not student_list_copy_grp: break # Если студенты закончились
                        student_to_assign_grp = student_list_copy_grp.pop(0)
                        assigned_students_for_this_group.append(student_to_assign_grp)

                    if assigned_students_for_this_group:
                        group_obj.students.set(assigned_students_for_this_group)
                        self.stdout.write(f'  + Группа: {group_name_str} ({len(assigned_students_for_this_group)} студ.) куратор: {curator_grp.email if curator_grp else "Нет"}')
                    elif created_grp:
                         self.stdout.write(f'  + Группа: {group_name_str} (0 студ.) куратор: {curator_grp.email if curator_grp else "Нет"}')
                else:
                     self.stdout.write(f'  * Найдена группа: {group_name_str} ({group_obj.students.count()} студ.)')

            except IntegrityError:
                 self.stderr.write(self.style.WARNING(f'  ! Группа с именем {group_name_str} уже существует (IntegrityError), пропуск.'))
            except Exception as e_grp:
                 self.stderr.write(self.style.WARNING(f'  ! Ошибка создания/заполнения группы {group_name_str}: {e_grp}'))
        return subjects_list, classrooms_list, groups_list

    def create_academic_years(self, num_years_option):
        self.stdout.write('  Создание учебных годов...')
        created_years = []
        current_calendar_year = timezone.now().year
        # Рассчитываем смещение так, чтобы текущий календарный год был примерно в середине диапазона
        start_year_offset = - (num_years_option // 2)
        # Если четное количество лет и сейчас вторая половина года, смещаем назад, чтобы текущий учебный год попал
        if num_years_option > 0 and num_years_option % 2 == 0 and timezone.now().month >= 9:
            start_year_offset -=1

        for i in range(max(1, num_years_option)): # Хотя бы 1 год, если параметр 0
            year_start_calendar = current_calendar_year + start_year_offset + i
            year_name = f"{year_start_calendar}/{year_start_calendar + 1}"
            start_date = py_date(year_start_calendar, 9, 1) # Учебный год с 1 сентября
            end_date = py_date(year_start_calendar + 1, 8, 31) # До конца августа следующего года

            # Определяем, является ли этот год текущим
            # Текущий учебный год: если сейчас между 1 сентября этого года и 31 августа следующего
            now = timezone.now().date()
            is_current_year = (start_date <= now <= end_date)

            try:
                # Если уже есть текущий год, новый не делаем текущим
                if is_current_year and AcademicYear.objects.filter(is_current=True).exclude(name=year_name).exists():
                    is_current_year = False

                year_obj, created = AcademicYear.objects.get_or_create(
                    name=year_name,
                    defaults={'start_date': start_date, 'end_date': end_date, 'is_current': is_current_year}
                )
                if not created and year_obj.is_current != is_current_year: # Обновляем is_current, если нужно
                    if is_current_year and AcademicYear.objects.filter(is_current=True).exclude(pk=year_obj.pk).exists():
                        pass # Не меняем, если уже есть другой текущий
                    else:
                        year_obj.is_current = is_current_year
                        year_obj.save()

                created_years.append(year_obj)
                if created: self.stdout.write(f'    + Учебный год: {year_name} (Текущий: {is_current_year})')
            except IntegrityError:
                self.stderr.write(self.style.WARNING(f'    ! Учебный год {year_name} уже существует.'))
            except DjangoValidationError as e_val:
                self.stderr.write(self.style.ERROR(f'    ! Ошибка валидации для года {year_name}: {e_val}'))
            except Exception as e_ay:
                self.stderr.write(self.style.ERROR(f'    ! Ошибка создания учебного года {year_name}: {e_ay}'))
        self.stdout.write(f'  + Создано/найдено {len(created_years)} учебных годов.')
        return created_years

    def create_academic_periods_for_years(self, academic_years):
        self.stdout.write('  Создание учебных периодов (четверти/семестры)...')
        created_periods = []
        for year_obj in academic_years:
            # Создаем семестры
            s1_name = f"1 Семестр {year_obj.name}"
            s1_start = year_obj.start_date
            # Примерная середина учебного года для конца 1 семестра
            s1_end = py_date(year_obj.start_date.year, 12, 31)
            s1, _ = AcademicPeriod.objects.get_or_create(
                academic_year=year_obj, period_type=AcademicPeriod.PeriodType.SEMESTER, order=1,
                defaults={'name': s1_name, 'start_date': s1_start, 'end_date': s1_end}
            )
            created_periods.append(s1)

            s2_name = f"2 Семестр {year_obj.name}"
            s2_start = py_date(year_obj.end_date.year, 1, 1) # C начала календарного года
            s2_end = year_obj.end_date # До конца учебного года
            s2, _ = AcademicPeriod.objects.get_or_create(
                academic_year=year_obj, period_type=AcademicPeriod.PeriodType.SEMESTER, order=2,
                defaults={'name': s2_name, 'start_date': s2_start, 'end_date': s2_end}
            )
            created_periods.append(s2)

            # Создаем четверти (примерно)
            q1_name = f"1 Четверть {year_obj.name}"
            q1_start = s1_start
            q1_end = py_date(s1_start.year, 10, 31) # Конец октября
            q1, _ = AcademicPeriod.objects.get_or_create(academic_year=year_obj, period_type=AcademicPeriod.PeriodType.QUARTER, order=1, defaults={'name': q1_name, 'start_date': q1_start, 'end_date': q1_end})
            created_periods.append(q1)

            q2_name = f"2 Четверть {year_obj.name}"
            q2_start = py_date(s1_start.year, 11, 1) # Начало ноября
            q2_end = s1_end # Конец 1 семестра
            q2, _ = AcademicPeriod.objects.get_or_create(academic_year=year_obj, period_type=AcademicPeriod.PeriodType.QUARTER, order=2, defaults={'name': q2_name, 'start_date': q2_start, 'end_date': q2_end})
            created_periods.append(q2)

            q3_name = f"3 Четверть {year_obj.name}"
            q3_start = s2_start # Начало 2 семестра
            q3_end = py_date(s2_start.year, 3, round(31/2)) # Середина марта
            q3, _ = AcademicPeriod.objects.get_or_create(academic_year=year_obj, period_type=AcademicPeriod.PeriodType.QUARTER, order=3, defaults={'name': q3_name, 'start_date': q3_start, 'end_date': q3_end})
            created_periods.append(q3)

            q4_name = f"4 Четверть {year_obj.name}"
            q4_start = py_date(s2_start.year, 3, round(31/2)+1) # После середины марта
            q4_end = s2_end # Конец 2 семестра / года
            q4, _ = AcademicPeriod.objects.get_or_create(academic_year=year_obj, period_type=AcademicPeriod.PeriodType.QUARTER, order=4, defaults={'name': q4_name, 'start_date': q4_start, 'end_date': q4_end})
            created_periods.append(q4)

            # Создаем годовой период
            year_period_name = f"Учебный год {year_obj.name}"
            yp, _ = AcademicPeriod.objects.get_or_create(
                academic_year=year_obj, period_type=AcademicPeriod.PeriodType.YEAR, order=1,
                defaults={'name': year_period_name, 'start_date': year_obj.start_date, 'end_date': year_obj.end_date}
            )
            created_periods.append(yp)

        self.stdout.write(f'  + Создано/найдено {len(set(created_periods))} учебных периодов.')
        return list(set(created_periods))


    def create_study_plans_and_items(self, groups, academic_years, subjects, teachers, plans_per_group_year, items_per_plan, all_academic_periods):
        self.stdout.write('  Создание учебных планов и элементов...')
        study_plans_list, study_plan_items_list = [], []
        if not academic_years or not groups or not subjects or not teachers or not all_academic_periods:
            self.stdout.write(self.style.WARNING('  ! Недостаточно данных для учебных планов.'))
            return [], []

        for group_obj_sp in groups:
            for year_obj_sp in random.sample(academic_years, k=min(len(academic_years), plans_per_group_year)):
                plan_name = f"УП {group_obj_sp.name} ({year_obj_sp.name})"
                try:
                    # План создается на весь учебный год
                    plan_obj, created_plan = StudyPlan.objects.get_or_create(
                        group=group_obj_sp,
                        academic_year=year_obj_sp,
                        defaults={'name': plan_name, 'is_active': year_obj_sp.is_current}
                    )
                    if not created_plan and plan_obj.name != plan_name : plan_obj.name = plan_name; plan_obj.save()
                    study_plans_list.append(plan_obj)

                    if created_plan or not plan_obj.items.exists():
                        num_items_to_create = random.randint(max(1, items_per_plan - 2), items_per_plan + 2)
                        chosen_subjects_for_plan = random.sample(subjects, k=min(len(subjects), num_items_to_create))

                        for order_idx, subject_sp_item in enumerate(chosen_subjects_for_plan):
                            # Период контроля выбирается из семестров или годового периода этого учебного года
                            possible_control_periods = [
                                p for p in all_academic_periods if p.academic_year == year_obj_sp and \
                                (p.period_type == AcademicPeriod.PeriodType.SEMESTER or \
                                 (p.period_type == AcademicPeriod.PeriodType.YEAR and \
                                  random.choice([StudyPlanItem.ControlType.EXAM, StudyPlanItem.ControlType.CREDIT, StudyPlanItem.ControlType.PASS_FAIL_CREDIT]) # Годовой контроль
                                  ))
                            ]
                            control_period_spi = random.choice(possible_control_periods) if possible_control_periods else None
                            teacher_spi = random.choice(teachers) if teachers else None

                            item_data_sp = {
                                'subject': subject_sp_item,
                                'teacher': teacher_spi,
                                'hours_total': random.randint(30, 120),
                                'hours_lecture': random.randint(10, 40),
                                'hours_practice': random.randint(10, 60),
                                'control_type': random.choice(StudyPlanItem.ControlType.values),
                                'control_period': control_period_spi,
                            }
                            try:
                                item_obj, _ = StudyPlanItem.objects.update_or_create(
                                    study_plan=plan_obj,
                                    subject=subject_sp_item,
                                    defaults=item_data_sp
                                )
                                study_plan_items_list.append(item_obj)
                            except IntegrityError: pass # Если такой элемент уже есть
                            except Exception as e_spi: self.stderr.write(self.style.WARNING(f'    ! Ошибка элемента плана: {e_spi} для {plan_obj.name} - {subject_sp_item.name}'))
                except IntegrityError: pass
                except Exception as e_sp: self.stderr.write(self.style.WARNING(f'   ! Ошибка уч. плана для {group_obj_sp.name} на {year_obj_sp.name}: {e_sp}'))
        self.stdout.write(f'  + Создано/найдено {len(set(study_plans_list))} учебных планов и {len(set(study_plan_items_list))} элементов.')
        return list(set(study_plans_list)), list(set(study_plan_items_list))


    def create_lessons(self, lessons_per_group_day, days_range, groups, teachers, classrooms, subjects, creators, study_plan_items=None):
        self.stdout.write(f'  Создание занятий (в среднем {lessons_per_group_day} на группу в день)...')
        created_lessons_list, lessons_count = [], 0
        now_date = timezone.now().date()
        # Определяем общий диапазон дат на основе учебных годов
        min_year_start = AcademicYear.objects.aggregate(min_date=models.Min('start_date'))['min_date']
        max_year_end = AcademicYear.objects.aggregate(max_date=models.Max('end_date'))['max_date']

        # Если нет учебных годов, используем days_range от текущей даты
        if not min_year_start or not max_year_end:
            min_dt_range = now_date - timedelta(days=days_range)
            max_dt_range = now_date + timedelta(days=days_range)
            self.stdout.write(self.style.WARNING(f'  ! Нет учебных годов, генерируем уроки в диапазоне {min_dt_range} - {max_dt_range}'))
        else:
            min_dt_range = min_year_start
            max_dt_range = max_year_end
            self.stdout.write(f'  Генерация уроков в диапазоне учебных годов: {min_dt_range} - {max_dt_range}')

        current_iter_date = min_dt_range

        # Создаем карту StudyPlanItems для быстрого доступа
        # Ключ: (group_id, subject_id, academic_year_id) -> study_plan_item
        spi_map_lessons = {}
        if study_plan_items:
            for spi_item_lesson in study_plan_items:
                key_lesson = (
                    spi_item_lesson.study_plan.group_id,
                    spi_item_lesson.subject_id,
                    spi_item_lesson.study_plan.academic_year_id
                )
                spi_map_lessons[key_lesson] = spi_item_lesson # Один spi на группу, предмет, год

        while current_iter_date <= max_dt_range:
            if current_iter_date.weekday() >= 5: # Пропускаем Сб, Вс
                current_iter_date += timedelta(days=1)
                continue

            # Определяем текущий учебный год для этой даты
            current_academic_year = AcademicYear.objects.filter(start_date__lte=current_iter_date, end_date__gte=current_iter_date).first()
            if not current_academic_year:
                current_iter_date += timedelta(days=1)
                continue # Дата не попадает ни в один учебный год

            for group_lesson in groups:
                # Пытаемся найти учебный план для этой группы и текущего учебного года
                active_study_plan = StudyPlan.objects.filter(group=group_lesson, academic_year=current_academic_year, is_active=True).first()
                if not active_study_plan:
                    continue # Нет активного плана для этой группы в этом году

                # Берем предметы и преподавателей из активного учебного плана
                items_for_group_plan = list(active_study_plan.items.select_related('subject', 'teacher').all())
                if not items_for_group_plan:
                    continue

                time_slots_lesson = [(time(8,0),time(8,45)),(time(8,55),time(9,40)),(time(9,50),time(10,35)),(time(10,55),time(11,40)),(time(12,0),time(12,45)),(time(12,55),time(13,40)),(time(14,0),time(14,45)),(time(14,55),time(15,40))]
                random.shuffle(time_slots_lesson)
                lessons_today_for_group_count = 0

                for start_time_slot, end_time_slot in time_slots_lesson:
                    if lessons_today_for_group_count >= lessons_per_group_day:
                        break
                    if random.random() > 0.75: # Не каждый слот будет занят
                        continue

                    chosen_spi = random.choice(items_for_group_plan)
                    lesson_subject_obj = chosen_spi.subject
                    lesson_teacher_obj = chosen_spi.teacher if chosen_spi.teacher else random.choice(teachers) # Если в УП нет учителя, берем случайного
                    lesson_classroom_obj = random.choice(classrooms + [None]*3) if classrooms else None # Шанс урока без аудитории
                    lesson_creator_obj = random.choice(creators) if creators else None

                    start_dt_lesson = timezone.make_aware(timezone.datetime.combine(current_iter_date, start_time_slot))
                    end_dt_lesson = timezone.make_aware(timezone.datetime.combine(current_iter_date, end_time_slot))

                    try:
                        lesson_instance = Lesson(
                            subject=lesson_subject_obj,
                            teacher=lesson_teacher_obj,
                            group=group_lesson,
                            classroom=lesson_classroom_obj,
                            lesson_type=random.choice(Lesson.LessonType.values),
                            start_time=start_dt_lesson,
                            end_time=end_dt_lesson,
                            created_by=lesson_creator_obj,
                            study_plan_item=chosen_spi # Привязываем к элементу УП
                        )
                        lesson_instance.full_clean() # Вызываем валидацию из модели
                        lesson_instance.save()
                        created_lessons_list.append(lesson_instance)
                        lessons_count += 1
                        lessons_today_for_group_count += 1
                    except DjangoValidationError as e_val_lesson:
                        # self.stderr.write(self.style.WARNING(f'   ! Ошибка валидации урока: {e_val_lesson}'))
                        pass # Просто пропускаем, если конфликт
                    except IntegrityError:
                        pass # Дубликат или другая ошибка целостности
                    except Exception as e_lesson_create:
                        self.stderr.write(self.style.WARNING(f'   ! Ошибка создания занятия: {e_lesson_create} ({lesson_subject_obj}, {group_lesson}, {start_dt_lesson})'))
            current_iter_date += timedelta(days=1)
        self.stdout.write(f'  + Создано {lessons_count} занятий.')
        return created_lessons_list

    def create_grades_and_attendance(self, lessons, students, teachers, study_plan_items, academic_periods, all_subjects, grades_per_lesson_student):
        self.stdout.write('  Создание оценок и посещаемости...')
        grades_created_count, attendance_created_count = 0, 0
        if not lessons or not students or not teachers or not academic_periods:
            self.stdout.write(self.style.WARNING("  ! Недостаточно данных для оценок/посещаемости."))
            return

        possible_grades_numeric = [5.0, 4.0, 3.0, 2.0, 4.5, 3.5] # Числовые значения
        possible_grades_text = {5.0: "5", 4.0: "4", 3.0: "3", 2.0: "2", 4.5: "4", 3.5: "3"} # Соответствия, округляем 4.5 до 4, 3.5 до 3
                                                                                        # Это упрощение, в реальности система оценок сложнее

        # Текущие оценки и посещаемость
        for lesson_obj in random.sample(lessons, k=min(len(lessons), int(len(lessons) * 0.85))): # Не на всех уроках
            students_on_lesson = list(lesson_obj.group.students.all())
            if not students_on_lesson: continue

            for student_obj in random.sample(students_on_lesson, k=min(len(students_on_lesson), int(len(students_on_lesson) * 0.95))): # Не все студенты на каждом уроке
                # Посещаемость
                if random.random() < 0.95: # Не всегда отмечаем посещаемость
                    try:
                        Attendance.objects.update_or_create(
                            lesson=lesson_obj,
                            student=student_obj,
                            defaults={
                                'status': random.choice(Attendance.AttendanceStatus.values),
                                'comment': fake.word() if random.random() < 0.05 else "",
                                'marked_by': lesson_obj.teacher
                            }
                        )
                        attendance_created_count += 1
                    except Exception as e_att_create:
                        self.stderr.write(self.style.WARNING(f'   ! Ошибка посещаемости для урока {lesson_obj.id} студ {student_obj.id}: {e_att_create}'))

                # Текущие оценки
                if random.random() < 0.7: # Не всегда ставим оценку
                    for _ in range(random.randint(0, grades_per_lesson_student)):
                        grade_num_val = random.choice(possible_grades_numeric)
                        grade_txt_val = possible_grades_text.get(grade_num_val, str(int(grade_num_val)))
                        try:
                            Grade.objects.update_or_create(
                                student=student_obj,
                                lesson=lesson_obj, # Привязка к уроку
                                subject=lesson_obj.subject,
                                study_plan_item=lesson_obj.study_plan_item, # Привязка к элементу УП
                                grade_type=Grade.GradeType.CURRENT,
                                date_issued=lesson_obj.start_time.date(), # Дата урока
                                defaults={
                                    'value_numeric': grade_num_val,
                                    'value_text': grade_txt_val,
                                    'comment': fake.sentence(nb_words=3) if random.random() < 0.1 else "",
                                    'issued_by': lesson_obj.teacher
                                }
                            )
                            grades_created_count +=1
                        except (IntegrityError, DjangoValidationError) as e_grade_curr_val:
                            # self.stderr.write(self.style.WARNING(f'   ! Ошибка валидации текущей оценки: {e_grade_curr_val}'))
                            pass # Пропускаем, если такая оценка уже есть или невалидна
                        except Exception as e_grade_curr:
                            self.stderr.write(self.style.WARNING(f'   ! Ошибка текущей оценки для урока {lesson_obj.id} студ {student_obj.id}: {e_grade_curr}'))

        # Периодические и итоговые оценки
        if study_plan_items and academic_periods:
            for student_obj_final in students:
                student_groups = student_obj_final.student_groups.all()
                if not student_groups: continue
                group_for_student = student_groups.first() # Берем первую группу для простоты

                # Находим УП для этой группы
                student_study_plans = StudyPlan.objects.filter(group=group_for_student, is_active=True)

                for plan in student_study_plans:
                    year_for_plan = plan.academic_year
                    # Итоговые оценки за периоды этого учебного года
                    periods_in_year = AcademicPeriod.objects.filter(academic_year=year_for_plan).exclude(period_type=AcademicPeriod.PeriodType.YEAR) # Четверти, семестры

                    for spi_item in plan.items.select_related('subject').all(): # Элементы УП этого плана
                        for period_obj in periods_in_year:
                            if random.random() < 0.6: # Не для каждого предмета/периода ставим итоговую
                                grade_type_for_period = None
                                if period_obj.period_type == AcademicPeriod.PeriodType.QUARTER:
                                    grade_type_for_period = Grade.GradeType.QUARTER
                                elif period_obj.period_type == AcademicPeriod.PeriodType.SEMESTER:
                                    grade_type_for_period = Grade.GradeType.SEMESTER
                                # Годовая оценка будет рассчитываться отдельно или ставиться вручную

                                if grade_type_for_period:
                                    avg_current_grades = Grade.objects.filter(
                                        student=student_obj_final,
                                        study_plan_item=spi_item, # Оценки по этому элементу УП
                                        grade_type=Grade.GradeType.CURRENT,
                                        lesson__start_time__date__gte=period_obj.start_date,
                                        lesson__start_time__date__lte=period_obj.end_date,
                                        value_numeric__isnull=False
                                    ).aggregate(avg_grade=models.Avg('value_numeric'))

                                    final_numeric_val = None
                                    if avg_current_grades.get('avg_grade') is not None:
                                        final_numeric_val = round(avg_current_grades['avg_grade'] * 2) / 2 # Округляем до .0 или .5
                                        # Приводим к стандартным оценкам
                                        if final_numeric_val > 5.0: final_numeric_val = 5.0
                                        elif final_numeric_val < 2.0: final_numeric_val = 2.0 # Мин. положительная (или 1.0)

                                    # Если нет текущих, ставим случайную
                                    if final_numeric_val is None and random.random() < 0.5:
                                         final_numeric_val = random.choice(possible_grades_numeric)

                                    if final_numeric_val is not None:
                                        final_text_val = possible_grades_text.get(final_numeric_val, str(int(final_numeric_val)))
                                        try:
                                            Grade.objects.update_or_create(
                                                student=student_obj_final,
                                                subject=spi_item.subject,
                                                study_plan_item=spi_item,
                                                academic_period=period_obj,
                                                grade_type=grade_type_for_period,
                                                defaults={
                                                    'value_numeric': final_numeric_val,
                                                    'value_text': final_text_val,
                                                    'date_issued': period_obj.end_date - timedelta(days=random.randint(0, 2)),
                                                    'issued_by': spi_item.teacher if spi_item.teacher else random.choice(teachers)
                                                }
                                            )
                                            grades_created_count += 1
                                        except (IntegrityError, DjangoValidationError): pass
                                        except Exception as e_grade_period:
                                            self.stderr.write(self.style.WARNING(f'   ! Ошибка периодической оценки для студ {student_obj_final.id}, предмета {spi_item.subject.id}, периода {period_obj.id}: {e_grade_period}'))
        self.stdout.write(f'  + Создано {grades_created_count} оценок и {attendance_created_count} записей о посещаемости.')


    def create_news(self, num_news_categories, num_news_articles, creators):
        # ... (код без изменений) ...
        self.stdout.write('  Создание категорий и новостей...')
        news_categories_list = []
        cat_names_pool = ["Учебный процесс", "Спортивные достижения", "Школьные мероприятия", "Важные объявления", "Наука и инновации", "Студенческий совет", "Конкурсы и олимпиады", "Дополнительное образование", "Профсоюз", "Библиотека"]
        random.shuffle(cat_names_pool)

        for i in range(num_news_categories):
            name = cat_names_pool[i % len(cat_names_pool)]
            base_name = name
            suffix = 1
            while NewsCategory.objects.filter(name=name).exists():
                suffix += 1
                name = f"{base_name} ({suffix})"
                if suffix > 10: # Предохранитель
                    name = f"{base_name} (v{random.randint(100,999)})"
                    if NewsCategory.objects.filter(name=name).exists(): continue
                    break
            try:
                cat, _ = NewsCategory.objects.get_or_create(name=name, defaults={'description': fake.bs()})
                news_categories_list.append(cat)
            except IntegrityError:
                self.stderr.write(self.style.WARNING(f'   ! Категория новостей {name} уже существует (IntegrityError).'))
                existing_cat = NewsCategory.objects.filter(name__startswith=base_name).first()
                if existing_cat: news_categories_list.append(existing_cat)


        self.stdout.write(f'  + Создано/найдено {len(news_categories_list)} категорий новостей.')
        if not news_categories_list and num_news_articles > 0:
            cat, _ = NewsCategory.objects.get_or_create(name="Общие новости")
            news_categories_list.append(cat)

        news_articles_list = []
        if not creators and num_news_articles > 0:
             self.stdout.write(self.style.WARNING('  ! Нет создателей (учителей/админов), пропуск создания новостей.'))
             return news_categories_list, news_articles_list

        for _ in range(num_news_articles):
            if not creators: break
            author = random.choice(creators)
            category_obj = random.choice(news_categories_list) if news_categories_list else None
            try:
                article = NewsArticle.objects.create(
                    title=fake.sentence(nb_words=random.randint(5, 10)).capitalize().rstrip('.?!'),
                    content='\n\n'.join(fake.paragraphs(nb=random.randint(2, 5))),
                    category=category_obj,
                    author=author,
                    is_published=random.choice([True] * 9 + [False]) # 90% шанс
                )
                news_articles_list.append(article)
            except Exception as e_news: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать новость: {e_news}'))
        self.stdout.write(f'  + Создано {len(news_articles_list)} новостей.')
        return news_categories_list, news_articles_list

    def create_news_comments_and_reactions(self, news_articles, all_users):
        # ... (код без изменений, но убедитесь, что Reaction импортируется как NewsReaction) ...
        self.stdout.write('  Создание комментариев и реакций к новостям...')
        comments_count = 0
        reactions_count = 0
        if not all_users or not news_articles: return

        for article_obj in news_articles:
            # Комментарии первого уровня
            num_article_commenters = random.randint(0, min(MAX_COMMENTS_PER_NEWS, len(all_users)))
            article_commenters_list = random.sample(all_users, k=num_article_commenters)
            parent_comments_for_article_list = []

            for user_commenter_obj in article_commenters_list:
                try:
                    comment_obj = NewsComment.objects.create(
                        article=article_obj, author=user_commenter_obj,
                        content=fake.sentence(nb_words=random.randint(3, 25))
                    )
                    parent_comments_for_article_list.append(comment_obj)
                    comments_count += 1

                    # Реакции на комментарий
                    if random.random() < LIKES_RATIO * 2: # Больше шанс на реакцию на коммент
                        num_comment_reactors = random.randint(0, int(len(all_users) * LIKES_RATIO * 0.5))
                        comment_reactors_list = random.sample(all_users, k=min(len(all_users), num_comment_reactors))
                        for reactor_obj in comment_reactors_list:
                            if reactor_obj != user_commenter_obj: # Сам себе не ставит
                                try:
                                    NewsReaction.objects.create(user=reactor_obj, content_object=comment_obj, reaction_type=NewsReaction.ReactionType.LIKE)
                                    reactions_count +=1
                                except IntegrityError: pass # Уже лайкнул
                except Exception as e_comm: self.stderr.write(self.style.WARNING(f'   ! Ошибка комментария к новости {article_obj.id}: {e_comm}'))

            # Ответы на комментарии (второй уровень)
            if parent_comments_for_article_list:
                for parent_comment_obj in parent_comments_for_article_list:
                    if random.random() < REPLIES_RATIO: # Шанс ответа
                        num_replies_to_comment = random.randint(0, MAX_REPLIES_PER_COMMENT -1)
                        for _ in range(num_replies_to_comment):
                            replier_obj = random.choice(all_users)
                            # Не отвечаем сами себе и не отвечаем на свой ответ (простое ограничение)
                            if replier_obj == parent_comment_obj.author: continue

                            try:
                                reply_obj = NewsComment.objects.create(
                                    article=article_obj, author=replier_obj,
                                    content=fake.sentence(nb_words=random.randint(2, 15)),
                                    parent=parent_comment_obj # Привязка к родительскому комменту
                                )
                                comments_count += 1
                                # Реакции на ответ
                                if random.random() < LIKES_RATIO:
                                    num_reply_reactors = random.randint(0, int(len(all_users) * LIKES_RATIO * 0.2))
                                    reply_reactors_list = random.sample(all_users, k=min(len(all_users), num_reply_reactors))
                                    for reactor_reply_obj in reply_reactors_list:
                                        if reactor_reply_obj != replier_obj:
                                            try:
                                                NewsReaction.objects.create(user=reactor_reply_obj, content_object=reply_obj, reaction_type=NewsReaction.ReactionType.LIKE)
                                                reactions_count+=1
                                            except IntegrityError: pass
                            except Exception as e_reply: self.stderr.write(self.style.WARNING(f'   ! Ошибка ответа на комм. {parent_comment_obj.id}: {e_reply}'))

            # Реакции на саму статью
            if random.random() < LIKES_RATIO * 3: # Больше шанс на реакцию на статью
                num_article_reactors = random.randint(0, int(len(all_users) * LIKES_RATIO))
                article_reactors_list = random.sample(all_users, k=min(len(all_users), num_article_reactors))
                for reactor_art_obj in article_reactors_list:
                    if reactor_art_obj != article_obj.author: # Автор сам себе не ставит
                        try:
                            NewsReaction.objects.create(user=reactor_art_obj, content_object=article_obj, reaction_type=NewsReaction.ReactionType.LIKE)
                            reactions_count+=1
                        except IntegrityError: pass
        self.stdout.write(f'  + Создано {comments_count} комментариев и {reactions_count} реакций к новостям.')


    def create_forum(self, num_forum_categories, num_forum_topics, all_users, creators): # Добавил creators
        # ... (код для forum_categories без изменений, но используем creators) ...
        self.stdout.write('Создание данных форума...')
        forum_categories_list = []
        # ... (код генерации forum_categories_list)
        cat_names_forum_pool = ["Общие обсуждения", "Помощь по предметам", "Студенческая жизнь кампуса", "Техническая поддержка платформы", "Идеи и предложения", "Внеучебная деятельность", "Клуб по интересам: IT", "Клуб по интересам: Игры"]
        random.shuffle(cat_names_forum_pool)

        for i in range(num_forum_categories):
             name = cat_names_forum_pool[i % len(cat_names_forum_pool)]
             base_name = name
             suffix = 1
             while ForumCategory.objects.filter(name=name).exists():
                 suffix += 1
                 name = f"{base_name} ({suffix})"
                 if suffix > 10:
                     name = f"{base_name} (форум {random.randint(100,999)})"
                     if ForumCategory.objects.filter(name=name).exists(): continue
                     break
             try:
                cat_fc, _ = ForumCategory.objects.get_or_create(name=name, defaults={'display_order': i, 'description': fake.bs()})
                forum_categories_list.append(cat_fc)
             except IntegrityError:
                 self.stderr.write(self.style.WARNING(f'   ! Категория форума {name} уже существует (IntegrityError).'))
                 existing_fc_cat = ForumCategory.objects.filter(name__startswith=base_name).first()
                 if existing_fc_cat: forum_categories_list.append(existing_fc_cat)


        self.stdout.write(f'  + Создано/найдено {len(forum_categories_list)} категорий форума.')

        if not forum_categories_list or not all_users:
            self.stdout.write(self.style.WARNING('  ! Нет категорий или пользователей, пропуск создания тем и постов форума.'))
            return [], [], []

        forum_topics_list = []
        forum_posts_list_all = []

        # Авторами тем могут быть и студенты, и преподаватели, и админы
        topic_authors_pool = all_users # Или creators, если темы создают только они

        for _ in range(num_forum_topics):
            if not topic_authors_pool or not forum_categories_list: break
            author_topic = random.choice(topic_authors_pool)
            category_topic = random.choice(forum_categories_list)
            title_topic = fake.sentence(nb_words=random.randint(4, 9)).capitalize().rstrip('.?!') + random.choice(['?', '...', '!'])
            first_post_content_topic = '\n\n'.join(fake.paragraphs(nb=random.randint(1, 4)))
            tags_for_topic = fake.words(nb=random.randint(0, 4), unique=True) # django-taggit сам обработает уникальность
            try:
                 topic_obj = ForumTopic.objects.create(
                     category=category_topic, title=title_topic, author=author_topic,
                     is_pinned=random.random() < 0.08, is_closed=random.random() < 0.03
                 )
                 if tags_for_topic:
                     topic_obj.tags.set(tags_for_topic) # Передаем список напрямую
                 forum_topics_list.append(topic_obj)

                 # Первый пост создается от автора темы
                 first_post_obj = ForumPost.objects.create(topic=topic_obj, author=author_topic, content=first_post_content_topic)
                 # Модель ForumPost сама обновит first_post и last_post_at в ForumTopic при save()
                 forum_posts_list_all.append(first_post_obj)

                 parent_posts_in_this_topic_list = [first_post_obj]
                 num_additional_posts_in_topic = random.randint(0, MAX_POSTS_PER_TOPIC -1)
                 for _ in range(num_additional_posts_in_topic):
                    post_author_forum = random.choice(all_users) # Посты могут писать все
                    parent_post_for_reply_forum = None
                    if parent_posts_in_this_topic_list and random.random() < REPLIES_RATIO * 1.2: # Шанс ответа
                        parent_post_for_reply_forum = random.choice(parent_posts_in_this_topic_list)
                        # Простой фильтр, чтобы не отвечать самому себе, если в теме есть другие
                        if parent_post_for_reply_forum.author == post_author_forum and len(parent_posts_in_this_topic_list) > 1:
                            temp_parents_forum = [p for p in parent_posts_in_this_topic_list if p.author != post_author_forum]
                            if temp_parents_forum: parent_post_for_reply_forum = random.choice(temp_parents_forum)
                            else: parent_post_for_reply_forum = None # Если только свои посты, отвечаем на тему (без parent)

                    post_obj_forum = ForumPost.objects.create(
                        topic=topic_obj, author=post_author_forum,
                        content='\n'.join(fake.paragraphs(nb=random.randint(1,2))),
                        parent=parent_post_for_reply_forum
                    )
                    forum_posts_list_all.append(post_obj_forum)
                    parent_posts_in_this_topic_list.append(post_obj_forum) # Добавляем для возможности ответа на него
            except Exception as e_topic: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать тему/пост форума: {e_topic}'))
        self.stdout.write(f'  + Создано {len(forum_topics_list)} тем и {len(forum_posts_list_all)} постов форума.')
        return forum_categories_list, forum_topics_list, forum_posts_list_all


    def create_forum_reactions(self, forum_posts, all_users):
        # ... (код без изменений, но используем ForumForumReaction) ...
        self.stdout.write('  Создание реакций на посты форума...')
        reactions_forum_count = 0
        if not all_users or not forum_posts: return

        for post_forum_obj in random.sample(forum_posts, k=min(len(forum_posts), int(len(forum_posts) * 0.6))): # Реакции на 60% постов
            num_likes_forum = random.randint(0, int(len(all_users) * LIKES_RATIO * 0.4) + 1)
            reactors_forum_list = random.sample(all_users, k=min(len(all_users), num_likes_forum))
            for user_forum_obj in reactors_forum_list:
                 if user_forum_obj != post_forum_obj.author: # Сам себе не ставит
                    try:
                        ForumForumReaction.objects.create(user=user_forum_obj, content_object=post_forum_obj, reaction_type=ForumForumReaction.ReactionType.LIKE)
                        reactions_forum_count += 1
                    except IntegrityError: pass # Уже лайкнул
        self.stdout.write(f'  + Создано {reactions_forum_count} реакций на форуме.')


    def create_chats_and_messages(self, num_private_chats, groups, all_users): # Убрал teachers из аргументов
        # ... (код без изменений) ...
        self.stdout.write('Создание чатов и сообщений...')
        private_chats_count = 0
        private_messages_count = 0
        group_chats_count = 0
        group_messages_count = 0

        # Приватные чаты
        if not all_users or len(all_users) < 2:
            self.stdout.write(self.style.WARNING('  ! Недостаточно пользователей для создания приватных чатов.'))
        else:
            created_private_pairs = set() # Для отслеживания уже созданных пар
            attempts_to_create_private = 0
            max_attempts_private = num_private_chats * 3 # Чтобы не зацикливаться, если мало уникальных пар

            while private_chats_count < num_private_chats and attempts_to_create_private < max_attempts_private:
                attempts_to_create_private +=1
                if len(all_users) < 2: break
                user_a, user_b = random.sample(all_users, k=2)
                if user_a == user_b: continue # Пропускаем чат с самим собой

                # Ключ для уникальности пары
                pair_key = tuple(sorted((user_a.id, user_b.id)))
                if pair_key in created_private_pairs:
                    continue # Такая пара уже была обработана (или чат создан)

                # Проверка, существует ли уже такой приватный чат
                # Это сложный запрос, можно упростить или положиться на IntegrityError при создании ChatParticipant
                # Для простоты будем полагаться на то, что если пара уже в created_private_pairs, то чат есть
                # или его создание не удалось.
                # Более надежно:
                # existing_chat_qs = Chat.objects.filter(chat_type=Chat.ChatType.PRIVATE, participants=user_a).filter(participants=user_b)
                # if existing_chat_qs.annotate(p_count=models.Count('participants')).filter(p_count=2).exists():
                #    created_private_pairs.add(pair_key) # Отмечаем пару, чтобы не пытаться снова
                #    continue

                try:
                    chat_obj = Chat.objects.create(chat_type=Chat.ChatType.PRIVATE, created_by=user_a) # created_by - инициатор
                    ChatParticipant.objects.create(user=user_a, chat=chat_obj)
                    ChatParticipant.objects.create(user=user_b, chat=chat_obj)
                    private_chats_count += 1
                    created_private_pairs.add(pair_key) # Запоминаем созданную пару

                    chat_participants_list = [user_a, user_b]
                    last_msg_time = timezone.now() - timedelta(days=random.randint(1, 10), hours=random.randint(0,23))
                    num_messages_in_chat = random.randint(2, MAX_MESSAGES_PER_CHAT - 5)
                    current_message = None
                    for _ in range(num_messages_in_chat):
                        sender_msg = random.choice(chat_participants_list)
                        last_msg_time += timedelta(minutes=random.randint(1, 90), seconds=random.randint(0,59))
                        if last_msg_time > timezone.now(): # Сообщение не может быть в будущем
                            last_msg_time = timezone.now() - timedelta(seconds=random.randint(1,10))

                        msg_obj = Message.objects.create(
                            chat=chat_obj, sender=sender_msg,
                            content=fake.sentence(nb_words=random.randint(3,20)),
                            timestamp=last_msg_time
                        )
                        private_messages_count += 1
                        current_message = msg_obj # Запоминаем последнее сообщение
                    if current_message: # Обновляем last_message в чате
                        chat_obj.last_message = current_message
                        chat_obj.save(update_fields=['last_message'])

                except IntegrityError: # Если ChatParticipant уже существует (например, из-за гонки или неточной проверки выше)
                    created_private_pairs.add(pair_key) # Все равно отмечаем пару
                except Exception as e_priv_chat:
                    self.stderr.write(self.style.WARNING(f'  ! Не удалось создать личный чат ({user_a.id}-{user_b.id}): {e_priv_chat}'))
        self.stdout.write(f'  + Создано {private_chats_count} личных чатов и {private_messages_count} сообщений в них.')

        # Групповые чаты
        if not groups:
            self.stdout.write(self.style.WARNING('  ! Нет групп для создания групповых чатов.'))
        else:
            for group_obj_chat in groups:
                 if not group_obj_chat.students.exists(): # Пропускаем группы без студентов
                     continue
                 try:
                      chat_name_group = f"Чат группы {group_obj_chat.name}"
                      # Создатель группового чата - куратор или случайный учитель/админ
                      group_chat_creator = group_obj_chat.curator
                      if not group_chat_creator and creators:
                          group_chat_creator = random.choice(creators)
                      elif not group_chat_creator and all_users: # На крайний случай
                          group_chat_creator = random.choice(all_users)


                      chat_group_obj, created_group_chat = Chat.objects.get_or_create(
                          name=chat_name_group, # Ищем по имени
                          chat_type=Chat.ChatType.GROUP,
                          defaults={'created_by': group_chat_creator}
                      )
                      if created_group_chat:
                          group_chats_count += 1
                          self.stdout.write(f'    + Создан групповой чат: {chat_name_group}')
                      else:
                          self.stdout.write(f'    * Найден групповой чат: {chat_name_group}')

                      # Собираем всех участников, которые должны быть в чате
                      target_participants_for_group_chat = set(list(group_obj_chat.students.all()))
                      if group_obj_chat.curator:
                          target_participants_for_group_chat.add(group_obj_chat.curator)
                      # Можно добавить всех учителей, ведущих предметы у этой группы (сложнее, требует анализа StudyPlan)

                      # Добавляем недостающих участников
                      current_participants_in_chat = set(chat_group_obj.participants.all())
                      for user_to_add in target_participants_for_group_chat:
                          if user_to_add not in current_participants_in_chat:
                              ChatParticipant.objects.get_or_create(user=user_to_add, chat=chat_group_obj)

                      # Опционально: удаляем тех, кто больше не должен быть в чате (если состав группы изменился)
                      # users_to_remove = current_participants_in_chat - target_participants_for_group_chat
                      # if users_to_remove:
                      #    ChatParticipant.objects.filter(user__in=users_to_remove, chat=chat_group_obj).delete()

                      # Заполняем сообщениями, если чат новый или пустой
                      if created_group_chat or chat_group_obj.messages.count() < 3:
                          if not target_participants_for_group_chat: continue # Пропускаем, если нет участников
                          
                          all_chat_members = list(target_participants_for_group_chat) # Актуальный список участников
                          if not all_chat_members: continue

                          last_msg_time_group = timezone.now() - timedelta(days=random.randint(1, 7))
                          num_messages_group = random.randint(3, MAX_MESSAGES_PER_CHAT - 8)
                          current_group_message = None
                          for _ in range(num_messages_group):
                               sender_msg_group = random.choice(all_chat_members)
                               last_msg_time_group += timedelta(minutes=random.randint(1, 150), seconds=random.randint(0,59))
                               if last_msg_time_group > timezone.now():
                                   last_msg_time_group = timezone.now() - timedelta(seconds=random.randint(1,10))
                               msg_group_obj = Message.objects.create(
                                   chat=chat_group_obj, sender=sender_msg_group,
                                   content=fake.sentence(nb_words=random.randint(4, 15)),
                                   timestamp=last_msg_time_group
                               )
                               group_messages_count += 1
                               current_group_message = msg_group_obj
                          if current_group_message: # Обновляем last_message
                               chat_group_obj.last_message = current_group_message
                               chat_group_obj.save(update_fields=['last_message'])

                 except Exception as e_group_chat:
                      self.stderr.write(self.style.WARNING(f'  ! Не удалось создать/заполнить групповой чат для {group_obj_chat.name}: {e_group_chat}'))
            self.stdout.write(f'  + Создано/обновлено {group_chats_count} групповых чатов и {group_messages_count} сообщений в них.')