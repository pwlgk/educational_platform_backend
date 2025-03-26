from django.contrib import admin
from .models import Notification, UserNotificationSettings

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'message_preview', 'content_object_link', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at', 'recipient')
    search_fields = ('recipient__email', 'recipient__last_name', 'message')
    list_select_related = ('recipient', 'content_type') # Оптимизация
    readonly_fields = ('recipient', 'message', 'notification_type', 'content_type', 'object_id', 'content_object', 'created_at')
    list_per_page = 50

    def message_preview(self, obj):
        return obj.message[:70] + '...' if len(obj.message) > 70 else obj.message
    message_preview.short_description = 'Текст'

    def content_object_link(self, obj):
        # Ссылка на связанный объект в админке (если возможно)
        if obj.content_object:
            from django.urls import reverse
            try:
                admin_url = reverse(f'admin:{obj.content_type.app_label}_{obj.content_type.model}_change', args=[obj.object_id])
                return f'<a href="{admin_url}">{obj.content_object}</a>'
            except Exception:
                return f"{obj.content_object}"
        return '-'
    content_object_link.short_description = 'Связанный объект'
    content_object_link.allow_tags = True # Для рендеринга HTML


class UserNotificationSettingsInline(admin.StackedInline):
    model = UserNotificationSettings
    can_delete = False
    verbose_name_plural = 'Настройки уведомлений'

# Добавляем inline в админку User (нужно изменить users/admin.py)
# В users/admin.py:
# from notifications.admin import UserNotificationSettingsInline # Импорт
# class CustomUserAdmin(BaseUserAdmin):
#     inlines = (ProfileInline, UserNotificationSettingsInline) # Добавить сюда
#     ...

# Можно зарегистрировать и отдельно, но inline удобнее
# @admin.register(UserNotificationSettings)
# class UserNotificationSettingsAdmin(admin.ModelAdmin):
#    list_display = ('user', 'enable_news', 'enable_schedule', 'enable_messages', 'enable_forum')
#    search_fields = ('user__email',)