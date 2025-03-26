from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ForumPost
from notifications.utils import notify_forum_reply

@receiver(post_save, sender=ForumPost)
def forum_post_saved(sender, instance, created, **kwargs):
    if created:
         print(f"Sending notification for new forum post: {instance.id}")
         # Отправляем уведомление только если это ответ на чей-то пост
         if instance.parent:
             notify_forum_reply(instance)
         # TODO: Уведомлять подписчиков темы