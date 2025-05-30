from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Lesson, Homework, HomeworkSubmission, Grade
from notifications.utils import (
    notify_lesson_change, notify_new_homework,
    notify_homework_graded, notify_new_grade
)
from notifications.models import Notification # Импорт для Notification.NotificationType
from notifications.utils import send_notification # Импорт для прямого вызова send_notification

# Функция-обработчик сигнала lesson_saved_or_updated_receiver.
# Этот обработчик автоматически вызывается после сохранения (создания или обновления)
# экземпляра модели Lesson.
# - sender: Модель, отправившая сигнал (Lesson).
# - instance: Экземпляр модели Lesson, который был сохранен.
# - created: Булево значение, истинное, если объект был создан, и ложное, если обновлен.
# Принцип работы:
# 1. Определяет действие ("создано" или "изменено") в зависимости от значения `created`.
# 2. Вызывает функцию `notify_lesson_change` из `notifications.utils` для отправки
#    уведомления об этом событии соответствующим пользователям (преподавателю, студентам группы).
@receiver(post_save, sender=Lesson)
def lesson_saved_or_updated_receiver(sender, instance, created, **kwargs):
    action = "создано" if created else "изменено"
    notify_lesson_change(instance, action=action)

# Функция-обработчик сигнала homework_submission_status_changed.
# Вызывается после сохранения экземпляра модели HomeworkSubmission.
# - instance: Экземпляр HomeworkSubmission.
# - created: True, если сдача ДЗ была только что создана.
# Принцип работы:
# 1. Если сдача ДЗ была создана (`created` is True):
#    - Получает преподавателя (автора ДЗ).
#    - Если преподаватель активен, формирует сообщение о сдаче ДЗ студентом.
#    - Отправляет уведомление преподавателю типа `ASSIGNMENT_SUBMITTED` с помощью
#      функции `send_notification` из `notifications.utils`.
# 2. Если сдача ДЗ была обновлена (`created` is False) и теперь у нее есть оценка
#    (поле `grade_for_submission` не пустое):
#    - Вызывает функцию `notify_homework_graded` из `notifications.utils` для уведомления
#      студента о том, что его работа проверена и оценена.
@receiver(post_save, sender=HomeworkSubmission)
def homework_submission_status_changed(sender, instance: HomeworkSubmission, created: bool, **kwargs):
    if created:
        # Уведомление преподавателю о сдаче ДЗ
        # Проверяем, что автор ДЗ существует и активен
        if hasattr(instance.homework, 'author') and instance.homework.author and instance.homework.author.is_active:
            teacher = instance.homework.author
            student_name = instance.student.get_full_name() or instance.student.email
            message = f"Студент {student_name} сдал(а) ДЗ: '{instance.homework.title}'"
            send_notification(teacher, message, Notification.NotificationType.ASSIGNMENT_SUBMITTED, instance)
    # Если submission был обновлен и теперь есть оценка (grade_for_submission)
    elif hasattr(instance, 'grade_for_submission') and instance.grade_for_submission:
        # Уведомление студенту об оценке за ДЗ
        notify_homework_graded(instance)


# Функция-обработчик сигнала grade_created_or_updated_receiver.
# Вызывается после сохранения экземпляра модели Grade.
# - instance: Экземпляр Grade.
# Принцип работы:
# 1. Уведомляет пользователя (студента и, возможно, родителей) о новой или измененной оценке.
# 2. Исключает отправку дублирующего уведомления, если оценка относится к типу `HOMEWORK_GRADE`
#    и связана со сдачей ДЗ (`homework_submission`), так как уведомление об оценке за ДЗ
#    уже было отправлено через `notify_homework_graded` (в обработчике `homework_submission_status_changed`).
#    Для всех остальных типов оценок или если оценка за ДЗ выставлена не через объект HomeworkSubmission,
#    уведомление будет отправлено.
@receiver(post_save, sender=Grade)
def grade_created_or_updated_receiver(sender, instance: Grade, created: bool, **kwargs):
    # Уведомляем при создании любой оценки или при обновлении
    # Исключаем дублирование уведомления об оценке за ДЗ, если оно было отправлено через notify_homework_graded
    if instance.grade_type != Grade.GradeType.HOMEWORK_GRADE or not instance.homework_submission:
        notify_new_grade(instance)