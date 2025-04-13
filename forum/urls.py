# forum/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Основной роутер для приложения forum
router = DefaultRouter()

# 1. Категории Форума
# /api/forum/categories/
# /api/forum/categories/{slug}/
# /api/forum/categories/{slug}/topics/ (реализовано через @action в ForumCategoryViewSet, если оставили)
router.register(r'categories', views.ForumCategoryViewSet, basename='forum-category')

# 2. Темы Форума
# /api/forum/topics/ (list, create) - фильтрация по ?category__slug=...
# /api/forum/topics/{pk}/ (retrieve, update, partial_update, destroy)
# /api/forum/topics/{pk}/pin/ (@action)
# /api/forum/topics/{pk}/close/ (@action)
# /api/forum/topics/{pk}/posts/ (@action для получения постов, если оставили)
router.register(r'topics', views.ForumTopicViewSet, basename='forum-topic')

# 3. Посты Форума
# /api/forum/posts/ (list с фильтром ?topic=..., create)
# /api/forum/posts/{pk}/ (retrieve, update, partial_update, destroy)
# /api/forum/posts/{pk}/like/ (@action)
router.register(r'posts', views.ForumPostViewSet, basename='forum-post')


urlpatterns = [
    # Включаем все URL, сгенерированные роутером
    # Префикс /api/forum/ будет добавлен в главном urls.py
    path('', include(router.urls)),
]

# === Комментарии к предыдущему коду views.py ===
# - Убедитесь, что в ForumCategoryViewSet убран @action list_topics.
# - Убедитесь, что в ForumTopicViewSet убран @action list_posts и add_post.
# - ForumTopicViewSet должен фильтровать по ?category__slug=<slug> для получения тем категории.
# - ForumPostViewSet должен фильтровать по ?topic=<id> для получения постов темы.
# - Для создания поста используется POST /api/forum/posts/ с передачей topic ID в теле запроса.
# ==================================================