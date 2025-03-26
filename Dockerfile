# Используем базовый образ Python (выберите версию, которую вы использовали при разработке, например 3.11)
FROM python:3.11-slim

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE 1  # Предотвращает создание .pyc файлов
ENV PYTHONUNBUFFERED 1      # Вывод Python логов напрямую в консоль Docker

# Устанавливаем системные зависимости (если нужны, например, для psutil или баз данных)
# Для Debian/Ubuntu:
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev
# Для Alpine:
# RUN apk update && apk add --no-cache build-base postgresql-dev musl-dev
# Если вы используете sudo для управления службами (ВНИМАНИЕ: небезопасно и может не работать в Docker):
# RUN apt-get update && apt-get install -y sudo procps && rm -rf /var/lib/apt/lists/*
# Или для Alpine:
# RUN apk add --no-cache sudo procps

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл зависимостей и устанавливаем их
# Это делается отдельно от копирования всего кода для использования кэша Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта в рабочую директорию контейнера
COPY . .

# Открываем порт, на котором будет работать ваше приложение
EXPOSE 8000

# Команда для запуска ASGI сервера (Daphne)
# Важно использовать 0.0.0.0, чтобы сервер был доступен извне контейнера
CMD ["daphne", "server_api.asgi:application", "-b", "0.0.0.0", "-p", "8000"]

# Альтернативно, если используете Uvicorn:
# CMD ["uvicorn", "server_api.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]
# --reload полезен для разработки, но убедитесь, что том подключен (см. docker-compose.yml)