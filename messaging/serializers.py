# messaging/serializers.py
from rest_framework import serializers
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Q # Убедитесь, что Q импортирован
from django.contrib.auth import get_user_model
from django.utils import timezone
# Импортируем модели из .models
from .models import Chat, ChatParticipant, Message # Убедитесь, что модели импортированы правильно
# Импортируем UserSerializer
from users.serializers import UserSerializer, ProfileSerializer
from rest_framework.exceptions import ValidationError
from users.models import Profile

import logging
logger = logging.getLogger(__name__)

User = get_user_model()

class LimitedProfileSerializer(serializers.ModelSerializer):
    """ Показываем только аватар из профиля """
    avatar = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Profile # Укажите вашу модель профиля
        fields = ('avatar',)

    def get_avatar(self, obj):
        request = self.context.get('request')
        if obj.avatar and hasattr(obj.avatar, 'url'):
            return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url
        return None

class LimitedUserSerializer(serializers.ModelSerializer):
    """ Показываем только ID, имя, фамилию и аватар (из профиля) """
    profile = LimitedProfileSerializer(read_only=True) # Используем урезанный профиль

    class Meta:
        model = User # Ваша модель User
        fields = ('id', 'first_name', 'last_name', 'profile') # Только нужные поля
        read_only_fields = fields # Все только для чтения

class MediaMessageSerializer(serializers.ModelSerializer):
    """ Упрощенный сериализатор для сообщений с медиа/файлами. """
    # --- ИСПОЛЬЗУЕМ НОВЫЙ СЕРИАЛИЗАТОР ---
    sender = LimitedUserSerializer(read_only=True) # <-- Исправлено
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    file_url = serializers.SerializerMethodField(read_only=True)
    mime_type = serializers.CharField(read_only=True, allow_null=True) # Разрешаем null
    file_size = serializers.IntegerField(read_only=True, allow_null=True) # Разрешаем null
    original_filename = serializers.CharField(read_only=True, allow_null=True) # Разрешаем null

    class Meta:
        model = Message
        fields = (
            'id', 'sender', 'timestamp', 'content',
            'file_url', 'mime_type', 'file_size', 'original_filename',
        )
        read_only_fields = fields

    def get_file_url(self, obj):
        # ... (как раньше) ...
         if obj.file:
             request = self.context.get('request')
             return request.build_absolute_uri(obj.file.url) if request else obj.file.url
         return None

# --- Сериализатор для Сообщения ---
class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    chat_id = serializers.IntegerField(source='chat.id', read_only=True)
    file_url = serializers.SerializerMethodField(read_only=True)
    # --- ИСПРАВЛЕНИЕ: Добавим _isSending для оптимистичного UI ---
    # Это поле не будет сохраняться в БД, только для передачи на фронт
    _isSending = serializers.BooleanField(write_only=True, required=False)
    _tempId = serializers.CharField(write_only=True, required=False) # Для связи с оптимистичным сообщением
    mime_type = serializers.CharField(read_only=True, allow_null=True)
    file_size = serializers.IntegerField(read_only=True, allow_null=True)
    original_filename = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = Message
        fields = (
            'id', 'chat_id', 'sender', 'content', 'file', 'file_url', 'timestamp',
            'mime_type', 'file_size', 'original_filename', # Добавили
            '_isSending', '_tempId'
        )
        read_only_fields = ('id', 'sender', 'timestamp', 'file_url', 'chat_id', 'mime_type', 'file_size', 'original_filename')

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            # Проверка на request перед использованием build_absolute_uri
            return request.build_absolute_uri(obj.file.url) if request else obj.file.url
        return None

    def validate(self, data):
        # Проверка, что есть хотя бы текст или файл (при создании)
        # При обновлении может не быть - проверяем только если нет instance
        if not self.instance and not data.get('content', '').strip() and not data.get('file'):
            raise serializers.ValidationError(_('Сообщение должно содержать текст или прикрепленный файл.'))
        return data

# --- Сериализатор для Участника Чата (можно убрать, если не используется явно) ---
class ChatParticipantSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    last_read_timestamp = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ChatParticipant
        fields = ('id', 'user', 'joined_at', 'last_read_timestamp')

# --- Сериализатор для Чата ---
class ChatSerializer(serializers.ModelSerializer):
    participants = UserSerializer(many=True, read_only=True)
    last_message_details = MessageSerializer(source='last_message', read_only=True, allow_null=True)
    unread_count = serializers.SerializerMethodField(read_only=True)
    display_name = serializers.SerializerMethodField(read_only=True)
    chat_type = serializers.ChoiceField(choices=Chat.ChatType.choices, read_only=True) # Теперь должно работать

    # Поля только для ЗАПИСИ (создание чата)
    other_user_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), write_only=True, required=False, allow_null=True
    )
    # Поле name для создания/обновления группового чата
    name = serializers.CharField(max_length=150, required=False, allow_null=True, allow_blank=True) # Сделали не write_only

    class Meta:
        model = Chat
        fields = (
            'id', 'chat_type', 'name', 'created_at',
            'participants',
            'last_message_details',
            'unread_count',
            'display_name',
            # Write-only поля добавляем сюда, чтобы они были доступны в validated_data
            'other_user_id', 'participant_ids'
        )
        read_only_fields = ('id', 'created_at', 'participants', 'last_message_details', 'unread_count', 'display_name', 'chat_type')
        # Убрали name из extra_kwargs, он теперь в основном списке fields

    def get_unread_count(self, obj: Chat) -> int:
        request = self.context.get('request')
        if not request or not hasattr(request, 'user') or not request.user.is_authenticated: return 0
        user = request.user
        try:
            participant_info = ChatParticipant.objects.select_related('last_read_message').get(chat=obj, user=user)
            last_read_message = participant_info.last_read_message
            # Убрал лишние print
            if last_read_message and last_read_message.timestamp:
                last_read_ts = last_read_message.timestamp
                # Используем __gt для строго больше
                count = Message.objects.filter(chat=obj, timestamp__gt=last_read_ts).count()
                # print(count) # Оставил для отладки, если нужно
                return count
            else:
                # Считаем все сообщения
                return Message.objects.filter(chat=obj).count()
        except ChatParticipant.DoesNotExist:
            # Считаем все сообщения
            logger.warning(f"ChatParticipant entry not found for user {user.id} in chat {obj.id}. Counting all messages.")
            try: return Message.objects.filter(chat=obj).count()
            except Exception as e_count: logger.error(f"Error counting messages for chat {obj.id}: {e_count}", exc_info=True); return 0
        except Exception as e: # Ловим остальные ошибки
            logger.error(f"Error in get_unread_count for chat {obj.id}, user {user.id}: {e}", exc_info=True)
            return 0

    def get_display_name(self, obj: Chat) -> str:
        user = self.context.get('request').user
        if obj.chat_type == Chat.ChatType.GROUP:
            # Для группы возвращаем имя или плейсхолдер
            return obj.name or f"Group Chat" # Убрали ID для чистоты
        elif user and user.is_authenticated and obj.participants.count() > 0: # Проверяем наличие участников
            # Для приватного чата ищем собеседника
            # Используем prefetch_related('participants') во ViewSet для эффективности
            other_participant = next((p for p in obj.participants.all() if p.pk != user.pk), None)
            if other_participant:
                # Используем get_full_name() или email/username
                full_name = other_participant.get_full_name()
                return full_name or other_participant.get_username() # get_username() обычно возвращает email или username
            else:
                # Случай, если в приватном чате только текущий пользователь (не должно быть)
                return "Saved Messages" # Или что-то подобное
        return f"Chat" # Общий плейсхолдер

    def validate(self, data):
        # --- Валидация при СОЗДАНИИ чата ---
        if not self.instance: # Проверяем, что это создание нового объекта
            other_user_id = data.get('other_user_id')
            participant_ids_input = data.get('participant_ids')
            participant_ids = set(filter(None, participant_ids_input or []))
            name = data.get('name')
            user = self.context['request'].user

            if other_user_id and participant_ids:
                raise serializers.ValidationError("Please provide either 'other_user_id' for a private chat OR 'participant_ids' and 'name' for a group chat, not both.")
            if not other_user_id and not participant_ids:
                raise serializers.ValidationError("Please provide either 'other_user_id' or 'participant_ids' to create a chat.")

            if participant_ids: # Валидация для группового чата
                if not name or not name.strip():
                    raise serializers.ValidationError({"name": "Group name is required."})
                if user.id in participant_ids:
                    # Обычно фронтенд не должен передавать текущего пользователя,
                    # но если передал - игнорируем или выдаем ошибку. Пока игнорируем.
                    # participant_ids.remove(user.id)
                    pass
                if not participant_ids: # Если после удаления себя никого не осталось
                     raise serializers.ValidationError({"participant_ids": "Please select at least one other participant for the group."})

                # Проверка существования пользователей (оптимизированная)
                found_users = User.objects.filter(id__in=participant_ids).values_list('id', flat=True)
                missing_ids = participant_ids - set(found_users)
                if missing_ids:
                    raise serializers.ValidationError({"participant_ids": f"Invalid participant IDs: {', '.join(map(str, missing_ids))}."})

            if other_user_id: # Валидация для приватного чата
                 if name: # Имя не нужно для приватного чата
                    # Можно либо игнорировать, либо выдавать ошибку
                    # raise serializers.ValidationError({"name": "Name should not be provided for private chats."})
                    pass
                 if other_user_id == user.id:
                     raise serializers.ValidationError({"other_user_id": "You cannot create a private chat with yourself."})
                 if not User.objects.filter(pk=other_user_id).exists():
                    raise serializers.ValidationError({"other_user_id": "The specified user does not exist."})
        # --- Конец валидации при создании ---

        # Валидация при обновлении (если нужно, например, для имени)
        if self.instance and 'name' in data and not data.get('name', '').strip():
             if self.instance.chat_type == Chat.ChatType.GROUP:
                 raise serializers.ValidationError({"name": "Group name cannot be empty."})

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        other_user_id = validated_data.get('other_user_id')
        participant_ids_input = validated_data.get('participant_ids') # Получаем исходный список ID
        name = validated_data.get('name')

        if other_user_id:
            # --- СОЗДАНИЕ ПРИВАТНОГО ЧАТА ---
            chat_type = Chat.ChatType.PRIVATE
            try:
                other_user = User.objects.get(pk=other_user_id)
            except User.DoesNotExist:
                 # Эта проверка уже есть в validate, но для надежности
                 raise serializers.ValidationError({"other_user_id": "User not found."})

            # --- ИСПРАВЛЕНИЕ: Правильный поиск существующего чата БЕЗ annotate ---
            # Ищем приватный чат, где участников ровно 2 И это наши два пользователя
            existing_chat = Chat.objects.filter(
                chat_type=Chat.ChatType.PRIVATE,
                participants=user # Убеждаемся, что ТЕКУЩИЙ юзер есть в чате
            ).filter(
                participants=other_user # И также убеждаемся, что ДРУГОЙ юзер есть в чате
            ).annotate(
                num_participants=Count('participants') # Считаем ВСЕХ участников этого чата
            ).filter(
                num_participants=2 # И проверяем, что их всего ДВА
            ).first()
            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            if existing_chat:
                print(f"Returning existing private chat {existing_chat.id} for users {user.id} and {other_user.id}")
                return existing_chat

            # Создаем новый приватный чат
            # Имя для приватного чата не храним в БД, оно генерируется в get_display_name
            chat = Chat.objects.create(chat_type=chat_type, name=None, created_by=user)
            # Создаем записи участников
            ChatParticipant.objects.bulk_create([
                ChatParticipant(user=user, chat=chat),
                ChatParticipant(user=other_user, chat=chat)
            ])
            print(f"Created new private chat {chat.id} between users {user.id} and {other_user.id}")
            return chat

        elif participant_ids_input: # Если передан список ID для группы
             # --- СОЗДАНИЕ ГРУППОВОГО ЧАТА ---
             chat_type = Chat.ChatType.GROUP
             if not name: # Валидация имени уже была
                  raise serializers.ValidationError({"name": "Group name is required."})

             chat = Chat.objects.create(chat_type=chat_type, name=name, created_by=user)

             # Формируем финальный список участников (включая создателя)
             participant_ids = set(filter(None, participant_ids_input)) # Очищаем от null/0
             participant_ids.add(user.id) # Добавляем создателя

             # Получаем реальные объекты User (проверка на существование уже была в validate)
             participants_to_add = User.objects.filter(pk__in=list(participant_ids))

             # Создаем записи ChatParticipant
             chat_participants = [ChatParticipant(user=p, chat=chat) for p in participants_to_add]
             ChatParticipant.objects.bulk_create(chat_participants)
             print(f"Created new group chat {chat.id} with name '{name}' and {len(chat_participants)} participants")
             return chat
        else:
             # Сюда не должны попасть из-за validate
             raise serializers.ValidationError("Cannot create chat without 'other_user_id' or 'participant_ids'.")

    def update(self, instance, validated_data):
        # Обновляем только имя чата (если оно пришло)
        # Управление участниками - через отдельные actions во ViewSet
        instance.name = validated_data.get('name', instance.name)
        if instance.chat_type == Chat.ChatType.GROUP and not instance.name:
             raise serializers.ValidationError({"name": "Group name cannot be empty."})
        instance.save()
        return instance


# --- Сериализатор для отметки прочтения ---
class MarkReadSerializer(serializers.Serializer):
    """
    Сериализатор для пометки сообщений прочитанными до определенного момента.
    Не принимает входных данных, вся логика в методе save.
    """
    # read_until_timestamp не используется, т.к. всегда отмечаем до последнего сообщения

    def save(self, **kwargs):
        """
        Обновляет last_read_message для текущего пользователя в данном чате.
        """
        chat = self.context['chat']
        user = self.context['request'].user
        participant_info = None # Инициализируем None на случай ошибки

        # Лог начала операции
        logger.debug(f"MarkRead Save: Chat={chat.id}, User={user.id}. Finding last message...")

        # Находим последнее сообщение в чате
        last_message = Message.objects.filter(chat=chat).order_by('-timestamp').first()

        if not last_message:
            logger.info(f"MarkRead Save: No messages found in chat {chat.id}. No update needed for user {user.id}.")
            # Пытаемся вернуть существующего участника, если он есть, или None
            return ChatParticipant.objects.filter(chat=chat, user=user).first()

        logger.debug(f"MarkRead Save: Found last_message {last_message.id} (ts: {last_message.timestamp}) for chat {chat.id}, user {user.id}.")

        try:
            # Пытаемся обновить или создать запись участника, устанавливая last_read_message
            # Используем filter().first() чтобы избежать DoesNotExist и проверить текущее значение
            current_participant = ChatParticipant.objects.filter(user=user, chat=chat).select_related('last_read_message').first()

            # Проверяем, нужно ли обновление (если сообщение уже прочитано или новее)
            if current_participant and current_participant.last_read_message_id == last_message.id:
                 logger.info(f"MarkRead Save: Chat {chat.id} already marked as read up to message {last_message.id} for user {user.id}. No update performed.")
                 return current_participant # Возвращаем без изменений

            # Используем update_or_create для атомарности и создания, если записи нет
            participant_info, created = ChatParticipant.objects.update_or_create(
                user=user,
                chat=chat,
                defaults={'last_read_message': last_message} # Устанавливаем последнее сообщение
            )

            # Логируем результат update_or_create
            if created:
                logger.warning(f"MarkRead Save: CREATED ChatParticipant for user {user.id} in chat {chat.id} (should normally exist). Set last_read_message_id: {participant_info.last_read_message_id}")
            else:
                # Достаем обновленную запись для логгирования (update_or_create не всегда ее возвращает с обновленными полями из defaults)
                # participant_info.refresh_from_db() # Не нужно, если мы не используем ее дальше
                logger.info(f"MarkRead Save: UPDATED ChatParticipant for user {user.id} in chat {chat.id}. Set last_read_message_id: {last_message.id}") # Логируем ID установленного сообщения

            return participant_info # Возвращаем обновленного/созданного участника

        except Exception as e:
             # Логируем ошибку, убрав participant_info.id, т.к. он может быть не определен
             logger.error(f"MarkRead Save: Error during update_or_create for chat {chat.id}, user {user.id}: {e}", exc_info=True)
             raise # Пробрасываем ошибку дальше, чтобы ViewSet вернул 500/400