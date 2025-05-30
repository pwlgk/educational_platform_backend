import django_filters
from .models import Message

# Класс ChatMediaFilter представляет собой набор фильтров для модели Message,
# предназначенный для фильтрации сообщений с медиа-вложениями по их типу.
# Он наследуется от django_filters.FilterSet, что интегрирует его с библиотекой
# django-filter для удобного создания фильтров в Django REST framework.
#
# Основные компоненты:
# - Поле 'type': Это ChoiceFilter, который позволяет пользователю выбирать тип медиа
#   из предопределенного списка: 'image' (изображение), 'video' (видео) или 'file' (другой файл).
#   - method='filter_by_media_type': Указывает, что для применения этого фильтра
#     будет использоваться кастомный метод `filter_by_media_type`.
#   - choices: Определяет доступные варианты выбора для фильтра.
#   - label: Метка, отображаемая для этого фильтра (например, в интерфейсе DRF Browsable API).
#
# - Meta класс:
#   - model = Message: Указывает, что фильтры применяются к модели Message.
#   - fields = ['type']: Список полей, по которым можно фильтровать. В данном случае,
#     это кастомное поле 'type', определенное выше.
#
# - Метод `filter_by_media_type(self, queryset, name, value)`:
#   Этот метод реализует логику фильтрации на основе значения, выбранного для поля 'type'.
#   - queryset: Исходный набор данных (QuerySet) сообщений, к которому применяется фильтр.
#   - name: Имя поля фильтра (в данном случае, 'type').
#   - value: Выбранное значение фильтра ('image', 'video' или 'file').
#   Логика фильтрации:
#     - Если value == 'image': Фильтрует сообщения, у которых поле `mime_type` начинается с 'image/'.
#     - Если value == 'video': Фильтрует сообщения, у которых поле `mime_type` начинается с 'video/'.
#     - Если value == 'file': Фильтрует сообщения, исключая те, у которых `mime_type` начинается
#       с 'image/' или 'video/', таким образом оставляя только "другие" файлы.
#   Если тип не указан или не распознан, возвращает исходный queryset без изменений.
class ChatMediaFilter(django_filters.FilterSet):
    type = django_filters.ChoiceFilter(
        method='filter_by_media_type',
        choices=(
            ('image', 'Image'),
            ('video', 'Video'),
            ('file', 'File'),
        ),
        label='Media Type'
    )

    class Meta:
        model = Message
        fields = ['type']

    def filter_by_media_type(self, queryset, name, value):
        if value == 'image':
            return queryset.filter(mime_type__istartswith='image/')
        elif value == 'video':
            return queryset.filter(mime_type__istartswith='video/')
        elif value == 'file':
            return queryset.exclude(mime_type__istartswith='image/').exclude(mime_type__istartswith='video/')
        return queryset