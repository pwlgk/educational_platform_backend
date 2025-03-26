import asyncio
import json
import psutil
import os
import aiofiles # Для асинхронного tail
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async # Для доступа к user в async context
from django.conf import settings
from .views import get_system_info # Используем ту же функцию

# --- Вспомогательные функции для Consumer ---

@database_sync_to_async
def user_is_authenticated(user):
    """Проверяет, аутентифицирован ли пользователь (асинхронно)."""
    if not user:
        return False
    return user.is_authenticated

@database_sync_to_async
def user_is_superuser(user):
    """Проверяет, является ли пользователь суперюзером (асинхронно)."""
    if not user:
        return False
    return user.is_superuser

async def tail_log(consumer, log_alias, log_path):
    """Асинхронная функция для 'tail -f' лог-файла."""
    try:
        # Проверка существования и прав доступа
        if not os.path.exists(log_path) or not os.path.isfile(log_path):
            await consumer.send_error(f"Log file not found: {log_path}")
            return
        if not os.access(log_path, os.R_OK):
            await consumer.send_error(f"Permission denied for log file: {log_path}")
            return

        async with aiofiles.open(log_path, mode='r', encoding='utf-8', errors='ignore') as f:
            # Переходим в конец файла
            await f.seek(0, os.SEEK_END)
            while True:
                # Проверяем, подключен ли еще consumer
                if consumer.channel_name not in consumer.channel_layer.groups.get(consumer.log_group_name(log_alias), {}):
                     print(f"Stopping tail for {log_alias} as consumer disconnected from group.")
                     break

                line = await f.readline()
                if not line:
                    # Нет новых строк, ждем немного
                    await asyncio.sleep(0.5)
                    continue
                # Отправляем новую строку клиенту
                await consumer.send_log_update(log_alias, line.strip())
                # Небольшая задержка, чтобы не перегружать CPU в цикле
                await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        print(f"Log tailing task for {log_alias} cancelled.")
    except FileNotFoundError:
        await consumer.send_error(f"Log file disappeared: {log_path}")
    except PermissionError:
        await consumer.send_error(f"Permission lost for log file: {log_path}")
    except Exception as e:
        print(f"Error tailing log {log_alias}: {e}")
        await consumer.send_error(f"Error reading log {log_alias}: {e}")
    finally:
        print(f"Stopped tailing log: {log_alias}")
        # Убираем задачу из словаря consumer'а, если она там есть
        if log_alias in consumer.log_tail_tasks:
             del consumer.log_tail_tasks[log_alias]


# --- Consumer ---

class MonitorConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer для отправки данных мониторинга и логов в реальном времени.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitoring_task = None
        self.monitoring_interval = 5 # Интервал обновления системных данных (секунды)
        self.log_tail_tasks = {} # Словарь для хранения задач tail'инга логов {log_alias: task}

    async def connect(self):
        """Вызывается при установке WebSocket соединения."""
        self.user = self.scope.get("user", None) # Получаем user из AuthMiddlewareStack

        is_auth = await user_is_authenticated(self.user)
        if not is_auth:
            await self.close(code=4001) # Закрываем соединение, если пользователь не аутентифицирован
            return

        await self.accept()
        print(f"WebSocket connected for user: {self.user}")

        # Запускаем периодическую отправку системной информации
        self.monitoring_task = asyncio.create_task(self.send_system_info_periodically())

    async def disconnect(self, close_code):
        """Вызывается при разрыве WebSocket соединения."""
        print(f"WebSocket disconnected for user: {self.user}, code: {close_code}")
        # Останавливаем задачу мониторинга
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass # Ожидаемое исключение при отмене
        self.monitoring_task = None

        # Останавливаем все задачи tail'инга логов
        for task in self.log_tail_tasks.values():
            task.cancel()
        await asyncio.gather(*[task for task in self.log_tail_tasks.values()], return_exceptions=True) # Ждем завершения отмены
        self.log_tail_tasks = {}

        # Покидаем все группы логов (на всякий случай)
        for log_alias in list(settings.MONITOR_LOG_FILES.keys()): # Используем list для копии ключей
             await self.channel_layer.group_discard(
                 self.log_group_name(log_alias),
                 self.channel_name
             )

    async def receive(self, text_data=None, bytes_data=None):
        """Вызывается при получении сообщения от клиента."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            payload = data.get('payload', {})

            print(f"Received message type: {message_type} from {self.user}")

            if message_type == 'subscribe_log':
                await self.handle_subscribe_log(payload)
            elif message_type == 'unsubscribe_log':
                await self.handle_unsubscribe_log(payload)
            elif message_type == 'set_interval':
                await self.handle_set_interval(payload)
            else:
                await self.send_error(f"Unknown message type: {message_type}")

        except json.JSONDecodeError:
            await self.send_error("Invalid JSON received.")
        except Exception as e:
            print(f"Error processing received message: {e}")
            await self.send_error(f"Error processing message: {e}")

    # --- Обработчики сообщений от клиента ---

    async def handle_subscribe_log(self, payload):
        """Обработка запроса на подписку на лог."""
        log_alias = payload.get('log_alias')
        if not log_alias:
            await self.send_error("Missing 'log_alias' in subscribe_log payload.")
            return

        # Проверка прав доступа к логу (например, только для суперпользователей)
        is_admin = await user_is_superuser(self.user)
        if not is_admin: # Или более гранулярная проверка прав
             await self.send_error(f"Permission denied to subscribe to log '{log_alias}'.")
             return

        log_path = settings.MONITOR_LOG_FILES.get(log_alias)
        if not log_path:
            await self.send_error(f"Log alias '{log_alias}' not found.")
            return

        if log_alias in self.log_tail_tasks:
            await self.send_info(f"Already subscribed to log '{log_alias}'.")
            return

        # Добавляем consumer'а в группу для этого лога
        group_name = self.log_group_name(log_alias)
        await self.channel_layer.group_add(group_name, self.channel_name)
        print(f"User {self.user} subscribed to log group: {group_name}")

        # Запускаем задачу tail'инга в фоне
        task = asyncio.create_task(tail_log(self, log_alias, log_path))
        self.log_tail_tasks[log_alias] = task
        await self.send_info(f"Subscribed to log '{log_alias}'.")

    async def handle_unsubscribe_log(self, payload):
        """Обработка запроса на отписку от лога."""
        log_alias = payload.get('log_alias')
        if not log_alias:
            await self.send_error("Missing 'log_alias' in unsubscribe_log payload.")
            return

        if log_alias not in self.log_tail_tasks:
            await self.send_info(f"Not currently subscribed to log '{log_alias}'.")
            return

        # Останавливаем задачу tail'инга
        task = self.log_tail_tasks.pop(log_alias)
        task.cancel()
        try:
            await task # Ждем завершения отмены
        except asyncio.CancelledError:
            pass

        # Удаляем consumer'а из группы лога
        group_name = self.log_group_name(log_alias)
        await self.channel_layer.group_discard(group_name, self.channel_name)
        print(f"User {self.user} unsubscribed from log group: {group_name}")

        await self.send_info(f"Unsubscribed from log '{log_alias}'.")

    async def handle_set_interval(self, payload):
        """Обработка запроса на изменение интервала мониторинга."""
        try:
            interval = int(payload.get('interval'))
            if interval < 1: # Минимальный интервал 1 секунда
                raise ValueError("Interval too short")
            if interval > 60: # Максимальный интервал 60 секунд
                 raise ValueError("Interval too long")

            self.monitoring_interval = interval

            # Перезапускаем задачу мониторинга с новым интервалом
            if self.monitoring_task:
                self.monitoring_task.cancel()
                try:
                    await self.monitoring_task
                except asyncio.CancelledError:
                    pass
            self.monitoring_task = asyncio.create_task(self.send_system_info_periodically())

            await self.send_info(f"Monitoring interval set to {self.monitoring_interval} seconds.")

        except (ValueError, TypeError):
            await self.send_error("Invalid interval value. Must be an integer between 1 and 60.")

    # --- Отправка данных клиенту ---

    async def send_system_info_periodically(self):
        """Периодически собирает и отправляет системную информацию."""
        while True:
            try:
                # Запускаем сбор данных в отдельном потоке, чтобы не блокировать asyncio loop
                # psutil может делать блокирующие вызовы
                loop = asyncio.get_running_loop()
                system_data = await loop.run_in_executor(None, get_system_info)

                await self.send_json({
                    'type': 'system_update',
                    'payload': system_data
                })
            except psutil.Error as e:
                print(f"Error getting system info: {e}")
                await self.send_error(f"Error getting system info: {e}")
            except Exception as e:
                 print(f"Unexpected error in monitoring loop: {e}")
                 await self.send_error(f"Unexpected monitoring error: {e}")
            # Ждем заданный интервал
            await asyncio.sleep(self.monitoring_interval)

    async def send_log_update(self, log_alias, line):
        """Отправляет новую строку лога клиенту."""
        await self.send_json({
            'type': 'log_update',
            'payload': {
                'log_alias': log_alias,
                'line': line
            }
        })

    async def send_error(self, message):
        """Отправляет сообщение об ошибке клиенту."""
        print(f"Sending error to {self.user}: {message}")
        await self.send_json({'type': 'error', 'payload': {'message': str(message)}})

    async def send_info(self, message):
         """Отправляет информационное сообщение клиенту."""
         print(f"Sending info to {self.user}: {message}")
         await self.send_json({'type': 'info', 'payload': {'message': str(message)}})

    async def send_json(self, data):
         """Отправляет JSON данные клиенту."""
         await self.send(text_data=json.dumps(data))

    # --- Вспомогательные методы ---
    def log_group_name(self, log_alias):
        """Генерирует имя группы Channels для конкретного лога."""
        # Важно: Имя группы должно быть безопасным для Redis/других бэкендов
        # Используем префикс и простой формат
        safe_alias = ''.join(c if c.isalnum() or c in ['-', '_'] else '_' for c in log_alias)
        return f"log_{safe_alias}"