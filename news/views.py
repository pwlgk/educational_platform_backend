from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.contenttypes.models import ContentType
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
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsAdmin] # Читать могут все, менять - админы
    lookup_field = 'slug' # Используем slug для поиска категорий

class NewsArticleViewSet(viewsets.ModelViewSet):
    """CRUD для новостей."""
    queryset = NewsArticle.objects.filter(is_published=True).select_related('category', 'author').prefetch_related('reactions') # Только опубликованные
    serializer_class = NewsArticleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly] # Читать могут все
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category__slug', 'author'] # Фильтр по слагу категории, ID автора
    search_fields = ['title', 'content', 'author__last_name']
    ordering_fields = ['created_at', 'updated_at', 'title']
    ordering = ['-created_at'] # Сортировка по умолчанию

    def get_queryset(self):
        # Админы и авторы видят и неопубликованные свои статьи
        user = self.request.user
        if user.is_authenticated and (user.is_admin or user.is_teacher):
            # Админ видит все, Учитель - опубликованные + свои неопубликованные
            return NewsArticle.objects.select_related('category', 'author').prefetch_related('reactions').filter(
                Q(is_published=True) | Q(author=user) if user.is_teacher else Q()
            ).distinct()
        return super().get_queryset() # Только опубликованные для остальных

    def get_permissions(self):
        """Права: создавать/редактировать могут Учителя и Админы."""
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        if self.action in ['update', 'partial_update', 'destroy']:
            # Редактировать/удалять может автор или админ
            return [permissions.IsAuthenticated(), IsOwnerOrAdmin()] # IsOwnerOrAdmin проверит автора
        return super().get_permissions()

    # --- Реакции (Лайки) ---
    @action(detail=True, methods=['post', 'delete'], permission_classes=[permissions.IsAuthenticated])
    def like(self, request, pk=None):
        article = self.get_object()
        user = request.user
        content_type = ContentType.objects.get_for_model(article)
        reaction_type = Reaction.ReactionType.LIKE

        if request.method == 'POST':
            # Создать лайк, если его нет
            reaction, created = Reaction.objects.get_or_create(
                user=user, content_type=content_type, object_id=article.id, reaction_type=reaction_type
            )
            if created:
                # TODO: Опционально отправить уведомление автору статьи
                return Response({'status': 'liked'}, status=status.HTTP_201_CREATED)
            else:
                return Response({'status': 'already liked'}, status=status.HTTP_200_OK)

        elif request.method == 'DELETE':
            # Удалить лайк
            deleted_count, _ = Reaction.objects.filter(
                user=user, content_type=content_type, object_id=article.id, reaction_type=reaction_type
            ).delete()
            if deleted_count > 0:
                return Response({'status': 'unliked'}, status=status.HTTP_204_NO_CONTENT)
            else:
                return Response({'status': 'not liked'}, status=status.HTTP_404_NOT_FOUND)

    # --- Комментарии ---
    @action(detail=True, methods=['get'], url_path='comments')
    def list_comments(self, request, pk=None):
        """Получение комментариев первого уровня для статьи."""
        article = self.get_object()
        # Фильтруем комментарии первого уровня (без parent)
        comments = article.comments.filter(parent__isnull=True).select_related('author').prefetch_related('replies', 'reactions')
        # Пагинация (если нужна)
        page = self.paginate_queryset(comments)
        if page is not None:
            serializer = NewsCommentSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = NewsCommentSerializer(comments, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='comments/add')
    def add_comment(self, request, pk=None):
        """Добавление комментария к статье."""
        article = self.get_object()
        serializer = NewsCommentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Проверяем parent, если он есть
            parent_id = serializer.validated_data.get('parent')
            parent_comment = None
            if parent_id:
                 # Убедимся, что родительский коммент принадлежит этой же статье
                 parent_comment = get_object_or_404(NewsComment, pk=parent_id.id, article=article)

            serializer.save(author=request.user, article=article, parent=parent_comment)
            # TODO: Отправить уведомление автору статьи (и автору parent коммента)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NewsCommentViewSet(viewsets.ModelViewSet):
    """CRUD для комментариев (редактирование/удаление)."""
    queryset = NewsComment.objects.select_related('author', 'article', 'parent').prefetch_related('reactions')
    serializer_class = NewsCommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly] # Читать могут все

    def get_queryset(self):
        # Фильтруем по статье, если ID передан в URL (нестандартно для ViewSet)
        # Лучше получать комменты через @action в NewsArticleViewSet
        article_pk = self.request.query_params.get('article_pk')
        if article_pk:
            return self.queryset.filter(article_id=article_pk)
        # Или можно запретить доступ к этому ViewSet напрямую без фильтра
        # return NewsComment.objects.none()
        return super().get_queryset() # По умолчанию все комменты (не рекомендуется без фильтра)


    def get_permissions(self):
        """Автор или админ/учитель могут редактировать/удалять."""
        if self.action in ['update', 'partial_update', 'destroy']:
            # IsOwnerOrAdmin проверит автора, IsTeacherOrAdmin даст права модераторам
            return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        return super().get_permissions()

    def perform_create(self, serializer):
         # Создание лучше делать через @action в NewsArticleViewSet
         # Этот метод здесь больше для полноты ModelViewSet
         # Нужно будет передавать article_id в данных
         article_id = self.request.data.get('article')
         article = get_object_or_404(NewsArticle, pk=article_id)
         serializer.save(author=self.request.user, article=article)
         # TODO: Отправить уведомление

    def perform_update(self, serializer):
         # Дополнительная проверка прав (если IsOwnerOrAdmin недостаточно)
         instance = serializer.instance
         if not self.request.user.is_admin and not self.request.user.is_teacher and instance.author != self.request.user:
              self.permission_denied(self.request, message='Вы можете редактировать только свои комментарии.')
         serializer.save()

    def perform_destroy(self, instance):
         # Дополнительная проверка прав (если IsOwnerOrAdmin недостаточно)
         if not self.request.user.is_admin and not self.request.user.is_teacher and instance.author != self.request.user:
              self.permission_denied(self.request, message='Вы можете удалять только свои комментарии.')
         # TODO: Отправить уведомление (опционально)
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