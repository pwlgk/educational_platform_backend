from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

class Notification(models.Model):
    """Модель уведомления для пользователя."""
    class NotificationType(models.TextChoices):
        # Определяем типы уведомлений, совпадающие с настройками
        NEWS = 'NEWS', _('Новость')
        SCHEDULE = 'SCHEDULE', _('Расписание')
        MESSAGE = 'MESSAGE', _('Сообщение')
        FORUM = 'FORUM', _('Форум')
        SYSTEM = 'SYSTEM', _('Системное')
        # Добавить другие по необходимости (e.g., GRADES, ASSIGNMENTS)

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name=_('получатель'))
    message = models.TextField(_('текст уведомления'))
    notification_type = models.CharField(_('тип уведомления'), max_length=20, choices=NotificationType.choices, default=NotificationType.SYSTEM)
    created_at = models.DateTimeField(_('создано'), auto_now_add=True, db_index=True)
    is_read = models.BooleanField(_('прочитано'), default=False, db_index=True)

    # Generic Foreign Key для связи с источником уведомления
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = _('уведомление')
        verbose_name_plural = _('уведомления')
        ordering = ['-created_at'] # Сначала новые
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"Уведомление для {self.recipient}: {self.message[:50]}..."

class UserNotificationSettings(models.Model):
    """Настройки получения уведомлений для пользователя."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_settings', verbose_name=_('пользователь'))
    # Поля соответствуют NotificationType
    enable_news = models.BooleanField(_('новости'), default=True)
    enable_schedule = models.BooleanField(_('расписание'), default=True)
    enable_messages = models.BooleanField(_('сообщения'), default=True)
    enable_forum = models.BooleanField(_('форум'), default=True) # Например, ответы на посты
    enable_system = models.BooleanField(_('системные'), default=True)
    # Добавить другие по необходимости

    class Meta:
        verbose_name = _('настройки уведомлений')
        verbose_name_plural = _('настройки уведомлений')

    def __str__(self):
        return f"Настройки для {self.user.email}"

    @classmethod
    def get_settings_for_user(cls, user):
        """Возвращает настройки для пользователя, создавая их при необходимости."""
        settings, created = cls.objects.get_or_create(user=user)
        return settings

    def is_enabled(self, notification_type):
        """Проверяет, включен ли данный тип уведомлений."""
        field_name = f"enable_{notification_type.lower()}"
        return getattr(self, field_name, True) # По умолчанию True, если поле не найдено

# --- Сигналы для создания настроек ---
# Создаем настройки при создании нового пользователя
# Можно разместить здесь или в users/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_notification_settings(sender, instance, created, **kwargs):
    if created:
        UserNotificationSettings.objects.create(user=instance)

# @receiver(post_save, sender=settings.AUTH_USER_MODEL)
# def save_user_notification_settings(sender, instance, **kwargs):
#     # Не обязательно, т.к. OneToOneField не требует явного сохранения
#     # instance.notification_settings.save()
#     pass