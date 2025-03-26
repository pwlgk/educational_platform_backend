from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'subjects', views.SubjectViewSet)
router.register(r'groups', views.StudentGroupViewSet)
router.register(r'classrooms', views.ClassroomViewSet)
router.register(r'lessons', views.LessonViewSet)

urlpatterns = [
    path('my-schedule/', views.MyScheduleView.as_view(), name='my-schedule'),
    path('', include(router.urls)),
]