# messaging/filters.py (создайте этот файл, если его нет)
import django_filters
from .models import Message

class ChatMediaFilter(django_filters.FilterSet):
    # Фильтр по типу медиа
    type = django_filters.ChoiceFilter(
        method='filter_by_media_type',
        choices=(
            ('image', 'Image'),
            ('video', 'Video'),
            ('file', 'File'), # 'file' будет означать "не картинка и не видео"
        ),
        label='Media Type'
    )

    class Meta:
        model = Message
        fields = ['type'] # Поле для фильтрации

    def filter_by_media_type(self, queryset, name, value):
        # name будет 'type', value будет 'image', 'video' или 'file'
        if value == 'image':
            # Ищем все распространенные типы изображений
            return queryset.filter(mime_type__istartswith='image/')
        elif value == 'video':
            # Ищем все распространенные типы видео
            return queryset.filter(mime_type__istartswith='video/')
        elif value == 'file':
            # Исключаем изображения и видео
            return queryset.exclude(mime_type__istartswith='image/').exclude(mime_type__istartswith='video/')
        # Если тип не указан или не распознан, возвращаем исходный queryset
        return queryset