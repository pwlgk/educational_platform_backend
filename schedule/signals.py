from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Lesson
from notifications.utils import notify_schedule_change

@receiver(post_save, sender=Lesson)
def lesson_saved(sender, instance, created, **kwargs):
    action = "создано" if created else "изменено"
    print(f"Sending notification for {action} lesson: {instance.id}")
    notify_schedule_change(instance, action=action)

@receiver(post_delete, sender=Lesson)
def lesson_deleted(sender, instance, **kwargs):
    print(f"Sending notification for deleted lesson: {instance.id}")
    # Передаем копию данных, т.к. instance будет удален
    notify_schedule_change(instance, action="удалено") # Может понадобиться передать больше данных до удаления