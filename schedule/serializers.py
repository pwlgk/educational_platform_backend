from django.conf import settings
from rest_framework import serializers
from django.utils import timezone
from .models import Subject, StudentGroup, Classroom, Lesson
# Импортируем сериализатор пользователя для вложенного отображения
from users.serializers import UserSerializer # Убедитесь, что users app доступен
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


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
        """Валидация на пересечения и вместимость."""
        instance = self.instance # Для режима редактирования
        start_time = data.get('start_time', getattr(instance, 'start_time', None))
        end_time = data.get('end_time', getattr(instance, 'end_time', None))
        classroom_id = data.get('classroom_id', getattr(instance, 'classroom_id', None))
        teacher_id = data.get('teacher_id', getattr(instance, 'teacher_id', None))
        group_id = data.get('group_id', getattr(instance, 'group_id', None))

        classroom = Classroom.objects.filter(pk=classroom_id).first() if classroom_id else None
        teacher = User.objects.filter(pk=teacher_id).first() if teacher_id else None # Импортируйте User
        group = StudentGroup.objects.filter(pk=group_id).first() if group_id else None

        if not start_time or not end_time:
             raise serializers.ValidationError(_("Start time and end time are required."))

        if start_time >= end_time:
             raise serializers.ValidationError(_('End time must be after start time.'))

        # Собираем условия для проверки пересечений
        conflict_query = Q(start_time__lt=end_time) & Q(end_time__gt=start_time)
        potential_conflicts = (
             (Q(teacher=teacher) if teacher else Q()) | # Проверка на учителя
             (Q(group=group) if group else Q()) |       # Проверка на группу
             (Q(classroom=classroom) if classroom else Q()) # Проверка на аудиторию
        )

        overlapping_lessons = Lesson.objects.filter(
             conflict_query & potential_conflicts
        )

        if instance: # Исключаем себя при обновлении
             overlapping_lessons = overlapping_lessons.exclude(pk=instance.pk)

        if overlapping_lessons.exists():
             conflicts = []
             # Определяем, по какому ресурсу произошло пересечение (упрощенно)
             for lesson in overlapping_lessons.filter(teacher=teacher): conflicts.append(f"Teacher ({teacher})"); break
             for lesson in overlapping_lessons.filter(group=group): conflicts.append(f"Group ({group})"); break
             for lesson in overlapping_lessons.filter(classroom=classroom): conflicts.append(f"Classroom ({classroom})"); break

             unique_conflicts = ", ".join(sorted(list(set(conflicts)))) or "Unknown resource"
             raise serializers.ValidationError(
                  f"Lesson time conflict detected for: {unique_conflicts}."
             )

        # Проверка вместимости
        if classroom and group:
            # Получаем количество студентов в группе (может потребоваться оптимизация)
             student_count = group.students.count()
             if student_count > classroom.capacity:
                 raise serializers.ValidationError(
                     f'Classroom capacity {classroom.capacity} is less than group size {student_count}.'
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