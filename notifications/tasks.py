from celery import shared_task
from django.utils import timezone # Импортировано для использования в notify_upcoming_homework_deadlines
from .utils import notify_upcoming_homework_deadlines # Импорт функции из utils.py
import logging

logger = logging.getLogger(__name__)

# Декоратор @shared_task регистрирует эту функцию как задачу Celery.
# Это означает, что она может быть вызвана асинхронно и выполняться
# воркером Celery отдельно от основного потока веб-приложения.
# - name="send_homework_deadline_reminders": Явно задает имя задачи.
#   Это полезно для идентификации и управления задачей.
#
# Функция send_homework_deadline_reminders_task предназначена для периодического
# запуска (например, раз в день с помощью Celery Beat) для отправки напоминаний
# студентам о приближающихся сроках сдачи домашних заданий.
# - days_before: Параметр, указывающий, за сколько дней до дедлайна отправлять напоминание.
#   По умолчанию равен 3 дням.
#
# Принцип работы:
# 1. Логгирует начало выполнения задачи.
# 2. Вызывает функцию `notify_upcoming_homework_deadlines` из `notifications.utils`,
#    передавая ей параметр `days_before` (как `days_threshold`).
#    Эта функция содержит основную логику по поиску домашних заданий
#    с подходящими сроками и отправке уведомлений студентам.
# 3. Логгирует успешное завершение задачи.
# 4. В случае возникновения исключения, логгирует ошибку и перевыбрасывает исключение,
#    чтобы Celery мог зафиксировать сбой задачи и, возможно, применить
#    механизмы повторного выполнения (если они настроены).
@shared_task(name="send_homework_deadline_reminders")
def send_homework_deadline_reminders_task(days_before=3):
    logger.info(f"Celery task: Starting send_homework_deadline_reminders_task (days_before={days_before}).")
    try:
        notify_upcoming_homework_deadlines(days_threshold=days_before)
        logger.info(f"Celery task: Finished send_homework_deadline_reminders_task successfully.")
        return f"Reminders sent for homework due in {days_before} days."
    except Exception as e:
        logger.error(f"Celery task: Error in send_homework_deadline_reminders_task: {e}", exc_info=True)
        raise