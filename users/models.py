from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import uuid # Для токенов подтверждения

# --- Менеджер кастомного пользователя ---
class CustomUserManager(BaseUserManager):
    """
    Менеджер для кастомной модели пользователя, где email является уникальным идентификатором
    для аутентификации вместо username.
    """
    def create_user(self, email, password=None, **extra_fields):
        """
        Создает и сохраняет пользователя с указанным email и паролем.
        """
        if not email:
            raise ValueError(_('The Email must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        # Создаем связанный профиль после сохранения пользователя
        Profile.objects.create(user=user)
        # Создаем настройки уведомлений
        # (Предполагаем, что модель UserNotificationSettings будет в app 'notifications')
        # UserNotificationSettings.objects.create(user=user)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Создает и сохраняет суперпользователя с указанным email и паролем.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True) # Суперпользователь активен по умолчанию
        extra_fields.setdefault('role', User.Role.ADMIN) # Роль админа
        extra_fields.setdefault('is_role_confirmed', True) # Роль подтверждена

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        return self.create_user(email, password, **extra_fields)

# --- Кастомная модель пользователя ---
class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        STUDENT = 'STUDENT', _('Студент')
        TEACHER = 'TEACHER', _('Преподаватель')
        PARENT = 'PARENT', _('Родитель')
        ADMIN = 'ADMIN', _('Администратор')

    email = models.EmailField(_('email address'), unique=True)
    role = models.CharField(_('роль'), max_length=20, choices=Role.choices, default=Role.STUDENT) # Роль по умолчанию

    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    patronymic = models.CharField(_('patronymic'), max_length=150, blank=True) # Отчество

    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    is_active = models.BooleanField(
        _('active'),
        default=False, # Пользователь неактивен до подтверждения email
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    # Поля для подтверждения и связи
    is_role_confirmed = models.BooleanField(_('role confirmed'), default=False)
    confirmation_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, null=True, blank=True)
    invited_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_users')

    # Связь Родитель -> Студент (упрощенная, для примера).
    # В реальном приложении может потребоваться ManyToMany или отдельная модель связи.
    # Убедитесь, что используется related_name, чтобы избежать конфликтов.
    related_child = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='related_parents',
        limit_choices_to={'role': Role.STUDENT},
        verbose_name=_('связанный ребенок (для роли Родитель)')
    )

    objects = CustomUserManager()

    USERNAME_FIELD = 'email' # Используем email для входа
    REQUIRED_FIELDS = ['first_name', 'last_name', 'role'] # Поля, запрашиваемые при создании superuser

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return self.email

    def get_full_name(self):
        """
        Возвращает first_name плюс last_name с пробелом между ними.
        """
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name or self.email

    def get_short_name(self):
        """Возвращает короткое имя для пользователя (обычно first_name)."""
        return self.first_name or self.email.split('@')[0]

    # Методы для проверки роли (удобно для Permissions)
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

# --- Модель профиля пользователя ---
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name=_('пользователь'))
    avatar = models.ImageField(_('аватар'), upload_to='avatars/', null=True, blank=True)
    phone_number = models.CharField(_('номер телефона'), max_length=20, blank=True)
    bio = models.TextField(_('о себе'), blank=True)
    date_of_birth = models.DateField(_('дата рождения'), null=True, blank=True)
    # Добавьте другие поля профиля по необходимости

    class Meta:
        verbose_name = _('профиль')
        verbose_name_plural = _('профили')

    def __str__(self):
        return f"Профиль {self.user.email}"

# --- Модель кодов приглашения ---
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

    def is_valid(self):
        """Проверяет, действителен ли код (не использован и не истек)."""
        if self.used_by:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True