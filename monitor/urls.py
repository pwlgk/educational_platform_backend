from django.urls import path
from . import views

urlpatterns = [
    # REST эндпоинты
    path('system/', views.SystemInfoView.as_view(), name='system-info'),
    path('processes/', views.ProcessListView.as_view(), name='process-list'),
    path('processes/<int:pid>/', views.ProcessDetailView.as_view(), name='process-detail'),
    path('services/', views.ServiceListView.as_view(), name='service-list'),
    path('services/<str:service_name>/<str:action>/', views.ServiceActionView.as_view(), name='service-action'),
    path('logs/', views.LogFileView.as_view(), name='log-file'),
    path('command/', views.CommandExecutionView.as_view(), name='command-execution'),
]