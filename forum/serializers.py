# forum/serializers.py
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.db.models import Count # Импортируем Count
from taggit.serializers import (TagListSerializerField, TaggitSerializer)
from .models import ForumCategory, ForumTopic, ForumPost, ForumReaction
from users.serializers import UserSerializer # Используем UserSerializer
from django.utils.translation import gettext_lazy as _


User = get_user_model()

class ForumCategorySerializer(serializers.ModelSerializer):
    # Добавим счетчики для отображения
    topic_count = serializers.IntegerField(read_only=True) # Предполагает аннотацию в ViewSet
    post_count = serializers.IntegerField(read_only=True)  # Предполагает аннотацию в ViewSet

    class Meta:
        model = ForumCategory
        fields = ('id', 'name', 'slug', 'description', 'display_order', 'topic_count', 'post_count')
        read_only_fields = ('slug', 'topic_count', 'post_count')


# Сериализатор автора для форума
class ForumAuthorSerializer(UserSerializer):
     # Наследуем UserSerializer, но ограничиваем поля
     class Meta(UserSerializer.Meta): # Наследуем Meta от UserSerializer
         model = User # Указываем модель явно
         fields = ('id', 'first_name', 'last_name', 'profile') # Profile должен быть сериализатором или ссылкой
         # profile = ProfileSerializer(read_only=True) # Пример, если ProfileSerializer есть
         # fields = ('id', 'get_full_name', 'profile') # Или так


# Базовый сериализатор для постов (для рекурсии)
class BaseForumPostSerializer(serializers.ModelSerializer):
     author = ForumAuthorSerializer(read_only=True)
     # Убираем рекурсивные replies из базового для предотвращения бесконечной вложенности

     class Meta:
         model = ForumPost
         fields = ('id', 'author', 'content', 'created_at', 'updated_at')
         read_only_fields = ('id', 'author', 'created_at', 'updated_at')



# Основной сериализатор для постов
class ForumPostSerializer(BaseForumPostSerializer):
    # Переопределяем author для большей информации, если нужно
    # author = ForumAuthorSerializer(read_only=True)
    topic = serializers.PrimaryKeyRelatedField(
        queryset=ForumTopic.objects.all(),
        write_only=True # Только для записи
    )
    # Опционально: поле для чтения ID (если нужно в ответе)
    # chat_id = serializers.IntegerField(source='chat.id', read_only=True) # Аналогично для topic
    topic_id_read = serializers.IntegerField(source='topic.id', read_only=True)


    parent_id = serializers.PrimaryKeyRelatedField(queryset=ForumPost.objects.all(), source='parent', write_only=True, required=False, allow_null=True)
    replies = serializers.SerializerMethodField(read_only=True)
    likes_count = serializers.SerializerMethodField(read_only=True)
    is_liked_by_current_user = serializers.SerializerMethodField(read_only=True)

    class Meta(BaseForumPostSerializer.Meta):
         # --- ИСПРАВЛЕНИЕ: Используем 'topic' для записи, 'topic_id_read' для чтения ---
        fields = BaseForumPostSerializer.Meta.fields + (
            'topic', # <--- Имя поля для записи (write_only)
            'topic_id_read', # <--- Имя поля для чтения ID (read_only)
            'parent_id',
            'replies', 'likes_count', 'is_liked_by_current_user'
        )
        # read_only_fields остаются из базового + новые read_only
        read_only_fields = BaseForumPostSerializer.Meta.read_only_fields + ('replies', 'likes_count', 'is_liked_by_current_user')
        # Убираем topic/parent из extra_kwargs, т.к. объявили их явно
        extra_kwargs = {
            'content': {'required': True}, # Контент поста обязателен
        }

    def get_replies(self, obj: ForumPost):
        # Загружаем только первый уровень ответов для производительности
        # Можно добавить пагинацию или настройку глубины
        replies = obj.replies.select_related('author__profile').prefetch_related('reactions').order_by('created_at')[:10] # Пример: первые 10
        # Используем этот же сериализатор для ответов
        serializer = ForumPostSerializer(replies, many=True, context=self.context)
        return serializer.data

    def get_likes_count(self, obj: ForumPost) -> int:
         # Эффективнее аннотировать в queryset во ViewSet, но можно и здесь
         # Убедитесь, что у модели ForumPost есть related_name='reactions' от ForumReaction
         return obj.reactions.filter(reaction_type=ForumReaction.ReactionType.LIKE).count()

    def get_is_liked_by_current_user(self, obj: ForumPost) -> bool:
        user = self.context.get('request').user
        if user and user.is_authenticated:
             # Используем prefetch_related('reactions') из ViewSet для оптимизации
             # Проверяем наличие лайка в подгруженных реакциях
             return any(r.user_id == user.id and r.reaction_type == ForumReaction.ReactionType.LIKE for r in obj.reactions.all())
             # Запасной вариант, если prefetch не сработал:
             # ctype = ContentType.objects.get_for_model(obj)
             # return ForumReaction.objects.filter(
             #     content_type=ctype, object_id=obj.id, user=user, reaction_type=ForumReaction.ReactionType.LIKE
             # ).exists()
        return False

    def validate_parent_id(self, value):
        # Дополнительная валидация родительского поста
        if value:
             topic = self.context.get('topic') # Получаем тему из контекста (нужно передать во view)
             if not topic:
                  # Если создаем через PostViewSet, получаем topic из validated_data
                  topic_id = self.initial_data.get('topic')
                  if topic_id:
                       topic = get_object_or_404(ForumTopic, pk=topic_id)
                  else: # Нельзя создать ответ без указания темы
                       raise serializers.ValidationError("Тема не определена для проверки родительского поста.")

             if value.topic != topic:
                 raise serializers.ValidationError("Ответ должен быть в той же теме, что и родительский пост.")
             # Можно добавить проверку глубины вложенности
             # current_depth = 0
             # temp_parent = value
             # while temp_parent:
             #     current_depth += 1
             #     temp_parent = temp_parent.parent
             # if current_depth >= MAX_REPLY_DEPTH:
             #      raise serializers.ValidationError("Достигнута максимальная глубина ответов.")
        return value

# Сериализатор для создания темы (обрабатывает первый пост)
class ForumTopicCreateSerializer(TaggitSerializer, serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ForumCategory.objects.all(), source='category', write_only=True, label=_("Категория")
    )
    tags = TagListSerializerField(required=False)
    first_post_content = serializers.CharField(write_only=True, required=True, label=_("Текст первого сообщения"), style={'base_template': 'textarea.html'}) # Используем textarea

    class Meta:
        model = ForumTopic
        fields = (
            'category_id', 'title', 'tags', 'first_post_content',
            'is_pinned', 'is_closed' # Поля, которые могут установить модераторы при создании
        )
        extra_kwargs = {
             # По умолчанию при создании тема не закреплена и открыта
            'is_pinned': {'required': False, 'default': False},
            'is_closed': {'required': False, 'default': False},
        }

    def validate(self, data):
         # Дополнительная валидация, если нужна
         user = self.context['request'].user
         # Проверка прав на закрепление/закрытие (если не админ/учитель - сбрасываем)
         if not (user.is_staff or user.is_superuser or user.is_teacher):
              data['is_pinned'] = False
              data['is_closed'] = False
         return data

    def create(self, validated_data):
        first_post_content = validated_data.pop('first_post_content')
        tags = validated_data.pop('tags', [])
        validated_data['author'] = self.context['request'].user

        # Создаем тему
        topic = ForumTopic.objects.create(**validated_data)

        # Устанавливаем теги
        if tags:
            topic.tags.set(*tags)

        # Создаем первый пост
        ForumPost.objects.create(
            topic=topic,
            author=topic.author,
            content=first_post_content
            # first_post для темы обновится автоматически через сигнал или метод save модели Post
        )
        return topic


# Сериализатор для чтения/обновления темы (основной)
class ForumTopicSerializer(TaggitSerializer, serializers.ModelSerializer):
    category = ForumCategorySerializer(read_only=True)
    author = ForumAuthorSerializer(read_only=True)
    tags = TagListSerializerField(required=False)
    # Используем SerializerMethodField для гибкости и оптимизации
    last_post = serializers.SerializerMethodField(read_only=True)
    post_count = serializers.SerializerMethodField(read_only=True)
     # Поле для ID категории при обновлении (если нужно разрешить смену категории)
    # category_id = serializers.PrimaryKeyRelatedField(queryset=ForumCategory.objects.all(), source='category', write_only=True, required=False)

    class Meta:
        model = ForumTopic
        fields = (
            'id', 'category', 'title', 'author', 'created_at', 'last_post_at',
            'is_pinned', 'is_closed', 'tags', 'post_count', 'last_post'
            # 'category_id' # Если разрешена смена категории
        )
        # Поля, которые обычно нельзя менять напрямую при PATCH/PUT темы
        read_only_fields = ('id', 'author', 'created_at', 'last_post_at', 'post_count', 'last_post', 'category')

    def get_last_post(self, obj: ForumTopic):
        """Получаем данные о последнем посте (оптимизировано)."""
        # Предполагаем, что last_post (ForeignKey или OneToOne) уже подгружен через select_related во ViewSet
        last = obj.last_post
        # Альтернатива: last = obj.posts.order_by('-created_at').first() # Менее эффективно
        if last:
             # Используем базовый сериализатор поста или только нужные поля
             return {
                 'id': last.id,
                 # Используем ForumAuthorSerializer для автора
                 'author': ForumAuthorSerializer(last.author).data if last.author else None,
                 'created_at': last.created_at
             }
             # Или: return BaseForumPostSerializer(last, context=self.context).data
        return None

    def get_post_count(self, obj: ForumTopic) -> int:
         # Используем аннотацию из ViewSet или свойство модели
         return getattr(obj, 'post_count_annotated', obj.post_count) # obj.post_count - это @property


# Упрощенный сериализатор для списков тем
class ForumTopicListSerializer(serializers.ModelSerializer):
     """Упрощенный сериализатор для списков тем."""
     category_name = serializers.CharField(source='category.name', read_only=True)
     author_name = serializers.SerializerMethodField(read_only=True)
     # Отображаем теги как список строк
     tags = TagListSerializerField(read_only=True)
     last_post_author_name = serializers.SerializerMethodField(read_only=True)
     post_count = serializers.SerializerMethodField(read_only=True)

     class Meta:
         model = ForumTopic
         fields = (
             'id', 'category_name', 'title', 'author_name', 'created_at', 'last_post_at',
             'is_pinned', 'is_closed', 'tags', 'post_count', 'last_post_author_name' # Упрощенная информация о последнем посте
         )
         read_only_fields = fields # Все поля только для чтения в этом сериализаторе

     def get_author_name(self, obj: ForumTopic) -> str:
          if obj.author:
               return obj.author.get_full_name() or obj.author.email
          return "Unknown"

     def get_last_post_author_name(self, obj: ForumTopic) -> str | None:
          # Используем аннотацию или select_related из ViewSet для эффективности
          last = obj.last_post # Предполагаем, что подгружено
          # Или: last = getattr(obj, 'last_post_annotated', None)
          if last and last.author:
               return last.author.get_full_name() or last.author.email
          # Можно добавить запрос, но это N+1 проблема:
          # last = obj.posts.order_by('-created_at').select_related('author').first()
          # if last and last.author: return last.author.get_full_name() or last.author.email
          return None

     def get_post_count(self, obj: ForumTopic) -> int:
         return getattr(obj, 'post_count_annotated', obj.post_count) # Используем аннотацию или property