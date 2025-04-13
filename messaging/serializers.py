# messaging/serializers.py
from rest_framework import serializers
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Q # Убедитесь, что Q импортирован
from django.contrib.auth import get_user_model
from django.utils import timezone
# Импортируем модели из .models
from .models import Chat, ChatParticipant, Message
# Импортируем UserSerializer
from users.serializers import UserSerializer
from rest_framework.exceptions import ValidationError# Импортируем UserSerializer из приложения users

User = get_user_model()

# --- Сериализатор для Сообщения ---
class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    # Добавляем chat_id для использования на фронтенде
    chat_id = serializers.IntegerField(source='chat.id', read_only=True)
    file_url = serializers.SerializerMethodField(read_only=True)
    # Убираем поле 'chat' для записи, оно будет установлено во ViewSet
    # chat = serializers.PrimaryKeyRelatedField(queryset=Chat.objects.all(), write_only=True)

    class Meta:
        model = Message
        # Убираем 'chat' из fields
        fields = ('id', 'chat_id', 'sender', 'content', 'file', 'file_url', 'timestamp')
        read_only_fields = ('id', 'sender', 'timestamp', 'file_url', 'chat_id')
        extra_kwargs = {
            'file': {'write_only': True, 'required': False, 'allow_null': True},
            'content': {'required': False, 'allow_null': True}, # Проверка в validate
        }

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.file.url) if request else obj.file.url
        return None

    def validate(self, data):
        if not data.get('content') and not data.get('file'):
            raise serializers.ValidationError(_('Сообщение должно содержать текст или прикрепленный файл.'))
        return data

    # create не нужен, т.к. ViewSet.perform_create его заменяет

# --- Сериализатор для Участника Чата (если используется) ---
class ChatParticipantSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    last_read_timestamp = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ChatParticipant
        # Используем last_read_timestamp вместо last_read_message_id
        fields = ('id', 'user', 'joined_at', 'last_read_timestamp')


# --- Сериализатор для Чата ---
class ChatSerializer(serializers.ModelSerializer):
    participants = UserSerializer(many=True, read_only=True)
    last_message_details = MessageSerializer(source='last_message', read_only=True, allow_null=True)
    unread_count = serializers.SerializerMethodField(read_only=True)
    display_name = serializers.SerializerMethodField(read_only=True)
    # --- ИСПРАВЛЕНИЕ: Обращаемся к Chat.ChatType ---
    chat_type = serializers.ChoiceField(choices=Chat.ChatType.choices, read_only=True)

    other_user_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Chat
        fields = (
            'id', 'chat_type', 'name', 'created_at',
            'participants',
            'last_message_details',
            'unread_count',
            'display_name',
            'other_user_id', 'participant_ids'
        )
        read_only_fields = ('id', 'created_at', 'participants', 'last_message_details', 'unread_count', 'display_name', 'chat_type')
        extra_kwargs = {
            'name': {'required': False, 'allow_null': True, 'allow_blank': True},
        }

    def get_unread_count(self, obj: Chat) -> int:
        # ... (логика подсчета как раньше, используя participant_info.last_read_timestamp) ...
        user = self.context.get('request').user
        if not (user and user.is_authenticated): return 0
        try:
            participant_info = ChatParticipant.objects.get(chat=obj, user=user)
            last_read_ts = participant_info.last_read_timestamp
            if last_read_ts:
                count = Message.objects.filter(chat=obj, timestamp__gt=last_read_ts).count()
                return count
            else:
                count = Message.objects.filter(chat=obj).count()
                return count
        except ChatParticipant.DoesNotExist:
             print(f"Warning: ChatParticipant entry not found for user {user.id} in chat {obj.id}")
             return 0
        except Exception as e:
             print(f"Error calculating unread count for chat {obj.id}: {e}")
             return 0

    def get_display_name(self, obj: Chat) -> str:
        user = self.context.get('request').user
        # --- ИСПРАВЛЕНИЕ: Обращаемся к Chat.ChatType ---
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.name or f"Группа без названия ({obj.id})"
        elif user and user.is_authenticated:
            # Находим другого участника (предполагается, что participants подгружены)
            other_participant = next((p for p in obj.participants.all() if p.pk != user.pk), None)
            if other_participant:
                return other_participant.get_full_name() or other_participant.email
            else: return f"Чат ({obj.id})"
        return f"Чат {obj.id}"

    def validate(self, data):
        other_user_id = data.get('other_user_id')
        participant_ids_input = data.get('participant_ids')
        participant_ids = set(filter(None, participant_ids_input or [])) # Убираем null/0 и дубликаты
        name = data.get('name')
        user = self.context['request'].user

        if other_user_id and participant_ids:
            raise serializers.ValidationError("Укажите либо 'other_user_id' для личного чата, либо 'participant_ids' для группового.")
        # При создании (POST) одно из полей должно быть указано
        # Эта проверка лучше во ViewSet.perform_create или в Serializer.create
        # if self.instance is None and not other_user_id and not participant_ids:
        #      raise serializers.ValidationError("Необходимо указать 'other_user_id' или 'participant_ids'.")

        if participant_ids:
            if not name or not name.strip():
                 raise serializers.ValidationError({"name": "Название обязательно для группового чата."})
            if user.id in participant_ids:
                raise serializers.ValidationError({"participant_ids": "Не нужно указывать себя в списке участников."})
            # Проверка существования пользователей
            found_users_count = User.objects.filter(id__in=participant_ids).count()
            if found_users_count != len(participant_ids):
                 raise serializers.ValidationError({"participant_ids": "Один или несколько ID участников недействительны."})

        if other_user_id:
            if other_user_id == user.id:
                 raise serializers.ValidationError({"other_user_id": "Нельзя создать чат с самим собой."})
            if not User.objects.filter(pk=other_user_id).exists():
                raise serializers.ValidationError({"other_user_id": "Пользователь с указанным ID не найден."})

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        other_user_id = validated_data.get('other_user_id')
        participant_ids = validated_data.get('participant_ids')
        name = validated_data.get('name')

        if other_user_id:
            # --- ИСПРАВЛЕНИЕ: Обращаемся к Chat.ChatType ---
            chat_type = Chat.ChatType.PRIVATE
            # ... (остальная логика создания приватного чата как раньше) ...
            try:
                other_user = User.objects.get(pk=other_user_id)
            except User.DoesNotExist:
                 raise serializers.ValidationError({"other_user_id": "Пользователь не найден."})

            existing_chat = Chat.objects.annotate(...).filter(...).first()
            if existing_chat: return existing_chat

            chat = Chat.objects.create(chat_type=chat_type, name=f"Chat with {other_user.email}", created_by=user)
            ChatParticipant.objects.bulk_create([
                ChatParticipant(user=user, chat=chat),
                ChatParticipant(user=other_user, chat=chat)
            ])
            return chat
        elif participant_ids:
             chat_type = Chat.ChatType.GROUP
             if not name:
                  raise serializers.ValidationError({"name": "Название обязательно для группового чата."})

             chat = Chat.objects.create(chat_type=chat_type, name=name, created_by=user)
             # Формируем список участников
             participants_to_add_pks = set(participant_ids)
             participants_to_add_pks.add(user.id)
             participants_to_add = User.objects.filter(pk__in=list(participants_to_add_pks))
             # Создаем записи ChatParticipant
             chat_participants = [ChatParticipant(user=p, chat=chat) for p in participants_to_add]
             ChatParticipant.objects.bulk_create(chat_participants)
             print(f"Created new group chat {chat.id} with name '{name}'")
             return chat
        else:
             # Если сюда попали, значит ни other_user_id, ни participant_ids не были предоставлены
             raise serializers.ValidationError("Не указаны участники для создания чата ('other_user_id' или 'participant_ids').")


# --- Сериализатор для отметки прочтения ---
class MarkReadSerializer(serializers.Serializer):
    """Сериализатор для пометки сообщений прочитанными до определенного момента."""
    read_until_timestamp = serializers.DateTimeField(required=False, allow_null=True)

    def save(self, **kwargs):
        chat = self.context['chat']
        user = self.context['request'].user
        timestamp_to_set = self.validated_data.get('read_until_timestamp')

        if not timestamp_to_set:
            # Используем order_by().values().first() для оптимизации, если нужно только время
            last_message_data = Message.objects.filter(chat=chat).order_by('-timestamp').values('timestamp').first()
            timestamp_to_set = last_message_data['timestamp'] if last_message_data else timezone.now()

        # Используем update() для атомарности
        # Правильно используем filter и Q объекты
        updated_count = ChatParticipant.objects.filter(
            user=user,
            chat=chat
        ).filter(
            Q(last_read_timestamp__lt=timestamp_to_set) | Q(last_read_timestamp__isnull=True)
        ).update(last_read_timestamp=timestamp_to_set)


        if updated_count > 0:
            print(f"User {user.id} marked chat {chat.id} read up to {timestamp_to_set}")
            # TODO: Отправить WS уведомление об обновлении статуса прочтения?
        else:
            try:
                participant = ChatParticipant.objects.get(chat=chat, user=user)
                current_ts = participant.last_read_timestamp
                print(f"User {user.id} already marked chat {chat.id} read up to {current_ts} (attempted: {timestamp_to_set})")
            except ChatParticipant.DoesNotExist:
                 print(f"User {user.id} is not participant of chat {chat.id} during mark read.")


        # Метод save сериализатора DRF должен возвращать созданный/обновленный инстанс
        # В данном случае мы обновляем ChatParticipant, вернем его
        # Возвращаем None, если не нашли участника (хотя это ошибка)
        return ChatParticipant.objects.filter(chat=chat, user=user).first()