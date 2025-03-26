from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType

class NewsCategory(models.Model):
    """Категория новостей."""
    name = models.CharField(_('название категории'), max_length=100, unique=True)
    slug = models.SlugField(_('слаг'), max_length=120, unique=True, blank=True, help_text=_("Оставьте пустым для авто-генерации"))
    description = models.TextField(_('описание'), blank=True)

    class Meta:
        verbose_name = _('категория новостей')
        verbose_name_plural = _('категории новостей')
        ordering = ['name']

    def save(self, *args, **kwargs):
        # Автоматически генерируем slug, если он пуст
        if not self.slug:
            self.slug = slugify(self.name)[:120] # Обрезаем до длины поля
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class NewsArticle(models.Model):
    """Новостная статья."""
    title = models.CharField(_('заголовок'), max_length=255)
    content = models.TextField(_('содержание'))
    category = models.ForeignKey(NewsCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='articles', verbose_name=_('категория'))
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, # Если удаляем автора, удаляем и его новости? Или SET_NULL?
        related_name='news_articles',
        limit_choices_to={'role__in': ['TEACHER', 'ADMIN']},
        verbose_name=_('автор')
    )
    created_at = models.DateTimeField(_('создано'), auto_now_add=True)
    updated_at = models.DateTimeField(_('обновлено'), auto_now=True)
    is_published = models.BooleanField(_('опубликовано'), default=True, db_index=True) # Индекс для фильтрации

    # Связь для реакций (через GenericRelation)
    reactions = GenericRelation('news.Reaction', related_query_name='news_article')

    class Meta:
        verbose_name = _('новость')
        verbose_name_plural = _('новости')
        ordering = ['-created_at'] # Сначала новые
        indexes = [
            models.Index(fields=['is_published', 'created_at']),
        ]

    def __str__(self):
        return self.title

    @property
    def comment_count(self):
        """Возвращает количество комментариев первого уровня."""
        return self.comments.filter(parent__isnull=True).count()

    @property
    def likes_count(self):
        """Возвращает количество лайков."""
        return self.reactions.filter(reaction_type=Reaction.ReactionType.LIKE).count()


class NewsComment(models.Model):
    """Комментарий к новости."""
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name='comments', verbose_name=_('статья'))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='news_comments', verbose_name=_('автор'))
    content = models.TextField(_('текст комментария'))
    created_at = models.DateTimeField(_('создано'), auto_now_add=True, db_index=True)
    # Для древовидных комментариев
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies', verbose_name=_('ответ на'))

    # Связь для реакций
    reactions = GenericRelation('news.Reaction', related_query_name='news_comment')

    class Meta:
        verbose_name = _('комментарий к новости')
        verbose_name_plural = _('комментарии к новостям')
        ordering = ['created_at'] # Сначала старые комментарии

    def __str__(self):
        return f"Комментарий от {self.author} к '{self.article.title[:30]}...'"

    @property
    def likes_count(self):
        """Возвращает количество лайков."""
        return self.reactions.filter(reaction_type=Reaction.ReactionType.LIKE).count()

class Reaction(models.Model):
    """Модель реакции (лайка) на статью или комментарий."""
    class ReactionType(models.TextChoices):
        LIKE = 'LIKE', _('Нравится')
        # Можно добавить другие типы: DISLIKE, HEART, etc.

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='news_reactions', verbose_name=_('пользователь'))
    reaction_type = models.CharField(_('тип реакции'), max_length=10, choices=ReactionType.choices, default=ReactionType.LIKE)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Generic Foreign Key для связи с Article или Comment
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, limit_choices_to=models.Q(app_label='news', model='newsarticle') | models.Q(app_label='news', model='newscomment'))
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = _('реакция')
        verbose_name_plural = _('реакции')
        # Уникальность: один пользователь - одна реакция на объект
        unique_together = ('user', 'content_type', 'object_id', 'reaction_type')
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.get_reaction_type_display()} на {self.content_object}"