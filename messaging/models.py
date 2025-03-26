from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

class Chat(models.Model):
    """Модель чата (личного или группового)."""
    class ChatType(models.TextChoices):
        PRIVATE = 'PRIVATE', _('Личный чат')
        GROUP = 'GROUP', _('Групповой чат')

    chat_type = models.CharField(_('тип чата'), max_length=10, choices=ChatType.choices)
    name = models.CharField(_('название чата'), max_length=150, blank=True, help_text=_("Обязательно для групповых чатов"))
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ChatParticipant', # Используем промежуточную модель
        related_name='chats',
        verbose_name=_('участники')
    )
    created_at = models.DateTimeField(_('создан'), auto_now_add=True)
    # Опционально: создатель чата (для групповых)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_chats')
    # Опционально: последнее сообщение для быстрого отображения в списке чатов
    last_message = models.OneToOneField('Message', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = _('чат')
        verbose_name_plural = _('чаты')
        ordering = ['-last_message__timestamp', '-created_at'] # Сначала чаты с последними сообщениями

    def __str__(self):
        if self.chat_type == self.ChatType.GROUP:
            return self.name or f"Групповой чат {self.id}"
        else:
            # Для личных чатов можно формировать имя из участников
            # Это может быть затратно, лучше делать в сериализаторе или методе
            return f"Личный чат {self.id}"

    def clean(self):
        if self.chat_type == self.ChatType.GROUP and not self.name:
            raise ValidationError(_('Название обязательно для группового чата.'))
        # Валидацию количества участников для личного чата лучше делать при создании

    def get_other_participant(self, user):
        """Возвращает другого участника в личном чате."""
        if self.chat_type == self.ChatType.PRIVATE:
            for participant in self.participants.all():
                if participant != user:
                    return participant
        return None


class ChatParticipant(models.Model):
    """Промежуточная модель для связи пользователя и чата с доп. информацией."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name=_('пользователь'))
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, verbose_name=_('чат'))
    joined_at = models.DateTimeField(_('присоединился'), auto_now_add=True)
    # Отслеживание последнего прочитанного сообщения
    last_read_message = models.ForeignKey('Message', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = _('участник чата')
        verbose_name_plural = _('участники чатов')
        unique_together = ('user', 'chat') # Пользователь может быть в чате только один раз
        ordering = ['chat', 'joined_at']

    def __str__(self):
        return f"{self.user} в чате {self.chat_id}"

def chat_file_upload_path(instance, filename):
    """Генерирует путь для загрузки файлов чата."""
    # Пример: chat_files/chat_<chat_id>/<filename>
    return f'chat_files/chat_{instance.chat.id}/{filename}'

class Message(models.Model):
    """Модель сообщения в чате."""
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages', verbose_name=_('чат'))
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages', verbose_name=_('отправитель'))
    content = models.TextField(_('текст сообщения'), blank=True)
    file = models.FileField(_('файл'), upload_to=chat_file_upload_path, null=True, blank=True)
    timestamp = models.DateTimeField(_('время отправки'), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('сообщение')
        verbose_name_plural = _('сообщения')
        ordering = ['timestamp'] # Сначала старые сообщения
        indexes = [
            models.Index(fields=['chat', 'timestamp']),
        ]

    def __str__(self):
        preview = self.content[:50] + '...' if len(self.content) > 50 else self.content
        return f"Сообщение от {self.sender} в чате {self.chat.id} ({preview})"

    def clean(self):
        # Сообщение должно иметь либо текст, либо файл
        if not self.content and not self.file:
            raise ValidationError(_('Сообщение должно содержать текст или прикрепленный файл.'))

    def save(self, *args, **kwargs):
        created = self.pk is None # Проверяем, создается ли объект
        super().save(*args, **kwargs)
        # Обновляем last_message в чате после сохранения нового сообщения
        if created:
            Chat.objects.filter(pk=self.chat_id).update(last_message=self)