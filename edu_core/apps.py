# edu_core/apps.py
from django.apps import AppConfig

class EduCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'edu_core'
    verbose_name = "Учебный Модуль" # Название для админки

    def ready(self):
        import edu_core.signals # Импортируем сигналы