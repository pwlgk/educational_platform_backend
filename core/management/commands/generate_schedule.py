import random
from datetime import timedelta, time, date
from django.db.models import Q
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from faker import Faker
from jsonschema import ValidationError

# Импортируем модели из schedule и users
from schedule.models import Subject, StudentGroup, Classroom, Lesson
from users.models import User

fake = Faker('ru_RU')

# --- Константы для генерации расписания ---
WORK_START_HOUR = 8
WORK_END_HOUR = 18 # До какого часа могут идти занятия
LESSON_DURATIONS_MINUTES = [45, 80, 90] # Возможные длительности пар
BREAK_MINUTES = 10 # Минимальный перерыв между парами
MAX_LESSONS_PER_DAY = 6 # Максимальное количество пар в день у группы/преподавателя
MAX_RETRIES = 15 # Макс. попыток найти слот для одного занятия

class Command(BaseCommand):
    help = 'Генерирует тестовое расписание занятий на указанный период.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Удалить существующие занятия перед генерацией.',
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Дата начала генерации (YYYY-MM-DD). По умолчанию: сегодня.',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            required=True, # Конечная дата обязательна
            help='Дата окончания генерации (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--lessons-per-group-day',
            type=int,
            default=4,
            help='Среднее желаемое количество уроков у группы в день.',
        )
        parser.add_argument(
            '--skip-weekends',
            action='store_true',
            help='Пропускать субботу и воскресенье при генерации.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        clear_data = options['clear']
        start_date_str = options['start_date']
        end_date_str = options['end_date']
        lessons_per_group_day = options['lessons_per_group_day']
        skip_weekends = options['skip_weekends']

        # --- Валидация дат ---
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else timezone.now().date()
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            raise CommandError("Неверный формат даты. Используйте YYYY-MM-DD.")

        if start_date > end_date:
            raise CommandError("Дата начала не может быть позже даты окончания.")

        # --- Очистка старого расписания ---
        if clear_data:
            self.stdout.write(self.style.WARNING(f'Удаление существующих занятий в диапазоне с {start_date} по {end_date}...'))
            deleted_count, _ = Lesson.objects.filter(
                start_time__date__gte=start_date,
                start_time__date__lte=end_date # Включая конечную дату
            ).delete()
            self.stdout.write(self.style.SUCCESS(f'Удалено {deleted_count} занятий.'))

        # --- Получаем необходимые данные ---
        self.stdout.write('Получение данных для генерации...')
        subjects = list(Subject.objects.all())
        teachers = list(User.objects.filter(role=User.Role.TEACHER, is_active=True))
        groups = list(StudentGroup.objects.prefetch_related('students').all())
        classrooms = list(Classroom.objects.all())
        # Администраторы или учителя, которые могут быть 'created_by'
        creators = list(User.objects.filter(Q(role=User.Role.ADMIN) | Q(role=User.Role.TEACHER), is_active=True))

        if not all([subjects, teachers, groups, classrooms, creators]):
             missing = [name for name, data in [("предметы", subjects), ("преподаватели", teachers), ("группы", groups), ("аудитории", classrooms), ("создатели (админ/учитель)", creators)] if not data]
             raise CommandError(f"Недостаточно данных для генерации расписания. Отсутствуют: {', '.join(missing)}.")

        self.stdout.write(f"Найдено: {len(subjects)} предм., {len(teachers)} препод., {len(groups)} групп, {len(classrooms)} аудит.")

        # --- Генерация расписания по дням и группам ---
        self.stdout.write(f'Генерация расписания с {start_date} по {end_date}...')
        total_lessons_created = 0
        current_date = start_date

        while current_date <= end_date:
            day_str = current_date.strftime('%Y-%m-%d (%a)')
            if skip_weekends and current_date.weekday() >= 5: # 5=Sat, 6=Sun
                self.stdout.write(f'  {day_str} - Пропуск выходного.')
                current_date += timedelta(days=1)
                continue

            self.stdout.write(f'  {day_str}:')
            lessons_on_this_day = 0
            # Пытаемся создать занятия для каждой группы
            for group in groups:
                lessons_for_group_today = 0
                # Пытаемся создать желаемое кол-во занятий + немного случайности
                target_lessons = random.randint(max(0, lessons_per_group_day - 1), lessons_per_group_day + 1)

                # Генерируем слоты времени для пар
                available_slots = self._get_time_slots(current_date)
                random.shuffle(available_slots) # Перемешиваем слоты

                retries_group = 0 # Попытки для группы
                while lessons_for_group_today < target_lessons and retries_group < MAX_LESSONS_PER_DAY * 2 and available_slots:
                    slot = available_slots.pop(0) # Берем следующий слот
                    start_dt, end_dt = slot
                    retries_group += 1

                    # Пытаемся найти подходящие ресурсы для этого слота
                    assigned = False
                    for _ in range(MAX_RETRIES): # Попытки найти учителя/аудиторию
                        teacher = random.choice(teachers)
                        subject = random.choice(subjects)
                        classroom = random.choice(classrooms + [None] * 5) # Чаще без аудитории для гибкости
                        creator = random.choice(creators)

                        lesson = Lesson(
                            subject=subject, teacher=teacher, group=group, classroom=classroom,
                            start_time=start_dt, end_time=end_dt,
                            lesson_type=random.choice(Lesson.LessonType.values),
                            created_by=creator
                        )

                        try:
                            lesson.full_clean() # Проверяем пересечения и ограничения
                            lesson.save()
                            total_lessons_created += 1
                            lessons_for_group_today += 1
                            lessons_on_this_day += 1
                            assigned = True
                            # self.stdout.write(f'    + {group.name}: {subject.name} ({start_dt.strftime("%H:%M")}) - Успешно')
                            break # Переходим к следующему слоту для этой группы
                        except ValidationError:
                            continue # Пробуем другую комбинацию учителя/аудитории

                    # Если не смогли назначить за MAX_RETRIES, слот остается свободным
                    # if not assigned:
                    #    self.stdout.write(f'    - {group.name}: Не удалось найти слот/ресурсы для {start_dt.strftime("%H:%M")}')


            self.stdout.write(f'    Итого за день создано: {lessons_on_this_day} занятий.')
            current_date += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(f'\nГенерация расписания завершена. Всего создано: {total_lessons_created} занятий.'))


    def _get_time_slots(self, current_date: date) -> list[tuple[timezone.datetime, timezone.datetime]]:
        """Генерирует список возможных временных слотов для занятий на день."""
        slots = []
        current_time = time(WORK_START_HOUR, 0)
        end_work_time = time(WORK_END_HOUR, 0)

        while current_time < end_work_time:
            duration_minutes = random.choice(LESSON_DURATIONS_MINUTES)
            start_dt_naive = timezone.datetime.combine(current_date, current_time)
            end_dt_naive = start_dt_naive + timedelta(minutes=duration_minutes)

            # Проверяем, не выходит ли занятие за пределы рабочего дня
            if end_dt_naive.time() > end_work_time:
                break # Не начинаем пару, если она закончится после WORK_END_HOUR

            start_dt_aware = timezone.make_aware(start_dt_naive)
            end_dt_aware = timezone.make_aware(end_dt_naive)
            slots.append((start_dt_aware, end_dt_aware))

            # Переходим к началу следующей возможной пары (через перерыв)
            next_start_naive = end_dt_naive + timedelta(minutes=BREAK_MINUTES)
            current_time = next_start_naive.time()

        return slots