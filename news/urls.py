from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'categories', views.NewsCategoryViewSet, basename='news-category')
router.register(r'articles', views.NewsArticleViewSet, basename='news-article')
router.register(r'comments', views.NewsCommentViewSet, basename='news-comment') # Для редактирования/удаления/лайка комментов

# urlpatterns создаются роутером автоматически

urlpatterns = [
    path('', include(router.urls)),
]