from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from messaging.models import Chat
from .models import Notification, UserNotificationSettings
from .serializers import NotificationSerializer

def send_notification(recipient, message, notification_type, related_object=None):
    """
    Создает уведомление в БД, проверяет настройки пользователя и отправляет
    уведомление через WebSocket, если разрешено.
    """
    if not recipient or not recipient.is_active:
        return # Не отправляем неактивным или несуществующим

    # 1. Проверяем настройки пользователя
    settings = UserNotificationSettings.get_settings_for_user(recipient)
    if not settings.is_enabled(notification_type):
        # print(f"Notifications '{notification_type}' disabled for user {recipient.id}")
        return # Уведомления этого типа отключены

    # 2. Создаем уведомление в БД
    content_type = None
    object_id = None
    if related_object:
        try:
            content_type = ContentType.objects.get_for_model(related_object)
            object_id = related_object.pk
        except Exception as e:
             print(f"Error getting content type for related_object: {e}")
             # Можно продолжить без связанного объекта или прервать

    notification = Notification.objects.create(
        recipient=recipient,
        message=message,
        notification_type=notification_type,
        content_type=content_type,
        object_id=object_id
    )

    # 3. Отправляем через WebSocket
    try:
        channel_layer = get_channel_layer()
        # Используем сериализатор, чтобы отправить те же данные, что и через API
        serializer = NotificationSerializer(notification)
        payload = serializer.data

        async_to_sync(channel_layer.group_send)(
            f"user_{recipient.id}", # Отправляем в личную группу пользователя
            {
                "type": "notify",       # Метод в консьюмере NotificationConsumer
                "payload": payload      # Сериализованные данные уведомления
            }
        )
        # print(f"Sent notification {notification.id} to user {recipient.id}")
    except Exception as e:
         # Логируем ошибку, но не прерываем основной процесс
         print(f"Error sending notification via WebSocket to user {recipient.id}: {e}")

# --- Вспомогательные функции для генерации сообщений (примеры) ---

def notify_new_news(news_article):
    """Уведомление о новой новости."""
    message = f"Новая новость: '{news_article.title}'"
    # Отправляем всем (или определенным ролям) - это может быть много пользователей!
    # Рассмотреть асинхронную отправку через Celery для массовых уведомлений
    users_to_notify = settings.AUTH_USER_MODEL.objects.filter(is_active=True).exclude(id=news_article.author_id) # Пример: все, кроме автора
    for user in users_to_notify:
         send_notification(user, message, Notification.NotificationType.NEWS, news_article)

def notify_schedule_change(lesson, action="изменено"):
    """Уведомление об изменении/создании/удалении занятия."""
    action_text = "Создано" if action == "создано" else "Удалено" if action == "удалено" else "Изменено"
    message = f"{action_text} занятие: {lesson.subject.name} для группы {lesson.group.name} ({lesson.start_time.strftime('%d.%m %H:%M')})"
    recipients = set()
    # Добавляем преподавателя
    if lesson.teacher: recipients.add(lesson.teacher)
    # Добавляем студентов группы
    recipients.update(lesson.group.students.filter(is_active=True))
    # Добавляем родителей студентов
    student_ids = lesson.group.students.values_list('id', flat=True)
    recipients.update(settings.AUTH_USER_MODEL.objects.filter(related_child_id__in=student_ids, is_active=True))

    # Исключаем того, кто внес изменение (если это возможно определить)
    if hasattr(lesson, 'created_by') and lesson.created_by in recipients:
         recipients.remove(lesson.created_by)

    for user in recipients:
        send_notification(user, message, Notification.NotificationType.SCHEDULE, lesson)

def notify_new_message(message_instance):
     """Уведомление о новом сообщении в чате."""
     chat = message_instance.chat
     sender = message_instance.sender
     # Краткое сообщение, т.к. полное сообщение придет по WS чата
     sender_name = sender.get_short_name()
     if chat.chat_type == Chat.ChatType.PRIVATE:
         message_text = f"Новое сообщение от {sender_name}"
     else:
         message_text = f"Новое сообщение в '{chat.name}' от {sender_name}"

     # Отправляем всем участникам чата, кроме отправителя
     recipients = chat.participants.filter(is_active=True).exclude(id=sender.id)
     for user in recipients:
          send_notification(user, message_text, Notification.NotificationType.MESSAGE, message_instance.chat) # Ссылка на чат

def notify_forum_reply(post_instance):
     """Уведомление об ответе на пост или в теме (упрощенно)."""
     # Отправляем автору родительского поста, если это ответ
     if post_instance.parent and post_instance.parent.author != post_instance.author:
          message = f"{post_instance.author.get_short_name()} ответил на ваш пост в теме '{post_instance.topic.title}'"
          send_notification(post_instance.parent.author, message, Notification.NotificationType.FORUM, post_instance)

     # TODO: Реализовать подписки на темы и уведомлять подписчиков