from django.contrib import admin
from .models import ForumCategory, ForumTopic, ForumPost, ForumReaction
from taggit.models import Tag

# Отдельно регистрируем стандартную модель Tag, если нужно
# admin.site.register(Tag)

@admin.register(ForumCategory)
class ForumCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'display_order')
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ('display_order',)

class ForumPostInline(admin.TabularInline):
    model = ForumPost
    fields = ('author', 'content', 'parent', 'created_at')
    readonly_fields = ('author', 'created_at')
    extra = 0
    ordering = ('created_at',)

@admin.register(ForumTopic)
class ForumTopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author', 'created_at', 'last_post_at', 'is_pinned', 'is_closed', 'post_count')
    list_filter = ('is_pinned', 'is_closed', 'category', 'created_at', 'author')
    search_fields = ('title', 'author__email', 'author__last_name', 'category__name')
    list_select_related = ('category', 'author', 'first_post') # Оптимизация
    date_hierarchy = 'created_at'
    ordering = ('-is_pinned', '-last_post_at')
    # Отображаем теги
    filter_horizontal = () # TaggableManager не работает с filter_horizontal
    readonly_fields = ('created_at', 'last_post_at', 'first_post')
    # Поля для редактирования
    fields = ('category', 'title', 'author', ('is_pinned', 'is_closed'), 'tags')
    # inlines = [ForumPostInline] # Может быть слишком много постов

    def get_queryset(self, request):
        # Оптимизируем подсчет постов, если нужно (или используем @property)
        return super().get_queryset(request) #.annotate(num_posts=models.Count('posts'))

    # def post_count(self, obj):
    #     return obj.num_posts # Если используем annotate
    # post_count.admin_order_field = 'num_posts'
    # post_count.short_description = 'Постов'


@admin.register(ForumPost)
class ForumPostAdmin(admin.ModelAdmin):
    list_display = ('id', 'topic_title', 'author', 'content_preview', 'parent', 'created_at', 'likes_count')
    list_filter = ('created_at', 'author', 'topic__category')
    search_fields = ('content', 'author__email', 'author__last_name', 'topic__title')
    list_select_related = ('author', 'topic', 'parent') # Оптимизация
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def topic_title(self, obj):
        return obj.topic.title
    topic_title.short_description = 'Тема'
    topic_title.admin_order_field = 'topic__title'

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Текст'

@admin.register(ForumReaction)
class ForumReactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'reaction_type', 'content_object', 'timestamp')
    list_filter = ('reaction_type', 'timestamp', 'content_type')
    search_fields = ('user__email', 'user__last_name')
    readonly_fields = ('user', 'reaction_type', 'content_type', 'object_id', 'content_object', 'timestamp')