from rest_framework import serializers
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Chat, ChatParticipant, Message
from users.serializers import UserSerializer, ProfileSerializer # Полный UserSerializer
from rest_framework.exceptions import ValidationError
from users.models import Profile # Модель профиля пользователя
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

# Сериализатор LimitedProfileSerializer предназначен для отображения
# ограниченной информации из профиля пользователя, в данном случае - только аватара.
# - avatar: SerializerMethodField для формирования полного URL аватара.
# Используется для встраивания в другие сериализаторы, когда полная информация
# о профиле не требуется.
class LimitedProfileSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Profile
        fields = ('avatar',)

    def get_avatar(self, obj):
        request = self.context.get('request')
        if obj.avatar and hasattr(obj.avatar, 'url'):
            return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url
        return None

# Сериализатор LimitedUserSerializer предоставляет урезанное представление пользователя,
# включая только ID, имя, фамилию и информацию об аватаре (через LimitedProfileSerializer).
# - profile: Вложенный LimitedProfileSerializer для отображения аватара.
# Все поля доступны только для чтения. Используется для отображения информации
# об отправителях сообщений или участниках чата без раскрытия всех данных пользователя.
class LimitedUserSerializer(serializers.ModelSerializer):
    profile = LimitedProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'profile')
        read_only_fields = fields

# Сериализатор MediaMessageSerializer используется для отображения сообщений,
# содержащих медиа-вложения (файлы). Он предоставляет упрощенное представление сообщения.
# - sender: Использует LimitedUserSerializer для отображения информации об отправителе.
# - file_url: SerializerMethodField для получения URL прикрепленного файла.
# - mime_type, file_size, original_filename: Поля только для чтения, отображающие метаданные файла.
# Все поля доступны только для чтения.
class MediaMessageSerializer(serializers.ModelSerializer):
    sender = LimitedUserSerializer(read_only=True)
    file_url = serializers.SerializerMethodField(read_only=True)
    mime_type = serializers.CharField(read_only=True, allow_null=True)
    file_size = serializers.IntegerField(read_only=True, allow_null=True)
    original_filename = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = Message
        fields = (
            'id', 'sender', 'timestamp', 'content',
            'file_url', 'mime_type', 'file_size', 'original_filename',
        )
        read_only_fields = fields

    def get_file_url(self, obj):
         if obj.file:
             request = self.context.get('request')
             return request.build_absolute_uri(obj.file.url) if request else obj.file.url
         return None

# Сериализатор MessageSerializer предназначен для полного представления сообщений чата,
# включая информацию об отправителе, содержимое, прикрепленный файл и временную метку.
# - sender: Использует полный UserSerializer для отображения данных отправителя (read-only).
# - chat_id: ID чата, к которому принадлежит сообщение (read-only).
# - file_url: URL прикрепленного файла (read-only, получается через get_file_url).
# - _isSending, _tempId: Поля только для записи (write_only), используемые для
#   оптимистичного обновления UI на фронтенде. Эти поля не сохраняются в БД.
# - mime_type, file_size, original_filename: Метаданные файла (read-only).
# Метод validate проверяет, что при создании нового сообщения присутствует либо текст, либо файл.
class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True) # Используем полный UserSerializer
    chat_id = serializers.IntegerField(source='chat.id', read_only=True)
    file_url = serializers.SerializerMethodField(read_only=True)
    _isSending = serializers.BooleanField(write_only=True, required=False)
    _tempId = serializers.CharField(write_only=True, required=False)
    mime_type = serializers.CharField(read_only=True, allow_null=True)
    file_size = serializers.IntegerField(read_only=True, allow_null=True)
    original_filename = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = Message
        fields = (
            'id', 'chat_id', 'sender', 'content', 'file', 'file_url', 'timestamp',
            'mime_type', 'file_size', 'original_filename',
            '_isSending', '_tempId'
        )
        read_only_fields = ('id', 'sender', 'timestamp', 'file_url', 'chat_id', 'mime_type', 'file_size', 'original_filename')

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.file.url) if request else obj.file.url
        return None

    def validate(self, data):
        if not self.instance and not data.get('content', '').strip() and not data.get('file'):
            raise serializers.ValidationError(_('Сообщение должно содержать текст или прикрепленный файл.'))
        return data

# Сериализатор ChatParticipantSerializer отображает информацию об участнике чата.
# - user: Использует полный UserSerializer для отображения данных пользователя (read-only).
# - last_read_timestamp: Временная метка последнего прочитанного сообщения (read-only).
# (Примечание: в коде это поле `last_read_timestamp`, но в модели `last_read_message`.
# Для корректной работы здесь должен быть SerializerMethodField или source на timestamp этого сообщения)
class ChatParticipantSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True) # Используем полный UserSerializer
    # Для last_read_timestamp нужен SerializerMethodField или source='last_read_message.timestamp'
    last_read_timestamp = serializers.DateTimeField(source='last_read_message.timestamp', read_only=True, allow_null=True)


    class Meta:
        model = ChatParticipant
        fields = ('id', 'user', 'joined_at', 'last_read_timestamp')


# Сериализатор ChatSerializer предназначен для представления информации о чате.
# - participants: Список участников чата (использует UserSerializer, read-only).
# - last_message_details: Детали последнего сообщения в чате (использует MessageSerializer, read-only).
# - unread_count: Количество непрочитанных сообщений для текущего пользователя (read-only, получается через get_unread_count).
# - display_name: Отображаемое имя чата (read-only, получается через get_display_name). Для групповых чатов - это имя чата,
#   для личных - имя собеседника.
# - chat_type: Тип чата (read-only).
# - created_by_details: Информация о создателе чата (использует UserSerializer, read-only).
# - Поля для создания чата (write-only):
#   - other_user_id: ID другого пользователя для создания личного чата.
#   - participant_ids: Список ID пользователей для создания группового чата.
#   - name: Имя чата (обязательно для групповых, можно изменять).
# Метод get_unread_count вычисляет количество непрочитанных сообщений.
# Метод get_display_name формирует отображаемое имя чата.
# Метод validate выполняет валидацию данных при создании и обновлении чата.
# Метод create обрабатывает создание нового личного или группового чата. Если личный чат между
# указанными пользователями уже существует, возвращается существующий чат.
# Метод update обновляет имя чата (если оно передано).
class ChatSerializer(serializers.ModelSerializer):
    participants = UserSerializer(many=True, read_only=True)
    last_message_details = MessageSerializer(source='last_message', read_only=True, allow_null=True)
    unread_count = serializers.SerializerMethodField(read_only=True)
    display_name = serializers.SerializerMethodField(read_only=True)
    chat_type = serializers.ChoiceField(choices=Chat.ChatType.choices, read_only=True)
    created_by_details = UserSerializer(source='created_by', read_only=True, allow_null=True)

    other_user_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), write_only=True, required=False, allow_null=True
    )
    name = serializers.CharField(max_length=150, required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Chat
        fields = (
            'id', 'chat_type', 'name', 'created_at',
            'participants',
            'last_message_details',
            'unread_count',
            'display_name',
            'created_by_details',
            'other_user_id', 'participant_ids'
        )
        read_only_fields = ('id', 'created_at', 'participants', 'last_message_details', 'unread_count', 'display_name', 'chat_type')

    def get_unread_count(self, obj: Chat) -> int:
        request = self.context.get('request')
        if not request or not hasattr(request, 'user') or not request.user.is_authenticated: return 0
        user = request.user
        try:
            participant_info = ChatParticipant.objects.select_related('last_read_message').get(chat=obj, user=user)
            last_read_message = participant_info.last_read_message
            if last_read_message and last_read_message.timestamp:
                last_read_ts = last_read_message.timestamp
                count = Message.objects.filter(chat=obj, timestamp__gt=last_read_ts).count()
                return count
            else:
                return Message.objects.filter(chat=obj).count()
        except ChatParticipant.DoesNotExist:
            logger.warning(f"ChatParticipant entry not found for user {user.id} in chat {obj.id}. Counting all messages.")
            try: return Message.objects.filter(chat=obj).count()
            except Exception as e_count: logger.error(f"Error counting messages for chat {obj.id}: {e_count}", exc_info=True); return 0
        except Exception as e:
            logger.error(f"Error in get_unread_count for chat {obj.id}, user {user.id}: {e}", exc_info=True)
            return 0

    def get_display_name(self, obj: Chat) -> str:
        user = self.context.get('request').user
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.name or f"Group Chat"
        elif user and user.is_authenticated and obj.participants.count() > 0:
            other_participant = next((p for p in obj.participants.all() if p.pk != user.pk), None)
            if other_participant:
                full_name = other_participant.get_full_name()
                return full_name or other_participant.get_username()
            else:
                return "Saved Messages"
        return f"Chat"

    def validate(self, data):
        if not self.instance:
            other_user_id = data.get('other_user_id')
            participant_ids_input = data.get('participant_ids')
            participant_ids = set(filter(None, participant_ids_input or []))
            name = data.get('name')
            user = self.context['request'].user

            if other_user_id and participant_ids:
                raise serializers.ValidationError("Please provide either 'other_user_id' for a private chat OR 'participant_ids' and 'name' for a group chat, not both.")
            if not other_user_id and not participant_ids:
                raise serializers.ValidationError("Please provide either 'other_user_id' or 'participant_ids' to create a chat.")

            if participant_ids:
                if not name or not name.strip():
                    raise serializers.ValidationError({"name": "Group name is required."})
                if not participant_ids:
                     raise serializers.ValidationError({"participant_ids": "Please select at least one other participant for the group."})
                found_users = User.objects.filter(id__in=participant_ids).values_list('id', flat=True)
                missing_ids = participant_ids - set(found_users)
                if missing_ids:
                    raise serializers.ValidationError({"participant_ids": f"Invalid participant IDs: {', '.join(map(str, missing_ids))}."})

            if other_user_id:
                 if other_user_id == user.id:
                     raise serializers.ValidationError({"other_user_id": "You cannot create a private chat with yourself."})
                 if not User.objects.filter(pk=other_user_id).exists():
                    raise serializers.ValidationError({"other_user_id": "The specified user does not exist."})

        if self.instance and 'name' in data and not data.get('name', '').strip():
             if self.instance.chat_type == Chat.ChatType.GROUP:
                 raise serializers.ValidationError({"name": "Group name cannot be empty."})
        return data

    def create(self, validated_data):
        user = self.context['request'].user
        other_user_id = validated_data.get('other_user_id')
        participant_ids_input = validated_data.get('participant_ids')
        name = validated_data.get('name')

        if other_user_id:
            chat_type = Chat.ChatType.PRIVATE
            try:
                other_user = User.objects.get(pk=other_user_id)
            except User.DoesNotExist:
                 raise serializers.ValidationError({"other_user_id": "User not found."})

            existing_chat = Chat.objects.filter(
                chat_type=Chat.ChatType.PRIVATE, participants=user
            ).filter(
                participants=other_user
            ).annotate(
                num_participants=Count('participants')
            ).filter(
                num_participants=2
            ).first()

            if existing_chat:
                return existing_chat

            chat = Chat.objects.create(chat_type=chat_type, name=None, created_by=user)
            ChatParticipant.objects.bulk_create([
                ChatParticipant(user=user, chat=chat),
                ChatParticipant(user=other_user, chat=chat)
            ])
            return chat

        elif participant_ids_input:
             chat_type = Chat.ChatType.GROUP
             if not name:
                  raise serializers.ValidationError({"name": "Group name is required."})
             chat = Chat.objects.create(chat_type=chat_type, name=name, created_by=user)
             participant_ids = set(filter(None, participant_ids_input))
             participant_ids.add(user.id)
             participants_to_add = User.objects.filter(pk__in=list(participant_ids))
             chat_participants = [ChatParticipant(user=p, chat=chat) for p in participants_to_add]
             ChatParticipant.objects.bulk_create(chat_participants)
             return chat
        else:
             raise serializers.ValidationError("Cannot create chat without 'other_user_id' or 'participant_ids'.")

    def update(self, instance, validated_data):
        instance.name = validated_data.get('name', instance.name)
        if instance.chat_type == Chat.ChatType.GROUP and not instance.name:
             raise serializers.ValidationError({"name": "Group name cannot be empty."})
        instance.save()
        return instance

# Сериализатор MarkReadSerializer используется для отметки сообщений в чате как прочитанных.
# Он не принимает входных данных; вся логика выполняется в методе save.
# Метод save обновляет поле `last_read_message` для текущего пользователя в данном чате,
# устанавливая его равным последнему сообщению в чате. Если сообщений нет,
# или все уже прочитано, никаких изменений не происходит.
class MarkReadSerializer(serializers.Serializer):
    def save(self, **kwargs):
        chat = self.context['chat']
        user = self.context['request'].user
        participant_info = None
        logger.debug(f"MarkRead Save: Chat={chat.id}, User={user.id}. Finding last message...")
        last_message = Message.objects.filter(chat=chat).order_by('-timestamp').first()

        if not last_message:
            logger.info(f"MarkRead Save: No messages found in chat {chat.id}. No update needed for user {user.id}.")
            return ChatParticipant.objects.filter(chat=chat, user=user).first()
        logger.debug(f"MarkRead Save: Found last_message {last_message.id} (ts: {last_message.timestamp}) for chat {chat.id}, user {user.id}.")

        try:
            current_participant = ChatParticipant.objects.filter(user=user, chat=chat).select_related('last_read_message').first()
            if current_participant and current_participant.last_read_message_id == last_message.id:
                 logger.info(f"MarkRead Save: Chat {chat.id} already marked as read up to message {last_message.id} for user {user.id}. No update performed.")
                 return current_participant

            participant_info, created = ChatParticipant.objects.update_or_create(
                user=user,
                chat=chat,
                defaults={'last_read_message': last_message}
            )
            if created:
                logger.warning(f"MarkRead Save: CREATED ChatParticipant for user {user.id} in chat {chat.id} (should normally exist). Set last_read_message_id: {participant_info.last_read_message_id}")
            else:
                logger.info(f"MarkRead Save: UPDATED ChatParticipant for user {user.id} in chat {chat.id}. Set last_read_message_id: {last_message.id}")
            return participant_info
        except Exception as e:
             logger.error(f"MarkRead Save: Error during update_or_create for chat {chat.id}, user {user.id}: {e}", exc_info=True)
             raise