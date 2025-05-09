from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from .models import NewsCategory, NewsArticle, NewsComment, Reaction
from .serializers import (
    NewsCategorySerializer, NewsArticleSerializer, NewsCommentSerializer
)
from users.permissions import IsAdmin, IsTeacherOrAdmin, IsOwnerOrAdmin

class NewsCategoryViewSet(viewsets.ModelViewSet):
    """CRUD для категорий новостей (только Админы)."""
    queryset = NewsCategory.objects.all()
    serializer_class = NewsCategorySerializer
    # --- ИСПРАВЛЕНИЕ: Используем IsAdminUser из DRF или ваш кастомный IsAdmin ---
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsAdmin]
    permission_classes = [permissions.IsAdminUser] # Стандартный DRF permission для админов
    lookup_field = 'slug'

class NewsArticleViewSet(viewsets.ModelViewSet):
    """CRUD для новостей."""
    # Убираем фильтр is_published=True из базового queryset,
    # так как get_queryset будет его настраивать динамически
    queryset = NewsArticle.objects.select_related('category', 'author').prefetch_related('reactions')
    serializer_class = NewsArticleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # --- ИСПРАВЛЕНИЕ: Добавляем is_published для фильтрации ---
    filterset_fields = ['category__slug', 'author', 'is_published'] # Фильтр по слагу категории, ID автора, статусу
    search_fields = ['title', 'content', 'author__last_name']
    # --- ИСПРАВЛЕНИЕ: Добавляем is_published для сортировки ---
    ordering_fields = ['created_at', 'updated_at', 'title', 'is_published']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        # Получаем базовый queryset (уже с prefetch/select_related)
        queryset = super().get_queryset()

        # Логика видимости для разных ролей
        if user.is_authenticated:
            if user.is_staff or user.is_superuser or user.is_admin: # Админ видит всё
                return queryset.distinct() # distinct нужен из-за Q() | Q() ниже
            elif user.is_teacher:
                # Учитель видит опубликованные + свои неопубликованные
                return queryset.filter(Q(is_published=True) | Q(author=user)).distinct()
            else:
                # Обычный аутентифицированный пользователь видит только опубликованные
                return queryset.filter(is_published=True)
        else:
            # Анонимный пользователь видит только опубликованные
            return queryset.filter(is_published=True)

    def get_permissions(self):
        """Права: создавать/редактировать могут Учителя и Админы."""
        if self.action in ['create']:
             # --- ИСПРАВЛЕНИЕ: Используем стандартный IsAuthenticated ---
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        if self.action in ['update', 'partial_update', 'destroy']:
             # --- ИСПРАВЛЕНИЕ: Используем стандартный IsAuthenticated ---
            # IsOwnerOrAdmin проверит автора (нужно убедиться, что он корректно работает или использовать стандартный IsAdminUser в OR)
            # Пример с OR: return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | permissions.IsAdminUser)]
            return [permissions.IsAuthenticated(), IsOwnerOrAdmin()] # Оставляем ваш кастомный
        # Для list, retrieve - IsAuthenticatedOrReadOnly (установлен по умолчанию)
        return super().get_permissions()

    # --- Реакции (Лайки) (Без изменений) ---
    @action(detail=True, methods=['post', 'delete'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        # ... код лайка ...
        pass # Заглушка, чтобы не повторять код

    # --- Комментарии ---
    # --- ИСПРАВЛЕНИЕ: list_comments должен возвращать ВСЕ комментарии для фронтенда ---
    @action(detail=True, methods=['get'], url_path='comments')
    def list_comments(self, request, pk=None):
        """Получение ВСЕХ комментариев для статьи (фронтенд построит дерево)."""
        article = self.get_object()
        # Получаем ВСЕ комментарии статьи, сортируем по дате создания
        comments = article.comments.select_related('author', 'author__profile').order_by('created_at')
        # Применяем пагинацию, если настроена глобально или локально
        page = self.paginate_queryset(comments)
        if page is not None:
            serializer = NewsCommentSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = NewsCommentSerializer(comments, many=True, context={'request': request})
        return Response(serializer.data)

    # --- ИСПРАВЛЕНИЕ: add_comment - передаем article в контекст ---
    @action(detail=True, methods=['post'], url_path='comments/add', permission_classes=[permissions.IsAuthenticated]) # Явно указываем права
    def add_comment(self, request, pk=None):
        """Добавление комментария к статье."""
        article = self.get_object()
        # Передаем 'article' в контекст для возможной валидации parent в сериализаторе
        serializer = NewsCommentSerializer(data=request.data, context={'request': request, 'article': article})
        if serializer.is_valid():
            parent_comment = serializer.validated_data.get('parent') # Получаем объект parent, если был передан и валиден
            # Сохраняем, передавая автора и статью явно
            serializer.save(author=request.user, article=article, parent=parent_comment)
            # TODO: Отправить уведомление автору статьи (и автору parent коммента)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NewsCommentViewSet(viewsets.ModelViewSet):
    """
    CRUD для комментариев (редактирование/удаление/лайки).
    НЕ используется для получения списка комментариев статьи (см. NewsArticleViewSet.list_comments).
    Используется для GET /api/news/comments/{id}/, PUT/PATCH/DELETE /api/news/comments/{id}/, POST/DELETE /api/news/comments/{id}/like/
    """
    queryset = NewsComment.objects.select_related('author', 'article', 'parent', 'author__profile').prefetch_related('reactions')
    serializer_class = NewsCommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly] # Читать могут все (для retrieve)

    # --- ИСПРАВЛЕНИЕ: Убираем get_queryset с фильтрацией по article_pk ---
    # Этот ViewSet не должен отвечать за списки комментариев статьи
    # def get_queryset(self):
    #     article_pk = self.request.query_params.get('article_pk')
    #     if article_pk:
    #         return self.queryset.filter(article_id=article_pk)
    #     # Запрещаем доступ к списку без фильтра
    #     return NewsComment.objects.none()

    # --- ИСПРАВЛЕНИЕ: Добавляем фильтрацию (если все же нужен /api/news/comments/?article=...) ---
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['article', 'author'] # Позволяем фильтровать по ID статьи и ID автора
    ordering_fields = ['created_at']
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---


    def get_permissions(self):
        """Определяем пермишены в зависимости от действия."""
        permission_classes = [] # Начинаем с пустого списка

        if self.action in ['update', 'partial_update', 'destroy']:
            # --- УРОВЕНЬ ACTION: ---
            # Кто в принципе может ПЫТАТЬСЯ обновить/удалить комментарий?
            # Любой аутентифицированный пользователь. Реальная проверка будет на уровне объекта.
            permission_classes = [permissions.IsAuthenticated]
            # --- УРОВЕНЬ ОБЪЕКТА (будет проверяться позже через has_object_permission): ---
            # Добавляем классы, которые будут проверять ПРАВА НА ОБЪЕКТ.
            # DRF вызовет has_object_permission для каждого из них.
            # Если ХОТЯ БЫ ОДИН вернет True, доступ будет разрешен.
            permission_classes.extend([
                IsOwnerOrAdmin,
                IsTeacherOrAdmin # Если учителя тоже могут удалять/редактировать ЛЮБЫЕ комменты
                # Если учителя могут только свои, то IsTeacherOrAdmin здесь не нужен,
                # достаточно IsOwnerOrAdmin (который проверяет и владельца, и админа)
            ])

        elif self.action == 'like':
            # Лайкать может любой аутентифицированный
            permission_classes = [permissions.IsAuthenticated]

        elif self.action == 'create':
             # Создавать (через /api/news/comments/) может любой аутентифицированный?
             # Или используем action add_comment в NewsArticleViewSet?
             # Если этот метод не используется для создания, можно запретить:
             # permission_classes = [permissions.IsAdminUser] # Запрещаем всем, кроме админа
             # Или оставить IsAuthenticated, если создание здесь разрешено
             permission_classes = [permissions.IsAuthenticated]

        else: # Для retrieve, list (если разрешен)
            permission_classes = list(self.permission_classes) # Используем базовые

        # Возвращаем список ЭКЗЕМПЛЯРОВ
        return [permission() for permission in permission_classes]
   

    def perform_update(self, serializer):
         instance = serializer.instance
         # --- Упрощаем проверку прав, полагаясь на get_permissions ---
         # (Дополнительная проверка, если get_permissions недостаточно)
         # if not self.request.user.is_staff and instance.author != self.request.user:
         #     self.permission_denied(self.request, message='Вы можете редактировать только свои комментарии.')
         serializer.save()

    def perform_destroy(self, instance):
         # --- Упрощаем проверку прав, полагаясь на get_permissions ---
         # if not self.request.user.is_staff and instance.author != self.request.user:
         #     self.permission_denied(self.request, message='Вы можете удалять только свои комментарии.')
         instance.delete()

    # --- Лайк комментария ---
    @action(detail=True, methods=['post', 'delete'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        comment = self.get_object()
        user = request.user
        content_type = ContentType.objects.get_for_model(comment)
        reaction_type = Reaction.ReactionType.LIKE

        if request.method == 'POST':
            reaction, created = Reaction.objects.get_or_create(
                user=user, content_type=content_type, object_id=comment.id, reaction_type=reaction_type
            )
            if created:
                 # TODO: Уведомление автору коммента
                return Response({'status': 'liked'}, status=status.HTTP_201_CREATED)
            else:
                return Response({'status': 'already liked'}, status=status.HTTP_200_OK)

        elif request.method == 'DELETE':
            deleted_count, _ = Reaction.objects.filter(
                user=user, content_type=content_type, object_id=comment.id, reaction_type=reaction_type
            ).delete()
            if deleted_count > 0:
                return Response({'status': 'unliked'}, status=status.HTTP_204_NO_CONTENT)
            else:
                return Response({'status': 'not liked'}, status=status.HTTP_404_NOT_FOUND)