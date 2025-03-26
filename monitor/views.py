import psutil
import subprocess
import re
import os
import asyncio
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, inline_serializer
from rest_framework import serializers # Для inline_serializer

# --- Вспомогательные функции ---

def get_system_info():
    """Собирает основную информацию о системе."""
    return {
        'cpu_percent': psutil.cpu_percent(interval=0.1), # Небольшой интервал для получения актуального значения
        'cpu_count_logical': psutil.cpu_count(),
        'cpu_count_physical': psutil.cpu_count(logical=False),
        'memory': psutil.virtual_memory()._asdict(), # ._asdict() для сериализации
        'swap': psutil.swap_memory()._asdict(),
        'disk_usage': psutil.disk_usage('/')._asdict(), # Корень диска, можно добавить другие
        'network': psutil.net_io_counters()._asdict(),
        'uptime': psutil.boot_time() # Timestamp загрузки
    }

def get_process_list():
    """Возвращает список процессов."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status', 'create_time', 'cmdline']):
        try:
            pinfo = proc.info
            # Преобразуем cmdline в строку для простоты
            pinfo['cmdline'] = ' '.join(pinfo['cmdline']) if pinfo['cmdline'] else ''
            processes.append(pinfo)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return processes

def execute_command(command, timeout=10):
    """Безопасное выполнение команды с таймаутом."""
    # ВАЖНО: Здесь нужна строгая валидация и/или ограничение доступных команд!
    # Пример простой валидации (очень ограниченный):
    allowed_commands = ['ls', 'pwd', 'hostname', 'uptime'] # Только безопасные команды без аргументов
    command_parts = command.split()
    if not command_parts or command_parts[0] not in allowed_commands:
        # Или более сложная проверка аргументов
        # if command_parts[0] == 'tail' and len(command_parts) > 1:
        #     # Проверить, что второй аргумент - разрешенный файл лога
        #     pass
        # else:
             raise PermissionDenied("Выполнение этой команды запрещено.")

    try:
        # Не используйте shell=True без крайней необходимости и строгой санации ввода!
        result = subprocess.run(
            command_parts, # Передаем как список для безопасности
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False # Не выбрасывать исключение при ненулевом коде возврата
        )
        return {
            'command': command,
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'command': command,
            'stdout': '',
            'stderr': f'Ошибка: Команда "{command}" превысила таймаут ({timeout}с)',
            'returncode': -1 # Условный код ошибки таймаута
        }
    except FileNotFoundError:
         return {
            'command': command,
            'stdout': '',
            'stderr': f'Ошибка: Команда или исполняемый файл не найден.',
            'returncode': -1
        }
    except Exception as e:
        return {
            'command': command,
            'stdout': '',
            'stderr': f'Неизвестная ошибка выполнения: {e}',
            'returncode': -1
        }

async def read_log_file(log_path, lines=50):
    """Асинхронно читает последние строки лог-файла."""
    try:
        import aiofiles
        # Проверка безопасности пути (предотвращение выхода за пределы разрешенных директорий)
        # Здесь нужна более надежная проверка в реальном приложении
        if '..' in log_path:
             raise PermissionDenied("Недопустимый путь к файлу.")

        # Проверяем, существует ли файл
        if not os.path.exists(log_path) or not os.path.isfile(log_path):
            raise NotFound(f"Файл лога не найден: {log_path}")

        # Проверяем права доступа на чтение
        if not os.access(log_path, os.R_OK):
             raise PermissionDenied(f"Нет прав на чтение файла: {log_path}")

        async with aiofiles.open(log_path, mode='r', encoding='utf-8', errors='ignore') as f:
            # Чтение может быть неэффективным для больших файлов,
            # но для последних N строк это приемлемо.
            # Для очень больших файлов лучше использовать `tail` через subprocess.
            log_lines = await f.readlines()
            return log_lines[-lines:]
    except ImportError:
         raise APIException("Модуль 'aiofiles' не установлен. Установите его: pip install aiofiles")
    except FileNotFoundError:
         raise NotFound(f"Файл лога не найден: {log_path}")
    except PermissionError:
        raise PermissionDenied(f"Нет прав на чтение файла: {log_path}")
    except Exception as e:
        raise APIException(f"Ошибка чтения лога: {e}")

def manage_service(service_name, action):
    """Управление службами (пример для systemd)."""
    # ВАЖНО: Требует прав sudo или настройки polkit/sudoers для пользователя www-data (или от кого запущен Django)
    # Это небезопасно без должной настройки!
    allowed_actions = ['start', 'stop', 'restart', 'status']
    if action not in allowed_actions:
        raise ValidationError("Недопустимое действие.")

    # Проверка имени службы (простая, можно улучшить)
    if not re.match(r'^[a-zA-Z0-9\-._]+$', service_name):
        raise ValidationError("Недопустимое имя службы.")

    command = ['sudo', 'systemctl', action, service_name]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False # Статус может возвращать ненулевой код, если служба не активна
        )
        # `systemctl status` возвращает 0, если активна, и не 0, если неактивна/не найдена
        success = result.returncode == 0 if action != 'status' else True # Для status любой код OK

        return {
            'service': service_name,
            'action': action,
            'success': success,
            'output': (result.stdout.strip() + "\n" + result.stderr.strip()).strip(),
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'service': service_name, 'action': action, 'success': False, 'output': f'Ошибка: Таймаут при выполнении {action} {service_name}', 'returncode': -1}
    except FileNotFoundError:
         return {'service': service_name, 'action': action, 'success': False, 'output': 'Ошибка: Команда systemctl или sudo не найдена.', 'returncode': -1}
    except Exception as e:
         return {'service': service_name, 'action': action, 'success': False, 'output': f'Неизвестная ошибка: {e}', 'returncode': -1}

def get_service_list_systemd():
    """Получение списка служб systemd."""
    # Это может быть медленно и требует прав
    try:
        result = subprocess.run(
            ['systemctl', 'list-units', '--type=service', '--all', '--no-pager', '--plain'],
            capture_output=True,
            text=True,
            timeout=10,
            check=True
        )
        lines = result.stdout.strip().split('\n')
        services = []
        # Пропускаем заголовок и последнюю строку
        for line in lines[1:-1]:
            parts = line.split(maxsplit=4)
            if len(parts) >= 4:
                # Имя может содержать '@', удаляем его и часть после для шаблонов
                name = parts[0].split('@')[0].replace('.service', '')
                services.append({
                    'unit': parts[0],
                    'name': name,
                    'load': parts[1],
                    'active': parts[2],
                    'sub': parts[3],
                    'description': parts[4] if len(parts) > 4 else ''
                })
        return services
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
        # Возвращаем пустой список или информацию об ошибке
        print(f"Ошибка получения списка служб: {e}")
        return []
    except Exception as e:
        print(f"Неизвестная ошибка при получении списка служб: {e}")
        return []


# --- Права доступа ---
class IsSuperUserOrReadOnly(permissions.BasePermission):
    """
    Разрешает чтение всем аутентифицированным пользователям,
    а изменение/управление только суперпользователям.
    """
    def has_permission(self, request, view):
        # Разрешить GET, HEAD, OPTIONS запросы всем аутентифицированным
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        # Разрешить другие методы только суперпользователям
        return request.user and request.user.is_superuser


# --- Представления API ---

@extend_schema(tags=['Monitoring'])
class SystemInfoView(APIView):
    """
    Возвращает общую информацию о системе (CPU, RAM, Disk, Network).
    """
    permission_classes = [permissions.IsAuthenticated] # Доступно всем авторизованным

    def get(self, request, format=None):
        """Получить текущие системные метрики."""
        try:
            data = get_system_info()
            return Response(data)
        except Exception as e:
            raise APIException(f"Ошибка получения системной информации: {e}")


@extend_schema(tags=['Process Management'])
class ProcessListView(APIView):
    """
    Возвращает список запущенных процессов.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, format=None):
        """Получить список процессов."""
        try:
            data = get_process_list()
            return Response(data)
        except Exception as e:
            raise APIException(f"Ошибка получения списка процессов: {e}")


@extend_schema(tags=['Process Management'])
class ProcessDetailView(APIView):
    """
    Позволяет выполнить действия над процессом (например, завершить).
    """
    permission_classes = [IsSuperUserOrReadOnly] # Управление только для админов

    @extend_schema(
        request=inline_serializer(
            name='ProcessAction',
            fields={'action': serializers.ChoiceField(choices=['terminate', 'kill'])}
        ),
        responses={
            200: inline_serializer(name='ProcessActionResponse', fields={'status': serializers.CharField()}),
            400: OpenApiExample("Bad Request", value={'detail': 'Invalid action'}),
            403: OpenApiExample("Forbidden", value={'detail': 'Permission denied'}),
            404: OpenApiExample("Not Found", value={'detail': 'Process not found'}),
        }
    )
    def post(self, request, pid, format=None):
        """
        Выполнить действие над процессом (terminate/kill).
        Требует прав суперпользователя.
        """
        if not request.user.is_superuser:
             raise PermissionDenied("Требуются права суперпользователя для управления процессами.")

        action = request.data.get('action')
        if action not in ['terminate', 'kill']:
            raise ValidationError('Недопустимое действие. Доступно: terminate, kill')

        try:
            proc = psutil.Process(pid)
            if action == 'terminate':
                proc.terminate() # SIGTERM
                return Response({'status': f'Sent SIGTERM to process {pid}'})
            elif action == 'kill':
                proc.kill() # SIGKILL
                return Response({'status': f'Sent SIGKILL to process {pid}'})
        except psutil.NoSuchProcess:
            raise NotFound(f'Процесс с PID {pid} не найден.')
        except psutil.AccessDenied:
             raise PermissionDenied(f'Недостаточно прав для управления процессом {pid}.')
        except Exception as e:
             raise APIException(f'Ошибка при управлении процессом {pid}: {e}')


@extend_schema(tags=['Service Management'])
class ServiceListView(APIView):
    """
    Возвращает список системных служб (зависит от ОС, пример для systemd).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, format=None):
        """Получить список служб (systemd)."""
        # Здесь можно добавить проверку ОС и вызывать разные функции
        # if sys.platform == 'linux':
        #     # Проверить наличие systemctl
        # else:
        #     return Response({"error": "Service listing not supported on this OS"}, status=status.HTTP_501_NOT_IMPLEMENTED)
        services = get_service_list_systemd()
        return Response(services)


@extend_schema(tags=['Service Management'])
class ServiceActionView(APIView):
    """
    Управляет системными службами (start, stop, restart, status).
    Требует прав суперпользователя (или настроенного sudo/polkit).
    """
    permission_classes = [IsSuperUserOrReadOnly] # Управление только для админов

    @extend_schema(
         parameters=[
             OpenApiParameter(name='service_name', location=OpenApiParameter.PATH, required=True, type=str, description='Имя службы'),
             OpenApiParameter(name='action', location=OpenApiParameter.PATH, required=True, type=str, enum=['start', 'stop', 'restart', 'status'], description='Действие над службой'),
         ],
         responses={
            200: inline_serializer(name='ServiceActionResponse', fields={
                'service': serializers.CharField(),
                'action': serializers.CharField(),
                'success': serializers.BooleanField(),
                'output': serializers.CharField(),
                'returncode': serializers.IntegerField(),
            }),
            400: OpenApiExample("Bad Request", value={'detail': 'Invalid action or service name'}),
            403: OpenApiExample("Forbidden", value={'detail': 'Permission denied'}),
         }
    )
    def post(self, request, service_name, action, format=None):
        """
        Выполнить действие (start, stop, restart, status) над службой.
        Требует прав суперпользователя и настроенного sudo/polkit.
        """
        if not request.user.is_superuser:
             raise PermissionDenied("Требуются права суперпользователя для управления службами.")

        try:
            result = manage_service(service_name, action)
            # Определяем статус ответа на основе результата
            response_status = status.HTTP_200_OK if result['success'] else status.HTTP_400_BAD_REQUEST
            # Для действия 'status' всегда возвращаем 200 OK, если команда выполнилась,
            # даже если служба неактивна (ненулевой returncode). Фронтенд разберет 'output'.
            if action == 'status' and 'output' in result:
                 response_status = status.HTTP_200_OK

            return Response(result, status=response_status)
        except (ValidationError, PermissionDenied) as e:
            # Перехватываем ошибки валидации и прав доступа из manage_service
             raise e
        except Exception as e:
             raise APIException(f"Неизвестная ошибка при управлении службой: {e}")

@extend_schema(tags=['Logging'])
class LogFileView(APIView):
    """
    Позволяет просмотреть последние строки указанного лог-файла.
    """
    permission_classes = [IsSuperUserOrReadOnly] # Чтение логов может быть чувствительным

    @extend_schema(
        parameters=[
            OpenApiParameter(name='log_alias', required=True, type=str, description='Псевдоним лог-файла (из настроек MONITOR_LOG_FILES)'),
            OpenApiParameter(name='lines', required=False, type=int, default=50, description='Количество последних строк для отображения'),
        ],
        responses={
            200: inline_serializer(name='LogResponse', fields={'log_alias': serializers.CharField(), 'lines': serializers.ListField(child=serializers.CharField())}),
            400: OpenApiExample("Bad Request", value={'detail': 'Missing log_alias parameter'}),
            403: OpenApiExample("Forbidden", value={'detail': 'Permission denied'}),
            404: OpenApiExample("Not Found", value={'detail': 'Log alias or file not found'}),
        }
    )
    async def get(self, request, format=None):
        """
        Получить последние N строк лог-файла по его псевдониму.
        """
        log_alias = request.query_params.get('log_alias')
        if not log_alias:
             raise ValidationError('Параметр "log_alias" обязателен.')

        lines = request.query_params.get('lines', 50)
        try:
            lines = int(lines)
            if lines <= 0 or lines > 1000: # Ограничение на количество строк
                 raise ValueError()
        except ValueError:
            raise ValidationError('Параметр "lines" должен быть положительным числом (макс. 1000).')

        log_path = settings.MONITOR_LOG_FILES.get(log_alias)
        if not log_path:
             raise NotFound(f'Псевдоним лога "{log_alias}" не найден в настройках.')

        # Проверяем права доступа перед чтением
        if not request.user.is_superuser and not request.user.has_perm('monitor.view_log'): # Пример кастомного права
             # Если не суперюзер, проверяем, есть ли у него спец. право (нужно создать модель и миграции для этого)
             # Для простоты пока ограничимся суперюзером
             raise PermissionDenied("Недостаточно прав для просмотра этого лога.")

        try:
            log_lines = await read_log_file(log_path, lines)
            return Response({'log_alias': log_alias, 'lines': log_lines})
        except (APIException, NotFound, PermissionDenied, ValidationError) as e:
            # Перебрасываем ошибки, возникшие при чтении файла
             raise e
        except Exception as e:
            # Ловим остальные неожиданные ошибки
            raise APIException(f"Непредвиденная ошибка при чтении лога: {e}")


@extend_schema(tags=['Management'])
class CommandExecutionView(APIView):
    """
    Выполняет предопределенные (безопасные) команды на сервере.
    **ВНИМАНИЕ:** Эта функция очень опасна, если не ограничить строго список доступных команд!
    """
    permission_classes = [IsSuperUserOrReadOnly] # Только для суперпользователей

    @extend_schema(
        request=inline_serializer(name='CommandRequest', fields={'command': serializers.CharField()}),
        responses={
            200: inline_serializer(name='CommandResponse', fields={
                'command': serializers.CharField(),
                'stdout': serializers.CharField(),
                'stderr': serializers.CharField(),
                'returncode': serializers.IntegerField(),
            }),
            400: OpenApiExample("Bad Request", value={'detail': 'Missing command parameter'}),
            403: OpenApiExample("Forbidden", value={'detail': 'Command execution forbidden or permission denied'}),
        }
    )
    def post(self, request, format=None):
        """
        Выполнить разрешенную команду на сервере.
        Требует прав суперпользователя.
        """
        if not request.user.is_superuser:
             raise PermissionDenied("Требуются права суперпользователя для выполнения команд.")

        command = request.data.get('command')
        if not command:
            raise ValidationError('Параметр "command" обязателен.')

        try:
            # Валидация и выполнение команды происходит внутри execute_command
            result = execute_command(command)
            # Определяем статус HTTP на основе returncode
            status_code = status.HTTP_200_OK if result['returncode'] == 0 else status.HTTP_400_BAD_REQUEST
            # Если команда просто не найдена или таймаут, тоже можно считать ошибкой клиента/сервера
            if result['returncode'] == -1:
                 status_code = status.HTTP_500_INTERNAL_SERVER_ERROR if 'Таймаут' in result['stderr'] else status.HTTP_400_BAD_REQUEST

            return Response(result, status=status_code)
        except PermissionDenied as e:
             raise PermissionDenied(f"Ошибка выполнения команды: {e}") # Перебрасываем ошибку прав
        except Exception as e:
             raise APIException(f"Неизвестная ошибка при выполнении команды: {e}")