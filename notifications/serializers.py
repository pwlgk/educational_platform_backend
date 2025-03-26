from rest_framework import serializers
from .models import Notification, UserNotificationSettings

class NotificationSerializer(serializers.ModelSerializer):
    # Опционально: добавить информацию о связанном объекте
    # content_object_url = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            'id', 'recipient', 'message', 'notification_type',
            'created_at', 'is_read',
            'content_type', 'object_id', # По ID можно будет перейти на клиенте
            # 'content_object_url'
        )
        read_only_fields = ('recipient', 'message', 'notification_type', 'created_at', 'content_type', 'object_id')

    # def get_content_object_url(self, obj):
    #     # Генерация URL для связанного объекта (сложно и зависит от URL-структуры)
    #     if obj.content_object:
    #         try:
    #             # Пример для новости
    #             if isinstance(obj.content_object, NewsArticle):
    #                  from rest_framework.reverse import reverse
    #                  return reverse('news-article-detail', args=[obj.object_id], request=self.context.get('request'))
    #             # Добавить другие типы...
    #         except Exception:
    #             return None
    #     return None

class UserNotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationSettings
        exclude = ('user', 'id') # Исключаем ID и пользователя, т.к. доступ по user