import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from monitor.middleware import JwtAuthMiddlewareStack 
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server_api.settings')
django.setup()

import messaging.routing
import notifications.routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JwtAuthMiddlewareStack( 
        URLRouter(
            messaging.routing.websocket_urlpatterns +
            notifications.routing.websocket_urlpatterns
        )
    ),
})
