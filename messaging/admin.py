from django.contrib import admin
from .models import Chat, ChatParticipant, Message

class ChatParticipantInline(admin.TabularInline):
    model = ChatParticipant
    extra = 1
    # raw_id_fields = ('user',) # Если пользователей много

class MessageInline(admin.TabularInline): # Или StackedInline
    model = Message
    fields = ('sender', 'content', 'file', 'timestamp')
    readonly_fields = ('sender', 'timestamp')
    extra = 0
    ordering = ('timestamp',)

@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('id', 'display_name', 'chat_type', 'created_at', 'participant_count', 'last_message_time')
    list_filter = ('chat_type', 'created_at')
    search_fields = ('name', 'participants__email', 'participants__last_name') # Поиск по названию и участникам
    inlines = [ChatParticipantInline, MessageInline]
    readonly_fields = ('created_at', 'last_message')

    def display_name(self, obj):
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.name or f"Группа {obj.id}"
        else:
            # Показываем имена 2 участников (может быть медленно)
            participants = list(obj.participants.all()[:2])
            if len(participants) == 2:
                return f"Личный: {participants[0].get_full_name()} ↔ {participants[1].get_full_name()}"
            return f"Личный чат {obj.id}"
    display_name.short_description = 'Название/Участники'

    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = 'Участников'

    def last_message_time(self, obj):
        return obj.last_message.timestamp if obj.last_message else '-'
    last_message_time.short_description = 'Последнее сообщение'
    last_message_time.admin_order_field = 'last_message__timestamp'


@admin.register(ChatParticipant)
class ChatParticipantAdmin(admin.ModelAdmin):
    list_display = ('user', 'chat_id_display', 'joined_at', 'last_read_message_time')
    list_select_related = ('user', 'chat', 'last_read_message')
    search_fields = ('user__email', 'chat__name')

    def chat_id_display(self, obj):
        return obj.chat.id
    chat_id_display.short_description = 'ID чата'

    def last_read_message_time(self, obj):
        return obj.last_read_message.timestamp if obj.last_read_message else '-'
    last_read_message_time.short_description = 'Последнее прочитанное'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat_id_display', 'sender', 'content_preview', 'has_file', 'timestamp')
    list_filter = ('timestamp', 'chat')
    search_fields = ('content', 'sender__email', 'chat__name')
    list_select_related = ('sender', 'chat')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Текст'

    def has_file(self, obj):
        return bool(obj.file)
    has_file.short_description = 'Файл'
    has_file.boolean = True

    def chat_id_display(self, obj):
        return obj.chat.id
    chat_id_display.short_description = 'ID чата'