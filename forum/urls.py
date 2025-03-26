from django.urls import path, include
from rest_framework_nested import routers # Используем вложенные роутеры
from . import views

router = routers.DefaultRouter()
router.register(r'categories', views.ForumCategoryViewSet, basename='forum-category')
router.register(r'topics', views.ForumTopicViewSet, basename='forum-topic')
router.register(r'posts', views.ForumPostViewSet, basename='forum-post') # Для редактирования/лайков постов

# Вложенный роутер для тем внутри категорий (не обязательно, т.к. есть action)
# categories_router = routers.NestedDefaultRouter(router, r'categories', lookup='category')
# categories_router.register(r'topics', views.ForumTopicViewSet, basename='category-topics')

# Вложенный роутер для постов внутри тем (не обязательно, т.к. есть action)
# topics_router = routers.NestedDefaultRouter(router, r'topics', lookup='topic')
# topics_router.register(r'posts', views.ForumPostViewSet, basename='topic-posts')

urlpatterns = [
    path('', include(router.urls)),
    # path('', include(categories_router.urls)),
    # path('', include(topics_router.urls)),
]