import os
from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-zp0vjk_gb_17k@x2p3c1n_s)9t143(hkqo_=$wa!q5l$1=^j&1'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']


# Application definition

INSTALLED_APPS = [
    'daphne', 
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_filters',
    'taggit',
    'channels',
    'corsheaders',
    'drf_spectacular',
    'users',
    'messaging',
    'notifications',
    'core',
    'edu_core',
    'django_celery_results', # Для хранения результатов задач
    'django_celery_beat', 
    'stats',
    
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'server_api.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ASGI_APPLICATION = 'server_api.asgi.application'
WSGI_APPLICATION = 'server_api.wsgi.application' 


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'test_db',
        'USER': 'test_user',
        'PASSWORD': 'test_pass',
        'HOST': 'localhost',
        'PORT': '5433',
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_USER_MODEL = 'users.User'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'ru-ru'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = 'staticfiles/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Настройки DRF ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated', # Требовать аутентификацию по умолчанию
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema', # Для Swagger/OpenAPI
    
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    # 'DEFAULT_THROTTLING_CLASSES': [ # Ограничение частоты запросов (рекомендуется для продакшена)
    #     'rest_framework.throttling.AnonRateThrottle',
    #     'rest_framework.throttling.UserRateThrottle'
    # ],
    # 'DEFAULT_THROTTLE_RATES': {
    #     'anon': '100/day',
    #     'user': '1000/day'
    # }
    # 'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination', # Или 'rest_framework.pagination.LimitOffsetPagination'
    # 'PAGE_SIZE': 10, 
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2), # Увеличим время жизни
    'REFRESH_TOKEN_LIFETIME': timedelta(days=14),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True, # Обновлять last_login при получении токена

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY, # Используйте переменную окружения для ключа в проде!
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id', # Поле в вашей модели User
    'USER_ID_CLAIM': 'user_id', # Имя поля в JWT payload
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
}

if DEBUG: # Или просто для локальной разработки
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    # Настройки для реального SMTP (для продакшена)
    EMAIL_BACKEND = os.environ.get('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
    EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.yourprovider.com')

    # EMAIL_HOST = 'smtp.example.com'
    # EMAIL_PORT = 587
    # EMAIL_USE_TLS = True
    # EMAIL_HOST_USER = 'your_email@example.com'
    # EMAIL_HOST_PASSWORD = 'your_password'
    # DEFAULT_FROM_EMAIL = 'webmaster@example.com'


FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173') # Или другой порт вашего локального фронтенда
EMAIL_CONFIRMATION_EXPIRE_DAYS = 1
PASSWORD_RESET_TIMEOUT_HOURS = int(os.environ.get('PASSWORD_RESET_TIMEOUT_HOURS', 24))

# --- Настройки Channels ---

# --- Настройки CORS ---
CORS_ALLOW_ALL_ORIGINS = True # Для разработки. В продакшене используйте CORS_ALLOWED_ORIGINS
# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:3000", # Адрес вашего фронтенда
#     "http://127.0.0.1:3000",
# ]
# CORS_ALLOW_CREDENTIALS = True # Если фронтенд отправляет куки или заголовки авторизации

# --- Настройки drf-spectacular ---
SPECTACULAR_SETTINGS = {
    'TITLE': 'Educational Platform API',
    'DESCRIPTION': 'API для образовательной платформы',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
}

# --- Настройки Мониторинга ---
MONITOR_LOG_FILES = { # Словарь псевдонимов и путей к лог-файлам
    #'syslog': '/var/log/syslog',
    #'auth': '/var/log/auth.log',
    # Добавьте другие логи по необходимости
    # 'nginx_access': '/var/log/nginx/access.log',
    # 'my_app': '/path/to/your/app.log',
    'app_log': '/app/logs/my_app.log',
}
# Убедитесь, что пользователь, от которого запущен Django, имеет права на чтение этих файлов!

REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1') # Получаем из env или дефолт
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379)) # Получаем из env или дефолт

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [(REDIS_HOST, REDIS_PORT)], # Используем имя сервиса 'redis'
        },
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False, # Важно, чтобы не отключить логгеры Django/DRF
    'formatters': { # Формат вывода логов
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': { # Куда выводить логи
        'console': {
            'level': 'DEBUG', # <-- Уровень для обработчика консоли
            'class': 'logging.StreamHandler', # Вывод в консоль (stderr)
            'formatter': 'simple', # Используем простой формат
        },
        # Можно добавить обработчик для файла:
        # 'file': {
        #     'level': 'DEBUG',
        #     'class': 'logging.FileHandler',
        #     'filename': BASE_DIR / 'django_debug.log', # Путь к файлу логов
        #     'formatter': 'verbose',
        # },
    },
    'loggers': { # Настройка конкретных логгеров
        'django': { # Логгер Django
            'handlers': ['console'],
            'level': 'INFO', # Оставляем INFO для Django, чтобы не засорять вывод
            'propagate': True,
        },
        'django.request': { # Логгер запросов Django
             'handlers': ['console'],
             'level': 'WARNING', # Повышаем уровень для запросов, чтобы видеть ошибки 4xx/5xx
             'propagate': False, # Не передавать выше, чтобы не дублировать
         },
        'users': { # Логгер вашего приложения 'users'
            'handlers': ['console'],
            'level': 'DEBUG', # <-- Устанавливаем DEBUG для вашего приложения
            'propagate': False, # Не передавать выше, если не нужно
        },
        'news': { # Логгер вашего приложения 'news' (добавьте по аналогии)
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
         # Можно настроить корневой логгер, если не указаны логгеры приложений
         # '': {
         #     'handlers': ['console'],
         #     'level': 'DEBUG',
         # },
    }
}

# --- Настройки Celery ---
# URL брокера сообщений (Redis)
# Используем ту же базу Redis, что и для Channels, или другую, если хотите разделить
# CELERY_BROKER_URL = f"redis://{':'+REDIS_PASSWORD+'@' if REDIS_PASSWORD else ''}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"
# Бэкенд для хранения результатов задач (опционально)
# Если используете django-celery-results:
CELERY_RESULT_BACKEND = 'django-db' # Результаты будут храниться в БД Django
# Если не нужен бэкенд результатов или хотите использовать Redis:
# CELERY_RESULT_BACKEND = CELERY_BROKER_URL # Можно использовать тот же Redis
# CELERY_IGNORE_RESULT = True # Если результаты не важны и вы не хотите их хранить

# Формат сериализации задач и результатов
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Временная зона для Celery (важно для Celery Beat)
CELERY_TIMEZONE = TIME_ZONE # Используем TIME_ZONE из настроек Django

# Настройки для django-celery-beat (если используется)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler' # Хранить расписание в БД

REDIS_CACHE_DB = "redis://127.0.0.1:6379/1"
cache_location = ""
# if REDIS_PASSWORD:
#     cache_location = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_CACHE_DB}"
# else:
cache_location = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_CACHE_DB}"
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}