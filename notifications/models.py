import logging
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# Модель Notification представляет собой отдельное уведомление для пользователя.
# Она использует GenericForeignKey для связи с любым другим объектом в системе,
# который может быть источником или контекстом уведомления (например, новое сообщение,
# домашнее задание, событие расписания и т.д.).
# - NotificationType: Внутренний класс TextChoices, определяющий возможные типы уведомлений.
#   Включает типы для расписания, сообщений в чате, различных событий домашних заданий,
#   новых оценок и системных уведомлений.
# - recipient: Внешний ключ на модель пользователя (AUTH_USER_MODEL), которому адресовано уведомление.
# - message: Текстовое содержимое уведомления.
# - notification_type: Тип уведомления (выбор из NotificationType).
# - created_at: Дата и время создания уведомления (устанавливается автоматически, индексируется).
# - is_read: Булево поле, указывающее, прочитано ли уведомление пользователем (индексируется).
# - content_type, object_id, content_object: Поля для GenericForeignKey, позволяющие
#   связать уведомление с конкретным объектом-источником.
# Мета-класс определяет человекочитаемые имена, порядок сортировки по умолчанию
# (сначала новые уведомления) и составной индекс для полей ('recipient', 'is_read', '-created_at')
# для ускорения запросов на получение непрочитанных уведомлений для пользователя.
class Notification(models.Model):
    class NotificationType(models.TextChoices):
        SCHEDULE = 'SCHEDULE', _('Расписание')
        MESSAGE = 'MESSAGE', _('Сообщение в чате')
        ASSIGNMENT_NEW = 'ASSIGNMENT_NEW', _('Новое домашнее задание')
        ASSIGNMENT_DUE = 'ASSIGNMENT_DUE', _('Срок сдачи ДЗ')
        ASSIGNMENT_SUBMITTED = 'ASSIGNMENT_SUBMITTED', _('ДЗ сдано')
        ASSIGNMENT_GRADED = 'ASSIGNMENT_GRADED', _('ДЗ проверено/оценено')
        GRADE_NEW = 'GRADE_NEW', _('Новая оценка')
        SYSTEM = 'SYSTEM', _('Системное')
        # При необходимости сюда добавляются новые типы уведомлений

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name=_('получатель'))
    message = models.TextField(_('текст уведомления'))
    notification_type = models.CharField(
        _('тип уведомления'),
        max_length=25,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM
    )
    created_at = models.DateTimeField(_('создано'), auto_now_add=True, db_index=True)
    is_read = models.BooleanField(_('прочитано'), default=False, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = _('уведомление')
        verbose_name_plural = _('уведомления')
        ordering = ['-created_at']
        indexes = [models.Index(fields=['recipient', 'is_read', '-created_at'])]

    def __str__(self):
        recipient_name = self.recipient.email if self.recipient else "N/A"
        return f"Уведомление для {recipient_name}: {self.message[:50]}..."

# Модель UserNotificationSettings хранит индивидуальные настройки уведомлений для каждого пользователя.
# Она связана с моделью пользователя (AUTH_USER_MODEL) отношением "один-к-одному".
# - user: OneToOneField на модель пользователя.
# - Поля enable_*: Набор булевых полей, каждое из которых соответствует определенному
#   типу уведомлений из Notification.NotificationType (например, enable_schedule, enable_messages).
#   Эти поля позволяют пользователю включать или отключать получение уведомлений конкретных типов.
#   По умолчанию все типы уведомлений включены.
# Метод класса get_settings_for_user возвращает объект настроек для указанного пользователя,
# создавая его с настройками по умолчанию, если он еще не существует.
# Метод is_enabled проверяет, включен ли конкретный тип уведомления для данного пользователя,
# используя карту сопоставления строкового значения типа уведомления (из Notification.NotificationType)
# с соответствующим полем enable_* в модели настроек. Если для типа уведомления
# нет явной настройки, по умолчанию уведомление разрешается (возвращает True).
class UserNotificationSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='notification_settings', 
        verbose_name=_('пользователь')
    )
    
    enable_schedule = models.BooleanField(_('расписание'), default=True)
    enable_messages = models.BooleanField(_('сообщения в чате'), default=True)
    enable_assignment_new = models.BooleanField(_('новые ДЗ'), default=True)
    enable_assignment_due = models.BooleanField(_('напоминания о сроках ДЗ'), default=True)
    enable_assignment_submitted = models.BooleanField(_('сдача ДЗ (для преподавателя)'), default=True)
    enable_assignment_graded = models.BooleanField(_('проверка/оценка ДЗ'), default=True)
    enable_grade_new = models.BooleanField(_('новые оценки'), default=True)
    enable_system = models.BooleanField(_('системные'), default=True)
    # При добавлении новых NotificationType, сюда также добавляются соответствующие поля enable_...

    class Meta:
        verbose_name = _('настройки уведомлений')
        verbose_name_plural = _('настройки уведомлений')

    def __str__(self):
        user_email = self.user.email if self.user else "N/A"
        return f"Настройки для {user_email}"

    @classmethod
    def get_settings_for_user(cls, user):
        settings_obj, created = cls.objects.get_or_create(user=user)
        return settings_obj

    def is_enabled(self, notification_type_value: str) -> bool:
        type_to_field_map = {
            Notification.NotificationType.SCHEDULE: 'enable_schedule',
            Notification.NotificationType.MESSAGE: 'enable_messages',
            Notification.NotificationType.ASSIGNMENT_NEW: 'enable_assignment_new',
            Notification.NotificationType.ASSIGNMENT_DUE: 'enable_assignment_due',
            Notification.NotificationType.ASSIGNMENT_SUBMITTED: 'enable_assignment_submitted',
            Notification.NotificationType.ASSIGNMENT_GRADED: 'enable_assignment_graded',
            Notification.NotificationType.GRADE_NEW: 'enable_grade_new',
            Notification.NotificationType.SYSTEM: 'enable_system',
        }

        field_name_to_check = type_to_field_map.get(notification_type_value)

        if field_name_to_check and hasattr(self, field_name_to_check):
            is_setting_enabled = getattr(self, field_name_to_check)
            logger.debug(
                f"UserNotificationSettings.is_enabled for user {self.user_id}: "
                f"Type '{notification_type_value}' -> Mapped Field '{field_name_to_check}' -> Enabled: {is_setting_enabled}"
            )
            return is_setting_enabled
        else:
            logger.warning(
                f"UserNotificationSettings.is_enabled for user {self.user_id}: "
                f"No setting field found for notification type '{notification_type_value}'. "
                f"Mapped field was '{field_name_to_check}'. Notification will be ALLOWED by default."
            )
            return True 

# Функция-обработчик сигнала create_user_notification_settings_receiver.
# Этот обработчик автоматически вызывается после сохранения нового экземпляра
# модели пользователя (AUTH_USER_MODEL), когда created=True.
# Его задача - создать объект UserNotificationSettings с настройками по умолчанию
# для только что зарегистрированного пользователя. Использует метод
# UserNotificationSettings.get_settings_for_user для создания или получения настроек.
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_notification_settings_receiver(sender, instance, created, **kwargs):
    if created:
        UserNotificationSettings.get_settings_for_user(instance)
        logger.info(f"Созданы настройки уведомлений по умолчанию для нового пользователя {instance.email}")