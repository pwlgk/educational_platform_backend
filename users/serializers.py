from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.validators import EmailValidator
from django.utils import timezone
from .models import User, Profile, InvitationCode

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('avatar', 'phone_number', 'bio', 'date_of_birth')
        read_only_fields = ('user',) # Пользователь не меняется

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True) # Вложенный профиль для чтения

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'patronymic',
            'role', 'profile', 'is_active', 'is_role_confirmed', 'date_joined'
            # Не включаем is_staff, is_superuser, password и т.д. по умолчанию
        )
        read_only_fields = ('email', 'role', 'is_active', 'is_role_confirmed', 'date_joined') # Что нельзя менять через этот сериализатор

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