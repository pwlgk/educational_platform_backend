from rest_framework import serializers
from django.shortcuts import get_object_or_404
from .models import Chat, ChatParticipant, Message
from users.serializers import UserSerializer # Для информации об участниках/отправителе
from users.models import User # Для валидации

class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    # Добавляем URL файла, если он есть
    file_url = serializers.FileField(source='file', read_only=True)

    class Meta:
        model = Message
        fields = ('id', 'chat', 'sender', 'content', 'file', 'file_url', 'timestamp')
        read_only_fields = ('sender', 'timestamp', 'file_url')
        extra_kwargs = {
            'chat': {'write_only': True}, # ID чата при создании
            'file': {'write_only': True, 'required': False}, # Файл опционален
            'content': {'required': False}, # Текст опционален
        }

    def validate(self, data):
        # Проверка, что есть либо текст, либо файл
        if not data.get('content') and not data.get('file'):
            raise serializers.ValidationError(_('Сообщение должно содержать текст или прикрепленный файл.'))
        return data

class ChatParticipantSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = ChatParticipant
        fields = ('id', 'user', 'joined_at') # Не показываем last_read_message здесь

class ChatSerializer(serializers.ModelSerializer):
    # Используем SerializerMethodField для гибкого отображения участников и названия
    participants_details = serializers.SerializerMethodField(read_only=True)
    last_message_details = MessageSerializer(source='last_message', read_only=True, allow_null=True)
    # Поле для подсчета непрочитанных сообщений
    unread_count = serializers.SerializerMethodField(read_only=True)
    # Поле для отображения названия (особенно для личных чатов)
    display_name = serializers.SerializerMethodField(read_only=True)

    # Поля для записи (создание чата)
    # ID другого пользователя для создания личного чата
    other_user_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    # Список ID пользователей для создания группового чата
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Chat
        fields = (
            'id', 'chat_type', 'name', 'created_at',
            'participants_details', # Детали участников
            'last_message_details', # Детали последнего сообщения
            'unread_count',         # Кол-во непрочитанных
            'display_name',         # Отображаемое имя чата
            # Поля для записи
            'other_user_id', 'participant_ids'
        )
        read_only_fields = ('created_at', 'participants_details', 'last_message_details', 'unread_count', 'display_name')
        extra_kwargs = {
            'name': {'required': False}, # Имя не обязательно при создании личного чата
            'chat_type': {'read_only': True}, # Тип определяется при создании
        }

    def get_participants_details(self, obj):
        # Получаем участников чата
        participants = obj.participants.all()
        # Сериализуем пользователей
        return UserSerializer(participants, many=True, context=self.context).data

    def get_unread_count(self, obj):
        user = self.context.get('request').user
        if user and user.is_authenticated:
            try:
                participant_info = ChatParticipant.objects.get(chat=obj, user=user)
                last_read = participant_info.last_read_message
                if last_read:
                    # Считаем сообщения новее, чем последнее прочитанное
                    return obj.messages.filter(timestamp__gt=last_read.timestamp).count()
                else:
                    # Если ничего не прочитано, считаем все сообщения
                    return obj.messages.count()
            except ChatParticipant.DoesNotExist:
                return 0 # Пользователь не участник? Странно, но обработаем.
        return 0

    def get_display_name(self, obj):
        """Формирует имя для отображения в списке чатов."""
        user = self.context.get('request').user
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.name or f"Группа {obj.id}"
        else:
            # Для личного чата находим другого участника
            other_participant = obj.get_other_participant(user)
            if other_participant:
                return other_participant.get_full_name()
            return f"Личный чат {obj.id}" # Запасной вариант

    def validate(self, data):
        other_user_id = data.get('other_user_id')
        participant_ids = data.get('participant_ids')
        name = data.get('name')

        if other_user_id and participant_ids:
            raise serializers.ValidationError("Укажите либо 'other_user_id' для личного чата, либо 'participant_ids' для группового.")
        if not other_user_id and not participant_ids:
            raise serializers.ValidationError("Необходимо указать 'other_user_id' или 'participant_ids'.")

        if participant_ids: # Создание группового чата
            if not name:
                 raise serializers.ValidationError({"name": "Название обязательно для группового чата."})
            if len(participant_ids) < 1: # Хотя бы один участник кроме себя
                 raise serializers.ValidationError({"participant_ids": "В групповом чате должен быть хотя бы один участник кроме вас."})
            # Проверка существования пользователей
            if not User.objects.filter(id__in=participant_ids).count() == len(set(participant_ids)):
                 raise serializers.ValidationError({"participant_ids": "Один или несколько ID участников недействительны."})
            data['chat_type'] = Chat.ChatType.GROUP

        if other_user_id: # Создание личного чата
            user = self.context['request'].user
            if other_user_id == user.id:
                 raise serializers.ValidationError({"other_user_id": "Нельзя создать чат с самим собой."})
            try:
                User.objects.get(pk=other_user_id)
            except User.DoesNotExist:
                raise serializers.ValidationError({"other_user_id": "Пользователь с указанным ID не найден."})
            # Проверка, существует ли уже личный чат между этими пользователями
            # Это сложный запрос, можно вынести в .create() или менеджер модели
            existing_chat = Chat.objects.filter(
                chat_type=Chat.ChatType.PRIVATE,
                participants=user
            ).filter(participants=other_user_id)
            if existing_chat.exists():
                 # Вместо ошибки, можно вернуть существующий чат в .create()
                 # raise serializers.ValidationError("Личный чат с этим пользователем уже существует.")
                 pass # Обработаем в create
            data['chat_type'] = Chat.ChatType.PRIVATE

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        chat_type = validated_data['chat_type']
        other_user_id = validated_data.get('other_user_id')
        participant_ids = validated_data.get('participant_ids')
        name = validated_data.get('name')

        if chat_type == Chat.ChatType.PRIVATE:
            # Повторная проверка существующего чата
            other_user = User.objects.get(pk=other_user_id)
            existing_chat = Chat.objects.filter(
                chat_type=Chat.ChatType.PRIVATE,
                participants=user
            ).filter(participants=other_user).first() # Используем .first()
            if existing_chat:
                return existing_chat # Возвращаем существующий чат

            # Создаем новый личный чат
            chat = Chat.objects.create(chat_type=chat_type, created_by=user)
            ChatParticipant.objects.create(user=user, chat=chat)
            ChatParticipant.objects.create(user=other_user, chat=chat)
            return chat

        elif chat_type == Chat.ChatType.GROUP:
            # Создаем групповой чат
            chat = Chat.objects.create(chat_type=chat_type, name=name, created_by=user)
            # Добавляем создателя и указанных участников
            participants_to_add = [user] + list(User.objects.filter(id__in=participant_ids))
            chat_participants = [ChatParticipant(user=p, chat=chat) for p in set(participants_to_add)] # Уникальные участники
            ChatParticipant.objects.bulk_create(chat_participants)
            return chat

        # На всякий случай
        raise serializers.ValidationError("Не удалось определить тип создаваемого чата.")


class MarkReadSerializer(serializers.Serializer):
    """Сериализатор для пометки сообщений прочитанными."""
    # ID последнего сообщения, которое пользователь увидел
    last_message_id = serializers.IntegerField(required=True)

    def validate_last_message_id(self, value):
        # Проверяем, что сообщение с таким ID существует
        try:
            message = Message.objects.get(pk=value)
            # Сохраняем объект сообщения для использования в save
            self.context['message_instance'] = message
            return value
        except Message.DoesNotExist:
            raise serializers.ValidationError("Сообщение с указанным ID не найдено.")

    def save(self, chat_id):
        user = self.context['request'].user
        message = self.context['message_instance']

        # Убедимся, что сообщение принадлежит указанному чату
        if message.chat_id != chat_id:
             raise serializers.ValidationError("Указанное сообщение не принадлежит данному чату.")

        # Обновляем last_read_message для участника
        updated_count = ChatParticipant.objects.filter(user=user, chat_id=chat_id).update(last_read_message=message)

        if updated_count == 0:
             raise serializers.ValidationError("Вы не являетесь участником этого чата или чат не найден.")
        return message # Возвращаем сообщение, до которого прочитали