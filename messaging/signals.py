from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Message, Chat, ChatParticipant
from notifications.utils import notify_new_message
from notifications.models import Notification

User = settings.AUTH_USER_MODEL

# Функция-обработчик сигнала new_message_created_notification.
# Этот обработчик автоматически вызывается после сохранения нового экземпляра
# модели Message (когда created=True).
# Его задача - инициировать отправку уведомлений (через отдельную систему уведомлений,
# а не через WebSocket самого чата) всем участникам чата, за исключением отправителя сообщения.
# - sender: Модель, отправившая сигнал (в данном случае, Message).
# - instance: Экземпляр модели Message, который был сохранен.
# - created: Булево значение, истинное, если объект был создан, и ложное, если обновлен.
# - **kwargs: Дополнительные аргументы.
# Принцип работы:
# 1. Проверяет, было ли сообщение только что создано (created is True).
# 2. Если да, то вызывает функцию `notify_new_message` из модуля `notifications.utils`,
#    передавая ей созданный объект сообщения.
# 3. Предполагается, что функция `notify_new_message` сама разбирается, кому и как
#    отправлять уведомления (проверяет настройки получателей, создает запись
#    в модели Notification и, возможно, отправляет real-time уведомление через
#    отдельный WebSocket-канал для уведомлений).
@receiver(post_save, sender=Message)
def new_message_created_notification(sender, instance: Message, created: bool, **kwargs):
    if created:
        notify_new_message(instance)