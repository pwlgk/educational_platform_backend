# server_api/celery.py (замените server_api на имя вашего проекта)

from datetime import timedelta
import os
from celery import Celery
from django.conf import settings # Для доступа к настройкам Django

# Устанавливаем переменную окружения для настроек Django,
# чтобы Celery знал, где их искать.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server_api.settings') # Замените server_api.settings

# Создаем экземпляр Celery
# 'server_api' - это имя вашего проекта Celery, может совпадать с Django-проектом
app = Celery('server_api') # Замените server_api

# Загружаем конфигурацию из настроек Django.
# Все настройки Celery в settings.py должны начинаться с префикса 'CELERY_'.
# Например: CELERY_BROKER_URL, CELERY_RESULT_BACKEND и т.д.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически обнаруживаем задачи в файлах tasks.py всех зарегистрированных приложений Django.
app.autodiscover_tasks()

# Пример простой задачи для проверки (можно удалить позже)
@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

# Если вы используете django-celery-beat, здесь можно настроить расписание
# (альтернатива настройке в settings.py или админке)
# from celery.schedules import crontab
# CELERY_BEAT_SCHEDULE = {
#     'send-homework-reminders-test': {
#         'task': 'send_homework_deadline_reminders',
#         'schedule': crontab(minute='*/1'), # Каждую минуту
#         'args': (2,), # Напоминать за 2 дня
#     },
# }
app.conf.beat_schedule.update({  # Используем update, если beat_schedule уже определен
    'test-submission-notifications-every-10-seconds': {
        'task': 'test_send_submission_notification', # Имя задачи из @shared_task
        'schedule': timedelta(seconds=10),        # Каждые 10 секунд
        # 'args': (), # Аргументы не нужны для этой задачи
    },
})