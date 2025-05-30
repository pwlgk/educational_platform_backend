from django.contrib import admin
from .models import Notification, UserNotificationSettings
from django.urls import reverse # Импортировано для reverse

# Класс NotificationAdmin настраивает отображение и управление моделью Notification
# в административной панели Django.
# - list_display: Определяет колонки, отображаемые в списке уведомлений (получатель, тип,
#   предпросмотр сообщения, ссылка на связанный объект, статус прочтения, дата создания).
# - list_filter: Позволяет фильтровать список уведомлений по типу, статусу прочтения,
#   дате создания и получателю.
# - search_fields: Позволяет выполнять поиск по email/фамилии получателя и тексту сообщения.
# - list_select_related: Оптимизирует запросы к базе данных путем предварительной загрузки
#   связанных объектов User (recipient) и ContentType.
# - readonly_fields: Указывает поля, которые будут доступны только для чтения на странице
#   редактирования уведомления, так как они обычно устанавливаются программно.
# - list_per_page: Устанавливает количество уведомлений, отображаемых на одной странице списка.
# - message_preview: Кастомный метод для отображения сокращенного предпросмотра текста уведомления.
# - content_object_link: Кастомный метод для генерации HTML-ссылки на связанный объект
#   в административной панели, если такой объект существует и для него есть страница в админке.
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'message_preview', 'content_object_link', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at', 'recipient')
    search_fields = ('recipient__email', 'recipient__last_name', 'message')
    list_select_related = ('recipient', 'content_type')
    readonly_fields = ('recipient', 'message', 'notification_type', 'content_type', 'object_id', 'content_object', 'created_at')
    list_per_page = 50

    def message_preview(self, obj):
        return obj.message[:70] + '...' if len(obj.message) > 70 else obj.message
    message_preview.short_description = 'Текст'

    def content_object_link(self, obj):
        if obj.content_object:
            try:
                admin_url = reverse(f'admin:{obj.content_type.app_label}_{obj.content_type.model}_change', args=[obj.object_id])
                # Используем format_html для безопасного рендеринга HTML
                from django.utils.html import format_html
                return format_html('<a href="{}">{}</a>', admin_url, obj.content_object)
            except Exception:
                return f"{obj.content_object}"
        return '-'
    content_object_link.short_description = 'Связанный объект'
    # allow_tags устарел, format_html является предпочтительным способом

# Класс UserNotificationSettingsInline определяет встроенное отображение настроек
# уведомлений пользователя (модель UserNotificationSettings) непосредственно на странице
# редактирования объекта User в административной панели.
# Это позволяет администраторам просматривать и изменять настройки уведомлений
# конкретного пользователя в контексте его основной информации.
# - model: Указывает, что инлайн связан с моделью UserNotificationSettings.
# - can_delete: Устанавливает значение False, так как настройки уведомлений обычно
#   не удаляются отдельно от пользователя, а изменяются.
# - verbose_name_plural: Задает отображаемое имя для группы настроек в админ-панели.
#
# Для использования этого инлайна необходимо добавить его в список `inlines`
# класса `CustomUserAdmin` в файле `users/admin.py` модуля `users`.
class UserNotificationSettingsInline(admin.StackedInline):
    model = UserNotificationSettings
    can_delete = False
    verbose_name_plural = 'Настройки уведомлений'
