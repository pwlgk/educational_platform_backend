import random
from faker import Faker
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

# Импортируем модели из ваших приложений
# Убедитесь, что пути к моделям правильные
from users.models import User as UserModel # Переименовываем, чтобы не конфликтовать с переменной user
from edu_core.models import Subject, StudentGroup, AcademicYear, StudyPeriod, Homework, LessonJournalEntry, Lesson as EduLesson
from quizzes.models import (
    Question, QuestionImage, QuestionChoice, QuestionType,
    Quiz, QuizQuestion,
    QuizAttempt, StudentAnswer, QuizAppeal
)
from taggit.models import Tag # Для добавления тегов

# Настройки
NUM_TEACHERS = 3
NUM_STUDENTS_PER_GROUP = 10
NUM_GROUPS = 2
NUM_SUBJECTS = 5
NUM_QUESTIONS_PER_SUBJECT = 10
NUM_QUIZZES_PER_SUBJECT = 2
QUESTIONS_PER_QUIZ_MIN = 5
QUESTIONS_PER_QUIZ_MAX = 8 # Должно быть <= NUM_QUESTIONS_PER_SUBJECT
NUM_ATTEMPTS_PER_STUDENT_QUIZ = 1 # Количество попыток для каждого студента на доступный тест


class Command(BaseCommand):
    help = 'Populates the database with fake data for the quizzes module and related entities.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake = Faker('ru_RU') # Используем русскую локализацию
        self.User = get_user_model() # Получаем кастомную модель пользователя

    def _create_users(self):
        teachers = []
        students = []

        # Создаем администратора, если его нет (для примера, можно пропустить)
        if not self.User.objects.filter(email='admin@example.com').exists():
            admin_user = self.User.objects.create_superuser(
                email='admin@example.com',
                password='password123',
                first_name='Главный',
                last_name='Администратор',
                role=self.User.Role.ADMIN
            )
            self.stdout.write(self.style.SUCCESS(f'Created admin: {admin_user.email}'))

        # Создаем преподавателей
        for i in range(NUM_TEACHERS):
            first_name = self.fake.first_name_male() if i % 2 == 0 else self.fake.first_name_female()
            last_name = self.fake.last_name_male() if i % 2 == 0 else self.fake.last_name_female()
            email = f'teacher{i+1}@example.com'
            if self.User.objects.filter(email=email).exists():
                teachers.append(self.User.objects.get(email=email))
                continue
            user, created = self.User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'role': self.User.Role.TEACHER,
                    'is_active': True,
                    'is_role_confirmed': True,
                }
            )
            if created: user.set_password('password123')
            user.save()
            teachers.append(user)
            if created: self.stdout.write(self.style.SUCCESS(f'Created teacher: {user.email}'))
        self.teachers = teachers

        # Создаем учебный год и период, если их нет
        self.academic_year, _ = AcademicYear.objects.get_or_create(
            name="2024-2025",
            defaults={
                'start_date': timezone.now().date().replace(month=9, day=1),
                'end_date': timezone.now().date().replace(year=timezone.now().year + 1, month=6, day=30),
                'is_current': True
            }
        )
        self.study_period, _ = StudyPeriod.objects.get_or_create(
            academic_year=self.academic_year,
            name="1 Семестр",
            defaults={
                'start_date': self.academic_year.start_date,
                'end_date': self.academic_year.start_date.replace(month=12, day=31)
            }
        )


        # Создаем группы и студентов
        self.student_groups = []
        for i in range(NUM_GROUPS):
            group_name = f'Группа ИС-{101+i}'
            group, created = StudentGroup.objects.get_or_create(
                name=group_name,
                academic_year=self.academic_year,
                defaults={'curator': random.choice(self.teachers) if self.teachers else None}
            )
            self.student_groups.append(group)
            if created: self.stdout.write(self.style.SUCCESS(f'Created group: {group.name}'))

            current_group_students = []
            for j in range(NUM_STUDENTS_PER_GROUP):
                s_first_name = self.fake.first_name_male() if j % 2 == 0 else self.fake.first_name_female()
                s_last_name = self.fake.last_name_male() if j % 2 == 0 else self.fake.last_name_female()
                s_email = f'student{i*NUM_STUDENTS_PER_GROUP + j + 1}@example.com'
                if self.User.objects.filter(email=s_email).exists():
                    student = self.User.objects.get(email=s_email)
                else:
                    student, s_created = self.User.objects.get_or_create(
                        email=s_email,
                        defaults={
                            'first_name': s_first_name,
                            'last_name': s_last_name,
                            'role': self.User.Role.STUDENT,
                            'is_active': True,
                            'is_role_confirmed': True,
                        }
                    )
                    if s_created: student.set_password('password123')
                    student.save()
                    if s_created: self.stdout.write(self.style.SUCCESS(f'Created student: {student.email}'))
                current_group_students.append(student)
                students.append(student)
            group.students.set(current_group_students) # Добавляем студентов в группу
        self.students = students


    def _create_subjects(self):
        self.subjects = []
        subject_names = [
            "Математический анализ", "Линейная алгебра", "Программирование на Python",
            "Базы данных", "Философия", "История Искусств", "Английский язык"
        ]
        for i in range(min(NUM_SUBJECTS, len(subject_names))):
            name = subject_names[i]
            subject, created = Subject.objects.get_or_create(
                name=name,
                defaults={
                    'description': self.fake.sentence(nb_words=10),
                    'code': f'SUBJ{100+i}'
                }
            )
            # Назначаем ведущих преподавателей
            if self.teachers:
                subject.lead_teachers.set(random.sample(self.teachers, k=min(len(self.teachers), 2)))
            self.subjects.append(subject)
            if created: self.stdout.write(self.style.SUCCESS(f'Created subject: {subject.name}'))


    def _create_questions(self):
        self.questions_dict = {} # {subject_id: [question1, question2, ...]}
        common_tags = ["основы", "теория", "практика", "введение", "задачи"]
        for tag_name in common_tags:
            Tag.objects.get_or_create(name=tag_name) # Создаем теги, если их нет

        for subject in self.subjects:
            self.questions_dict[subject.id] = []
            for i in range(NUM_QUESTIONS_PER_SUBJECT):
                q_type = random.choice(list(QuestionType))
                question_text = self.fake.sentence(nb_words=random.randint(8, 15)) + "?"
                
                question_author = random.choice(self.teachers) if self.teachers else None

                question = Question.objects.create(
                    subject=subject,
                    author=question_author,
                    question_text=question_text,
                    question_type=q_type,
                    points=random.randint(1, 5),
                    difficulty=random.randint(1, 5)
                )
                # Добавляем теги
                question.tags.add(*random.sample(common_tags, k=random.randint(1,3)))

                # Создаем варианты ответов для CHOICE типов
                if q_type in [QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE]:
                    num_choices = random.randint(3, 5)
                    correct_indices = []
                    if q_type == QuestionType.SINGLE_CHOICE:
                        correct_indices.append(random.randint(0, num_choices - 1))
                    else: # MULTIPLE_CHOICE
                        num_correct = random.randint(1, num_choices -1) # Хотя бы один правильный, не все
                        correct_indices = random.sample(range(num_choices), k=num_correct)

                    for j in range(num_choices):
                        QuestionChoice.objects.create(
                            question=question,
                            choice_text=self.fake.sentence(nb_words=random.randint(3,7)),
                            is_correct=(j in correct_indices),
                            feedback=self.fake.sentence(nb_words=5) if random.random() < 0.3 else ""
                        )
                # Создаем изображения (1-2 на вопрос, опционально)
                # if random.random() < 0.4:
                #     for _ in range(random.randint(1,2)):
                #         # Здесь нужна реальная картинка или заглушка. Faker не генерирует файлы изображений.
                #         # QuestionImage.objects.create(question=question, image="path/to/fake_image.jpg", caption=self.fake.sentence(nb_words=3))
                #         pass
                self.questions_dict[subject.id].append(question)
            self.stdout.write(self.style.SUCCESS(f'Created {NUM_QUESTIONS_PER_SUBJECT} questions for subject: {subject.name}'))


    def _create_quizzes(self):
        self.quizzes = []
        for subject in self.subjects:
            if not self.questions_dict.get(subject.id):
                continue
            for i in range(NUM_QUIZZES_PER_SUBJECT):
                quiz_author = random.choice(self.teachers) if self.teachers else None
                is_random_selection = random.choice([True, False, False]) # Чаще не случайный
                
                quiz_data = {
                    'title': f'Тест по "{subject.name}" №{i+1} ({self.fake.bs().capitalize()})',
                    'description': self.fake.paragraph(nb_sentences=2),
                    'subject': subject,
                    'author': quiz_author,
                    'time_limit_minutes': random.choice([None, 20, 30, 45, 60]),
                    'shuffle_questions': self.fake.boolean(chance_of_getting_true=60),
                    'shuffle_choices': self.fake.boolean(chance_of_getting_true=75),
                    'allowed_attempts': random.choice([1, 2, 3, 0]), # 0 - неограниченно
                    'show_correct_answers': random.choice(['NEVER', 'AFTER_ATTEMPT', 'AFTER_QUIZ_ENDS']),
                    'is_active': True,
                    'select_random_questions': is_random_selection
                }
                if is_random_selection:
                    quiz_data['questions_to_select_count'] = random.randint(QUESTIONS_PER_QUIZ_MIN, QUESTIONS_PER_QUIZ_MAX)
                    quiz_data['random_questions_subject'] = subject # Фильтр по текущему предмету
                    # quiz_data['random_questions_tags'] = # Можно добавить случайные теги
                    quiz_data['random_questions_difficulty_min'] = random.choice([None, 1, 2, 3])
                    quiz_data['random_questions_difficulty_max'] = random.choice([None, 3, 4, 5])


                quiz = Quiz.objects.create(**quiz_data)

                # Если не случайный выбор, добавляем вопросы через QuizQuestion
                if not is_random_selection:
                    available_questions = self.questions_dict[subject.id]
                    num_q_in_quiz = random.randint(QUESTIONS_PER_QUIZ_MIN, min(QUESTIONS_PER_QUIZ_MAX, len(available_questions)))
                    selected_questions_for_quiz = random.sample(available_questions, k=num_q_in_quiz)
                    for order, question_obj in enumerate(selected_questions_for_quiz):
                        QuizQuestion.objects.create(quiz=quiz, question=question_obj, order=order)
                
                # Связываем с ДЗ (опционально)
                if random.random() < 0.3 and self.student_groups:
                    try:
                        # Создаем фиктивное ДЗ, если нужно
                        # Это упрощенный вариант, ДЗ обычно связано с занятием
                        group_for_hw = random.choice(self.student_groups)
                        # Нужно создать LessonJournalEntry -> Lesson -> StudyPeriod -> AcademicYear
                        # Это усложнит скрипт, пока пропустим создание полного ДЗ
                        # homework, _ = Homework.objects.get_or_create(
                        #     # journal_entry=..., # Требует создания LessonJournalEntry
                        #     title=f"ДЗ к тесту: {quiz.title}",
                        #     defaults={
                        #         'description': "Выполните тест.",
                        #         'due_date': timezone.now() + timezone.timedelta(days=7),
                        #         'author': quiz.author
                        #     }
                        # )
                        # quiz.homework = homework
                        # quiz.save(update_fields=['homework'])
                        pass
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'Could not link quiz to homework: {e}'))


                self.quizzes.append(quiz)
                self.stdout.write(self.style.SUCCESS(f'Created quiz: {quiz.title}'))


    def _create_quiz_attempts(self):
        if not self.students or not self.quizzes:
            self.stdout.write(self.style.WARNING('No students or quizzes to create attempts.'))
            return

        for student in self.students:
            # Студент проходит несколько случайных доступных тестов
            num_quizzes_to_attempt = random.randint(1, min(3, len(self.quizzes)))
            quizzes_for_student = random.sample(self.quizzes, k=num_quizzes_to_attempt)

            for quiz in quizzes_for_student:
                for attempt_num in range(1, NUM_ATTEMPTS_PER_STUDENT_QUIZ + 1):
                    if quiz.allowed_attempts > 0 and attempt_num > quiz.allowed_attempts:
                        break

                    start_time = timezone.now() - timezone.timedelta(minutes=random.randint(5, 120)) # Начал некоторое время назад
                    attempt = QuizAttempt.objects.create(
                        quiz=quiz,
                        student=student,
                        attempt_number=attempt_num,
                        start_time=start_time,
                        ip_address=self.fake.ipv4()
                    )
                    # Заполняем вопросы, которые были в этой попытке
                    questions_in_this_attempt = quiz.get_questions_for_attempt()
                    attempt.questions_in_attempt.set(questions_in_this_attempt)
                    
                    attempt_answers_snapshot = {}
                    is_fully_graded_by_student = True # Считаем, что студент ответил на все (или пометил)

                    for question in questions_in_this_attempt:
                        answer_later = self.fake.boolean(chance_of_getting_true=15)
                        student_answer_snapshot = {'answer_later': answer_later}

                        sa, _ = StudentAnswer.objects.get_or_create(quiz_attempt=attempt, question=question)
                        if not answer_later:
                            if question.question_type == QuestionType.TEXT_ANSWER:
                                sa.text_answer = self.fake.sentence(nb_words=random.randint(5,20))
                                student_answer_snapshot['text_answer'] = sa.text_answer
                                # Текстовые ответы не авто-оцениваются сразу
                            else: # SINGLE_CHOICE, MULTIPLE_CHOICE
                                choices = list(question.choices.all())
                                if choices:
                                    selected = []
                                    if question.question_type == QuestionType.SINGLE_CHOICE:
                                        selected.append(random.choice(choices))
                                    else: # MULTIPLE_CHOICE
                                        num_selected = random.randint(1, len(choices))
                                        selected = random.sample(choices, k=num_selected)
                                    sa.selected_choices.set(selected)
                                    student_answer_snapshot['selected_choice_ids'] = [c.id for c in selected]
                            sa.auto_grade() # Автооценка
                        
                        attempt_answers_snapshot[str(question.id)] = student_answer_snapshot

                    # Обновляем state_snapshot попытки
                    attempt.state_snapshot = {
                        'question_order_ids': [q.id for q in questions_in_this_attempt],
                        'answers': attempt_answers_snapshot
                    }
                    attempt.save(update_fields=['state_snapshot'])


                    # Завершаем попытку
                    should_complete = self.fake.boolean(chance_of_getting_true=85)
                    if should_complete:
                        attempt.complete_attempt(by_student=True) # Метод вызовет calculate_score и create_grade
                        # Ручная проверка некоторых текстовых ответов (если есть)
                        text_answers_to_grade = attempt.answers.filter(question__question_type=QuestionType.TEXT_ANSWER, is_graded=False)
                        for text_answer in text_answers_to_grade:
                            if random.random() < 0.7: # 70% шанс, что преподаватель проверил
                                text_answer.points_awarded = random.randint(0, text_answer.question.points)
                                text_answer.is_graded = True
                                text_answer.grader_comment = self.fake.sentence() if random.random() < 0.5 else ""
                                text_answer.graded_by = random.choice(self.teachers) if self.teachers else None
                                text_answer.graded_at = timezone.now()
                                text_answer.save()
                        # После ручной проверки, еще раз пересчитываем общий балл и статус
                        attempt.calculate_score_and_grade_status()
                        if attempt.is_graded and attempt.quiz.homework: # Если все проверено и есть ДЗ
                            attempt.create_or_update_grade()


                    self.stdout.write(self.style.SUCCESS(f'Created attempt {attempt_num} for quiz "{quiz.title}" by student {student.email} (Completed: {attempt.is_completed})'))


    @transaction.atomic # Выполняем все в одной транзакции
    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO('Starting to populate quizzes data...'))

        self._create_users()
        self._create_subjects()
        self._create_questions()
        self._create_quizzes()
        self._create_quiz_attempts()

        self.stdout.write(self.style.SUCCESS('Successfully populated quizzes and related data.'))