from datetime import timedelta
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.validators import EmailValidator
from django.utils import timezone
from django.conf import settings
from django.utils.translation import gettext_lazy as _
import uuid
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile

from edu_core.models import StudentGroup # Предполагается, что эта модель существует
from .models import User, Profile, InvitationCode
# from .utils import send_confirmation_email # Импорт будет произведен по месту использования


# Класс ProfileSerializer отвечает за сериализацию и десериализацию данных модели Profile.
# Он преобразует экземпляры модели Profile в JSON-представление и обратно,
# позволяя передавать данные профиля через API.
# Включает поля: 'avatar', 'phone_number', 'bio', 'date_of_birth'.
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('avatar', 'phone_number', 'bio', 'date_of_birth')


# Сериализатор для краткой информации о курируемой группе
# Этот сериализатор используется для поля curated_groups_info
class CuratedGroupInfoSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)
    student_count = serializers.IntegerField(source='students.count', read_only=True) # Количество студентов в группе

    class Meta:
        model = StudentGroup if StudentGroup else object 
        fields = ('id', 'name', 'academic_year_name', 'student_count')
        read_only_fields = fields



# Класс UserSerializer предназначен для сериализации и десериализации данных модели User.
# Он обрабатывает основные поля пользователя, а также включает вложенный ProfileSerializer
# для данных профиля (только для чтения). Дополнительно, он предоставляет write-only поля
# для аватара и других данных профиля, которые обрабатываются в методах create и update
# для создания или обновления связанного объекта Profile.
# Содержит методы для получения списка групп студента (get_student_groups) и проверки,
# является ли пользователь куратором (get_is_curator_of_any_group).
# Метод create создает нового пользователя и его профиль, обрабатывая пароль и данные профиля.
# Метод update обновляет данные пользователя и его профиля, включая управление аватаром (загрузка, удаление).
class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    avatar = serializers.ImageField(required=False, allow_null=True, write_only=True)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20, write_only=True)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True, write_only=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True, write_only=True)
    clear_avatar = serializers.BooleanField(required=False, write_only=True, default=False)

    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    student_groups = serializers.SerializerMethodField(read_only=True)
    is_curator_of_any_group = serializers.SerializerMethodField(read_only=True)
    curated_groups_info = serializers.SerializerMethodField(read_only=True) # Поле объявлено здесь

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'patronymic',
            'role', 'profile', 
            'student_groups',
            'is_active', 'is_role_confirmed', 'date_joined',
            'is_staff', 'is_superuser',
            'parents', 'children',
            'is_curator_of_any_group',
            'curated_groups_info',     # <--- ДОБАВЛЕНО СЮДА (было в предыдущем ответе, но проверьте)
            # Поля для записи, если UserSerializer используется и для обновления профиля
            'avatar', 'phone_number', 'bio', 'date_of_birth', 'clear_avatar',
            'password' 
        )
        read_only_fields = (
            'id', 'email', 'role', 'profile', 'date_joined', 'is_staff', 'is_superuser',
            'parents', 'children', 'student_groups', 
            'is_curator_of_any_group', 
            'curated_groups_info',     # <--- И СЮДА (было в предыдущем ответе, но проверьте)
            'is_active', 'is_role_confirmed'
        )

    # Метод для получения и сериализации списка учебных групп, в которых состоит студент.
    # Использует локально определенный UserStudentGroupInfoSerializer для вывода только необходимых полей группы.
    def get_student_groups(self, obj):
        if hasattr(obj, 'is_student') and obj.is_student:
            # --- ИМПОРТИРУЕМ ЗДЕСЬ ---
            try:
                from edu_core.serializers import StudentGroupSerializer as BaseStudentGroupSerializer
                # Можно определить UserStudentGroupInfoSerializer прямо здесь или тоже импортировать
                class UserStudentGroupInfoSerializer(BaseStudentGroupSerializer):
                    class Meta(BaseStudentGroupSerializer.Meta):
                        model = BaseStudentGroupSerializer.Meta.model
                        fields = ('id', 'name', 'academic_year_name')
                        read_only_fields = fields
                
                groups = obj.student_group_memberships.select_related('academic_year').all()
                return UserStudentGroupInfoSerializer(groups, many=True, context=self.context).data
            except ImportError:
                pass
        return []

    # Метод для определения, является ли пользователь (преподаватель) куратором
    # хотя бы одной активной группы в текущем или будущем учебном году.
    def get_is_curator_of_any_group(self, obj: User) -> bool:
        if StudentGroup is None:
            return False
            
        if obj.is_teacher:
            current_date = timezone.now().date()
            return StudentGroup.objects.filter(
                curator=obj,
                academic_year__end_date__gte=current_date 
            ).exists()
        return False

    def get_curated_groups_info(self, obj: User) -> list:
        if StudentGroup is None or CuratedGroupInfoSerializer.Meta.model is object:
            return []

        if obj.is_teacher:
            current_date = timezone.now().date()
            # Запрос курируемых групп для текущего или будущих учебных годов
            curated_groups = StudentGroup.objects.filter(
                curator=obj,
                academic_year__end_date__gte=current_date # Группы в активных/будущих учебных годах
                # academic_year__is_current=True # Если хотите только группы текущего года
            ).select_related('academic_year').prefetch_related('students').order_by('academic_year__start_date', 'name')
            
            # Используем CuratedGroupInfoSerializer для формирования ответа
            return CuratedGroupInfoSerializer(curated_groups, many=True, context=self.context).data
        return []

    # Метод для создания нового пользователя и его профиля.
    # Извлекает данные для профиля и пароль из validated_data.
    # Использует User.objects.create_user для создания пользователя, что обеспечивает правильную обработку пароля.
    # Создает или обновляет связанный объект Profile.
    def create(self, validated_data):
        profile_data = {}
        profile_field_names = ['avatar', 'phone_number', 'bio', 'date_of_birth']
        for field_name in profile_field_names:
            if field_name in validated_data:
                profile_data[field_name] = validated_data.pop(field_name)

        validated_data.pop('clear_avatar', None)
        password = validated_data.pop('password', None)

        try:
            user = User.objects.create_user(**validated_data)
            if password:
                user.set_password(password)
                user.save(update_fields=['password'])
        except TypeError as e:
            raise serializers.ValidationError(f"Invalid data for user creation: {e}")

        if profile_data:
            profile_instance, created = Profile.objects.get_or_create(user=user)
            for attr, value in profile_data.items():
                setattr(profile_instance, attr, value)
            profile_instance.save()
        
        return user
    
    # Метод для обновления данных существующего пользователя и его профиля.
    # Обрабатывает загрузку нового аватара, удаление существующего аватара (по флагу clear_avatar
    # или передаче null/пустого значения для поля avatar).
    # Обновляет остальные поля профиля и поля самого пользователя.
    def update(self, instance: User, validated_data: dict):
        profile_instance, _ = Profile.objects.get_or_create(user=instance)
        profile_needs_save = False
        profile_updated_fields = []

        clear_avatar_flag = validated_data.pop('clear_avatar', False)
        new_avatar_file = validated_data.pop('avatar', 'NOT_PRESENT')

        should_delete_old = False
        if clear_avatar_flag:
            should_delete_old = True
        elif new_avatar_file != 'NOT_PRESENT':
             if new_avatar_file is None or new_avatar_file == '':
                  should_delete_old = True
             elif isinstance(new_avatar_file, (InMemoryUploadedFile, TemporaryUploadedFile)):
                  if profile_instance.avatar and profile_instance.avatar.name:
                      profile_instance.avatar.delete(save=False)
                  profile_instance.avatar = new_avatar_file
                  profile_updated_fields.append('avatar')
                  profile_needs_save = True
        
        if should_delete_old and 'avatar' not in profile_updated_fields:
             if profile_instance.avatar and profile_instance.avatar.name:
                  profile_instance.avatar.delete(save=False)
                  profile_instance.avatar = None
                  profile_updated_fields.append('avatar')
                  profile_needs_save = True

        profile_fields_to_check = ['phone_number', 'bio', 'date_of_birth']
        for key in profile_fields_to_check:
            if key in validated_data:
                value = validated_data.pop(key)
                current_value = getattr(profile_instance, key, None)
                if current_value != value:
                    setattr(profile_instance, key, value)
                    profile_updated_fields.append(key)
                    profile_needs_save = True

        if profile_needs_save:
            profile_updated_fields = list(set(profile_updated_fields))
            profile_instance.save(update_fields=profile_updated_fields)

        instance = super().update(instance, validated_data)

        return instance


# Класс AdminUserUpdateSerializer предназначен для обновления данных пользователя администратором.
# Позволяет администратору изменять основные атрибуты пользователя, такие как имя, фамилия,
# отчество, статус активности (is_active), подтверждение роли (is_role_confirmed) и саму роль (role).
# Также включает поля 'parent_ids' и 'children_ids' (write-only) для управления M2M связями
# "родитель-студент". Поле 'parent_ids' позволяет назначать родителей студенту, а 'children_ids'
# (хотя и присутствует) не реализует логику обновления детей в текущей версии метода update,
# так как эта логика сложнее и обычно обрабатывается со стороны родительского объекта.
# Метод validate содержит проверки, специфичные для назначения ролей и связей (например,
# родители могут быть назначены только студентам, ограничение на количество родителей).
# Метод update обновляет поля пользователя и M2M связь 'parents'.
class AdminUserUpdateSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(required=False, max_length=150)
    last_name = serializers.CharField(required=False, max_length=150)
    patronymic = serializers.CharField(required=False, allow_blank=True, max_length=150, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    is_role_confirmed = serializers.BooleanField(required=False)
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)

    parent_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.PARENT),
        source='parents',
        many=True,
        required=False,
        write_only=True,
        help_text="List of Parent IDs to assign to this student (max 2)."
    )
    children_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT),
        source='children',
        many=True,
        required=False,
        write_only=True,
        help_text="List of Student IDs to assign to this parent."
    )

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'patronymic',
            'is_active', 'is_role_confirmed', 'role',
            'parent_ids',
            'children_ids',
        ]
        
    # Метод валидации данных перед обновлением.
    # Проверяет корректность назначения родителей/детей в зависимости от роли пользователя,
    # запрещает одновременное указание родителей и детей, ограничивает количество родителей.
    def validate(self, attrs):
        instance: User | None = getattr(self, 'instance', None)
        role_to_check = attrs.get('role', instance.role if instance else None)

        if 'parent_ids' in attrs and role_to_check != User.Role.STUDENT:
            raise serializers.ValidationError({"parent_ids": "Only users with the STUDENT role can have parents assigned."})
        if 'children_ids' in attrs and role_to_check != User.Role.PARENT:
            raise serializers.ValidationError({"children_ids": "Only users with the PARENT role can have children assigned."})

        if 'parent_ids' in attrs and 'children_ids' in attrs:
             raise serializers.ValidationError("Cannot assign both parents and children in the same request.")

        if 'parent_ids' in attrs and len(attrs.get('parent_ids', [])) > 2:
            raise serializers.ValidationError({"parent_ids": "A student can have a maximum of 2 parents."})

        return attrs

    # Метод для обновления данных пользователя администратором.
    # Обновляет основные поля пользователя и M2M связь 'parents' (для назначения родителей студенту).
    # Логика обновления 'children' (назначение детей родителю) в данном методе не реализована.
    def update(self, instance: User, validated_data: dict):
        parents_data = validated_data.pop('parents', None)
        # children_data = validated_data.pop('children', None) # Логика для children не реализуется здесь

        instance = super().update(instance, validated_data)

        if parents_data is not None:
            instance.parents.set(parents_data)
        
        # Логика для children_data не добавляется, как в оригинальном коде.
        return instance

# Класс UserRegistrationSerializer используется для регистрации новых пользователей.
# Он требует указания email, пароля (с подтверждением), имени, фамилии и роли.
# Отчество и код приглашения (invite_code) являются опциональными.
# Метод validate_email проверяет уникальность email.
# Метод validate_role проверяет допустимость указанной роли.
# Общий метод validate сравнивает пароли и обрабатывает код приглашения: если код действителен
# и соответствует заявленной роли, пользователь будет активирован и его роль подтверждена
# автоматически; в противном случае, на email будет отправлено письмо для подтверждения.
# Метод create создает пользователя, обрабатывает код приглашения (если был использован)
# и отправляет email-подтверждение, если пользователь не был активирован по инвайт-коду.
# Метод to_representation добавляет флаг used_invitation_code в ответ.
class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True, label="Confirm password")
    invite_code = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    # Флаг, показывающий, был ли использован инвайт-код при регистрации.
    used_invitation_code = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = User
        fields = ('email', 'password', 'password2', 'first_name', 'last_name', 'patronymic', 'role', 'invite_code', 'used_invitation_code')
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'role': {'required': True},
        }
        read_only_fields = ('used_invitation_code',)

    # Валидация поля email на уникальность.
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")
        return value

    # Валидация поля role на соответствие допустимым значениям.
    def validate_role(self, value):
        if value not in User.Role.values:
            raise serializers.ValidationError("Недопустимая роль пользователя.")
        return value

    # Общая валидация данных регистрации.
    # Проверяет совпадение паролей и обрабатывает код приглашения.
    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password2": "Пароли не совпадают."})

        invite_code_str = attrs.get('invite_code')
        self.used_invitation_code_flag = False 
        if invite_code_str:
            try:
                invitation = InvitationCode.objects.get(code=invite_code_str)
                if not invitation.is_valid():
                    raise serializers.ValidationError({"invite_code": "Недействительный или уже использованный код приглашения."})
                if invitation.role != attrs.get('role'):
                     raise serializers.ValidationError({"role": f"Код приглашения предназначен для роли '{invitation.get_role_display()}', а не для '{dict(User.Role.choices).get(attrs.get('role'))}'."})
                attrs['invitation_instance'] = invitation
                self.used_invitation_code_flag = True
            except InvitationCode.DoesNotExist:
                raise serializers.ValidationError({"invite_code": "Код приглашения не найден."})

        attrs.pop('password2')
        attrs.pop('invite_code', None)
        return attrs

    # Метод создания нового пользователя.
    # Активирует пользователя и подтверждает его роль, если был использован действительный код приглашения.
    # В противном случае, отправляет email для подтверждения.
    def create(self, validated_data):
        from .utils import send_confirmation_email # Локальный импорт

        invitation = validated_data.pop('invitation_instance', None)
        user_is_active_due_to_invite = self.used_invitation_code_flag

        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            patronymic=validated_data.get('patronymic', ''),
            role=validated_data['role'],
            is_active=user_is_active_due_to_invite,
            is_role_confirmed=user_is_active_due_to_invite
        )
        
        if invitation:
            invitation.used_by = user
            invitation.save()

        user.used_invitation_code_on_registration = self.used_invitation_code_flag

        if not user_is_active_due_to_invite:
            send_confirmation_email(user)

        return user

    # Модификация представления пользователя при ответе API.
    # Добавляет флаг used_invitation_code и удаляет write-only поля.
    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['used_invitation_code'] = getattr(instance, 'used_invitation_code_on_registration', False)
        
        representation.pop('password', None)
        representation.pop('password2', None)
        representation.pop('invite_code', None)
        return representation


# Класс ChangePasswordSerializer предназначен для смены пароля аутентифицированным пользователем.
# Требует указания старого пароля и нового пароля (с подтверждением).
# Метод validate_old_password проверяет корректность старого пароля.
# Общий метод validate проверяет совпадение новых паролей.
# Метод save устанавливает новый пароль для пользователя.
class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    new_password2 = serializers.CharField(required=True, write_only=True)

    # Валидация старого пароля.
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Старый пароль неверен.")
        return value

    # Валидация на совпадение новых паролей.
    def validate(self, data):
        if data['new_password'] != data['new_password2']:
            raise serializers.ValidationError({"new_password2": "Новые пароли не совпадают."})
        return data

    # Сохранение нового пароля пользователя.
    def save(self, **kwargs):
        password = self.validated_data['new_password']
        user = self.context['request'].user
        user.set_password(password)
        user.save()
        return user

# Класс InvitationCodeSerializer отвечает за сериализацию и десериализацию данных модели InvitationCode.
# Он отображает информацию о коде приглашения, включая email создателя и использовавшего пользователя.
# Поля code, created_by, used_by и др. являются read-only при отображении.
# Метод create устанавливает текущего пользователя (из запроса) как создателя кода
# и генерирует уникальный код, если он не был передан.
class InvitationCodeSerializer(serializers.ModelSerializer):
    # Отображение email пользователя, создавшего код.
    created_by_email = serializers.EmailField(source='created_by.email', read_only=True)
    # Отображение email пользователя, использовавшего код (может быть null).
    used_by_email = serializers.EmailField(source='used_by.email', read_only=True, allow_null=True)

    class Meta:
        model = InvitationCode
        fields = ('id', 'code', 'role', 'created_by', 'created_by_email', 'used_by', 'used_by_email', 'created_at', 'expires_at', 'is_valid')
        read_only_fields = ('id', 'code', 'created_by', 'created_by_email', 'used_by', 'used_by_email', 'created_at', 'is_valid')

    # Метод для создания нового кода приглашения.
    # Автоматически устанавливает создателя кода и генерирует код.
    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        if 'code' not in validated_data:
             validated_data['code'] = uuid.uuid4()
        return super().create(validated_data)
    
# Класс PasswordResetRequestSerializer используется для запроса сброса пароля.
# Принимает email пользователя.
# Метод validate_email проверяет, существует ли активный пользователь с указанным email.
# В целях безопасности, не сообщает явно, найден ли email или нет.
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    # Валидация email для запроса сброса пароля.
    def validate_email(self, value):
        if not User.objects.filter(email=value, is_active=True).exists():
            raise serializers.ValidationError(_("Если пользователь с таким email существует, ему будет отправлена инструкция."))
        return value
    
# Класс PasswordResetConfirmSerializer используется для подтверждения сброса пароля.
# Принимает новый пароль (с подтверждением) и токен сброса пароля.
# Метод validate_token проверяет валидность токена и срок его действия,
# а также сохраняет найденного пользователя в контексте для последующего использования в методе save.
# Общий метод validate проверяет совпадение новых паролей.
# Метод save устанавливает новый пароль для пользователя и очищает данные токена сброса.
class PasswordResetConfirmSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    new_password2 = serializers.CharField(write_only=True, required=True)
    token = serializers.CharField(write_only=True, required=True)

    # Валидация токена сброса пароля.
    def validate_token(self, value):
        try:
            user = User.objects.get(password_reset_token=value, is_active=True)
            if user.password_reset_token_expires_at and user.password_reset_token_expires_at < timezone.now():
                raise serializers.ValidationError(_("Срок действия токена сброса пароля истек."))
            self.context['user_instance'] = user
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError(_("Недействительный токен сброса пароля."))

    # Валидация на совпадение новых паролей.
    def validate(self, data):
        if data['new_password'] != data['new_password2']:
            raise serializers.ValidationError({"new_password2": _("Пароли не совпадают.")})
        return data

    # Установка нового пароля и очистка токена сброса.
    def save(self):
        user = self.context['user_instance']
        user.set_password(self.validated_data['new_password'])
        user.password_reset_token = None
        user.password_reset_token_expires_at = None
        user.save(update_fields=['password', 'password_reset_token', 'password_reset_token_expires_at', 'last_login'])
        return user