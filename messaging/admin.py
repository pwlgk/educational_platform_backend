from django.contrib import admin
from .models import Chat, ChatParticipant, Message

# Класс ChatParticipantInline определяет встроенное отображение участников чата
# непосредственно на странице редактирования объекта Chat в административной панели.
# Это позволяет администраторам просматривать и добавлять участников чата
# без необходимости переходить на отдельную страницу для ChatParticipant.
# - model: Указывает, что инлайн связан с моделью ChatParticipant.
# - extra: Определяет количество пустых форм для добавления новых участников, отображаемых по умолчанию.
# - raw_id_fields: (Закомментировано) Если раскомментировать, поле 'user' будет отображаться
#   как текстовое поле для ввода ID пользователя, что удобно при большом количестве пользователей,
#   так как заменяет стандартный выпадающий список на более производительный виджет.
class ChatParticipantInline(admin.TabularInline):
    model = ChatParticipant
    extra = 1
    # raw_id_fields = ('user',)

# Класс MessageInline определяет встроенное отображение сообщений чата
# на странице редактирования объекта Chat. Это позволяет администраторам
# просматривать недавние сообщения в контексте конкретного чата.
# - model: Связывает инлайн с моделью Message.
# - fields: Явно указывает поля модели Message, которые будут отображаться в инлайне.
# - readonly_fields: Поля 'sender' и 'timestamp' делаются доступными только для чтения
#   в данном инлайне, так как они обычно устанавливаются автоматически при создании сообщения.
# - extra: Устанавливает значение 0, что означает, что по умолчанию не будет отображаться
#   пустых форм для добавления новых сообщений через этот интерфейс (сообщения создаются через приложение).
# - ordering: Сообщения в инлайне будут отсортированы по времени их создания ('timestamp').
class MessageInline(admin.TabularInline):
    model = Message
    fields = ('sender', 'content', 'file', 'timestamp')
    readonly_fields = ('sender', 'timestamp')
    extra = 0
    ordering = ('timestamp',)

# Класс ChatAdmin настраивает отображение и управление моделью Chat
# в административной панели Django.
# - list_display: Определяет колонки, отображаемые в списке чатов. Включает кастомные методы.
# - list_filter: Позволяет фильтровать список чатов по типу и дате создания.
# - search_fields: Позволяет выполнять поиск по названию чата и email/фамилии участников.
# - inlines: Включает ChatParticipantInline и MessageInline для отображения участников и сообщений
#   непосредственно на странице редактирования чата.
# - readonly_fields: Поля 'created_at' и 'last_message' доступны только для чтения.
# - display_name: Кастомный метод для отображения информативного имени чата (название группы
#   или имена участников для личных чатов).
# - participant_count: Кастомный метод для отображения количества участников в чате.
# - last_message_time: Кастомный метод для отображения времени последнего сообщения в чате.
@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('id', 'display_name', 'chat_type', 'created_at', 'participant_count', 'last_message_time')
    list_filter = ('chat_type', 'created_at')
    search_fields = ('name', 'participants__email', 'participants__last_name')
    inlines = [ChatParticipantInline, MessageInline]
    readonly_fields = ('created_at', 'last_message')

    def display_name(self, obj):
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.name or f"Группа {obj.id}"
        else:
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


# Класс ChatParticipantAdmin настраивает отображение и управление моделью ChatParticipant
# (связь между пользователем и чатом) в административной панели.
# - list_display: Определяет колонки в списке участников чатов (пользователь, ID чата, дата присоединения,
#   время последнего прочитанного сообщения).
# - list_select_related: Оптимизирует запросы к базе данных путем предварительной загрузки
#   связанных объектов User, Chat и Message (для last_read_message).
# - search_fields: Позволяет искать по email пользователя и названию чата.
# - chat_id_display: Кастомный метод для отображения ID чата.
# - last_read_message_time: Кастомный метод для отображения времени последнего прочитанного сообщения.
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


# Класс MessageAdmin настраивает отображение и управление моделью Message
# в административной панели Django.
# - list_display: Определяет колонки в списке сообщений (ID, ID чата, отправитель,
#   предпросмотр контента, наличие файла, временная метка).
# - list_filter: Позволяет фильтровать сообщения по временной метке и чату.
# - search_fields: Позволяет искать по содержимому сообщения, email отправителя и названию чата.
# - list_select_related: Оптимизирует запросы путем предварительной загрузки связанных
#   объектов User (sender) и Chat.
# - readonly_fields: Поле 'timestamp' доступно только для чтения.
# - date_hierarchy: Добавляет навигацию по датам в списке сообщений, используя поле 'timestamp'.
# - content_preview: Кастомный метод для отображения сокращенного предпросмотра текста сообщения.
# - has_file: Кастомный метод для отображения булева значения, указывающего на наличие прикрепленного файла.
# - chat_id_display: Кастомный метод для отображения ID чата, к которому принадлежит сообщение.
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