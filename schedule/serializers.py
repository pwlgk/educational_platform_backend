from django.conf import settings
from rest_framework import serializers
from django.utils import timezone
from .models import Subject, StudentGroup, Classroom, Lesson
# Импортируем сериализатор пользователя для вложенного отображения
from users.serializers import UserSerializer # Убедитесь, что users app доступен
from django.contrib.auth import get_user_model

from schedule import models

User = get_user_model()

class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = '__all__'

class StudentGroupSerializer(serializers.ModelSerializer):
    # Отображаем email куратора и количество студентов
    curator_email = serializers.EmailField(source='curator.email', read_only=True, allow_null=True)
    student_count = serializers.SerializerMethodField(read_only=True)
    # Опционально: можно вложить список студентов, но это может быть тяжело
    # students = UserSerializer(many=True, read_only=True)

    class Meta:
        model = StudentGroup
        fields = ('id', 'name', 'curator', 'curator_email', 'student_count', 'students')
        read_only_fields = ('curator_email', 'student_count')
        extra_kwargs = {
            'students': {'required': False}, # Необязательно добавлять студентов при создании/обновлении группы
        }

    def get_student_count(self, obj):
        return obj.students.count()

class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = '__all__'

class LessonSerializer(serializers.ModelSerializer):
    # Вложенное представление для чтения связанных объектов
    subject = SubjectSerializer(read_only=True)
    teacher = UserSerializer(read_only=True)
    group = StudentGroupSerializer(read_only=True)
    classroom = ClassroomSerializer(read_only=True, allow_null=True)

    # Поля для записи (используем PrimaryKeyRelatedField)
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), source='subject', write_only=True
    )
    teacher_id = serializers.PrimaryKeyRelatedField(
        queryset = User.objects.filter(role=User.Role.TEACHER),
        source='teacher', write_only=True
    )
    group_id = serializers.PrimaryKeyRelatedField(
        queryset=StudentGroup.objects.all(), source='group', write_only=True
    )
    classroom_id = serializers.PrimaryKeyRelatedField(
        queryset=Classroom.objects.all(), source='classroom', write_only=True, allow_null=True, required=False
    )

    class Meta:
        model = Lesson
        fields = (
            'id', 'subject', 'teacher', 'group', 'classroom', 'lesson_type',
            'start_time', 'end_time',
            'subject_id', 'teacher_id', 'group_id', 'classroom_id', # Поля для записи
            'created_at', 'updated_at', 'created_by'
        )
        read_only_fields = ('created_at', 'updated_at', 'created_by')

    def validate(self, data):
        """Валидация на уровне сериализатора."""
        start_time = data.get('start_time') or getattr(self.instance, 'start_time', None)
        end_time = data.get('end_time') or getattr(self.instance, 'end_time', None)
        teacher = data.get('teacher') or getattr(self.instance, 'teacher', None)
        group = data.get('group') or getattr(self.instance, 'group', None)
        classroom = data.get('classroom', None) # Может быть None при записи
        if self.instance: # Если это обновление, classroom может быть в instance
             classroom = data.get('classroom', getattr(self.instance, 'classroom', None))

        # 1. Проверка времени
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError(_('Время окончания должно быть позже времени начала.'))

        # 2. Проверка пересечений (используя Q-объекты для OR)
        overlapping_lessons = Lesson.objects.filter(
            # Ищем пересечения по ЛЮБОМУ из: аудитория (если есть), преподаватель, группа
            models.Q(classroom=classroom) if classroom else models.Q(), # Только если аудитория указана
            models.Q(teacher=teacher) | models.Q(group=group),
            start_time__lt=end_time,    # Занятие начинается до окончания нового
            end_time__gt=start_time     # Занятие заканчивается после начала нового
        )
        if self.instance: # Исключаем себя при обновлении
            overlapping_lessons = overlapping_lessons.exclude(pk=self.instance.pk)

        if overlapping_lessons.exists():
             # Формируем сообщение об ошибке (более детально, чем в модели)
             conflicts = []
             for lesson in overlapping_lessons.select_related('classroom', 'teacher', 'group'): # Оптимизация
                 if classroom and lesson.classroom == classroom: conflicts.append(f"Аудитория ({classroom.identifier})")
                 if lesson.teacher == teacher: conflicts.append(f"Преподаватель ({teacher.get_full_name()})")
                 if lesson.group == group: conflicts.append(f"Группа ({group.name})")

             if conflicts:
                 unique_conflicts = ", ".join(sorted(list(set(conflicts))))
                 raise serializers.ValidationError(_(f'Обнаружено пересечение занятий по времени для: {unique_conflicts}.'))


        # 3. Проверка вместимости аудитории
        if classroom and group:
            # Получаем количество студентов (лучше получить group из data, если он там есть)
            group_instance = data.get('group', getattr(self.instance, 'group', None))
            if group_instance and group_instance.students.count() > classroom.capacity:
                raise serializers.ValidationError(
                     _(f'Вместимость аудитории {classroom.identifier} ({classroom.capacity}) меньше, '
                       f'чем количество студентов в группе {group_instance.name} ({group_instance.students.count()}).')
                 )

        return data

    def create(self, validated_data):
        # Устанавливаем created_by из контекста запроса
        validated_data['created_by'] = self.context['request'].user
        instance = super().create(validated_data)
        # TODO: Отправить уведомление о создании занятия
        # send_lesson_creation_notification(instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        # TODO: Отправить уведомление об изменении занятия
        # send_lesson_update_notification(instance)
        return instance


class ScheduleListSerializer(LessonSerializer):
    """Упрощенный сериализатор для отображения списков расписания."""
    # Используем строки вместо полных объектов для краткости
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    group_name = serializers.CharField(source='group.name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.identifier', read_only=True, allow_null=True)

    class Meta:
        model = Lesson
        fields = (
            'id', 'subject_name', 'teacher_name', 'group_name', 'classroom_name',
            'lesson_type', 'start_time', 'end_time',
        )
        read_only_fields = fields # Этот сериализатор только для чтения