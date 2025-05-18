# edu_core/signals.py
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from django.conf import settings
from .models import StudentGroup
# Предполагаем, что модуль messaging и его модели/сервисы существуют
from messaging.models import Chat, ChatParticipant # Замените на ваш путь, если отличается
# from messaging.services import create_chat_service # Если у вас есть сервисный слой

User = settings.AUTH_USER_MODEL # Получаем модель User из настроек

@receiver(post_save, sender=StudentGroup)
def create_or_update_group_chat_on_save(sender, instance, created, **kwargs):
    """
    Создает или обновляет групповой чат при создании/изменении StudentGroup.
    Создает чат, если назначен куратор и есть студенты.
    Обновляет участников, если куратор или состав студентов изменился.
    """
    group = instance
    if not group.curator: # Если нет куратора, чат не создаем или удаляем существующий (опционально)
        # Можно добавить логику удаления чата, если куратор убран
        # Chat.objects.filter(student_group_link=group).delete()
        print(f"Группа {group.name} без куратора, чат не создан/обновлен.")
        return

    chat_name = f"Чат группы: {group.name}"
    # Попробуем найти существующий чат по связи с группой (если бы мы добавили ForeignKey от Chat к StudentGroup)
    # Или по имени и типу (менее надежно, если имена могут совпадать)
    # Для простоты, будем искать по имени и создателю, если он админ чата
    
    # Простой вариант: создаем чат, если его еще нет, или обновляем участников.
    # Нужен механизм, чтобы не создавать дубликаты.
    # Идеально, если бы модель Chat имела прямую связь с StudentGroup,
    # например, `student_group = OneToOneField(StudentGroup, ...)`
    # Тогда можно было бы делать Chat.objects.get_or_create(student_group=group, ...)

    # Пока сделаем так: если чат с таким названием и типом уже есть и связан с куратором,
    # то обновляем участников. Иначе создаем. Это не идеально.
    
    # Попытка найти чат, где куратор является участником и название совпадает
    # (это грубый поиск, лучше иметь прямую связь Chat <-> StudentGroup)
    existing_chats = Chat.objects.filter(
        chat_type=Chat.ChatType.GROUP,
        name=chat_name,
        participants=group.curator
    )
    
    chat_instance = None
    if existing_chats.exists():
        # Если таких чатов несколько (маловероятно, но возможно при плохом дизайне),
        # берем первый или тот, где он администратор (если есть такая роль в чате)
        chat_instance = existing_chats.first() 
        print(f"Найден существующий чат '{chat_name}' для группы {group.name}.")
    
    if not chat_instance:
        # Создаем новый чат
        chat_instance = Chat.objects.create(
            chat_type=Chat.ChatType.GROUP,
            name=chat_name,
            created_by=group.curator # Куратор создает чат
        )
        print(f"Создан новый чат '{chat_name}' для группы {group.name}.")

    # Участники чата: куратор + все студенты группы
    all_participants_qs = group.students.all()
    # Преобразуем queryset в список объектов User, если он еще не такой
    desired_participants = [group.curator] + list(all_participants_qs)
    
    # Текущие участники чата
    current_chat_participants_users = [cp.user for cp in chat_instance.chatparticipant_set.all()]

    # Добавляем новых участников
    users_to_add = [user for user in desired_participants if user not in current_chat_participants_users]
    for user_to_add in users_to_add:
        ChatParticipant.objects.get_or_create(chat=chat_instance, user=user_to_add)
        print(f"Добавлен пользователь {user_to_add.email} в чат '{chat_name}'.")

    # Удаляем тех, кто больше не должен быть в чате
    # (например, если студент ушел из группы или сменился куратор, а старый был участником)
    users_to_remove = [user for user in current_chat_participants_users if user not in desired_participants]
    for user_to_remove in users_to_remove:
        ChatParticipant.objects.filter(chat=chat_instance, user=user_to_remove).delete()
        print(f"Удален пользователь {user_to_remove.email} из чата '{chat_name}'.")
    
    # Опционально: назначить куратора администратором чата (если есть такая роль в ChatParticipant)
    # chat_participant_curator, _ = ChatParticipant.objects.get_or_create(chat=chat_instance, user=group.curator)
    # if hasattr(chat_participant_curator, 'is_admin'):
    #     chat_participant_curator.is_admin = True
    #     chat_participant_curator.save()


@receiver(m2m_changed, sender=StudentGroup.students.through)
def update_group_chat_on_students_change(sender, instance, action, pk_set, **kwargs):
    """
    Обновляет участников группового чата при изменении состава студентов в StudentGroup.
    """
    if action in ["post_add", "post_remove", "post_clear"]:
        group = instance # instance здесь - это StudentGroup
        # Вызываем ту же логику, что и при сохранении группы
        # Это может быть избыточно, если post_save уже вызывается
        # Но m2m_changed срабатывает отдельно
        print(f"Состав студентов группы {group.name} изменился, обновляем чат.")
        create_or_update_group_chat_on_save(sender=StudentGroup, instance=group, created=False)