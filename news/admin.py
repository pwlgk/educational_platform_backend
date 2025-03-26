from django.contrib import admin
from .models import NewsCategory, NewsArticle, NewsComment, Reaction

@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)} # Автозаполнение slug

class NewsCommentInline(admin.TabularInline): # Или StackedInline
    """Отображение комментариев внутри статьи."""
    model = NewsComment
    fields = ('author', 'content', 'parent', 'created_at')
    readonly_fields = ('author', 'created_at')
    extra = 0 # Не показывать пустые формы по умолчанию
    # Ограничение глубины для производительности
    # raw_id_fields = ('author', 'parent')

@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author', 'created_at', 'is_published', 'comment_count', 'likes_count')
    list_filter = ('is_published', 'category', 'created_at', 'author')
    search_fields = ('title', 'content', 'author__email', 'author__last_name')
    list_select_related = ('category', 'author') # Оптимизация
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    inlines = [NewsCommentInline] # Отображаем комментарии
    readonly_fields = ('created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        # Устанавливаем автора при создании из админки
        if not obj.pk:
            obj.author = request.user
        super().save_model(request, obj, form, change)

@admin.register(NewsComment)
class NewsCommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'article_title', 'content_preview', 'parent', 'created_at', 'likes_count')
    list_filter = ('created_at', 'author')
    search_fields = ('content', 'author__email', 'author__last_name', 'article__title')
    list_select_related = ('author', 'article', 'parent') # Оптимизация
    readonly_fields = ('created_at',)

    def article_title(self, obj):
        return obj.article.title
    article_title.short_description = 'Статья'
    article_title.admin_order_field = 'article__title'

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Текст'

@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'reaction_type', 'content_object', 'timestamp')
    list_filter = ('reaction_type', 'timestamp', 'content_type')
    search_fields = ('user__email', 'user__last_name')
    readonly_fields = ('user', 'reaction_type', 'content_type', 'object_id', 'content_object', 'timestamp')