# notifications/utils.py
import logging
import traceback # Для детального логирования ошибок
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
# --- ИМПОРТИРУЕМ get_user_model ---
from django.contrib.auth import get_user_model

# Импортируем нужные модели в начале файла, если это возможно
# Если возникают циклические зависимости, импортируйте внутри функций
from django.db.models import Model # Для type hinting
from messaging.models import Chat, Message
from news.models import NewsArticle # Предполагаем, что модель новостей здесь
from edu_core.models import Lesson # Предполагаем, что модель занятий здесь
# from forum.models import Post # Если есть форум
from .models import Notification, UserNotificationSettings # Убедитесь, что путь верный
from .serializers import NotificationSerializer

# --- Получаем модель пользователя ОДИН РАЗ ---
User = get_user_model()
logger = logging.getLogger(__name__) # <-- Инициализируем логгер

def send_notification(
    recipient: User, # type: ignore
    message: str,
    notification_type: str, # Используем строковый тип для NotificationType
    related_object: Model | None = None # Используем базовый Model для type hinting
):
    """
    Создает уведомление в БД, проверяет настройки пользователя и отправляет
    уведомление через WebSocket, если разрешено.
    """
    # Проверяем, что recipient - это экземпляр User, а не строка или None
    if not isinstance(recipient, User) or not recipient.is_active:
        logger.warning(f"Attempted to send notification to invalid recipient: {recipient}")
        return # Не отправляем неактивным или некорректным получателям

    # 1. Проверяем настройки пользователя
    try:
        # Используем get_or_create для большей надежности
        settings, created = UserNotificationSettings.objects.get_or_create(user=recipient)
        if created:
            logger.info(f"Created default notification settings for user {recipient.id}")
        if not settings.is_enabled(notification_type):
            logger.debug(f"Notifications '{notification_type}' disabled for user {recipient.id}")
            return # Уведомления этого типа отключены
    except Exception as e:
         logger.error(f"Error getting/creating notification settings for user {recipient.id}: {e}", exc_info=True)
         # Продолжаем отправку? Или прерываем? Пока продолжаем.
         # return

    # 2. Создаем уведомление в БД
    content_type = None
    object_id = None
    if related_object and isinstance(related_object, Model) and related_object.pk:
        try:
            content_type = ContentType.objects.get_for_model(related_object)
            object_id = related_object.pk
        except Exception as e:
             logger.error(f"Error getting content type for related_object {related_object.__class__.__name__} (pk={related_object.pk}): {e}", exc_info=True)
             # Продолжаем без связанного объекта

    try:
        notification = Notification.objects.create(
            recipient=recipient,
            message=message,
            notification_type=notification_type,
            content_type=content_type,
            object_id=object_id
        )
    except Exception as e:
         logger.error(f"Error creating notification in DB for user {recipient.id}: {e}", exc_info=True)
         return # Не удалось создать в БД, не отправляем по WS

    # 3. Отправляем через WebSocket
    try:
        channel_layer = get_channel_layer()
        # Сериализуем СОЗДАННЫЙ объект уведомления
        serializer = NotificationSerializer(notification) # Предполагаем, что такой сериализатор есть
        payload = serializer.data

        # Имя группы для пользователя
        user_group_name = f"user_{recipient.id}"

        async_to_sync(channel_layer.group_send)(
            user_group_name,
            {
                # Используем имя метода-обработчика в NotificationConsumer
                "type": "new.notification", # ИЛИ просто "notify", в зависимости от консьюмера
                "notification": payload # Отправляем сериализованные данные
            }
        )
        logger.info(f"Sent notification {notification.id} to user {recipient.id} via group {user_group_name}")
    except Exception as e:
         # Логируем ошибку, но не прерываем основной процесс
         logger.error(f"Error sending notification via WebSocket to user {recipient.id}: {e}", exc_info=True)

# --- Вспомогательные функции для генерации сообщений ---

def notify_new_news(news_article: NewsArticle):
    """Уведомление о новой опубликованной новости."""
    if not news_article or not news_article.is_published:
         logger.debug(f"Notification for news article {news_article.id} skipped (not published or invalid).")
         return

    # --- ИСПРАВЛЕНИЕ: Формируем текст уведомления ---
    message = f"Новая новость: '{news_article.title[:50]}...'" # Обрезаем заголовок
    author_id = getattr(news_article, 'author_id', None)

    try:
         queryset = User.objects.filter(is_active=True)
         if author_id:
              queryset = queryset.exclude(id=author_id) # Исключаем автора

         users_to_notify = queryset
         logger.info(f"Notifying {users_to_notify.count()} users about news {news_article.id}")

         for user in users_to_notify:
             try:
                 send_notification(user, message, Notification.NotificationType.NEWS, news_article)
             except Exception as e:
                 logger.error(f"Failed to send news notification to user {user.id} for article {news_article.id}: {e}", exc_info=True)
    except Exception as e:
         logger.error(f"Error getting users to notify for news {news_article.id}: {e}", exc_info=True)


def notify_schedule_change(lesson: Lesson, action="изменено"):
    """Уведомление об изменении/создании/удалении занятия."""
    try:
        action_text_map = {"создано": "Создано", "удалено": "Удалено"}
        action_text = action_text_map.get(action, "Изменено") # Default to "Изменено"

        # Проверяем наличие связанных объектов
        subject_name = getattr(lesson.subject, 'name', 'Неизвестный предмет')
        group_name = getattr(lesson.group, 'name', 'Неизвестная группа')
        start_time_str = lesson.start_time.strftime('%d.%m %H:%M') if lesson.start_time else 'Неизвестное время'

        message = f"{action_text} занятие: {subject_name} для группы {group_name} ({start_time_str})"

        recipients = set()
        # Добавляем студентов группы
        if hasattr(lesson.group, 'students'):
            recipients.update(lesson.group.students.filter(is_active=True))
        # Добавляем преподавателя
        if lesson.teacher and lesson.teacher.is_active:
            recipients.add(lesson.teacher)
        # Добавляем родителей студентов
        if hasattr(lesson.group, 'students'):
            student_ids = lesson.group.students.values_list('id', flat=True)
            # Предполагаем, что у User есть поле related_child или students для связи с родителем
            # Адаптируйте 'related_child_id__in' под вашу модель User/Parent
            parents = User.objects.filter(role=User.Role.PARENT, related_child_id__in=student_ids, is_active=True)
            recipients.update(parents)

        # Исключаем инициатора действия (если он передан в контексте, иначе сложно)
        # initiator = getattr(lesson, '_initiator', None) # Пример
        # if initiator and initiator in recipients:
        #     recipients.remove(initiator)

        logger.info(f"Notifying {len(recipients)} users about schedule change for lesson {lesson.id}")
        for user in recipients:
            try:
                 send_notification(user, message, Notification.NotificationType.SCHEDULE, lesson)
            except Exception as e:
                 logger.error(f"Failed to send schedule notification to user {user.id} for lesson {lesson.id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error preparing schedule notification for lesson {lesson.id}: {e}", exc_info=True)


def notify_new_message(message_instance: Message):
     """Уведомление о новом сообщении в чате."""
     try:
        chat = message_instance.chat
        sender = message_instance.sender
        sender_name = sender.get_full_name() or sender.get_username()
        content_preview = message_instance.content[:50] + '...' if message_instance.content and len(message_instance.content) > 50 else message_instance.content
        if message_instance.file and not content_preview: content_preview = "Attachment"

        # --- ИСПРАВЛЕНИЕ: Ошибка NameError была здесь ---
        if chat.chat_type == Chat.ChatType.PRIVATE:
             # Используем переменную sender_name, которая уже определена
             message_text = f"{sender_name}: {content_preview}"
        else:
             chat_name = chat.name or "Group Chat"
             # Используем переменную sender_name
             message_text = f"{sender_name} in {chat_name}: {content_preview}"
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        recipients = chat.participants.filter(is_active=True).exclude(id=sender.id)
        logger.info(f"Notifying {recipients.count()} users about new message {message_instance.id} in chat {chat.id}")

        for user in recipients:
            try:
                 # Передаем сформированный message_text
                 send_notification(user, message_text, Notification.NotificationType.MESSAGE, chat)
                 # --- ВЫЗЫВАЕМ ОБНОВЛЕНИЕ СЧЕТЧИКА ДЛЯ ПОЛУЧАТЕЛЯ ---
                 # Это нужно, чтобы WS сразу отправил правильный счетчик
                 # Создаем экземпляр ChatViewSet для вызова метода (не самый элегантный способ, но рабочий)
                 # Лучше вынести notify_user_unread_update в utils, если возможно
                 try:
                     from messaging.views import ChatViewSet # Импорт здесь, чтобы избежать цикла
                     chat_viewset = ChatViewSet()
                     chat_viewset.notify_user_unread_update(user, chat.pk)
                 except Exception as e_notify_ws:
                      logger.error(f"Failed to send WS unread update to user {user.id} for chat {chat.id} after sending notification: {e_notify_ws}", exc_info=True)
                 # --- КОНЕЦ ВЫЗОВА ОБНОВЛЕНИЯ СЧЕТЧИКА ---
            except Exception as e:
                 logger.error(f"Failed to send message notification to user {user.id} for chat {chat.id}: {e}", exc_info=True)
     except Exception as e:
          logger.error(f"Error preparing message notification for message {message_instance.id}: {e}", exc_info=True)

# Уведомление для форума (оставляем как есть, но с try-except)
def notify_forum_reply(post_instance):
     """Уведомление об ответе на пост или в теме (упрощенно)."""
     try:
        # Уведомляем автора родительского поста, если это не автор ответа
        if post_instance.parent and post_instance.parent.author != post_instance.author:
            parent_author = getattr(post_instance.parent, 'author', None)
            if parent_author and parent_author.is_active: # Проверяем активность
                 # Используем get_full_name или username
                 author_name = post_instance.author.get_full_name() or post_instance.author.get_username()
                 topic_title = getattr(post_instance.topic, 'title', 'the topic') # Безопасное получение заголовка темы
                 message = f"{author_name} replied to your post in '{topic_title}'"
                 try:
                      send_notification(parent_author, message, Notification.NotificationType.FORUM, post_instance)
                 except Exception as e:
                      logger.error(f"Failed to send forum reply notification to user {parent_author.id} for post {post_instance.id}: {e}", exc_info=True)
            else:
                 logger.warning(f"Parent author not found or inactive for post {getattr(post_instance.parent, 'id', 'N/A')}, cannot notify about reply {post_instance.id}")

        # TODO: Уведомлять подписчиков темы
     except Exception as e:
          logger.error(f"Error preparing forum reply notification for post {post_instance.id}: {e}", exc_info=True)