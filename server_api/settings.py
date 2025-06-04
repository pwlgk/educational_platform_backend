# django_app/server_api/settings.py

import os
from pathlib import Path
from datetime import timedelta
import json # Для загрузки MONITOR_LOG_FILES из JSON-строки

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent # Изменил, так как settings.py теперь в server_api/

# --- КЛЮЧЕВЫЕ НАСТРОЙКИ ДЛЯ ПРОДАКШЕНА ---

# SECURITY WARNING: keep the secret key used in production secret!
# Загрузите из переменной окружения!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'password!')

# SECURITY WARNING: don't run with debug turned on in production!
# Установите False в .env для продакшена.
DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True' # По умолчанию False для прода

# Домены, с которых разрешен доступ. Загружаются из .env
ALLOWED_HOSTS_STR = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1') # Дефолт для локальной разработки
if ALLOWED_HOSTS_STR == '*': # Не рекомендуется для прода
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_STR.split(',')]

# Домены, для которых CSRF безопасен (важно для HTTPS)
CSRF_TRUSTED_ORIGINS = []
for host_str in ALLOWED_HOSTS:
    if host_str not in ['*', 'localhost', '127.0.0.1'] and not host_str.startswith('.'): # Исключаем wildcard и локальные
        CSRF_TRUSTED_ORIGINS.append(f"https://{host_str}")
        if DEBUG: # Для локальной HTTP разработки
             CSRF_TRUSTED_ORIGINS.append(f"http://{host_str}")


# Application definition
INSTALLED_APPS = [
    'daphne', # Должен быть первым для ASGI
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
    # Ваши приложения (используйте AppConfig для явности)
    'users.apps.UsersConfig',
    'messaging.apps.MessagingConfig',
    'notifications.apps.NotificationsConfig',
    'core.apps.CoreConfig', # Если есть
    'edu_core.apps.EduCoreConfig', # Если есть
    'stats.apps.StatsConfig', # Если есть
    # Celery
    'django_celery_results',
    'django_celery_beat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # 'whitenoise.middleware.WhiteNoiseMiddleware', # Если используете WhiteNoise для статики
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'server_api.urls' # server_api - имя вашей основной папки проекта

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Общая папка шаблонов, если есть
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            # 'loaders': [ # Для кеширования шаблонов в проде (если DEBUG=False)
            #     ('django.template.loaders.cached.Loader', [
            #         'django.template.loaders.filesystem.Loader',
            #         'django.template.loaders.app_directories.Loader',
            #     ]),
            # ] if not DEBUG else [],
        },
    },
]

ASGI_APPLICATION = 'server_api.asgi.application'
WSGI_APPLICATION = 'server_api.wsgi.application' # Для manage.py команд

# Database (PostgreSQL, параметры из .env)
DB_ENGINE = os.environ.get('DB_ENGINE', 'django.db.backends.postgresql')
DB_NAME = os.environ.get('DB_NAME')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_HOST = os.environ.get('DB_HOST', 'postgres') # Имя сервиса Docker
DB_PORT = os.environ.get('DB_PORT', '5432')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'erudit_db',
        'USER': 'erudit_user',
        'PASSWORD': 'password',
        'HOST': '127.0.0.1',
        'PORT': '5432',
    }
}

# Password validation
AUTH_USER_MODEL = 'users.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = os.environ.get('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = os.environ.get('DJANGO_STATIC_ROOT', BASE_DIR / 'staticfiles_collected') # Путь ВНУТРИ контейнера

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'mediafiles') # Путь ВНУТРИ контейнера

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- DRF Settings ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_THROTTLING_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.environ.get('DRF_THROTTLE_ANON_RATE', '100/hour'),
        'user': os.environ.get('DRF_THROTTLE_USER_RATE', '1000/hour')
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': int(os.environ.get('DRF_PAGE_SIZE', 20)),
}

# --- Simple JWT Settings ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME_HOURS', 2))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('JWT_REFRESH_TOKEN_LIFETIME_DAYS', 14))),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': os.environ.get('DJANGO_JWT_SIGNING_KEY', SECRET_KEY), # ВАЖНО: Отдельный ключ в .env!
    'VERIFYING_KEY': None, 'AUDIENCE': None, 'ISSUER': None, 'JWK_URL': None, 'LEEWAY': 0,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'JTI_CLAIM': 'jti',
}

# --- Email Settings ---
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = os.environ.get('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
    EMAIL_HOST = os.environ.get('EMAIL_HOST')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
    DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
    SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL) # Для ошибок Django
    ADMINS_STR = os.environ.get('DJANGO_ADMINS', '') # "Admin Name <admin@example.com>"
    if ADMINS_STR:
        try:
            # Пытаемся распарсить строку вида "Name1 <email1@example.com>, Name2 <email2@example.com>"
            ADMINS = [tuple(map(str.strip, admin.strip().rsplit('<', 1))) for admin in ADMINS_STR.split(',') if '<' in admin and '>' in admin]
            ADMINS = [(name, email.rstrip('>')) for name, email in ADMINS]
        except:
            ADMINS = [] # В случае ошибки парсинга оставляем пустым
    else:
        ADMINS = []
    MANAGERS = ADMINS

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
EMAIL_CONFIRMATION_EXPIRE_DAYS = int(os.environ.get('EMAIL_CONFIRMATION_EXPIRE_DAYS', 1))
PASSWORD_RESET_TIMEOUT_HOURS = int(os.environ.get('PASSWORD_RESET_TIMEOUT_HOURS', 24))


# --- Channels Settings ---
REDIS_HOST_CHANNELS = os.environ.get('REDIS_HOST_CHANNELS', 'redis') # Имя сервиса Docker
REDIS_PORT_CHANNELS = int(os.environ.get('REDIS_PORT_CHANNELS', 6379))
REDIS_PASSWORD_CHANNELS = os.environ.get('REDIS_PASSWORD_CHANNELS', None)
REDIS_DB_CHANNELS = int(os.environ.get('REDIS_DB_CHANNELS', 0))

channel_layers_config = {}
if REDIS_PASSWORD_CHANNELS:
    redis_url_channels = f"redis://:{REDIS_PASSWORD_CHANNELS}@{REDIS_HOST_CHANNELS}:{REDIS_PORT_CHANNELS}/{REDIS_DB_CHANNELS}"
    channel_layers_config["hosts"] = [redis_url_channels]
else:
    channel_layers_config["hosts"] = [(REDIS_HOST_CHANNELS, REDIS_PORT_CHANNELS)]

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': channel_layers_config,
    },
}

# --- CORS Settings ---
CORS_ALLOWED_ORIGINS_STR = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:3000') # Замените в .env на прод URL
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_STR.split(',')]
# CORS_ALLOW_ALL_ORIGINS = False # Установите False в продакшене, если не используете CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True

# --- DRF Spectacular Settings ---
SPECTACULAR_SETTINGS = {
    'TITLE': os.environ.get('API_TITLE', 'Educational Platform API'),
    'DESCRIPTION': os.environ.get('API_DESCRIPTION', 'API для образовательной платформы'),
    'VERSION': os.environ.get('API_VERSION', '1.0.0'),
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
}

# --- Monitor App Settings ---
MONITOR_LOG_FILES_STR = os.environ.get('MONITOR_LOG_FILES', '{}')
try:
    MONITOR_LOG_FILES = json.loads(MONITOR_LOG_FILES_STR)
except json.JSONDecodeError:
    MONITOR_LOG_FILES = {'app_log': '/app/logs/app_monitor.log'} # Дефолт, если JSON невалидный или пустой

# --- Logging Settings ---
# Директория для логов будет создана в Dockerfile с нужными правами
LOGS_DIR = BASE_DIR / ('logs_dev' if DEBUG else 'logs_prod')
# LOGS_DIR.mkdir(parents=True, exist_ok=True) # ЭТУ СТРОКУ УБРАЛИ - создается в Dockerfile

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {name} [{module}:{lineno:d}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file_django': { # Отдельный файл для логов Django
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / os.environ.get('DJANGO_LOG_FILENAME', 'django.log'),
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_app': { # Отдельный файл для логов ваших приложений
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / os.environ.get('APP_LOG_FILENAME', 'app.log'),
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True,
            'formatter': 'verbose',
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_django'] + (['mail_admins'] if not DEBUG and ADMINS else []),
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['file_django'] + (['mail_admins'] if not DEBUG and ADMINS else []),
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['file_django'] + (['mail_admins'] if not DEBUG and ADMINS else []),
            'level': 'WARNING',
            'propagate': False,
        },
        # Логгеры для ваших приложений - направляем в file_app
        'users': {'handlers': ['console', 'file_app'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'messaging': {'handlers': ['console', 'file_app'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'notifications': {'handlers': ['console', 'file_app'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'core': {'handlers': ['console', 'file_app'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'edu_core': {'handlers': ['console', 'file_app'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        'stats': {'handlers': ['console', 'file_app'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
        # Логгеры для сторонних библиотек
        'channels': {'handlers': ['console', 'file_django'], 'level': 'INFO', 'propagate': False},
        'daphne': {'handlers': ['console', 'file_django'], 'level': 'INFO', 'propagate': False},
        'celery': {'handlers': ['console', 'file_django'], 'level': 'INFO', 'propagate': False},
    },
    'root': { # Корневой логгер
        'handlers': ['console'] if DEBUG else [], # В проде root логгер может ничего не делать, если все логгеры явно настроены
        'level': 'WARNING',
    }
}

# --- Celery Settings ---
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', f"redis://{os.environ.get('REDIS_HOST_CELERY', 'redis')}:{os.environ.get('REDIS_PORT_CELERY', 6379)}/{os.environ.get('REDIS_DB_CELERY', 0)}")
if os.environ.get('REDIS_PASSWORD_CELERY'):
    CELERY_BROKER_URL = f"redis://:{os.environ.get('REDIS_PASSWORD_CELERY')}@{os.environ.get('REDIS_HOST_CELERY', 'redis')}:{os.environ.get('REDIS_PORT_CELERY', 6379)}/{os.environ.get('REDIS_DB_CELERY', 0)}"

CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
# CELERY_TASK_TRACK_STARTED = True # Если нужно отслеживать статус STARTED

# --- Caching Settings (django-redis) ---
REDIS_HOST_CACHE = os.environ.get('REDIS_HOST_CACHE', 'redis')
REDIS_PORT_CACHE = int(os.environ.get('REDIS_PORT_CACHE', 6379))
REDIS_PASSWORD_CACHE = os.environ.get('REDIS_PASSWORD_CACHE', None)
REDIS_DB_CACHE = int(os.environ.get('REDIS_DB_CACHE', 1)) # Используем другую БД Redis для кэша

cache_location = f"redis://{REDIS_HOST_CACHE}:{REDIS_PORT_CACHE}/{REDIS_DB_CACHE}"
if REDIS_PASSWORD_CACHE:
    cache_location = f"redis://:{REDIS_PASSWORD_CACHE}@{REDIS_HOST_CACHE}:{REDIS_PORT_CACHE}/{REDIS_DB_CACHE}"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": cache_location,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# --- HTTPS Security Settings (ВКЛЮЧИТЕ ПОСЛЕ НАСТРОЙКИ SSL НА ВЕБ-СЕРВЕРЕ) ---
# if not DEBUG:
#     SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') # Если Nginx терминирует SSL
#     SECURE_SSL_REDIRECT = True
#     SESSION_COOKIE_SECURE = True
#     CSRF_COOKIE_SECURE = True
#     # HSTS (включать осторожно, после тестирования HTTPS)
#     SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', 31536000)) # 1 год
#     SECURE_HSTS_INCLUDE_SUBDOMAINS = True
#     SECURE_HSTS_PRELOAD = True # Отправка домена в preload-список HSTS (необратимо надолго!)