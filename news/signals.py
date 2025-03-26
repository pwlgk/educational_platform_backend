from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import NewsArticle
# Импортируем функцию из notifications.utils
from notifications.utils import notify_new_news
# from celery import shared_task # Если используем Celery

# @shared_task # Делаем задачу Celery для асинхронной отправки
# def send_news_notification_task(article_id):
#     try:
#         article = NewsArticle.objects.get(pk=article_id)
#         notify_new_news(article)
#     except NewsArticle.DoesNotExist:
#         pass # Статья была удалена?

@receiver(post_save, sender=NewsArticle)
def news_article_saved(sender, instance, created, **kwargs):
    # Отправляем уведомление только при создании опубликованной статьи
    # или при изменении статуса на "опубликовано"
    update_fields = kwargs.get('update_fields')
    is_published_updated = update_fields is None or 'is_published' in update_fields

    if instance.is_published and (created or (not created and is_published_updated)):
        # Проверяем, не была ли она уже опубликована до этого сохранения
        # Это простая проверка, может быть неточной при частых сохранениях
        was_published_before = False
        if not created and update_fields:
             # Если есть история изменений или previous_state, можно использовать их
             pass # Для простоты пока пропустим точную проверку "только что опубликовано"

        if created or not was_published_before: # Отправляем при создании или первой публикации
             print(f"Sending notification for published news: {instance.id}")
             # send_news_notification_task.delay(instance.id) # Вызов задачи Celery
             notify_new_news(instance) # Синхронный вызов (может быть долгим)