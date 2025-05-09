from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from .models import NewsCategory, NewsArticle, NewsComment, Reaction
from users.serializers import UserSerializer # Для отображения автора

class NewsCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsCategory
        fields = ('id', 'name', 'slug', 'description')
        read_only_fields = ('slug',) # Slug генерируется автоматически

class NewsReactionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True) # Показываем информацию о пользователе

    class Meta:
        model = Reaction
        fields = ('id', 'user', 'reaction_type', 'timestamp')

class NewsCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    # Для вложенных ответов (рекурсивно)
    replies = serializers.SerializerMethodField(read_only=True)
    likes_count = serializers.IntegerField(read_only=True)
    # Поле для проверки, лайкнул ли текущий пользователь
    is_liked_by_current_user = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = NewsComment
        fields = (
            'id', 'article', 'author', 'content', 'parent', 'created_at',
            'replies', 'likes_count', 'is_liked_by_current_user'
        )
        # Добавляем 'article' сюда, т.к. он устанавливается в save()
        read_only_fields = ('id', 'author', 'created_at', 'replies', 'likes_count', 'is_liked_by_current_user', 'article')
        extra_kwargs = {
            # Убираем 'article' отсюда, если добавили в read_only_fields
            # 'article': {'write_only': True},
            'parent': {'write_only': True, 'required': False, 'allow_null': True},
        }

    def get_replies(self, obj):
        """Рекурсивно получаем ответы на комментарий."""
        # Ограничиваем глубину для производительности
        if obj.replies.exists(): # Загружаем только если есть ответы
            # Можно ограничить глубину здесь, если потребуется
            serializer = NewsCommentSerializer(obj.replies.all(), many=True, context=self.context)
            return serializer.data
        return []

    def get_is_liked_by_current_user(self, obj):
        """Проверяет, лайкнул ли текущий пользователь этот комментарий."""
        user = self.context.get('request').user
        if user and user.is_authenticated:
             ctype = ContentType.objects.get_for_model(obj)
             return Reaction.objects.filter(
                 content_type=ctype,
                 object_id=obj.id,
                 user=user,
                 reaction_type=Reaction.ReactionType.LIKE
             ).exists()
        return False

class NewsArticleSerializer(serializers.ModelSerializer):
    category = NewsCategorySerializer(read_only=True)
    author = UserSerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=NewsCategory.objects.all(), source='category', write_only=True, required=False, allow_null=True
    )
    # Получаем комментарии первого уровня
    # comments = NewsCommentSerializer(many=True, read_only=True, source='get_top_level_comments') # Неэффективно для списка
    comment_count = serializers.IntegerField(read_only=True)
    likes_count = serializers.IntegerField(read_only=True)
    # Поле для проверки, лайкнул ли текущий пользователь
    is_liked_by_current_user = serializers.SerializerMethodField(read_only=True)


    class Meta:
        model = NewsArticle
        fields = (
            'id', 'title', 'content', 'category', 'author', 'created_at', 'updated_at',
            'is_published', 'category_id', 'comment_count', 'likes_count', 'is_liked_by_current_user'
        )
        read_only_fields = ('author', 'created_at', 'updated_at', 'comment_count', 'likes_count', 'is_liked_by_current_user')

    def get_is_liked_by_current_user(self, obj):
        """Проверяет, лайкнул ли текущий пользователь эту статью."""
        user = self.context.get('request').user
        if user and user.is_authenticated:
             ctype = ContentType.objects.get_for_model(obj)
             return Reaction.objects.filter(
                 content_type=ctype,
                 object_id=obj.id,
                 user=user,
                 reaction_type=Reaction.ReactionType.LIKE
             ).exists()
        return False

    def create(self, validated_data):
        # Устанавливаем автора из контекста запроса
        validated_data['author'] = self.context['request'].user
        instance = super().create(validated_data)
        # TODO: Отправить уведомление о создании новости (если is_published)
        # if instance.is_published:
        #    send_news_creation_notification(instance)
        return instance

    def update(self, instance, validated_data):
        was_published = instance.is_published
        instance = super().update(instance, validated_data)
        # TODO: Отправить уведомление, если новость стала опубликованной
        # if not was_published and instance.is_published:
        #    send_news_creation_notification(instance)
        # TODO: Отправить уведомление об изменении (опционально)
        return instance