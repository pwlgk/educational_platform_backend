import random
from datetime import timedelta, time

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.utils.text import slugify
from faker import Faker # Импортируем Faker

# Импортируем модели из ваших приложений
from users.models import Profile
from schedule.models import Subject, StudentGroup, Classroom, Lesson
from news.models import NewsCategory, NewsArticle, NewsComment, Reaction as NewsReaction
from messaging.models import Chat, Message
from forum.models import ForumCategory, ForumTopic, ForumPost, ForumReaction
from notifications.models import Notification # Уведомления создаются через сигналы, но можно и вручную

User = get_user_model()
fake = Faker('ru_RU') # Используем русский язык для Faker

# --- Константы для генерации ---
MAX_COMMENTS_PER_NEWS = 5
MAX_REPLIES_PER_COMMENT = 3
MAX_POSTS_PER_TOPIC = 15
MAX_REPLIES_PER_POST = 4
MAX_MESSAGES_PER_CHAT = 25
LIKES_RATIO = 0.3 # Вероятность лайка
REPLIES_RATIO = 0.4 # Вероятность ответа на коммент/пост

# --- Рабочее время для расписания ---
WORK_START_HOUR = 8
WORK_END_HOUR = 18
LESSON_DURATIONS_MINUTES = [45, 80, 90]
BREAK_MINUTES = 15


class Command(BaseCommand):
    help = 'Заполняет базу данных тестовыми данными для ВСЕХ модулей (пользователи, расписание, новости, мессенджер, форум).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Удалить существующие данные (кроме суперпользователей) перед заполнением.',
        )
        parser.add_argument('--num-students', type=int, default=50, help='Количество студентов.')
        parser.add_argument('--num-teachers', type=int, default=10, help='Количество преподавателей.')
        parser.add_argument('--num-parents', type=int, default=30, help='Количество родителей.')
        parser.add_argument('--num-subjects', type=int, default=15, help='Количество предметов.')
        parser.add_argument('--num-groups', type=int, default=5, help='Количество групп.')
        parser.add_argument('--num-classrooms', type=int, default=10, help='Количество аудиторий.')
        parser.add_argument('--days-range', type=int, default=14, help='Диапазон дней (+/-) для генерации расписания.')
        parser.add_argument('--lessons-per-group-day', type=int, default=3, help='Среднее кол-во уроков у группы в день.')
        parser.add_argument('--num-news-categories', type=int, default=5, help='Количество категорий новостей.')
        parser.add_argument('--num-news-articles', type=int, default=30, help='Количество новостей.')
        parser.add_argument('--num-forum-categories', type=int, default=4, help='Количество категорий форума.')
        parser.add_argument('--num-forum-topics', type=int, default=25, help='Количество тем форума.')
        parser.add_argument('--num-private-chats', type=int, default=40, help='Количество личных чатов.')
        parser.add_argument('--num-group-chats', type=int, default=5, help='Количество групповых чатов (добавляются к группам студентов).')
        parser.add_argument('--password', type=str, default='testpass123', help='Пароль для всех созданных пользователей.')

    @transaction.atomic # Выполняем все в одной транзакции
    def handle(self, *args, **options):
        clear_data = options['clear']
        num_students = options['num_students']
        num_teachers = options['num_teachers']
        num_parents = options['num_parents']
        num_subjects = options['num_subjects']
        num_groups = options['num_groups']
        num_classrooms = options['num_classrooms']
        days_range = options['days_range']
        lessons_per_group_day = options['lessons_per_group_day']
        num_news_categories = options['num_news_categories']
        num_news_articles = options['num_news_articles']
        num_forum_categories = options['num_forum_categories']
        num_forum_topics = options['num_forum_topics']
        num_private_chats = options['num_private_chats']
        num_group_chats = options['num_group_chats']
        password = options['password']

        # --- Очистка данных (если нужно) ---
        if clear_data:
            self.clear_database()

        # --- Создание пользователей ---
        self.stdout.write(self.style.SUCCESS('--- Создание пользователей ---'))
        students, teachers, parents, admins = self.create_users(
            num_students, num_teachers, num_parents, password
        )
        all_users = students + teachers + parents + admins
        creators = teachers + admins # Для создания контента

        if not creators:
             self.stderr.write(self.style.ERROR('Не найдено ни одного администратора или преподавателя. Создание контента невозможно.'))
             # return # Можно прервать, но попробуем создать остальное

        # --- Создание данных Расписания ---
        self.stdout.write(self.style.SUCCESS('\n--- Создание данных Расписания ---'))
        subjects, classrooms, groups = self.create_schedule_base(
            num_subjects, num_classrooms, num_groups, teachers, students
        )
        if groups and classrooms and subjects and teachers:
            self.create_lessons(num_groups, lessons_per_group_day, days_range, groups, teachers, classrooms, subjects, creators)
        else:
            self.stdout.write(self.style.WARNING('Пропуск создания занятий из-за отсутствия групп, аудиторий, предметов или преподавателей.'))

        # --- Создание данных Новостей ---
        self.stdout.write(self.style.SUCCESS('\n--- Создание данных Новостей ---'))
        news_categories, news_articles = self.create_news(
            num_news_categories, num_news_articles, creators
        )
        if news_articles and all_users:
            self.create_news_comments_and_reactions(news_articles, all_users)

        # --- Создание данных Форума ---
        self.stdout.write(self.style.SUCCESS('\n--- Создание данных Форума ---'))
        forum_categories, forum_topics, forum_posts = self.create_forum(
             num_forum_categories, num_forum_topics, all_users
        )
        if forum_posts and all_users:
             self.create_forum_reactions(forum_posts, all_users)

        # --- Создание данных Мессенджера ---
        self.stdout.write(self.style.SUCCESS('\n--- Создание данных Мессенджера ---'))
        self.create_chats_and_messages(
            num_private_chats, num_group_chats, all_users, groups
        )

        # --- Завершение ---
        self.stdout.write(self.style.SUCCESS('\n--- Генерация тестовых данных завершена! ---'))

    # ===========================================
    # --- МЕТОДЫ ОЧИСТКИ И СОЗДАНИЯ ДАННЫХ ---
    # ===========================================

    def clear_database(self):
        self.stdout.write(self.style.WARNING('Очистка существующих данных...'))
        # Удаляем в порядке обратной зависимости
        Notification.objects.all().delete()
        Message.objects.all().delete()
        Chat.objects.all().delete() # Участники удалятся каскадно
        ForumReaction.objects.all().delete()
        ForumPost.objects.all().delete()
        ForumTopic.objects.all().delete()
        ForumCategory.objects.all().delete()
        NewsComment.objects.all().delete()
        NewsReaction.objects.all().delete()
        NewsArticle.objects.all().delete()
        NewsCategory.objects.all().delete()
        Lesson.objects.all().delete()
        StudentGroup.objects.all().delete() # M2M со студентами очистится
        Classroom.objects.all().delete()
        Subject.objects.all().delete()
        # Профили удалятся каскадно с пользователями
        User.objects.filter(is_superuser=False).delete()
        self.stdout.write(self.style.SUCCESS('Данные очищены (кроме суперпользователей).'))

    def create_users(self, num_students, num_teachers, num_parents, password):
        students = []
        teachers = []
        parents = []
        admins = list(User.objects.filter(is_superuser=True))

        # Учителя
        for i in range(num_teachers):
            email = f'teacher{i+1}@example.test'
            if User.objects.filter(email=email).exists(): continue
            first_name, last_name = self._get_fake_name()
            try:
                user = User.objects.create_user(email=email, password=password, first_name=first_name, last_name=last_name, role=User.Role.TEACHER, is_active=True, is_role_confirmed=True)
                teachers.append(user)
                self.stdout.write(f'  + Учитель: {email}')
            except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать учителя {email}: {e}'))

        # Студенты
        for i in range(num_students):
            email = f'student{i+1}@example.test'
            if User.objects.filter(email=email).exists(): continue
            first_name, last_name = self._get_fake_name()
            try:
                user = User.objects.create_user(email=email, password=password, first_name=first_name, last_name=last_name, role=User.Role.STUDENT, is_active=True, is_role_confirmed=True)
                students.append(user)
                self.stdout.write(f'  + Студент: {email}')
            except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать студента {email}: {e}'))

        # Родители
        available_students_for_parents = list(students)
        for i in range(num_parents):
            email = f'parent{i+1}@example.test'
            if User.objects.filter(email=email).exists(): continue
            related_child = None
            if available_students_for_parents:
                related_child = random.choice(available_students_for_parents)
                available_students_for_parents.remove(related_child)
            first_name, last_name = self._get_fake_name()
            try:
                user = User.objects.create_user(email=email, password=password, first_name=first_name, last_name=last_name, role=User.Role.PARENT, related_child=related_child, is_active=True, is_role_confirmed=True)
                parents.append(user)
                child_email = related_child.email if related_child else "нет"
                self.stdout.write(f'  + Родитель: {email} (ребенок: {child_email})')
            except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать родителя {email}: {e}'))

        return students, teachers, parents, admins

    def create_schedule_base(self, num_subjects, num_classrooms, num_groups, teachers, students):
        subjects = [Subject.objects.get_or_create(name=fake.catch_phrase().capitalize())[0] for _ in range(num_subjects)]
        self.stdout.write(f'  + Создано/найдено {len(subjects)} предметов.')
        classrooms = []
        for i in range(num_classrooms):
             identifier=f"{random.randint(1, 5)}0{random.randint(1, 9)}{random.choice(['', 'a', 'b'])}"
             classroom, _ = Classroom.objects.get_or_create(
                 identifier=identifier,
                 defaults={
                     'capacity': random.choice([20, 25, 30, 50, 100]),
                     'type': random.choice(Classroom.ClassroomType.values)
                 }
             )
             classrooms.append(classroom)
        self.stdout.write(f'  + Создано/найдено {len(classrooms)} аудиторий.')

        groups = []
        if not students or num_groups <= 0: return subjects, classrooms, groups

        students_per_group = max(1, len(students) // num_groups)
        student_list_copy = list(students)
        for i in range(num_groups):
            group_name = f"Группа-{100 + i + 1}"
            curator = random.choice(teachers) if teachers else None
            group, created = StudentGroup.objects.get_or_create(name=group_name, defaults={'curator': curator})
            groups.append(group)
            if created or not group.students.exists(): # Назначаем студентов только если группа новая или пустая
                assigned_students = []
                count_to_assign = students_per_group if i < num_groups - 1 else len(student_list_copy)
                for _ in range(count_to_assign):
                     if student_list_copy:
                         student = random.choice(student_list_copy)
                         assigned_students.append(student)
                         student_list_copy.remove(student)
                group.students.set(assigned_students)
                self.stdout.write(f'  + Создана/заполнена группа: {group_name} ({len(assigned_students)} студ.)')
            else:
                 self.stdout.write(f'  * Найдена группа: {group_name}')


        return subjects, classrooms, groups

    def create_lessons(self, num_groups, lessons_per_group_day, days_range, groups, teachers, classrooms, subjects, creators):
        self.stdout.write(f'  Попытка создания занятий (в среднем {lessons_per_group_day} на группу в день)...')
        lessons_created_count = 0
        start_date = timezone.now().date() - timedelta(days=days_range)
        end_date = timezone.now().date() + timedelta(days=days_range)
        current_date = start_date

        while current_date <= end_date:
            # Пропускаем выходные
            if current_date.weekday() >= 5: # 5 = Суббота, 6 = Воскресенье
                current_date += timedelta(days=1)
                continue

            for group in groups:
                # Слоты времени для пар (пример)
                time_slots = [
                    (time(8, 30), time(9, 50)),
                    (time(10, 5), time(11, 25)),
                    (time(11, 40), time(13, 0)),
                    (time(13, 45), time(15, 5)),
                    (time(15, 20), time(16, 40)),
                ]
                random.shuffle(time_slots)
                lessons_today = 0
                for start_t, end_t in time_slots:
                    if lessons_today >= lessons_per_group_day: break
                    if random.random() > 0.7: continue # Добавляем случайности, не каждый слот занят

                    start_dt = timezone.make_aware(timezone.datetime.combine(current_date, start_t))
                    end_dt = timezone.make_aware(timezone.datetime.combine(current_date, end_t))

                    lesson_data = {
                        'subject': random.choice(subjects),
                        'teacher': random.choice(teachers),
                        'group': group,
                        'classroom': random.choice(classrooms + [None]),
                        'lesson_type': random.choice(Lesson.LessonType.values),
                        'start_time': start_dt,
                        'end_time': end_dt,
                        'created_by': random.choice(creators) if creators else None,
                    }
                    try:
                        lesson = Lesson(**lesson_data)
                        lesson.full_clean()
                        lesson.save()
                        lessons_created_count += 1
                        lessons_today += 1
                    except Exception:
                        pass # Пропускаем при конфликте
            current_date += timedelta(days=1)
        self.stdout.write(f'  + Создано {lessons_created_count} занятий.')

    def create_news(self, num_news_categories, num_news_articles, creators):
        news_categories = []
        cat_names = ["Учеба", "Спорт", "Мероприятия", "Объявления", "Наука", "Студсовет"]
        for i in range(num_news_categories):
             name = random.choice(cat_names) + f" {i+1}"
             cat, _ = NewsCategory.objects.get_or_create(name=name, defaults={'slug': slugify(name)})
             news_categories.append(cat)
        self.stdout.write(f'  + Создано/найдено {len(news_categories)} категорий новостей.')
        if not news_categories: news_categories = [None]

        news_articles = []
        if not creators:
             self.stdout.write(self.style.WARNING('  ! Нет создателей (учителей/админов), пропуск создания новостей.'))
             return news_categories, news_articles

        for _ in range(num_news_articles):
            author = random.choice(creators)
            category = random.choice(news_categories)
            try:
                article = NewsArticle.objects.create(
                    title=fake.sentence(nb_words=random.randint(4, 8)).capitalize(),
                    content='\n\n'.join(fake.paragraphs(nb=random.randint(2, 5))),
                    category=category,
                    author=author,
                    is_published=random.choice([True, True, False])
                )
                news_articles.append(article)
            except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать новость: {e}'))
        self.stdout.write(f'  + Создано {len(news_articles)} новостей.')
        return news_categories, news_articles

    def create_news_comments_and_reactions(self, news_articles, all_users):
        self.stdout.write('  Создание комментариев и реакций к новостям...')
        comments_count = 0
        reactions_count = 0
        for article in news_articles:
            commenters = random.sample(all_users, k=min(len(all_users), random.randint(0, MAX_COMMENTS_PER_NEWS)))
            parent_comments = []
            for user in commenters:
                 try:
                     comment = NewsComment.objects.create(
                         article=article, author=user, content=fake.sentence(nb_words=random.randint(5, 25))
                     )
                     parent_comments.append(comment)
                     comments_count += 1
                     # Реакции на комментарий
                     for reactor in random.sample(all_users, k=min(len(all_users), int(len(all_users) * LIKES_RATIO))):
                         if reactor != user: # Не лайкаем свой коммент
                            try:
                                NewsReaction.objects.create(user=reactor, content_object=comment)
                                reactions_count += 1
                            except IntegrityError: pass # Уже лайкнул
                 except Exception as e: self.stderr.write(self.style.WARNING(f'   ! Ошибка создания комментария к новости {article.id}: {e}'))

                 # Ответы на комментарии
                 if parent_comments and random.random() < REPLIES_RATIO:
                     parent_comment = random.choice(parent_comments)
                     replier = random.choice(all_users)
                     if replier != parent_comment.author: # Не отвечаем сами себе
                         try:
                             reply = NewsComment.objects.create(
                                 article=article, author=replier,
                                 content=fake.sentence(nb_words=random.randint(3, 15)),
                                 parent=parent_comment
                             )
                             comments_count += 1
                             # Реакции на ответ
                             for reactor in random.sample(all_users, k=min(len(all_users), int(len(all_users) * LIKES_RATIO))):
                                if reactor != replier:
                                    try:
                                        NewsReaction.objects.create(user=reactor, content_object=reply)
                                        reactions_count += 1
                                    except IntegrityError: pass
                         except Exception as e: self.stderr.write(self.style.WARNING(f'   ! Ошибка создания ответа на комм. {parent_comment.id}: {e}'))


            # Реакции на статью
            for reactor in random.sample(all_users, k=min(len(all_users), int(len(all_users) * LIKES_RATIO))):
                 if reactor != article.author: # Не лайкаем свою статью
                    try:
                        NewsReaction.objects.create(user=reactor, content_object=article)
                        reactions_count += 1
                    except IntegrityError: pass # Уже лайкнул
        self.stdout.write(f'  + Создано {comments_count} комментариев и {reactions_count} реакций к новостям.')


    def create_forum(self, num_forum_categories, num_forum_topics, all_users):
        self.stdout.write('Создание данных форума...')
        forum_categories = []
        cat_names = ["Общие вопросы", "Помощь по предметам", "Студенческая жизнь", "Техническая поддержка", "Предложения"]
        for i in range(num_forum_categories):
             name = random.choice(cat_names) + f" {i+1}"
             cat, _ = ForumCategory.objects.get_or_create(name=name, defaults={'slug': slugify(name), 'display_order': i})
             forum_categories.append(cat)
        self.stdout.write(f'  + Создано/найдено {len(forum_categories)} категорий форума.')
        if not forum_categories: return [], [], []

        forum_topics = []
        forum_posts = []
        if not all_users:
             self.stdout.write(self.style.WARNING('  ! Нет пользователей, пропуск создания тем и постов.'))
             return forum_categories, forum_topics, forum_posts

        for _ in range(num_forum_topics):
            author = random.choice(all_users)
            category = random.choice(forum_categories)
            title = fake.sentence(nb_words=random.randint(5, 10)).capitalize().replace('.', '?')
            first_post_content = '\n\n'.join(fake.paragraphs(nb=random.randint(1, 3)))
            tags = fake.words(nb=random.randint(1, 4), unique=True)
            try:
                 # Создаем тему
                 topic = ForumTopic.objects.create(
                     category=category,
                     title=title,
                     author=author,
                     is_pinned=random.random() < 0.1,
                     is_closed=random.random() < 0.05
                 )
                 topic.tags.set(*tags) # Добавляем теги
                 forum_topics.append(topic)

                 # Создаем первый пост
                 first_post = ForumPost.objects.create(
                     topic=topic,
                     author=author,
                     content=first_post_content
                 )
                 forum_posts.append(first_post)
                 # topic.first_post = first_post # Модель Post сама обновит
                 # topic.save(update_fields=['first_post'])

                 # Создаем остальные посты и ответы
                 parent_posts_in_topic = [first_post]
                 num_topic_posts = random.randint(1, MAX_POSTS_PER_TOPIC) # От 1 (первый уже есть) до MAX
                 for _ in range(num_topic_posts -1):
                    post_author = random.choice(all_users)
                    parent_post = None
                    # Отвечаем на случайный предыдущий пост с некоторой вероятностью
                    if parent_posts_in_topic and random.random() < REPLIES_RATIO:
                        parent_post = random.choice(parent_posts_in_topic)
                        # Не отвечаем сами себе
                        if parent_post.author == post_author: parent_post = None

                    post = ForumPost.objects.create(
                        topic=topic,
                        author=post_author,
                        content=fake.sentence(nb_words=random.randint(8, 40)),
                        parent=parent_post
                    )
                    forum_posts.append(post)
                    parent_posts_in_topic.append(post) # Добавляем для возможности ответа на него

            except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать тему/пост: {e}'))
        self.stdout.write(f'  + Создано {len(forum_topics)} тем и {len(forum_posts)} постов форума.')
        return forum_categories, forum_topics, forum_posts

    def create_forum_reactions(self, forum_posts, all_users):
        self.stdout.write('  Создание реакций на посты форума...')
        reactions_count = 0
        if not all_users: return
        for post in random.sample(forum_posts, k=min(len(forum_posts), int(len(forum_posts) * 0.8))): # Лайкаем не все посты
            num_likes = random.randint(0, int(len(all_users) * LIKES_RATIO) + 1)
            reactors = random.sample(all_users, k=min(len(all_users), num_likes))
            for user in reactors:
                 if user != post.author: # Не лайкаем свой пост
                    try:
                        ForumReaction.objects.create(user=user, content_object=post)
                        reactions_count += 1
                    except IntegrityError: pass # Уже лайкнул
        self.stdout.write(f'  + Создано {reactions_count} реакций на форуме.')

    def create_chats_and_messages(self, num_private_chats, num_group_chats, all_users, groups):
        self.stdout.write('Создание чатов и сообщений...')
        chats_created = 0
        messages_created = 0
        if not all_users or len(all_users) < 2:
             self.stdout.write(self.style.WARNING('  ! Недостаточно пользователей для создания чатов.'))
             return

        # Личные чаты
        for _ in range(num_private_chats):
            user1, user2 = random.sample(all_users, k=2)
            # Проверяем, существует ли уже чат
            existing_chat = Chat.objects.filter(
                chat_type=Chat.ChatType.PRIVATE, participants=user1
            ).filter(participants=user2).first()
            if existing_chat: continue # Пропускаем, если чат есть

            try:
                chat = Chat.objects.create(chat_type=Chat.ChatType.PRIVATE, created_by=user1)
                chat.participants.set([user1, user2])
                chats_created += 1
                # Добавляем сообщения
                participants = [user1, user2]
                last_timestamp = timezone.now() - timedelta(days=random.randint(1, 5)) # Начинаем с прошлого
                for _ in range(random.randint(5, MAX_MESSAGES_PER_CHAT)):
                     sender = random.choice(participants)
                     # Сообщения идут последовательно во времени
                     last_timestamp += timedelta(minutes=random.randint(1, 120))
                     message = Message.objects.create(
                         chat=chat, sender=sender, content=fake.sentence(), timestamp=last_timestamp
                     )
                     messages_created += 1
                     chat.last_message = message # Обновляем последнее сообщение
                     chat.save(update_fields=['last_message'])

            except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать личный чат: {e}'))

        # Групповые чаты (для учебных групп)
        for group in groups:
             if not group.students.exists(): continue # Пропускаем пустые группы
             try:
                  # Создаем чат для группы, если его нет
                  chat, created = Chat.objects.get_or_create(
                      name=f"Чат группы {group.name}",
                      chat_type=Chat.ChatType.GROUP,
                      defaults={'created_by': group.curator if group.curator else random.choice(all_users)}
                  )
                  if created: chats_created += 1
                  # Добавляем всех студентов и куратора в участники
                  participants = list(group.students.all())
                  if group.curator: participants.append(group.curator)
                  chat.participants.set(participants) # Перезаписываем участников на всякий случай

                  # Добавляем сообщения
                  last_timestamp = timezone.now() - timedelta(days=random.randint(1, 3))
                  for _ in range(random.randint(10, MAX_MESSAGES_PER_CHAT)):
                       sender = random.choice(participants)
                       last_timestamp += timedelta(minutes=random.randint(1, 180))
                       message = Message.objects.create(
                           chat=chat, sender=sender, content=fake.sentence(nb_words=random.randint(4, 15)), timestamp=last_timestamp
                       )
                       messages_created += 1
                       chat.last_message = message
                       chat.save(update_fields=['last_message'])

             except Exception as e: self.stderr.write(self.style.WARNING(f'  ! Не удалось создать/заполнить групповой чат для {group.name}: {e}'))

        self.stdout.write(f'  + Создано {chats_created} чатов и {messages_created} сообщений.')

    def _get_fake_name(self):
        """Генерирует случайное мужское или женское имя/фамилию."""
        if random.random() < 0.5:
            return fake.first_name_male(), fake.last_name_male()
        else:
            return fake.first_name_female(), fake.last_name_female()