from rest_framework import serializers
from .models import Notification, UserNotificationSettings

# Сериализатор NotificationSerializer предназначен для преобразования экземпляров
# модели Notification в JSON-представление и обратно (хотя в данном случае
# большинство полей read-only, что означает, что он в основном используется для чтения).
# - Meta класс:
#   - model = Notification: Указывает, что сериализатор работает с моделью Notification.
#   - fields: Определяет набор полей модели, которые будут включены в сериализованное
#     представление. Включает 'id', 'recipient' (получатель), 'message' (текст),
#     'notification_type' (тип), 'created_at' (дата создания), 'is_read' (статус прочтения),
#     а также 'content_type' и 'object_id' для ссылки на связанный объект (GenericForeignKey).
#   - read_only_fields: Список полей, которые доступны только для чтения. Это означает,
#     что эти поля не могут быть изменены через API с использованием этого сериализатора.
#     Обычно такие поля устанавливаются программно при создании уведомления.
#
# Закомментированное поле 'content_object_url' предполагает возможность добавления
# метода для генерации URL-адреса связанного объекта, если это необходимо для клиента.
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            'id', 'recipient', 'message', 'notification_type',
            'created_at', 'is_read',
            'content_type', 'object_id',
        )
        read_only_fields = ('recipient', 'message', 'notification_type', 'created_at', 'content_type', 'object_id')

# Сериализатор UserNotificationSettingsSerializer предназначен для преобразования
# экземпляров модели UserNotificationSettings (настройки уведомлений пользователя)
# в JSON-представление и обратно (для обновления настроек).
# - Meta класс:
#   - model = UserNotificationSettings: Указывает, что сериализатор работает с моделью UserNotificationSettings.
#   - exclude = ('user', 'id'): Определяет поля, которые будут исключены из сериализованного
#     представления. Поле 'user' исключается, так как настройки обычно получаются
#     и обновляются в контексте конкретного аутентифицированного пользователя (связь OneToOne).
#     Поле 'id' также часто исключается для настроек, связанных с пользователем через OneToOne,
#     так как идентификация происходит по пользователю.
#     Все остальные поля модели UserNotificationSettings (например, enable_schedule, enable_messages)
#     будут автоматически включены и доступны для чтения и записи, позволяя пользователю
#     обновлять свои предпочтения по уведомлениям.
class UserNotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationSettings
        exclude = ('user', 'id')