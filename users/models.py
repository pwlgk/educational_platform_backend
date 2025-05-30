import os
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import uuid

# Определяет путь для сохранения файла аватара пользователя.
# Файлы организованы в директории по ID пользователя с уникальным именем файла,
# что обеспечивает их организованное хранение и предотвращает конфликты имен.
def get_avatar_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join('avatars', f'user_{instance.user.id}', unique_filename)

# Класс CustomUserManager управляет созданием экземпляров кастомной модели User.
# Он переопределяет стандартные методы Django для создания пользователей (create_user)
# и суперпользователей (create_superuser), используя email в качестве основного
# идентификатора для аутентификации вместо username. При создании обычного пользователя
# автоматически создается связанный с ним профиль (Profile).
class CustomUserManager(BaseUserManager):
    # Создает и сохраняет пользователя с указанным email, паролем и дополнительными полями.
    # Также создает связанный объект Profile для нового пользователя.
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('The Email must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        Profile.objects.create(user=user)
        return user

    # Создает и сохраняет суперпользователя с указанным email, паролем и дополнительными полями.
    # Суперпользователю по умолчанию присваиваются права администратора, статус персонала и активность.
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', User.Role.ADMIN)
        extra_fields.setdefault('is_role_confirmed', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        return self.create_user(email, password, **extra_fields)

# Модель User представляет собой кастомную реализацию пользователя системы,
# наследуясь от AbstractBaseUser и PermissionsMixin Django. Она использует email
# как уникальный идентификатор для входа (USERNAME_FIELD).
# Модель включает поля для имени, фамилии, отчества, роли пользователя
# (студент, преподаватель, родитель, администратор), токенов для подтверждения
# email и сброса пароля, а также стандартные флаги состояния (is_active, is_staff).
# Пользователь неактивен по умолчанию до подтверждения email.
# Дополнительно, модель содержит поля для отслеживания подтверждения роли,
# информации о том, кем был приглашен пользователь, и ManyToMany-связь 'parents'
# для установления отношений "родитель-ребенок" (для пользователей с ролью Студент).
# Для управления объектами User используется CustomUserManager.
class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', _('Студент')
        TEACHER = 'TEACHER', _('Преподаватель')
        PARENT = 'PARENT', _('Родитель')
        ADMIN = 'ADMIN', _('Администратор')

    email = models.EmailField(_('email address'), unique=True)
    role = models.CharField(_('роль'), max_length=20, choices=Role.choices, default=Role.STUDENT)

    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    patronymic = models.CharField(_('patronymic'), max_length=150, blank=True)
    
    # Поля для механизма подтверждения email
    confirmation_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        null=True, blank=True,
        verbose_name=_('токен подтверждения email')
    )
    confirmation_token_expires_at = models.DateTimeField(
        _('срок действия токена подтверждения email'),
        null=True, blank=True
    )

    # Поля для механизма сброса пароля
    password_reset_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        null=True, blank=True,
        verbose_name=_('токен сброса пароля')
    )
    password_reset_token_expires_at = models.DateTimeField(
        _('срок действия токена сброса пароля'),
        null=True, blank=True
    )
    
    # Стандартные поля Django для управления доступом и состоянием пользователя
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    is_active = models.BooleanField(
        _('active'),
        default=False,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    # Дополнительные поля, связанные с подтверждением роли и приглашениями
    is_role_confirmed = models.BooleanField(_('role confirmed'), default=False)
    invited_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_users')

    # Связь для указания родителей студента.
    # Ограничена выбором пользователей с ролью PARENT.
    parents = models.ManyToManyField(
        'self',
        symmetrical=False,
        related_name='children',
        blank=True,
        limit_choices_to={'role': Role.PARENT},
        verbose_name=_('Родители (для Студента)'))
    
    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'role']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return self.email

    # Возвращает полное имя пользователя (имя и фамилия).
    # Если имя и фамилия не указаны, возвращает email.
    def get_full_name(self):
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name or self.email

    # Возвращает короткое имя пользователя (имя).
    # Если имя не указано, возвращает часть email до символа '@'.
    def get_short_name(self):
        return self.first_name or self.email.split('@')[0]

    # Property-методы для удобной проверки роли пользователя.
    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_parent(self):
        return self.role == self.Role.PARENT

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

# Модель Profile расширяет стандартную модель пользователя User дополнительной информацией,
# связываясь с ней отношением "один-к-одному" (OneToOneField), где поле 'user'
# также является первичным ключом для оптимизации запросов.
# Она хранит такие данные, как аватар пользователя (загружаемый с использованием
# функции get_avatar_upload_path), номер телефона, биографию и дату рождения.
# Переопределенные методы save и delete обеспечивают автоматическое удаление
# файла аватара из файловой системы при его замене или удалении профиля,
# чтобы избежать накопления "мусорных" файлов.
class Profile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        primary_key=True,
        verbose_name=_('пользователь')
    )
    avatar = models.ImageField(
        _('аватар'),
        upload_to=get_avatar_upload_path,
        null=True,
        blank=True,
        help_text=_('User profile picture')
    )
    phone_number = models.CharField(
        _('номер телефона'),
        max_length=20,
        blank=True,
        help_text=_('Contact phone number (optional)')
    )
    bio = models.TextField(
        _('о себе'),
        blank=True,
        help_text=_('A short biography (optional)')
    )
    date_of_birth = models.DateField(
        _('дата рождения'),
        null=True,
        blank=True,
        help_text=_('Date of birth (optional)')
    )
    
    class Meta:
        verbose_name = _('профиль')
        verbose_name_plural = _('профили')

    def __str__(self):
        return f"Профиль {self.user.email}"

    # Переопределенный метод сохранения профиля.
    # Перед сохранением нового аватара, если он был изменен, старый файл аватара удаляется из файловой системы.
    def save(self, *args, **kwargs):
        if self.pk:
            try:
                old_self = Profile.objects.get(pk=self.pk)
                if old_self.avatar and self.avatar != old_self.avatar:
                    if old_self.avatar.name:
                        old_self.avatar.delete(save=False)
            except Profile.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    # Переопределенный метод удаления профиля.
    # Перед удалением записи профиля из базы данных, связанный с ним файл аватара (если он существует)
    # удаляется из файловой системы.
    def delete(self, *args, **kwargs):
         if self.avatar and self.avatar.name:
              self.avatar.delete(save=False)
         super().delete(*args, **kwargs)


# Модель InvitationCode предназначена для управления кодами приглашений,
# которые позволяют новым пользователям регистрироваться с предопределенной ролью.
# Каждый код генерируется пользователем с ролью TEACHER или ADMIN, имеет уникальное
# значение (по умолчанию UUID), назначенную роль из User.Role.choices,
# срок действия (опционально) и может быть использован только один раз.
# Модель отслеживает, кем код был создан (created_by) и кем использован (used_by).
# Метод is_valid проверяет, активен ли код для использования (не использован и не истек срок действия).
class InvitationCode(models.Model):
    code = models.CharField(_('код'), max_length=50, unique=True, default=uuid.uuid4)
    role = models.CharField(_('назначенная роль'), max_length=20, choices=User.Role.choices)
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='generated_invitations',
        limit_choices_to={'role__in': [User.Role.TEACHER, User.Role.ADMIN]}
    )
    used_by = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='used_invitation')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(_('истекает'), null=True, blank=True)

    class Meta:
        verbose_name = _('код приглашения')
        verbose_name_plural = _('коды приглашения')

    def __str__(self):
        return self.code

    # Проверяет, действителен ли код приглашения.
    # Код считается действительным, если он еще не был использован
    # и его срок действия (если установлен) не истек.
    def is_valid(self):
        if self.used_by:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True