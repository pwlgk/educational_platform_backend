from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
import mimetypes # Импортировано для определения MIME-типа

# Модель Chat представляет собой чат между пользователями, который может быть
# личным (между двумя пользователями) или групповым (между несколькими пользователями).
# - chat_type: Определяет тип чата (PRIVATE или GROUP) с помощью внутреннего класса ChatType.
# - name: Название чата, обязательное для групповых чатов.
# - participants: ManyToMany-связь с моделью пользователя (AUTH_USER_MODEL) через
#   промежуточную модель ChatParticipant. Это позволяет хранить дополнительную информацию
#   о каждом участнике в чате.
# - created_at: Дата и время создания чата (устанавливается автоматически).
# - created_by: (Опционально) Пользователь, создавший чат, актуально для групповых чатов.
# - last_message: (Опционально) OneToOne-связь с последним сообщением в чате. Используется
#   для быстрого доступа к последнему сообщению при отображении списка чатов,
#   что улучшает производительность. Обновляется при сохранении нового сообщения.
# Мета-класс определяет человекочитаемые имена, порядок сортировки по умолчанию
# (сначала чаты с последними сообщениями, затем по дате создания).
# Метод clean выполняет валидацию (например, проверка наличия имени для группового чата).
# Метод get_other_participant возвращает другого участника в личном чате, если он есть.
class Chat(models.Model):
    class ChatType(models.TextChoices):
        PRIVATE = 'PRIVATE', _('Личный чат')
        GROUP = 'GROUP', _('Групповой чат')

    chat_type = models.CharField(_('тип чата'), max_length=10, choices=ChatType.choices)
    name = models.CharField(_('название чата'), max_length=150, blank=True, null=True, help_text=_("Обязательно для групповых чатов"))
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='ChatParticipant',
        related_name='chats',
        verbose_name=_('участники')
    )
    created_at = models.DateTimeField(_('создан'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_chats')
    last_message = models.OneToOneField('Message', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = _('чат')
        verbose_name_plural = _('чаты')
        ordering = ['-last_message__timestamp', '-created_at']

    def __str__(self):
        if self.chat_type == self.ChatType.GROUP:
            return self.name or f"Групповой чат {self.id}"
        else:
            return f"Личный чат {self.id}"

    def clean(self):
        if self.chat_type == self.ChatType.GROUP and not self.name:
            raise ValidationError(_('Название обязательно для группового чата.'))

    def get_other_participant(self, user):
        if self.chat_type == self.ChatType.PRIVATE:
            for participant_obj in self.participants.all(): # Изменено имя переменной во избежание конфликта
                if participant_obj != user:
                    return participant_obj
        return None

# Модель ChatParticipant является промежуточной таблицей для связи ManyToMany
# между моделями Chat и User (AUTH_USER_MODEL). Она позволяет хранить
# дополнительную информацию о каждом участнике в конкретном чате.
# - user: Внешний ключ на модель пользователя.
# - chat: Внешний ключ на модель чата.
# - joined_at: Дата и время, когда пользователь присоединился к чату.
# - last_read_message: Внешний ключ на последнее прочитанное сообщение этим
#   пользователем в данном чате. Это позволяет отслеживать непрочитанные сообщения.
# Мета-класс определяет уникальность пары (user, chat), гарантируя, что
# пользователь может быть участником одного чата только один раз.
# Устанавливает порядок сортировки по умолчанию.
class ChatParticipant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name=_('пользователь'))
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, verbose_name=_('чат'))
    joined_at = models.DateTimeField(_('присоединился'), auto_now_add=True)
    last_read_message = models.ForeignKey('Message', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = _('участник чата')
        verbose_name_plural = _('участники чатов')
        unique_together = ('user', 'chat')
        ordering = ['chat', 'joined_at']

    def __str__(self):
        return f"{self.user} в чате {self.chat_id}"

# Функция chat_file_upload_path генерирует путь для сохранения файлов,
# прикрепленных к сообщениям в чате. Файлы организуются в поддиректории
# на основе ID чата, чтобы избежать конфликтов имен и облегчить управление.
# Пример пути: 'chat_files/chat_{id_чата}/{имя_файла}'.
def chat_file_upload_path(instance, filename):
    return f'chat_files/chat_{instance.chat.id}/{filename}'

# Модель Message представляет собой отдельное сообщение в чате.
# - chat: Внешний ключ на чат, к которому принадлежит сообщение.
# - sender: Внешний ключ на пользователя, отправившего сообщение.
# - content: Текстовое содержимое сообщения (может быть пустым, если есть файл).
# - file: Поле для прикрепленного файла (использует chat_file_upload_path).
# - timestamp: Дата и время отправки сообщения (устанавливается автоматически, индексируется).
# - mime_type: MIME-тип прикрепленного файла (например, 'image/jpeg', 'application/pdf').
#   Индексируется для эффективной фильтрации медиафайлов.
# - file_size: Размер прикрепленного файла в байтах.
# - original_filename: Исходное имя файла, как оно было загружено пользователем.
# Мета-класс определяет порядок сортировки сообщений по умолчанию (по времени отправки)
# и создает составные индексы для полей ('chat', 'timestamp') и ('chat', 'mime_type')
# для ускорения запросов.
# Метод clean проверяет, что сообщение содержит либо текст, либо файл.
# Метод save переопределен для извлечения и сохранения метаданных файла (MIME-тип,
# размер, исходное имя) перед сохранением самого сообщения. Также, если сообщение
# создается впервые (created is True), он обновляет поле last_message
# у связанного объекта Chat, устанавливая текущее сообщение как последнее.
class Message(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages', verbose_name=_('чат'))
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages', verbose_name=_('отправитель'))
    content = models.TextField(_('текст сообщения'), blank=True)
    file = models.FileField(_('файл'), upload_to=chat_file_upload_path, max_length=255, null=True, blank=True)
    timestamp = models.DateTimeField(_('время отправки'), auto_now_add=True, db_index=True)

    mime_type = models.CharField(_('MIME тип'), max_length=100, null=True, blank=True, db_index=True)
    file_size = models.PositiveBigIntegerField(_('размер файла'), null=True, blank=True)
    original_filename = models.CharField(_('исходное имя файла'), max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = _('сообщение')
        verbose_name_plural = _('сообщения')
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['chat', 'timestamp']),
            models.Index(fields=['chat', 'mime_type']),
        ]

    def __str__(self):
        preview = self.content[:50] + '...' if len(self.content) > 50 else self.content
        return f"Сообщение от {self.sender} в чате {self.chat.id} ({preview})"

    def clean(self):
        if not self.content and not self.file:
            raise ValidationError(_('Сообщение должно содержать текст или прикрепленный файл.'))

    def save(self, *args, **kwargs):
        created = self.pk is None
        if self.file and not self.mime_type:
            try:
                self.mime_type = self.file.file.content_type
            except AttributeError:
                mime_type_guessed, _ = mimetypes.guess_type(self.file.name)
                self.mime_type = mime_type_guessed
            except Exception as e:
                 # Логирование или обработка ошибки определения MIME-типа
                 pass

        if self.file and not self.file_size:
            try:
                self.file_size = self.file.size
            except Exception as e:
                 # Логирование или обработка ошибки определения размера файла
                 pass

        if self.file and not self.original_filename:
             try:
                 self.original_filename = self.file.name.split('/')[-1]
             except Exception as e:
                  # Логирование или обработка ошибки определения исходного имени файла
                  pass
        
        super().save(*args, **kwargs)
        if created:
            # Обновляем last_message в чате
            # Используем .update() чтобы избежать вызова save() у Chat и связанных сигналов, если они есть
            Chat.objects.filter(pk=self.chat_id).update(last_message=self)