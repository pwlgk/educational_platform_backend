# notifications/tests.py

from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from channels.testing import WebsocketCommunicator
from unittest.mock import patch, MagicMock, AsyncMock # Используем AsyncMock
import json
from datetime import timedelta
from channels.db import database_sync_to_async # Для асинхронного создания
from channels.layers import get_channel_layer


from .models import Notification, UserNotificationSettings
from .consumers import NotificationConsumer
from .utils import send_notification

User = get_user_model()

class NotificationModelTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_recipient = User.objects.create_user(email='recipient@example.com', password='TestPassword123!', first_name='Recipient')
        # UserNotificationSettings создается сигналом

    def test_user_notification_settings_created_on_user_creation(self):
        new_user = User.objects.create_user(email='newsettingsuser@example.com', password='TestPassword123!')
        self.assertTrue(UserNotificationSettings.objects.filter(user=new_user).exists())

    def test_user_notification_settings_is_enabled(self):
        settings = UserNotificationSettings.objects.get(user=self.user_recipient)
        self.assertTrue(settings.is_enabled(Notification.NotificationType.MESSAGE))
        settings.enable_messages = False; settings.save()
        self.assertFalse(settings.is_enabled(Notification.NotificationType.MESSAGE))
        self.assertTrue(settings.is_enabled("UNKNOWN_TYPE"))

    def test_notification_creation(self):
        notification = Notification.objects.create(recipient=self.user_recipient, message="Test", notification_type=Notification.NotificationType.SYSTEM)
        self.assertEqual(str(notification), f"Уведомление для {self.user_recipient.email}: Test...")

    def test_notification_generic_foreign_key(self):
        from django.contrib.contenttypes.models import ContentType
        from messaging.models import Chat as MessagingChat
        chat_instance = MessagingChat.objects.create(chat_type=MessagingChat.ChatType.GROUP, name="Related Chat")
        notification = Notification.objects.create(recipient=self.user_recipient, message="About chat", notification_type=Notification.NotificationType.MESSAGE, content_object=chat_instance)
        self.assertEqual(notification.content_object, chat_instance)

class NotificationUtilsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='utilstest@example.com', password='TestPassword123!', is_active=True)
        # Настройки создадутся сигналом

    @patch('notifications.utils.get_channel_layer')
    def test_send_notification_success_and_websocket(self, mock_get_channel_layer):
        mock_layer = MagicMock()
        mock_layer.group_send = AsyncMock() # Используем AsyncMock
        mock_get_channel_layer.return_value = mock_layer
        send_notification(self.user, "Util message", Notification.NotificationType.SYSTEM)
        self.assertTrue(Notification.objects.filter(recipient=self.user, message="Util message").exists())
        notification_instance = Notification.objects.get(recipient=self.user, message="Util message")
        mock_layer.group_send.assert_called_once()
        args, _ = mock_layer.group_send.call_args
        self.assertEqual(args[0], f"user_{self.user.id}")
        self.assertEqual(args[1]['type'], "new_notification")
        self.assertEqual(args[1]['notification']['id'], notification_instance.id)


    @patch('notifications.utils.get_channel_layer')
    def test_send_notification_disabled_by_settings(self, mock_get_channel_layer):
        mock_layer = MagicMock(); mock_layer.group_send = AsyncMock()
        mock_get_channel_layer.return_value = mock_layer
        settings = UserNotificationSettings.objects.get(user=self.user)
        settings.enable_system = False; settings.save()
        send_notification(self.user, "System, but disabled", Notification.NotificationType.SYSTEM)
        self.assertFalse(Notification.objects.filter(recipient=self.user, message="System, but disabled").exists())
        mock_layer.group_send.assert_not_called()

    def test_send_notification_inactive_recipient(self):
        inactive_user = User.objects.create_user(email="inactive@example.com", password="pw", is_active=False)
        send_notification(inactive_user, "For inactive", Notification.NotificationType.SYSTEM)
        self.assertFalse(Notification.objects.filter(recipient=inactive_user).exists())

class NotificationAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user1 = User.objects.create_user(email='notifyapi1@example.com', password='pw', is_active=True)
        Notification.objects.create(recipient=cls.user1, message="N1 unread", notification_type=Notification.NotificationType.MESSAGE)
        Notification.objects.create(recipient=cls.user1, message="N2 read", notification_type=Notification.NotificationType.SYSTEM, is_read=True)

    def test_list_notifications_authenticated_user(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('notification-list-list') # ПРОВЕРЬТЕ ИМЯ URL
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results_data = response.data
        if isinstance(response.data, dict) and 'results' in response.data:
            results_data = response.data['results']
        self.assertEqual(len(results_data), 2)

    def test_mark_notification_as_read(self):
        self.client.force_authenticate(user=self.user1)
        unread_notification = Notification.objects.filter(recipient=self.user1, is_read=False).first()
        url = reverse('notification-list-mark-as-read', kwargs={'pk': unread_notification.pk}) # ПРОВЕРЬТЕ ИМЯ URL
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        unread_notification.refresh_from_db(); self.assertTrue(unread_notification.is_read)

    def test_mark_all_notifications_as_read(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('notification-list-mark-all-as-read') # ПРОВЕРЬТЕ ИМЯ URL
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Notification.objects.filter(recipient=self.user1, is_read=False).count(), 0)

    def test_user_notification_settings_api(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('notification-settings')
        response_get = self.client.get(url); self.assertEqual(response_get.status_code, status.HTTP_200_OK)
        response_patch = self.client.patch(url, {'enable_messages': False}, format='json')
        self.assertEqual(response_patch.status_code, status.HTTP_200_OK)
        self.assertFalse(response_patch.data['enable_messages'])


class NotificationConsumerTests(APITestCase):
    async def asyncSetUp(self):
        self.user_ws = await database_sync_to_async(User.objects.create_user)(email='ws_notify@example.com', password='TestPassword123!', is_active=True)
        # Настройки создадутся сигналом

    async def test_notification_consumer_connect_success(self):
        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        communicator.scope['user'] = self.user_ws
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        
        channel_layer = get_channel_layer()
        test_notification_data = {'id': 123, 'message': 'WS Test'}
        # Тип события должен точно совпадать с именем метода-обработчика в консьюмере
        await channel_layer.group_send(f"user_{self.user_ws.id}", {"type": "new.notification", "notification": test_notification_data})
        
        response = await communicator.receive_json_from(timeout=1)
        self.assertEqual(response['type'], 'new_notification')
        self.assertEqual(response['notification'], test_notification_data)
        await communicator.disconnect()

    async def test_notification_consumer_connect_unauthenticated(self):
        from django.contrib.auth.models import AnonymousUser
        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        communicator.scope['user'] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertFalse(connected)