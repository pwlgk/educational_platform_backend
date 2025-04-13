from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from taggit.managers import TaggableManager

class ForumCategory(models.Model):
    """Категория/раздел форума."""
    name = models.CharField(_('название категории'), max_length=150, unique=True)
    slug = models.SlugField(_('слаг'), max_length=170, unique=True, blank=True, help_text=_("Оставьте пустым для авто-генерации"))
    description = models.TextField(_('описание'), blank=True)
    # Опционально: Порядок отображения
    display_order = models.PositiveIntegerField(_('порядок'), default=0)
    # Опционально: Ограничение доступа по ролям (если нужно)
    # allowed_roles = models.JSONField(default=list, blank=True, help_text="Список ролей, которым разрешен доступ (e.g., ['STUDENT', 'TEACHER'])")

    class Meta:
        verbose_name = _('категория форума')
        verbose_name_plural = _('категории форума')
        ordering = ['display_order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:170]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class ForumTopic(models.Model):
    """Тема (тред) на форуме."""
    category = models.ForeignKey(ForumCategory, on_delete=models.CASCADE, related_name='topics', verbose_name=_('категория'))
    title = models.CharField(_('заголовок темы'), max_length=255)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='forum_topics', verbose_name=_('автор'))
    created_at = models.DateTimeField(_('создано'), auto_now_add=True)
    # Обновляем при добавлении нового поста
    last_post_at = models.DateTimeField(_('последний пост'), auto_now_add=True, db_index=True)
    is_pinned = models.BooleanField(_('закреплена'), default=False, db_index=True) # Для важных тем
    is_closed = models.BooleanField(_('закрыта'), default=False) # Запретить новые посты

    # Используем django-taggit для тегов
    tags = TaggableManager(blank=True)

    # Опционально: Ссылка на первый пост для удобства
    first_post = models.OneToOneField('ForumPost', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    # Опционально: Счетчик постов (можно денормализовать для производительности)
    # post_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        verbose_name = _('тема форума')
        verbose_name_plural = _('темы форума')
        # Сначала закрепленные, потом по последнему посту
        ordering = ['-is_pinned', '-last_post_at']
        indexes = [
            models.Index(fields=['category', '-is_pinned', '-last_post_at']),
        ]

    def __str__(self):
        return self.title

    @property
    def post_count(self):
        """Возвращает количество постов в теме."""
        return self.posts.count() # Динамический подсчет
    
    @property
    def last_post(self):
        """Возвращает последний пост в теме или None."""
        # Импортируем здесь, чтобы избежать циклического импорта
        from .models import ForumPost
        # order_by('-created_at') или по pk, если auto_now_add у поста
        return self.posts.select_related('author').order_by('-created_at').first()


class ForumPost(models.Model):
    """Пост/сообщение в теме форума."""
    topic = models.ForeignKey(ForumTopic, on_delete=models.CASCADE, related_name='posts', verbose_name=_('тема'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='forum_posts', verbose_name=_('автор'))
    content = models.TextField(_('текст сообщения'))
    created_at = models.DateTimeField(_('создано'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('обновлено'), auto_now=True)
    # Для ответов на конкретные посты (цитирование/вложенность)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies', verbose_name=_('ответ на'))

    # Связь для реакций
    reactions = GenericRelation('forum.ForumReaction', related_query_name='forum_post')

    class Meta:
        verbose_name = _('пост форума')
        verbose_name_plural = _('посты форума')
        ordering = ['created_at'] # Сначала старые посты в теме
        indexes = [
            models.Index(fields=['topic', 'created_at']),
        ]

    def __str__(self):
        return f"Пост от {self.author} в теме '{self.topic.title[:30]}...'"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        # Обновляем время последнего поста в теме и ссылку на первый пост
        if is_new:
            topic = self.topic
            topic.last_post_at = self.created_at
            if not topic.first_post: # Устанавливаем первый пост, если его еще нет
                topic.first_post = self
            # topic.post_count = topic.posts.count() # Обновляем счетчик, если денормализуем
            topic.save(update_fields=['last_post_at', 'first_post']) # 'post_count'

    @property
    def likes_count(self):
        """Возвращает количество лайков."""
        return self.reactions.filter(reaction_type=ForumReaction.ReactionType.LIKE).count()

class ForumReaction(models.Model):
    """Модель реакции (лайка) на пост форума."""
    class ReactionType(models.TextChoices):
        LIKE = 'LIKE', _('Нравится')
        # DISLIKE = 'DISLIKE', _('Не нравится') # Если нужно

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='forum_reactions', verbose_name=_('пользователь'))
    reaction_type = models.CharField(_('тип реакции'), max_length=10, choices=ReactionType.choices, default=ReactionType.LIKE)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Используем Generic Foreign Key для возможного расширения на реакции к темам
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, limit_choices_to=models.Q(app_label='forum', model='forumpost')) # Пока только к постам
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = _('реакция на форуме')
        verbose_name_plural = _('реакции на форуме')
        # Уникальность: один пользователь - одна реакция на объект
        unique_together = ('user', 'content_type', 'object_id', 'reaction_type')
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.get_reaction_type_display()} на {self.content_object}"