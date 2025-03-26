# monitor/middleware.py

import re
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
# Убираем ВСЕ импорты, зависящие от Django или библиотек, которые зависят от Django
# from rest_framework_simplejwt.tokens import AccessToken
# from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from channels.middleware import BaseMiddleware


@database_sync_to_async
def get_user_from_token(token_key):
    """
    Асинхронно получает пользователя по JWT токену.
    """
    # Импортируем всё необходимое прямо здесь:
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import AnonymousUser
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    User = get_user_model()
    try:
        # Проверяем токен
        access_token = AccessToken(token_key)
        # Получаем user_id из токена
        user_id = access_token['user_id']
        # Находим пользователя в базе данных
        user = User.objects.get(id=user_id)
        return user
    except (InvalidToken, TokenError, User.DoesNotExist):
        # Если токен недействителен или пользователь не найден
        return AnonymousUser()
    except Exception as e:
        print(f"Error authenticating user from token: {e}")
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    """
    Middleware для Channels, которое аутентифицирует пользователя по JWT токену
    из query string.
    """
    async def __call__(self, scope, receive, send):
        # Импортируем AnonymousUser здесь
        from django.contrib.auth.models import AnonymousUser
        # Извлекаем query string
        query_string = scope.get('query_string', b'').decode('utf-8')
        # Парсим query string
        query_params = parse_qs(query_string)
        # Ищем параметр 'token'
        token = query_params.get('token', [None])[0]

        if token:
            # Если токен есть, пытаемся получить пользователя
            scope['user'] = await get_user_from_token(token)
            print(f"JWT Auth Middleware: User {scope['user']} authenticated from token.")
        else:
            # Если токена нет, используем AnonymousUser
            if 'user' not in scope:
                 scope['user'] = AnonymousUser()
            print("JWT Auth Middleware: No token found in query string.")

        # Передаем управление следующему middleware или consumer'у
        return await super().__call__(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    # Эта обертка не требует импортов Django напрямую
    return JwtAuthMiddleware(inner)