# forum/views.py
from rest_framework import viewsets, permissions, status, generics, filters # filters добавлен
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, OuterRef, Subquery # Используем для подсчета лайков, если нужно
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import ForumCategory, ForumTopic, ForumPost, ForumReaction
from .serializers import (
    ForumCategorySerializer, ForumTopicSerializer, ForumPostSerializer,
    ForumTopicListSerializer # Для списков
)
# Используем правильные пермишены из users.permissions
from users.permissions import IsTeacherOrAdmin, IsOwnerOrAdmin

class ForumCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Просмотр категорий форума."""
    queryset = ForumCategory.objects.all().order_by('display_order', 'name') # Добавил сортировку
    serializer_class = ForumCategorySerializer
    permission_classes = [permissions.AllowAny] # Категории видны всем
    lookup_field = 'slug' # Используем слаг для поиска категории

    # Убираем @action list_topics, так как список тем будет в ForumTopicViewSet
    # @action(detail=True, methods=['get'], url_path='topics')
    # def list_topics(self, request, slug=None): ...


class ForumTopicViewSet(viewsets.ModelViewSet):
    """CRUD для тем форума."""
    # Убираем prefetch_related('posts'), это может быть слишком много данных для списка
    queryset = ForumTopic.objects.select_related('category', 'author').prefetch_related('tags').all()
    # Serializer будет подгружать last_post через SerializerMethodField или аннотацию
    serializer_class = ForumTopicSerializer # По умолчанию для деталей/создания/обновления
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category__slug', 'author', 'tags__name'] # Фильтр по тегам
    # Убираем posts__content из поиска по умолчанию, это может быть медленно
    search_fields = ['title', 'author__last_name', 'author__first_name', 'author__email']
    ordering_fields = ['created_at', 'last_post_at', 'title', 'post_count'] # Добавил post_count
    ordering = ['-is_pinned', '-last_post_at']

    def get_serializer_class(self):
         if self.action == 'list':
             return ForumTopicListSerializer # Используем упрощенный для списка
         return ForumTopicSerializer

    def get_queryset(self):
        # Получаем базовый queryset ИЗ РОДИТЕЛЬСКОГО КЛАССА (или определяем здесь)
        queryset = super().get_queryset().select_related('category', 'author') \
                                       .prefetch_related('tags') # tags - ManyToMany, нужен prefetch

        # --- ИСПРАВЛЕНИЕ: Убираем select_related('last_post__author') ---
        # Вместо этого используем аннотацию (рекомендуется для list И retrieve)

        last_post_subquery = ForumPost.objects.filter(
            topic=OuterRef('pk')
        ).order_by('-created_at')

        queryset = queryset.annotate(
            # Аннотируем ID, дату и ID автора последнего поста
            # last_post_id_annotated=Subquery(last_post_subquery.values('pk')[:1]), # Если нужен ID самого поста
            last_post_at_annotated=Subquery(last_post_subquery.values('created_at')[:1]),
            last_post_author_id_annotated=Subquery(last_post_subquery.values('author_id')[:1]),
            # Аннотируем количество постов
            post_count_annotated=Count('posts')
        )

        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        # Применяем фильтрацию, если она нужна для этого ViewSet
        # category_slug = self.request.query_params.get('category__slug')
        # if category_slug:
        #      queryset = queryset.filter(category__slug=category_slug)
        # ... другие фильтры ...

        # Сортировка должна использовать аннотированное поле
        # ordering = self.request.query_params.get('ordering', '-is_pinned,-last_post_at_annotated') # Пример
        # return queryset.order_by(ordering)
        # Используем стандартную сортировку DRF, если ordering_fields настроены
        return queryset


    def get_permissions(self):
        """Права доступа."""
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        # Для pin/close нужен IsTeacherOrAdmin (или ваш модераторский пермишен)
        elif self.action in ['update', 'partial_update', 'destroy', 'pin', 'close']:
            # Используем IsOwnerOrAdmin (проверит автора) | IsTeacherOrAdmin (проверит роль)
            return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        # Для list, retrieve - IsAuthenticatedOrReadOnly (установлен по умолчанию)
        return super().get_permissions()

    def perform_create(self, serializer):
        # perform_create в ModelViewSet вызывается ПОСЛЕ is_valid()
        # Логика создания темы и первого поста теперь полностью в сериализаторе
        # Мы только передаем пользователя
        serializer.save(author=self.request.user)


    @action(detail=True, methods=['post'], permission_classes=[IsTeacherOrAdmin]) # Только модераторы
    def pin(self, request, pk=None):
        """Закрепить/открепить тему."""
        topic = self.get_object()
        topic.is_pinned = not topic.is_pinned
        topic.save(update_fields=['is_pinned'])
        serializer = self.get_serializer(topic)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsTeacherOrAdmin]) # Только модераторы
    def close(self, request, pk=None):
        """Закрыть/открыть тему."""
        topic = self.get_object()
        topic.is_closed = not topic.is_closed
        topic.save(update_fields=['is_closed'])
        serializer = self.get_serializer(topic)
        return Response(serializer.data)

    # Убираем list_posts и add_post отсюда, они будут в ForumPostViewSet
    # или в API будут разные URL для них

# --- ViewSet для Постов ---
# Лучше сделать отдельный ViewSet для постов для ясности
class ForumPostViewSet(viewsets.ModelViewSet):
    """CRUD для постов форума (просмотр, создание, редактирование, удаление, лайки)."""
    serializer_class = ForumPostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    # Пагинация для постов
    # pagination_class = YourPostPaginationClass

    def get_queryset(self):
        # Обязательно фильтруем по теме!
        # Или если URL вложенный /api/forum/topics/{topic_pk}/posts/
        # topic_id = self.kwargs.get('topic_pk')
        topic_id = self.request.query_params.get('topic') # <--- Получаем параметр
        if topic_id:
            try:
                # Фильтруем по ID темы
                queryset = queryset.filter(topic_id=int(topic_id))
            except (ValueError, TypeError):
                # Возвращаем пустой queryset, если topic_id невалидный
                return ForumPost.objects.none()
            return queryset.order_by('created_at')
        else:
            # Не возвращаем ничего, если ID темы не указан
            return ForumPost.objects.none()
    def get_permissions(self):
        """Редактировать/удалять может автор или модератор."""
        if self.action in ['update', 'partial_update', 'destroy']:
             # Используем IsOwnerOrAdmin (проверит автора) | IsTeacherOrAdmin (проверит роль)
            return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        elif self.action == 'create': # Создавать могут аутентифицированные
             return [permissions.IsAuthenticated()]
        # Для list, retrieve - IsAuthenticatedOrReadOnly
        return super().get_permissions()

    def perform_create(self, serializer):
         # Получаем тему из validated_data (сериализатор должен ее валидировать)
         topic = serializer.validated_data.get('topic')
         # Проверяем, не закрыта ли тема
         if topic and topic.is_closed:
              raise PermissionDenied('Тема закрыта для новых сообщений.') # Лучше PermissionDenied

         # Проверяем родительский пост, если указан
         parent = serializer.validated_data.get('parent')
         if parent and parent.topic != topic:
              raise ValidationError({'parent': 'Ответ должен быть в той же теме.'})

         instance = serializer.save(author=self.request.user)
         # Обновление last_post_at темы происходит в модели Post при save()

         # TODO: Уведомление подписчикам темы

    # --- Лайк поста ---
    # Метод like остается здесь
    @action(detail=True, methods=['post', 'delete'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        # --- ИСПРАВЛЕНИЕ: Получаем объект явно по pk ---
        # Вместо self.get_object(), который может использовать get_queryset с фильтрами
        post = get_object_or_404(ForumPost, pk=pk)
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
        user = request.user
        content_type = ContentType.objects.get_for_model(post)
        reaction_type = ForumReaction.ReactionType.LIKE

        if request.method == 'POST':
            # ... (логика update_or_create) ...
            serializer = self.get_serializer(post) # Сериализуем найденный пост
            return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)

        elif request.method == 'DELETE':
            deleted_count, _ = ForumReaction.objects.filter(...).delete()
            if deleted_count > 0:
                serializer = self.get_serializer(post.refresh_from_db())
                return Response(serializer.data, status=status.HTTP_200_OK)
            else:
                serializer = self.get_serializer(post)
                return Response(serializer.data, status=status.HTTP_200_OK) # Или 404
