# users/serializers.py
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.validators import EmailValidator
from django.utils import timezone
from .models import User, Profile, InvitationCode
import uuid

import logging
from rest_framework import serializers
from .models import User, Profile
# Убедитесь, что FileField импортирован, если используете isinstance
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile

logger = logging.getLogger(__name__)

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('avatar', 'phone_number', 'bio', 'date_of_birth')

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20, write_only=True)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True, write_only=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True, write_only=True)
    clear_avatar = serializers.BooleanField(required=False, write_only=True, default=False)

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'patronymic',
            'role', 'profile', # profile будет содержать данные из ProfileSerializer для чтения
            'is_active', 'is_role_confirmed', 'date_joined',
            'is_staff',         # <-- ДОБАВЛЕНО для информации
            'is_superuser',     # <-- ДОБАВЛЕНО для информации
            'parents',          # <-- ДОБАВЛЕНО для чтения
            'children',         # <-- ДОБАВЛЕНО для чтения

            # Поля для записи профиля (write_only)
            'avatar',
            'phone_number',
            'bio',
            'date_of_birth',
            'clear_avatar'
        )
        read_only_fields = (
            'id', 'email', 'role', 'profile', # 'profile' как объект для чтения
            'is_active', 'is_role_confirmed', 'date_joined',
            'is_staff', 'is_superuser',
            'parents', 'children'
        )

    def update(self, instance: User, validated_data: dict):
        logger.debug(f"--- [SERIALIZER DEBUG] UserSerializer.update v8 ENTER ---")
        logger.debug(f"[SERIALIZER DEBUG] Validated data: {validated_data}")
 
        profile_instance, _ = Profile.objects.get_or_create(user=instance)
        profile_needs_save = False
        profile_updated_fields = []

        # --- Обработка аватара ---
        clear_avatar_flag = validated_data.pop('clear_avatar', False)
        new_avatar_file = validated_data.pop('avatar', 'NOT_PRESENT')
        logger.debug(f"[SERIALIZER DEBUG] clear_avatar: {clear_avatar_flag}, new_avatar_file type: {type(new_avatar_file)}")

        # Определяем, нужно ли удалять старый аватар
        should_delete_old = False
        if clear_avatar_flag:
            should_delete_old = True
            logger.debug("[SERIALIZER DEBUG] Avatar deletion requested via flag.")
        elif new_avatar_file != 'NOT_PRESENT': # Если пришел новый файл или null/None
             if new_avatar_file is None or new_avatar_file == '': # Сигнал на удаление
                  should_delete_old = True
                  logger.debug("[SERIALIZER DEBUG] Avatar deletion requested via null/empty value.")
             elif isinstance(new_avatar_file, (InMemoryUploadedFile, TemporaryUploadedFile)): # Пришел новый файл
                  # Удаляем старый ПЕРЕД присвоением нового
                  if profile_instance.avatar and profile_instance.avatar.name:
                      logger.debug(f"[SERIALIZER DEBUG] Deleting old avatar '{profile_instance.avatar.name}' before assigning new.")
                      profile_instance.avatar.delete(save=False)
                      # profile_needs_save не ставим здесь, т.к. ниже будет присвоение и сохранение
                  logger.debug(f"[SERIALIZER DEBUG] Assigning new avatar file: {new_avatar_file.name}")
                  profile_instance.avatar = new_avatar_file # Присваиваем новый файл
                  profile_updated_fields.append('avatar')
                  profile_needs_save = True
        # Если new_avatar_file == 'NOT_PRESENT', ничего с аватаром не делаем

        # Если нужно удалить (и еще не удалили выше при замене)
        if should_delete_old and 'avatar' not in profile_updated_fields:
             if profile_instance.avatar and profile_instance.avatar.name:
                  logger.debug(f"[SERIALIZER DEBUG] Deleting avatar based on flag/null value.")
                  profile_instance.avatar.delete(save=False)
                  profile_instance.avatar = None # Ставим None в модели
                  profile_updated_fields.append('avatar')
                  profile_needs_save = True
             else:
                 logger.debug("[SERIALIZER DEBUG] Deletion requested, but no avatar to delete.")


        # --- Обновление других полей профиля ---
        profile_fields_to_check = ['phone_number', 'bio', 'date_of_birth']
        for key in profile_fields_to_check:
            if key in validated_data:
                value = validated_data.pop(key)
                current_value = getattr(profile_instance, key, None)
                if current_value != value:
                    setattr(profile_instance, key, value)
                    profile_updated_fields.append(key)
                    profile_needs_save = True

        # Сохраняем профиль, если были изменения
        if profile_needs_save:
            profile_updated_fields = list(set(profile_updated_fields))
            logger.debug(f"[SERIALIZER DEBUG] Saving profile instance with fields: {profile_updated_fields}")
            profile_instance.save(update_fields=profile_updated_fields)

        # --- Обновление полей User ---
        logger.debug(f"[SERIALIZER DEBUG] Remaining data for User update: {validated_data}")
        instance = super().update(instance, validated_data) # Используем super для полей User
        logger.debug(f"[SERIALIZER DEBUG] User instance updated.")

        logger.debug(f"--- [SERIALIZER DEBUG] UserSerializer.update v8 EXIT ---")
        return instance


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    # Явно указываем поля, которые админ может менять
    # required=False делает их опциональными для PATCH
    first_name = serializers.CharField(required=False, max_length=150)
    last_name = serializers.CharField(required=False, max_length=150)
    patronymic = serializers.CharField(required=False, allow_blank=True, max_length=150, allow_null=True) # Allow null
    is_active = serializers.BooleanField(required=False)
    is_role_confirmed = serializers.BooleanField(required=False)
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)

    # Поля для управления связями Родитель <-> Студент
    # Принимаем список ID родителей для студента
    parent_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.PARENT), # Источник данных - только родители
        source='parents', # Связываем с полем 'parents' модели User
        many=True,        # Ожидаем список
        required=False,   # Поле не обязательно при обновлении
        write_only=True,  # Только для записи через API
        help_text="List of Parent IDs to assign to this student (max 2)."
    )
    # Принимаем список ID детей для родителя
    children_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT), # Источник данных - только студенты
        source='children', # Связываем с полем 'children' (related_name от 'parents')
        many=True,
        required=False,
        write_only=True,
        help_text="List of Student IDs to assign to this parent."
    )

    class Meta:
        model = User
        # Указываем все поля, которые может ОБНОВИТЬ админ через PATCH
        fields = [
            'first_name', 'last_name', 'patronymic',
            'is_active', 'is_role_confirmed', 'role',
            'parent_ids',   # Добавлено
            'children_ids', # Добавлено
        ]
        # Важно: не включаем 'email', 'password', 'id' и т.д.
        # read_only_fields не нужны, т.к. мы явно перечислили поля в fields

    def validate(self, attrs):
        # Получаем текущий экземпляр пользователя (если это обновление)
        instance: User | None = getattr(self, 'instance', None)

        # Определяем роль: либо новая из запроса, либо текущая у пользователя
        role_to_check = attrs.get('role', instance.role if instance else None)

        # Проверка 1: Можно ли назначать родителей/детей для ДАННОЙ роли?
        if 'parent_ids' in attrs and role_to_check != User.Role.STUDENT:
            raise serializers.ValidationError({"parent_ids": "Only users with the STUDENT role can have parents assigned."})
        if 'children_ids' in attrs and role_to_check != User.Role.PARENT:
            raise serializers.ValidationError({"children_ids": "Only users with the PARENT role can have children assigned."})

        # Проверка 2: Нельзя указывать и родителей, и детей одновременно
        # (Хотя технически возможно, если пользователь сменит роль в этом же запросе,
        # но это усложняет логику, проще запретить).
        # Эту проверку можно убрать, если нужна смена роли и связей одновременно.
        if 'parent_ids' in attrs and 'children_ids' in attrs:
             raise serializers.ValidationError("Cannot assign both parents and children in the same request.")

        # Проверка 3: Ограничение на количество родителей
        if 'parent_ids' in attrs and len(attrs.get('parent_ids', [])) > 2:
            raise serializers.ValidationError({"parent_ids": "A student can have a maximum of 2 parents."})

        # Проверка 4: Запрет на изменение роли суперпользователя (если нужно)
        # current_request_user = self.context['request'].user
        # if instance and instance.is_superuser and 'role' in attrs and not current_request_user.is_superuser:
        #      raise serializers.ValidationError({"role": "Cannot change the role of a superuser."})

        return attrs

    def update(self, instance: User, validated_data: dict):
        # validated_data здесь содержит РАЗРЕШЕННЫЕ К ИЗМЕНЕНИЮ поля,
        # включая 'parents' и 'children' (из-за source), а не 'parent_ids'/'children_ids'

        logger.debug(f"[AdminUserUpdateSerializer] Updating user {instance.id}. Validated data: {validated_data.keys()}")

        # Отделяем M2M поля от остальных
        parents_data = validated_data.pop('parents', None)
        children_data = validated_data.pop('children', None) # Используем 'children' из related_name='children'

        # Обновляем обычные поля через super().update или вручную
        # super().update обновляет только поля, присутствующие в validated_data
        instance = super().update(instance, validated_data)
        # Или вручную для большей наглядности:
        # instance.first_name = validated_data.get('first_name', instance.first_name)
        # instance.last_name = validated_data.get('last_name', instance.last_name)
        # ... и т.д. для is_active, is_role_confirmed, role ...
        # instance.save() # Если обновляли вручную

        # Обновляем M2M связи ПОСЛЕ сохранения основных полей
        # Метод .set() ожидает список объектов или ID
        if parents_data is not None: # Если поле parent_ids было в запросе (даже пустым списком)
            instance.parents.set(parents_data)
            logger.info(f"Set parents for student {instance.id} to {[p.id for p in parents_data]}")

        if children_data is not None: # Если поле children_ids было в запросе
             # Важно: нужно обновить children_set у РОДИТЕЛЯ, а не у ребенка
             # Эта логика должна быть в сериализаторе/view для РОДИТЕЛЯ,
             # а не здесь, где мы редактируем пользователя в общем.
             # Оставляем ТОЛЬКО обновление родителей студента.
             # Если нужно управлять детьми родителя, нужен другой подход
             # (например, отдельный эндпоинт или принимать children_ids только если role=PARENT)

             # --- УДАЛЯЕМ ЛОГИКУ ОБНОВЛЕНИЯ ДЕТЕЙ ЗДЕСЬ ---
             # instance.children.set(children_data) # НЕПРАВИЛЬНО, 'children' это related_name
             # logger.info(f"Set children for parent {instance.id} to {[c.id for c in children_data]}")
             # --- КОНЕЦ УДАЛЕНИЯ ---
             pass # Пока ничего не делаем с children_ids в этом сериализаторе

        return instance

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True, label="Confirm password")
    # Опционально: код приглашения
    invite_code = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'password2', 'first_name', 'last_name', 'patronymic', 'role', 'invite_code')
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'role': {'required': True}, # Роль обязательна при регистрации
        }

    def validate_email(self, value):
        # Проверка на уникальность email
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")
        return value

    def validate_role(self, value):
        # Проверка, что указана допустимая роль из User.Role
        if value not in User.Role.values:
            raise serializers.ValidationError("Недопустимая роль пользователя.")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password2": "Пароли не совпадают."})

        invite_code_str = attrs.get('invite_code')
        invitation = None
        if invite_code_str:
            try:
                invitation = InvitationCode.objects.get(code=invite_code_str)
                if not invitation.is_valid():
                    raise serializers.ValidationError({"invite_code": "Недействительный или уже использованный код приглашения."})
                # Проверка соответствия роли в коде и заявленной роли
                if invitation.role != attrs.get('role'):
                     raise serializers.ValidationError({"role": f"Код приглашения предназначен для роли '{invitation.get_role_display()}', а не для '{dict(User.Role.choices).get(attrs.get('role'))}'."})
                attrs['invitation_instance'] = invitation # Передаем объект кода в create
            except InvitationCode.DoesNotExist:
                raise serializers.ValidationError({"invite_code": "Код приглашения не найден."})

        attrs.pop('password2') # Убираем password2, он больше не нужен
        attrs.pop('invite_code', None) # Убираем строку кода, передаем объект
        return attrs

    def create(self, validated_data):
        invitation = validated_data.pop('invitation_instance', None)
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            patronymic=validated_data.get('patronymic', ''),
            role=validated_data['role'],
            # Если есть код, роль подтверждена и пользователь активен сразу
            is_active=bool(invitation),
            is_role_confirmed=bool(invitation)
        )
        if invitation:
            invitation.used_by = user
            invitation.save()
            # Опционально: связать пригласившего
            # user.invited_by = invitation.created_by
            # user.save()

        # Отправка email для подтверждения (если не было кода приглашения)
        if not invitation:
            # TODO: Реализовать отправку email с confirmation_token
            # send_confirmation_email(user)
            pass

        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True, write_only=True)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Старый пароль неверен.")
        return value

    def validate(self, data):
        if data['new_password'] != data['new_password2']:
            raise serializers.ValidationError({"new_password2": "Новые пароли не совпадают."})
        return data

    def save(self, **kwargs):
        password = self.validated_data['new_password']
        user = self.context['request'].user
        user.set_password(password)
        user.save()
        return user

class InvitationCodeSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    used_by_email = serializers.EmailField(source='used_by.email', read_only=True, allow_null=True)

    class Meta:
        model = InvitationCode
        fields = ('id', 'code', 'role', 'created_by', 'created_by_email', 'used_by', 'used_by_email', 'created_at', 'expires_at', 'is_valid')
        read_only_fields = ('id', 'code', 'created_by', 'created_by_email', 'used_by', 'used_by_email', 'created_at', 'is_valid')

    def create(self, validated_data):
        # Устанавливаем создателя из запроса
        validated_data['created_by'] = self.context['request'].user
        # Генерируем код, если не передан (хотя default=uuid4 в модели)
        if 'code' not in validated_data:
             validated_data['code'] = uuid.uuid4()
        return super().create(validated_data)