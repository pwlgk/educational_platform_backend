import logging
from mailbox import Message
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.utils import timezone

from edu_core.models import AcademicYear, Grade, Homework, HomeworkSubmission, Lesson, StudentGroup, StudyPeriod
from messaging.models import Chat, Message
from users.models import User # Импортировано для notify_upcoming_homework_deadlines


from .models import Notification, UserNotificationSettings
from .serializers import NotificationSerializer

logger = logging.getLogger(__name__)

# Функция send_notification является централизованным механизмом для создания
# и отправки уведомлений пользователям.
# Параметры:
#   - recipient: Объект пользователя, которому предназначено уведомление.
#   - message_text: Текст уведомления.
#   - notification_type_value: Строковое значение типа уведомления (из Notification.NotificationType).
#   - related_object: (Опционально) Объект модели, с которым связано уведомление (для GenericForeignKey).
# Принцип работы:
# 1. Проверяет, активен ли получатель.
# 2. Получает или создает настройки уведомлений для пользователя (UserNotificationSettings).
# 3. Проверяет, включены ли у пользователя уведомления данного типа. Если нет, отправка пропускается.
# 4. Если передан `related_object`, получает для него ContentType и object_id.
# 5. Создает экземпляр модели Notification в базе данных.
# 6. Сериализует созданное уведомление с помощью NotificationSerializer.
# 7. Отправляет сериализованное уведомление через WebSocket (Django Channels)
#    в персональную группу пользователя (`user_{recipient.id}`).
#    Предполагается, что NotificationConsumer подписан на эту группу и обработает событие
#    с типом "new_notification".
# 8. Логирует ошибки на каждом этапе.
def send_notification(
    recipient: User,
    message_text: str, 
    notification_type_value: str, 
    related_object: Model | None = None
):
    if not isinstance(recipient, User) or not recipient.is_active:
        logger.warning(f"Attempted to send notification to invalid or inactive recipient: {recipient}")
        return

    try:
        user_settings, created = UserNotificationSettings.objects.get_or_create(user=recipient)
        if created:
            logger.info(f"Created default notification settings for user {recipient.id}")

        if not user_settings.is_enabled(notification_type_value):
            logger.debug(f"Notifications '{notification_type_value}' disabled for user {recipient.id}. Skipping.")
            return
    except Exception as e:
         logger.error(f"Error getting/creating notification settings for user {recipient.id}: {e}", exc_info=True)
         return

    content_type_instance = None
    object_id_value = None
    if related_object and isinstance(related_object, Model) and related_object.pk:
        try:
            content_type_instance = ContentType.objects.get_for_model(related_object)
            object_id_value = related_object.pk
        except Exception as e:
             logger.error(f"Error getting content type for related_object {related_object.__class__.__name__} (pk={getattr(related_object, 'pk', 'N/A')}): {e}", exc_info=True)

    try:
        notification_instance = Notification.objects.create(
            recipient=recipient,
            message=message_text,
            notification_type=notification_type_value,
            content_type=content_type_instance,
            object_id=object_id_value
        )
    except Exception as e:
         logger.error(f"Error creating Notification object in DB for user {recipient.id} (type: {notification_type_value}): {e}", exc_info=True)
         return 

    try:
        channel_layer = get_channel_layer()
        serializer = NotificationSerializer(notification_instance)
        payload = serializer.data
        user_group_name = f"user_{recipient.id}"

        async_to_sync(channel_layer.group_send)(
            user_group_name,
            {
                "type": "new_notification", 
                "notification": payload
            }
        )
        logger.info(f"Sent WS notification (ID: {notification_instance.id}, Type: {notification_type_value}) to user {recipient.id} via group {user_group_name}")
    except Exception as e:
         logger.error(f"Error sending WS notification (ID: {notification_instance.id}) to user {recipient.id}: {e}", exc_info=True)

# --- Функции для отправки уведомлений, связанных с модулем edu_core ---

# Уведомляет участников (преподавателя и студентов группы) об изменении,
# создании или удалении занятия в расписании.
def notify_lesson_change(lesson: Lesson, action="изменено"):
    if not Lesson: # Проверка, что модель Lesson была успешно импортирована
        logger.error("notify_lesson_change: Lesson model not imported.")
        return
    try:
        action_text_map = {"создано": "Создано", "удалено": "Удалено"}
        action_text = action_text_map.get(action, "Изменено")

        subject_name = getattr(lesson.subject, 'name', 'Неизвестный предмет')
        group_name = getattr(lesson.student_group, 'name', 'Неизвестная группа')
        start_time_str = lesson.start_time.strftime('%d.%m %H:%M') if lesson.start_time else 'Неизвестное время'
        message = f"{action_text} занятие: {subject_name} для группы {group_name} ({start_time_str})"

        recipients = set()
        if lesson.teacher and lesson.teacher.is_active:
            recipients.add(lesson.teacher)
        if hasattr(lesson, 'student_group') and lesson.student_group and hasattr(lesson.student_group, 'students'):
            recipients.update(lesson.student_group.students.filter(is_active=True))
            # Логика уведомления родителей студентов здесь может быть добавлена при необходимости

        logger.info(f"Notifying {len(recipients)} users about schedule change for lesson {lesson.id}")
        for user_recipient in recipients:
            send_notification(user_recipient, message, Notification.NotificationType.SCHEDULE, lesson)
    except Exception as e:
        logger.error(f"Error preparing schedule notification for lesson {getattr(lesson, 'id', 'N/A')}: {e}", exc_info=True)

# Уведомляет студентов группы о назначении нового домашнего задания.
def notify_new_homework(homework: Homework):
    if not Homework or not Lesson:
        logger.error("notify_new_homework: Homework or Lesson model not imported.")
        return
    try:
        lesson_subject_name = "Неизвестный предмет"
        group_students = set()

        if homework.journal_entry and homework.journal_entry.lesson:
            lesson_instance = homework.journal_entry.lesson
            if lesson_instance.subject:
                lesson_subject_name = lesson_instance.subject.name
            if hasattr(lesson_instance, 'student_group') and lesson_instance.student_group and hasattr(lesson_instance.student_group, 'students'):
                group_students.update(lesson_instance.student_group.students.filter(is_active=True))

        message = f"Новое домашнее задание: '{homework.title}' по предмету '{lesson_subject_name}'"
        
        logger.info(f"Notifying {len(group_students)} students about new homework {homework.id}")
        for student in group_students:
            send_notification(student, message, Notification.NotificationType.ASSIGNMENT_NEW, homework)
    except Exception as e:
        logger.error(f"Error preparing new homework notification for homework {getattr(homework, 'id', 'N/A')}: {e}", exc_info=True)

# Уведомляет студента о том, что его домашнее задание проверено и оценено.
def notify_homework_graded(submission: HomeworkSubmission):
    if not HomeworkSubmission or not Grade:
        logger.error("notify_homework_graded: HomeworkSubmission or Grade model not imported.")
        return
    try:
        grade_value_str = "оценено" # По умолчанию, если оценка не найдена
        grade_instance = getattr(submission, 'grade_for_submission', None)
        if grade_instance and grade_instance.grade_value:
            grade_value_str = grade_instance.grade_value

        message = f"Ваше домашнее задание '{submission.homework.title}' проверено. Результат: {grade_value_str}"
        if submission.student and submission.student.is_active:
            send_notification(submission.student, message, Notification.NotificationType.ASSIGNMENT_GRADED, submission)
    except Exception as e:
        logger.error(f"Error preparing homework graded notification for submission {getattr(submission, 'id', 'N/A')}: {e}", exc_info=True)

# Уведомляет студента (и опционально родителей) о выставлении новой оценки.
def notify_new_grade(grade: Grade):
    if not Grade or not Lesson or not Homework or not StudyPeriod or not AcademicYear:
        logger.error("notify_new_grade: One or more required models not imported.")
        return
    try:
        grade_type_display = grade.get_grade_type_display()
        subject_name = getattr(grade.subject, 'name', 'N/A')
        details = ""
        related_obj_for_notification = grade 

        if grade.lesson:
            details = f" за занятие {grade.lesson.start_time.strftime('%d.%m') if grade.lesson.start_time else 'N/A'}"
            related_obj_for_notification = grade.lesson
        elif grade.homework_submission:
            details = f" за ДЗ '{getattr(grade.homework_submission.homework, 'title', 'N/A')}'"
            related_obj_for_notification = grade.homework_submission
        elif grade.grade_type in [Grade.GradeType.PERIOD_FINAL, Grade.GradeType.PERIOD_AVERAGE] and grade.study_period:
            details = f" за {getattr(grade.study_period, 'name', 'N/A')}"
        elif grade.grade_type in [Grade.GradeType.YEAR_FINAL, Grade.GradeType.YEAR_AVERAGE] and grade.academic_year:
            details = f" за {getattr(grade.academic_year, 'name', 'N/A')} год"

        message = f"Новая оценка: {grade.grade_value} по предмету '{subject_name}' ({grade_type_display}{details})"
        recipients = set()
        if grade.student and grade.student.is_active:
            recipients.add(grade.student)
        # Логика уведомления родителей здесь может быть добавлена

        logger.info(f"Notifying {len(recipients)} users about new grade {grade.id}")
        for user_recipient in recipients:
            send_notification(user_recipient, message, Notification.NotificationType.GRADE_NEW, related_obj_for_notification)
    except Exception as e:
        logger.error(f"Error preparing new grade notification for grade {getattr(grade, 'id', 'N/A')}: {e}", exc_info=True)


# --- Функции для отправки уведомлений, связанных с модулем messaging ---

# Уведомляет участников чата (кроме отправителя) о новом сообщении.
# Вызывается из сигнала post_save для модели Message.
def notify_new_message(message_instance: Message):
     if not Message or not Chat: 
         logger.error("notify_new_message: Message or Chat model not imported.")
         return
     try:
        chat = message_instance.chat
        sender = message_instance.sender
        sender_name = sender.get_full_name() or sender.email # Имя или email

        content_preview = ""
        if message_instance.content:
            content_preview = message_instance.content[:30] + '...' if len(message_instance.content) > 30 else message_instance.content
        elif message_instance.file:
            content_preview = "Прикреплен файл"

        if chat.chat_type == Chat.ChatType.PRIVATE:
             other_participant = chat.get_other_participant(sender)
             # Проверяем, что other_participant не None перед вызовом методов
             other_name = getattr(other_participant, 'get_full_name', lambda: getattr(other_participant, 'email', 'N/A'))() if other_participant else "Собеседник"
             message_text_for_notification = f"{sender_name} - {content_preview}"
        else: # Групповой чат
             chat_name = chat.name or "Групповой чат"
             message_text_for_notification = f"{chat_name}: {sender_name} - {content_preview}"

        recipients = chat.participants.filter(is_active=True).exclude(id=sender.id)
        logger.info(f"Notifying (main notification system) {recipients.count()} users about new message {message_instance.id} in chat {chat.id}")

        for user_recipient in recipients:
            try:
                 send_notification(user_recipient, message_text_for_notification, Notification.NotificationType.MESSAGE, chat)
            except Exception as e:
                 logger.error(f"Failed to send main message notification to user {user_recipient.id} for chat {chat.id}: {e}", exc_info=True)
     except Exception as e:
          logger.error(f"Error preparing main message notification for message {getattr(message_instance, 'id', 'N/A')}: {e}", exc_info=True)

# Уведомляет пользователя о том, что его добавили в чат.
# actor - пользователь, который совершил действие (добавил).
def notify_added_to_chat(chat: Chat, added_user: User, actor: User | None = None):
    if not Chat or not User:
        logger.error("notify_added_to_chat: Chat or User model not imported.")
        return
    try:
        other_participant_for_private = chat.get_other_participant(added_user) if chat.chat_type == Chat.ChatType.PRIVATE else None
        chat_name_display = chat.name if chat.chat_type == Chat.ChatType.GROUP else \
                           (f"личный чат с {other_participant_for_private.get_full_name()}" if other_participant_for_private else "личный чат")
        
        actor_name = ""
        if actor:
            actor_name = actor.get_full_name() or actor.email

        # Не отправляем уведомление, если пользователь сам себя добавляет в приватный чат (что не должно происходить)
        if chat.chat_type == Chat.ChatType.PRIVATE and actor and actor == added_user:
            return

        if actor: # Если действие совершил другой пользователь
            message = f"{actor_name} добавил(а) Вас в чат '{chat_name_display}'."
        else: # Если actor не указан (например, системное добавление)
            message = f"Вы были добавлены в чат '{chat_name_display}'."

        send_notification(added_user, message, Notification.NotificationType.MESSAGE, chat)
    except Exception as e:
        logger.error(f"Error preparing 'added to chat' notification for user {added_user.id}, chat {getattr(chat, 'id', 'N/A')}: {e}", exc_info=True)

# Уведомляет пользователя о том, что его удалили из чата или он сам покинул чат.
# actor - пользователь, который совершил действие (удалил), или None, если пользователь сам покинул.
def notify_removed_from_chat(chat: Chat, removed_user: User, actor: User | None = None):
    if not Chat or not User:
        logger.error("notify_removed_from_chat: Chat or User model not imported.")
        return
    try:
        chat_name_display = chat.name if chat.chat_type == Chat.ChatType.GROUP else "личный чат"
        notification_type_value = Notification.NotificationType.SYSTEM # Системное уведомление

        if actor and actor != removed_user: # Если удалил другой пользователь
            actor_name = actor.get_full_name() or actor.email
            message = f"Вы были удалены из чата '{chat_name_display}' пользователем {actor_name}."
        elif actor == removed_user: # Если пользователь сам себя "удалил" (покинул)
            message = f"Вы покинули чат '{chat_name_display}'."
        else: # Если actor не указан (пользователь покинул сам)
            message = f"Вы покинули чат '{chat_name_display}'."

        send_notification(removed_user, message, notification_type_value, chat)
    except Exception as e:
        logger.error(f"Error preparing 'removed from chat' notification for user {removed_user.id}, chat {getattr(chat, 'id', 'N/A')}: {e}", exc_info=True)

# Отправляет напоминания студентам о приближающихся сроках сдачи домашних заданий.
# Предназначена для вызова периодической задачей (например, Celery beat).
def notify_upcoming_homework_deadlines(days_threshold=3):
    if not Homework or not HomeworkSubmission or not StudentGroup:
        logger.error("notify_upcoming_homework_deadlines: Required models (Homework, HomeworkSubmission, StudentGroup) not imported.")
        return

    now = timezone.now()
    deadline_limit_start = now
    deadline_limit_end = now + timezone.timedelta(days=days_threshold)

    upcoming_homeworks = Homework.objects.filter(
        due_date__gte=deadline_limit_start,
        due_date__lte=deadline_limit_end
    ).select_related(
        'journal_entry__lesson__student_group',
        'journal_entry__lesson__subject'
    ).prefetch_related(
        'journal_entry__lesson__student_group__students'
    )

    logger.info(f"Checking for upcoming homework deadlines (next {days_threshold} days). Found {upcoming_homeworks.count()} relevant homeworks.")

    for hw in upcoming_homeworks:
        if not hw.journal_entry or not hw.journal_entry.lesson or not hw.journal_entry.lesson.student_group:
            logger.warning(f"Homework ID {hw.id} is missing necessary linked lesson/group. Skipping.")
            continue

        submitted_students_ids = HomeworkSubmission.objects.filter(
            homework=hw
        ).values_list('student_id', flat=True)

        students_to_notify = hw.journal_entry.lesson.student_group.students.filter(
            is_active=True
        ).exclude(
            id__in=submitted_students_ids
        )

        if not students_to_notify.exists():
            logger.info(f"All students submitted or no students to notify for HW ID {hw.id} ('{hw.title}').")
            continue

        due_date_str = hw.due_date.strftime('%d.%m.%Y %H:%M') if hw.due_date else "N/A"
        subject_name = hw.journal_entry.lesson.subject.name if hw.journal_entry.lesson.subject else "N/A"
        message = f"Напоминание: срок сдачи ДЗ '{hw.title}' по предмету '{subject_name}' истекает {due_date_str}."
        
        logger.info(f"Notifying {students_to_notify.count()} students about upcoming deadline for HW ID {hw.id} ('{hw.title}').")
        for student in students_to_notify:
            send_notification(student, message, Notification.NotificationType.ASSIGNMENT_DUE, hw)