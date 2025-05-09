from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Profile, InvitationCode

class ProfileInline(admin.StackedInline):
    """Отображение профиля внутри админки пользователя."""
    model = Profile
    can_delete = False
    verbose_name_plural = 'Профиль'
    fk_name = 'user'

class CustomUserAdmin(BaseUserAdmin):
    """Кастомизация админки для модели User."""
    inlines = (ProfileInline,)
    list_display = ('email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active', 'is_role_confirmed')
    list_filter = ('role', 'is_staff', 'is_active', 'is_role_confirmed', 'date_joined')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)

    # Поля, отображаемые при редактировании пользователя
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'patronymic')}),
        ('Permissions', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'is_role_confirmed', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
('Relationships', {
            'fields': (
                'invited_by',
                'parents', # <-- НОВОЕ ПОЛЕ ДЛЯ СТУДЕНТА (выбираем родителей)
                # 'children', # Это обратная связь, ее лучше не редактировать напрямую здесь,
                             # а управлять через поле 'parents' у студента.
                             # Если очень нужно, используйте filter_horizontal или filter_vertical
            )
        }),    )
    # Поля, отображаемые при создании пользователя
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password', 'password2', 'role', 'first_name', 'last_name'),
        }),
    )
    # Т.к. используем email как username, нужно переопределить
    readonly_fields = ('date_joined', 'last_login')

# Регистрируем модели
admin.site.register(User, CustomUserAdmin)
admin.site.register(InvitationCode)
# Profile регистрируется через inline