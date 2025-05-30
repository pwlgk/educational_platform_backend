import datetime
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)

# Функция send_confirmation_email предназначена для отправки электронного письма
# пользователю с целью подтверждения его регистрации на платформе.
# Принцип работы:
# 1. Получает объект пользователя (user), у которого должен быть сгенерирован
#    токен подтверждения (user.confirmation_token).
# 2. Формирует URL-адрес для подтверждения на фронтенде, используя токен
#    и базовый URL фронтенда из настроек Django (settings.FRONTEND_URL).
# 3. Определяет имя платформы из настроек (settings.PLATFORM_NAME) или использует
#    значение по умолчанию.
# 4. Готовит контекст для рендеринга HTML-шаблона письма, включая пользователя,
#    URL подтверждения, имя платформы, имя пользователя (или часть email в качестве фолбэка)
#    и текущий год.
# 5. Рендерит HTML-версию письма из шаблона 'emails/account_confirmation_email.html'.
# 6. Создает текстовую версию письма путем удаления HTML-тегов из HTML-версии.
# 7. Отправляет письмо с помощью функции Django send_mail, указывая тему,
#    текстовое и HTML-содержимое, отправителя (из settings.DEFAULT_FROM_EMAIL)
#    и получателя (email пользователя).
# 8. Логирует успешную отправку или ошибку в случае сбоя.
def send_confirmation_email(user):
    token = user.confirmation_token
    confirm_url_on_frontend = f"{settings.FRONTEND_URL}/auth/confirm-email/{token}/"
    
    platform_name = getattr(settings, 'PLATFORM_NAME', 'Наша Платформа')

    subject = f'Подтверждение регистрации на {platform_name}'
    context = {
        'user': user,
        'confirm_url': confirm_url_on_frontend,
        'platform_name': platform_name,
        'first_name': user.first_name or user.email.split('@')[0],
        'current_year': datetime.date.today().year,
    }
    try:
        html_message = render_to_string('emails/account_confirmation_email.html', context)
        plain_message = strip_tags(html_message)

        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_message
        )
        logger.info(f"Confirmation email sent to {user.email}")
    except Exception as e:
        logger.error(f"Error sending confirmation email to {user.email}: {e}", exc_info=True)

# Функция send_password_reset_email отправляет пользователю электронное письмо
# со ссылкой для сброса пароля.
# Принцип работы:
# 1. Получает объект пользователя (user), для которого был сгенерирован
#    токен сброса пароля (user.password_reset_token).
# 2. Формирует URL-адрес для страницы сброса пароля на фронтенде, используя токен
#    и базовый URL фронтенда (settings.FRONTEND_URL).
# 3. Определяет имя платформы аналогично функции send_confirmation_email.
# 4. Готовит контекст для HTML-шаблона письма, включая пользователя, URL сброса,
#    имя платформы, имя пользователя и текущий год.
# 5. Рендерит HTML-версию письма из шаблона 'emails/password_reset_email.html'.
# 6. Создает текстовую версию письма.
# 7. Отправляет письмо с помощью send_mail.
# 8. Логирует результат отправки (успех или ошибка).
def send_password_reset_email(user):
    token = user.password_reset_token
    reset_url_on_frontend = f"{settings.FRONTEND_URL}/auth/reset-password/{token}/"
    
    platform_name = getattr(settings, 'PLATFORM_NAME', 'Наша Платформа')

    subject = f'Сброс пароля на {platform_name}'
    context = {
        'user': user,
        'reset_url': reset_url_on_frontend,
        'platform_name': platform_name,
        'first_name': user.first_name or user.email.split('@')[0],
        'current_year': datetime.date.today().year,
    }
    try:
        html_message = render_to_string('emails/password_reset_email.html', context)
        plain_message = strip_tags(html_message)

        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_message
        )
        logger.info(f"Password reset email sent to {user.email}")
    except Exception as e:
        logger.error(f"Error sending password reset email to {user.email}: {e}", exc_info=True)