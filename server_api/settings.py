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
    'channels',
    'corsheaders',
    'drf_spectacular',
    'monitor',
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

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

STATIC_URL = 'static/'

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
    # 'DEFAULT_THROTTLING_CLASSES': [ # Ограничение частоты запросов (рекомендуется для продакшена)
    #     'rest_framework.throttling.AnonRateThrottle',
    #     'rest_framework.throttling.UserRateThrottle'
    # ],
    # 'DEFAULT_THROTTLE_RATES': {
    #     'anon': '100/day',
    #     'user': '1000/day'
    # }
}

# --- Настройки Simple JWT ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15), # Время жизни Access токена
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),    # Время жизни Refresh токена
    'ROTATE_REFRESH_TOKENS': True, # Генерировать новый Refresh токен при обновлении
    'BLACKLIST_AFTER_ROTATION': True, # Добавлять старый Refresh токен в черный список
    'UPDATE_LAST_LOGIN': False,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY, # Используем Django SECRET_KEY для простоты, лучше генерировать отдельный
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',

    'JTI_CLAIM': 'jti',

    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

# --- Настройки Channels ---
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            # Укажите ваш хост и порт Redis
            "hosts": [('127.0.0.1', 6379)],
        },
    },
}

# --- Настройки CORS ---
CORS_ALLOW_ALL_ORIGINS = True # Для разработки. В продакшене используйте CORS_ALLOWED_ORIGINS
# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:3000", # Адрес вашего фронтенда
#     "http://127.0.0.1:3000",
# ]
# CORS_ALLOW_CREDENTIALS = True # Если фронтенд отправляет куки или заголовки авторизации

# --- Настройки drf-spectacular ---
SPECTACULAR_SETTINGS = {
    'TITLE': 'Server Monitoring API',
    'DESCRIPTION': 'API для мониторинга и управления сервером',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False, # Не показывать схему OpenAPI в UI по умолчанию
    # Дополнительные настройки...
    'COMPONENT_SPLIT_REQUEST': True, # Разделять параметры запроса в Swagger UI
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