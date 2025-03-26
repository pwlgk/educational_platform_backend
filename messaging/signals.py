from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Message
from notifications.utils import notify_new_message

@receiver(post_save, sender=Message)
def message_saved(sender, instance, created, **kwargs):
    if created:
        print(f"Sending notification for new message: {instance.id}")
        notify_new_message(instance)