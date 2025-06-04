# messaging/tests.py

from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase # APIClient не нужен отдельно
from channels.testing import WebsocketCommunicator
from channels.layers import get_channel_layer
from channels.db import database_sync_to_async # Для асинхронного создания
import json
from unittest.mock import AsyncMock, MagicMock, patch # Для мокирования

from .models import Chat, ChatParticipant, Message
from .consumers import ChatConsumer

User = get_user_model()

class MessagingModelTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user1 = User.objects.create_user(email='user1_msg@example.com', password='TestPassword123!', first_name='User1')
        cls.user2 = User.objects.create_user(email='user2_msg@example.com', password='TestPassword123!', first_name='User2')
        cls.user3 = User.objects.create_user(email='user3_msg@example.com', password='TestPassword123!', first_name='User3')

        cls.private_chat = Chat.objects.create(chat_type=Chat.ChatType.PRIVATE)
        ChatParticipant.objects.create(chat=cls.private_chat, user=cls.user1)
        ChatParticipant.objects.create(chat=cls.private_chat, user=cls.user2)

        cls.group_chat = Chat.objects.create(chat_type=Chat.ChatType.GROUP, name='Test Group Chat', created_by=cls.user1)
        ChatParticipant.objects.create(chat=cls.group_chat, user=cls.user1)
        ChatParticipant.objects.create(chat=cls.group_chat, user=cls.user2)
        ChatParticipant.objects.create(chat=cls.group_chat, user=cls.user3)

    def test_chat_creation_and_properties(self):
        self.assertEqual(self.private_chat.chat_type, Chat.ChatType.PRIVATE)
        self.assertEqual(self.group_chat.chat_type, Chat.ChatType.GROUP)
        self.assertEqual(self.group_chat.participants.count(), 3)

    def test_chat_str_representation(self):
        self.assertEqual(str(self.private_chat), f"Личный чат {self.private_chat.id}")
        self.assertEqual(str(self.group_chat), "Test Group Chat")

    def test_chat_get_other_participant(self):
        self.assertEqual(self.private_chat.get_other_participant(self.user1), self.user2)
        self.assertIsNone(self.group_chat.get_other_participant(self.user1))

    def test_chat_participant_creation(self):
        participant = ChatParticipant.objects.get(chat=self.private_chat, user=self.user1)
        self.assertIsNotNone(participant.joined_at)
        self.assertEqual(str(participant), f"{self.user1} в чате {self.private_chat.id}")

    def test_message_creation_and_chat_last_message_update(self):
        message = Message.objects.create(chat=self.private_chat, sender=self.user1, content="Hello")
        self.private_chat.refresh_from_db()
        self.assertEqual(self.private_chat.last_message, message)
        self.assertIn("Hello", str(message))

    def test_message_validation_content_or_file(self):
        from django.core.exceptions import ValidationError as DjangoValidationError
        message_no_content = Message(chat=self.private_chat, sender=self.user1)
        with self.assertRaises(DjangoValidationError) as cm:
            message_no_content.full_clean() # Вызываем full_clean для проверки валидации модели
        self.assertIn('Сообщение должно содержать текст или прикрепленный файл.', str(cm.exception))


class ChatViewSetAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user1 = User.objects.create_user(email='chatapi1@example.com', password='TestPassword123!', first_name='Api1', is_active=True)
        cls.user2 = User.objects.create_user(email='chatapi2@example.com', password='TestPassword123!', first_name='Api2', is_active=True)
        cls.user3 = User.objects.create_user(email='chatapi3@example.com', password='TestPassword123!', first_name='Api3', is_active=True)
        cls.private_chat = Chat.objects.create(chat_type=Chat.ChatType.PRIVATE)
        ChatParticipant.objects.create(chat=cls.private_chat, user=cls.user1)
        ChatParticipant.objects.create(chat=cls.private_chat, user=cls.user2)
        cls.group_chat = Chat.objects.create(chat_type=Chat.ChatType.GROUP, name="API Test Group", created_by=cls.user1)
        ChatParticipant.objects.create(chat=cls.group_chat, user=cls.user1)
        ChatParticipant.objects.create(chat=cls.group_chat, user=cls.user2)

    def test_list_chats_authenticated_user(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('chat-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results_data = response.data
        if isinstance(response.data, dict) and 'results' in response.data:
            results_data = response.data['results']
        self.assertEqual(len(results_data), 2)

    def test_list_chats_unauthenticated_user(self):
        url = reverse('chat-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_private_chat(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('chat-list')
        data = {'other_user_id': self.user3.id}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['chat_type'], Chat.ChatType.PRIVATE)

    def test_create_private_chat_with_self_forbidden(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('chat-list')
        data = {'other_user_id': self.user1.id}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_group_chat(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('chat-list')
        data = {'name': 'New Awesome Group', 'participant_ids': [self.user2.id, self.user3.id]}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'New Awesome Group')

    def test_retrieve_chat_participant(self):
        self.client.force_authenticate(user=self.user1)
        url = reverse('chat-detail', kwargs={'pk': self.private_chat.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_chat_non_participant(self):
        self.client.force_authenticate(user=self.user3)
        url = reverse('chat-detail', kwargs={'pk': self.private_chat.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

class MessageViewSetAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_sender = User.objects.create_user(email='sender_msg@example.com', password='pw', is_active=True)
        cls.user_receiver = User.objects.create_user(email='receiver_msg@example.com', password='pw', is_active=True)
        cls.chat = Chat.objects.create(chat_type=Chat.ChatType.PRIVATE)
        ChatParticipant.objects.create(chat=cls.chat, user=cls.user_sender)
        ChatParticipant.objects.create(chat=cls.chat, user=cls.user_receiver)
        Message.objects.create(chat=cls.chat, sender=cls.user_sender, content="Msg1")

    def test_list_messages_in_chat(self):
        self.client.force_authenticate(user=self.user_sender)
        url = reverse('chat-messages-list', kwargs={'chat_pk': self.chat.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results_data = response.data
        if isinstance(response.data, dict) and 'results' in response.data:
            results_data = response.data['results']
        self.assertGreaterEqual(len(results_data), 1) # Одна или больше, если есть пагинация

    def test_create_message_in_chat(self):
        self.client.force_authenticate(user=self.user_sender)
        url = reverse('chat-messages-list', kwargs={'chat_pk': self.chat.pk})
        data = {'content': 'New API Message'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['content'], 'New API Message')

    def test_create_message_in_chat_non_participant(self):
        non_participant = User.objects.create_user(email='stranger@example.com', password='pw', is_active=True)
        self.client.force_authenticate(user=non_participant)
        url = reverse('chat-messages-list', kwargs={'chat_pk': self.chat.pk})
        response = self.client.post(url, {'content': 'Intruder'}, format='json')
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])


class ChatConsumerTests(APITestCase):
    async def asyncSetUp(self):
        self.user_ws1 = await database_sync_to_async(User.objects.create_user)(email='ws_user1@example.com', password='TestPassword123!', first_name='WS1', is_active=True)
        self.user_ws2 = await database_sync_to_async(User.objects.create_user)(email='ws_user2@example.com', password='TestPassword123!', first_name='WS2', is_active=True)
        self.chat_ws = await database_sync_to_async(Chat.objects.create)(chat_type=Chat.ChatType.GROUP, name="WS Test Chat")
        await database_sync_to_async(ChatParticipant.objects.create)(chat=self.chat_ws, user=self.user_ws1)
        await database_sync_to_async(ChatParticipant.objects.create)(chat=self.chat_ws, user=self.user_ws2)

    async def test_chat_consumer_connect_success(self):
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), f"/ws/chat/{self.chat_ws.pk}/")
        communicator.scope['user'] = self.user_ws1
        communicator.scope['url_route'] = {'kwargs': {'chat_id': str(self.chat_ws.pk)}}
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_chat_consumer_connect_unauthenticated(self):
        from django.contrib.auth.models import AnonymousUser
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), f"/ws/chat/{self.chat_ws.pk}/")
        communicator.scope['user'] = AnonymousUser()
        communicator.scope['url_route'] = {'kwargs': {'chat_id': str(self.chat_ws.pk)}}
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_chat_consumer_connect_non_participant(self):
        non_participant = await database_sync_to_async(User.objects.create_user)(email='ws_nonparticipant@example.com', password='TestPassword123!', is_active=True)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), f"/ws/chat/{self.chat_ws.pk}/")
        communicator.scope['user'] = non_participant
        communicator.scope['url_route'] = {'kwargs': {'chat_id': str(self.chat_ws.pk)}}
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_chat_consumer_typing_event(self):
        comm1 = WebsocketCommunicator(ChatConsumer.as_asgi(), f"/ws/chat/{self.chat_ws.pk}/")
        comm1.scope['user'] = self.user_ws1; comm1.scope['url_route'] = {'kwargs': {'chat_id': str(self.chat_ws.pk)}}
        await comm1.connect()
        comm2 = WebsocketCommunicator(ChatConsumer.as_asgi(), f"/ws/chat/{self.chat_ws.pk}/")
        comm2.scope['user'] = self.user_ws2; comm2.scope['url_route'] = {'kwargs': {'chat_id': str(self.chat_ws.pk)}}
        await comm2.connect()
        await comm1.send_json_to({'type': 'typing', 'is_typing': True})
        response = await comm2.receive_json_from(timeout=1)
        self.assertEqual(response['type'], 'chat.typing')
        self.assertEqual(response['user_id'], self.user_ws1.id)
        is_typing_echo_received_by_sender = False
        try:
            echo_response = await comm1.receive_json_from(timeout=0.1) # Пропускаем начальное user_status_update
            if echo_response.get('type') == 'user_status_update' and echo_response['data']['user_id'] == self.user_ws2.id: # Это от второго юзера
                 echo_response = await comm1.receive_json_from(timeout=0.1) # Пробуем еще раз
            if echo_response.get('type') == 'chat.typing': is_typing_echo_received_by_sender = True
        except TimeoutError: pass
        self.assertFalse(is_typing_echo_received_by_sender)
        await comm1.disconnect(); await comm2.disconnect()

    async def test_message_via_rest_and_receive_via_websocket(self):
        # self.client доступен в APITestCase и может делать асинхронные запросы
        await database_sync_to_async(self.client.force_authenticate)(user=self.user_ws1)
        ws_communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), f"/ws/chat/{self.chat_ws.pk}/")
        ws_communicator.scope['user'] = self.user_ws2
        ws_communicator.scope['url_route'] = {'kwargs': {'chat_id': str(self.chat_ws.pk)}}
        await ws_communicator.connect()
        rest_url = reverse('chat-messages-list', kwargs={'chat_pk': self.chat_ws.pk})
        message_content = "Hello from REST to WS"
        response = await self.client.post(rest_url, {'content': message_content}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ws_response = await ws_communicator.receive_json_from(timeout=1)
        self.assertEqual(ws_response['type'], 'chat.message')
        self.assertEqual(ws_response['message']['content'], message_content)
        await ws_communicator.disconnect()