from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    # path('api/news/', include('news.urls')),
    path('api/messaging/', include('messaging.urls')),

    path('api/notifications/', include('notifications.urls')),
    # Эндпоинты API приложения monitor
    path('api/users/', include('users.urls')), 
    path('api/edu-core/', include('edu_core.urls')),

    # Эндпоинты для JWT аутентификации
    #path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    #path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    #path('api/schedule/', include('schedule.urls')),
    #path('api/testing/', include('testing.urls')),
    #path('api/monitor/', include('monitor.urls')),
    #path('api/academics/', include('academics.urls')),
    #path('api/forum/', include('forum.urls')),

    # Эндпоинты для Swagger/OpenAPI документации
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)