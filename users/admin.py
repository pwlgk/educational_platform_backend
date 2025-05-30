from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Profile, InvitationCode

# Класс ProfileInline определяет встроенное отображение модели Profile
# в административной панели Django внутри страницы редактирования пользователя (User).
# Это позволяет администраторам просматривать и редактировать данные профиля
# пользователя (аватар, телефон, биография, дата рождения) непосредственно
# на странице самого пользователя.
# - model: Указывает, что этот инлайн связан с моделью Profile.
# - can_delete: Устанавливает значение False, запрещая удаление профиля через этот инлайн.
#   Профиль обычно тесно связан с пользователем и удаляется вместе с ним.
# - verbose_name_plural: Задает отображаемое имя для инлайна в админ-панели.
# - fk_name: Указывает имя внешнего ключа в модели Profile, который ссылается на User.
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Профиль'
    fk_name = 'user'

# Класс CustomUserAdmin расширяет стандартный BaseUserAdmin для кастомизации
# отображения и управления моделью User в административной панели Django.
# Он включает следующие настройки:
# - inlines: Добавляет ProfileInline, чтобы профиль пользователя редактировался на той же странице.
# - list_display: Определяет поля, которые будут отображаться в списке пользователей
#   (email, имя, фамилия, роль, флаги персонала, активности и подтверждения роли).
# - list_filter: Добавляет фильтры для списка пользователей по роли, статусу персонала,
#   активности, подтверждению роли и дате присоединения.
# - search_fields: Позволяет осуществлять поиск пользователей по email, имени и фамилии.
# - ordering: Устанавливает сортировку списка пользователей по email по умолчанию.
# - fieldsets: Конфигурирует поля, отображаемые на странице редактирования существующего пользователя,
#   группируя их по секциям: основная информация (email, пароль), личная информация,
#   права доступа (включая роль и статусы), важные даты и связи (пригласивший, родители).
#   Поле 'parents' позволяет администратору управлять связями между студентами и родителями.
# - add_fieldsets: Определяет поля, доступные при создании нового пользователя.
# - readonly_fields: Указывает поля ('date_joined', 'last_login'), которые будут доступны только для чтения.
class CustomUserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active', 'is_role_confirmed')
    list_filter = ('role', 'is_staff', 'is_active', 'is_role_confirmed', 'date_joined')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'patronymic')}),
        ('Permissions', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'is_role_confirmed', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ('Relationships', {
            'fields': (
                'invited_by',
                'parents',
            )
        }),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password', 'password2', 'role', 'first_name', 'last_name'),
        }),
    )
    readonly_fields = ('date_joined', 'last_login')

# Регистрация модели User с кастомным административным классом CustomUserAdmin.
admin.site.register(User, CustomUserAdmin)
# Регистрация модели InvitationCode в административной панели с настройками по умолчанию.
# Модель Profile не регистрируется отдельно, так как она управляется через ProfileInline внутри CustomUserAdmin.
admin.site.register(InvitationCode)