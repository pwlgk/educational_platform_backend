from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from .models import ForumCategory, ForumTopic, ForumPost, ForumReaction
from .serializers import (
    ForumCategorySerializer, ForumTopicSerializer, ForumPostSerializer,
    ForumTopicListSerializer # Для списков
)
from users.permissions import IsAdmin, IsTeacherOrAdmin, IsOwnerOrAdmin

class ForumCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Просмотр категорий форума."""
    queryset = ForumCategory.objects.all() # .prefetch_related('topics') ?
    serializer_class = ForumCategorySerializer
    permission_classes = [permissions.AllowAny] # Категории видны всем
    lookup_field = 'slug'

    # Опционально: Получение тем для категории
    @action(detail=True, methods=['get'], url_path='topics')
    def list_topics(self, request, slug=None):
        category = self.get_object()
        topics = category.topics.select_related('author', 'category', 'last_post__author').prefetch_related('tags') # Оптимизация
        # Используем пагинацию ViewSet'а
        page = self.paginate_queryset(topics)
        if page is not None:
            # Используем сериализатор для списка тем
            serializer = ForumTopicListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = ForumTopicListSerializer(topics, many=True, context={'request': request})
        return Response(serializer.data)


class ForumTopicViewSet(viewsets.ModelViewSet):
    """CRUD для тем форума."""
    queryset = ForumTopic.objects.select_related('category', 'author', 'last_post__author').prefetch_related('tags', 'posts') # Оптимизация
    serializer_class = ForumTopicSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly] # Читать могут все
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category__slug', 'author', 'tags__name'] # Фильтр по тегам
    search_fields = ['title', 'author__last_name', 'posts__content'] # Искать и по содержимому постов
    ordering_fields = ['created_at', 'last_post_at', 'title']
    ordering = ['-is_pinned', '-last_post_at'] # Сортировка по умолчанию

    def get_serializer_class(self):
         # Используем разные сериализаторы для списка и деталей
         if self.action == 'list':
             return ForumTopicListSerializer
         return ForumTopicSerializer # Для retrieve, create, update

    def get_permissions(self):
        """Создавать могут все аутентифицированные. Редактировать/удалять - автор или модератор."""
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        if self.action in ['update', 'partial_update', 'destroy', 'pin', 'close']:
            # IsOwnerOrAdmin проверит автора, IsTeacherOrAdmin даст права модераторам
            return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        return super().get_permissions()

    # perform_create обрабатывается в сериализаторе
    # perform_update и perform_destroy можно добавить для проверки прав, если нужно

    @action(detail=True, methods=['post'], url_path='pin')
    def pin(self, request, pk=None):
        """Закрепить/открепить тему."""
        topic = self.get_object()
        topic.is_pinned = not topic.is_pinned
        topic.save(update_fields=['is_pinned'])
        serializer = self.get_serializer(topic) # Возвращаем обновленную тему
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='close')
    def close(self, request, pk=None):
        """Закрыть/открыть тему."""
        topic = self.get_object()
        topic.is_closed = not topic.is_closed
        topic.save(update_fields=['is_closed'])
        serializer = self.get_serializer(topic)
        return Response(serializer.data)

    # --- Посты темы ---
    @action(detail=True, methods=['get'], url_path='posts')
    def list_posts(self, request, pk=None):
        """Получение постов для темы."""
        topic = self.get_object()
        posts = topic.posts.select_related('author', 'parent').prefetch_related('reactions')
        # Пагинация
        page = self.paginate_queryset(posts)
        if page is not None:
            serializer = ForumPostSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = ForumPostSerializer(posts, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='posts/add')
    def add_post(self, request, pk=None):
        """Добавление поста в тему."""
        topic = self.get_object()
        if topic.is_closed:
            return Response({'error': 'Тема закрыта для новых сообщений.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = ForumPostSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            parent_id = serializer.validated_data.get('parent')
            parent_post = None
            if parent_id:
                 # Убедимся, что родительский пост из этой же темы
                 parent_post = get_object_or_404(ForumPost, pk=parent_id.id, topic=topic)

            instance = serializer.save(author=request.user, topic=topic, parent=parent_post)
            # TODO: Отправить уведомление подписчикам темы (если есть подписки)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ForumPostViewSet(viewsets.ModelViewSet):
    """CRUD для постов форума (редактирование, удаление, лайки)."""
    queryset = ForumPost.objects.select_related('author', 'topic', 'parent').prefetch_related('reactions')
    serializer_class = ForumPostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        # Обычно посты получают через ViewSet темы
        # Если нужен доступ по ID поста напрямую, добавляем фильтры
        topic_pk = self.request.query_params.get('topic_pk')
        if topic_pk:
             return self.queryset.filter(topic_id=topic_pk)
        # return ForumPost.objects.none() # Запретить доступ без фильтра
        return super().get_queryset() # Или показать все (не рекомендуется)

    def get_permissions(self):
        """Редактировать/удалять может автор или модератор."""
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        return super().get_permissions()

    def perform_create(self, serializer):
         # Создание лучше делать через @action в ForumTopicViewSet
         topic_id = self.request.data.get('topic')
         topic = get_object_or_404(ForumTopic, pk=topic_id)
         if topic.is_closed:
              raise serializers.ValidationError('Тема закрыта для новых сообщений.')
         serializer.save(author=self.request.user, topic=topic)
         # TODO: Уведомление

    # perform_update и perform_destroy можно добавить для доп. проверок прав

    # --- Лайк поста ---
    @action(detail=True, methods=['post', 'delete'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        user = request.user
        content_type = ContentType.objects.get_for_model(post)
        reaction_type = ForumReaction.ReactionType.LIKE

        if request.method == 'POST':
            reaction, created = ForumReaction.objects.get_or_create(
                user=user, content_type=content_type, object_id=post.id, reaction_type=reaction_type
            )
            if created:
                 # TODO: Уведомление автору поста
                return Response({'status': 'liked'}, status=status.HTTP_201_CREATED)
            else:
                return Response({'status': 'already liked'}, status=status.HTTP_200_OK)

        elif request.method == 'DELETE':
            deleted_count, _ = ForumReaction.objects.filter(
                user=user, content_type=content_type, object_id=post.id, reaction_type=reaction_type
            ).delete()
            if deleted_count > 0:
                return Response({'status': 'unliked'}, status=status.HTTP_204_NO_CONTENT)
            else:
                return Response({'status': 'not liked'}, status=status.HTTP_404_NOT_FOUND)