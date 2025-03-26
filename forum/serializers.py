from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from taggit.serializers import (TagListSerializerField, TaggitSerializer) # Для django-taggit
from .models import ForumCategory, ForumTopic, ForumPost, ForumReaction
from users.serializers import UserSerializer

class ForumCategorySerializer(serializers.ModelSerializer):
    # Опционально: можно добавить счетчик тем или последних тем
    class Meta:
        model = ForumCategory
        fields = ('id', 'name', 'slug', 'description', 'display_order')
        read_only_fields = ('slug',)

# Сериализатор для отображения автора (краткий)
class ForumAuthorSerializer(UserSerializer):
     class Meta(UserSerializer.Meta):
         fields = ('id', 'first_name', 'last_name', 'profile') # Только нужные поля

class ForumReactionSerializer(serializers.ModelSerializer):
    user = ForumAuthorSerializer(read_only=True)

    class Meta:
        model = ForumReaction
        fields = ('id', 'user', 'reaction_type', 'timestamp')


class ForumPostSerializer(serializers.ModelSerializer):
    author = ForumAuthorSerializer(read_only=True)
    # Рекурсивные ответы (аналогично комментариям к новостям)
    replies = serializers.SerializerMethodField(read_only=True)
    likes_count = serializers.IntegerField(read_only=True)
    is_liked_by_current_user = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ForumPost
        fields = (
            'id', 'topic', 'author', 'content', 'parent', 'created_at', 'updated_at',
            'replies', 'likes_count', 'is_liked_by_current_user'
        )
        read_only_fields = ('author', 'created_at', 'updated_at', 'replies', 'likes_count', 'is_liked_by_current_user')
        extra_kwargs = {
            'topic': {'write_only': True}, # ID темы при создании
            'parent': {'write_only': True, 'required': False, 'allow_null': True}, # ID родительского поста
        }

    def get_replies(self, obj):
        # Загружаем ответы, если они есть
        if obj.replies.exists():
             # Можно ограничить глубину или использовать пагинацию для ответов
             serializer = ForumPostSerializer(obj.replies.all(), many=True, context=self.context)
             return serializer.data
        return []

    def get_is_liked_by_current_user(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
             ctype = ContentType.objects.get_for_model(obj)
             return ForumReaction.objects.filter(
                 content_type=ctype, object_id=obj.id, user=user, reaction_type=ForumReaction.ReactionType.LIKE
             ).exists()
        return False


class ForumTopicSerializer(TaggitSerializer, serializers.ModelSerializer): # Наследуемся от TaggitSerializer
    category = ForumCategorySerializer(read_only=True)
    author = ForumAuthorSerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ForumCategory.objects.all(), source='category', write_only=True
    )
    # Сериализуем поле tags с помощью `django-taggit`
    tags = TagListSerializerField(required=False)
    # Информация о последнем посте (можно сделать отдельный сериализатор)
    last_post = serializers.SerializerMethodField(read_only=True)
    post_count = serializers.IntegerField(read_only=True) # Используем @property из модели
    # Первый пост (если нужно передать его содержимое при создании/отображении темы)
    first_post_content = serializers.CharField(write_only=True, required=True, label="Текст первого сообщения")

    class Meta:
        model = ForumTopic
        fields = (
            'id', 'category', 'title', 'author', 'created_at', 'last_post_at',
            'is_pinned', 'is_closed', 'tags', 'category_id', 'post_count',
            'last_post', 'first_post_content' # Добавляем поле для первого поста
        )
        read_only_fields = ('author', 'created_at', 'last_post_at', 'post_count', 'last_post')

    def get_last_post(self, obj):
        """Получаем данные о последнем посте."""
        last = obj.posts.order_by('-created_at').first()
        if last:
             # Используем сокращенный сериализатор для последнего поста
             return {
                 'id': last.id,
                 'author': ForumAuthorSerializer(last.author, context=self.context).data,
                 'created_at': last.created_at
             }
        return None

    def create(self, validated_data):
        # Извлекаем текст первого поста и теги
        first_post_content = validated_data.pop('first_post_content')
        tags = validated_data.pop('tags', [])
        validated_data['author'] = self.context['request'].user

        # Создаем тему
        topic = ForumTopic.objects.create(**validated_data)

        # Устанавливаем теги
        if tags:
            topic.tags.set(*tags) # Используем * для распаковки списка

        # Создаем первый пост
        # Не используем ForumPostSerializer, чтобы не было рекурсии
        first_post = ForumPost.objects.create(
            topic=topic,
            author=topic.author,
            content=first_post_content
        )
        # Связываем тему с первым постом (модель ForumPost сама обновит last_post_at)
        # topic.first_post = first_post # Модель Post сама это сделает при save()
        # topic.save(update_fields=['first_post'])

        # TODO: Уведомление о новой теме (опционально)

        return topic


class ForumTopicListSerializer(ForumTopicSerializer):
     """Упрощенный сериализатор для списков тем."""
     category_name = serializers.CharField(source='category.name', read_only=True)
     author_name = serializers.CharField(source='author.get_full_name', read_only=True)

     class Meta(ForumTopicSerializer.Meta):
         # Убираем или изменяем поля для краткости
         fields = (
             'id', 'category_name', 'title', 'author_name', 'created_at', 'last_post_at',
             'is_pinned', 'is_closed', 'tags', 'post_count', 'last_post'
         )
         read_only_fields = fields