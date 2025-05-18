from jsonschema import ValidationError
from rest_framework import serializers
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from django.contrib.auth import get_user_model
from django.db.models import Avg, Sum, F # Для агрегаций
from django.utils import timezone

from .models import (
    AcademicYear, StudyPeriod, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)
# Импортируем UserSerializer для отображения связанных пользователей
# Предполагаем, что он есть в users.serializers и содержит нужные поля
from users.serializers import UserSerializer as BaseUserSerializer # Переименуем, чтобы избежать конфликта имен

User = get_user_model()

# --- Базовый сериализатор для пользователя (можно вынести в users.serializers, если там нет подходящего) ---
# Этот сериализатор будет использоваться для краткого отображения пользователей в контексте edu_core
class EduUserSerializer(BaseUserSerializer): # Наследуем от вашего основного UserSerializer
    class Meta(BaseUserSerializer.Meta):
        # Выбираем только нужные поля для отображения в контексте edu_core
        fields = ('id', 'email', 'first_name', 'last_name', 'patronymic', 'role', 'profile')
        # Убираем profile, если он слишком тяжелый для списков, или делаем ProfileSerializer очень легковесным
        # fields = ('id', 'email', 'get_full_name', 'role') # Альтернативный, более легкий вариант

# --- Сериализаторы для Базовых Сущностей (Административные) ---

class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ('id', 'name', 'start_date', 'end_date', 'is_current')

class StudyPeriodSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)

    class Meta:
        model = StudyPeriod
        fields = ('id', 'academic_year', 'academic_year_name', 'name', 'start_date', 'end_date')
        extra_kwargs = {
            'academic_year': {'write_only': True, 'queryset': AcademicYear.objects.all()} # Добавил queryset
        }

class SubjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectType
        fields = ('id', 'name', 'description')

class SubjectSerializer(serializers.ModelSerializer):
    subject_type_name = serializers.CharField(source='subject_type.name', read_only=True, allow_null=True)
    lead_teachers_details = EduUserSerializer(source='lead_teachers', many=True, read_only=True)

    class Meta:
        model = Subject
        fields = ('id', 'name', 'code', 'description', 'subject_type', 'subject_type_name', 'lead_teachers', 'lead_teachers_details')
        extra_kwargs = {
            'lead_teachers': {'required': False, 'write_only': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'subject_type': {'required': False, 'allow_null': True, 'queryset': SubjectType.objects.all()}
        }

class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = ('id', 'identifier', 'capacity', 'type', 'equipment')

class StudentGroupSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)
    curator_details = EduUserSerializer(source='curator', read_only=True, allow_null=True)
    students_details = EduUserSerializer(source='students', many=True, read_only=True)
    group_monitor_details = EduUserSerializer(source='group_monitor', read_only=True, allow_null=True)
    student_count = serializers.IntegerField(source='students.count', read_only=True) # Более простой способ получить количество

    class Meta:
        model = StudentGroup
        fields = (
            'id', 'name', 'academic_year', 'academic_year_name',
            'curator', 'curator_details',
            'students', 'students_details',
            'group_monitor', 'group_monitor_details',
            'student_count'
        )
        read_only_fields = ('academic_year_name', 'curator_details', 'students_details', 'group_monitor_details', 'student_count')
        extra_kwargs = {
            'academic_year': {'required': True, 'queryset': AcademicYear.objects.all()}, # Для создания
            'curator': {'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'students': {'required': False, 'queryset': User.objects.filter(role=User.Role.STUDENT)},
            'group_monitor': {'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.STUDENT)},
        }

    def validate_curator(self, value):
        if value and value.role != User.Role.TEACHER:
            raise serializers.ValidationError(_("Куратор должен быть преподавателем."))
        return value

    def validate_group_monitor(self, value):
        if value and value.role != User.Role.STUDENT:
            raise serializers.ValidationError(_("Староста должен быть студентом."))
        return value

    def validate(self, data):
        # Проверка, что староста (если назначен) есть в списке студентов
        # Эта валидация лучше работает, если 'students' передается как список ID
        group_monitor = data.get('group_monitor')
        students_qs_or_list = data.get('students') # Это может быть список ID или QuerySet

        if group_monitor and students_qs_or_list:
            if isinstance(students_qs_or_list, list) and not any(s.pk == group_monitor.pk for s in students_qs_or_list if hasattr(s, 'pk')):
                # Если students - список объектов, и старосты там нет
                 is_monitor_in_list = False
                 for s_obj in students_qs_or_list:
                     if s_obj.pk == group_monitor.pk:
                         is_monitor_in_list = True
                         break
                 if not is_monitor_in_list:
                      raise serializers.ValidationError({'group_monitor': _("Староста должен быть одним из выбранных студентов группы.")})

            # Если students_qs_or_list - это queryset, проверка будет сложнее здесь,
            # лучше оставить на уровне модели clean() или perform_create/update во ViewSet.
            # В нашем случае, т.к. мы используем set() в create/update, эта проверка здесь может быть избыточна.
        return data

    def create(self, validated_data):
        students_data = validated_data.pop('students', [])
        group = StudentGroup.objects.create(**validated_data)
        if students_data:
            group.students.set(students_data)
        return group

    def update(self, instance, validated_data):
        students_data = validated_data.pop('students', None)
        # Запрещаем изменение academic_year после создания через этот сериализатор
        validated_data.pop('academic_year', None)
        instance = super().update(instance, validated_data)
        if students_data is not None:
            instance.students.set(students_data)
        return instance

# --- Сериализаторы для Учебных Планов ---

class CurriculumEntrySerializer(serializers.ModelSerializer):
    subject_details = SubjectSerializer(source='subject', read_only=True)
    teacher_details = EduUserSerializer(source='teacher', read_only=True, allow_null=True)
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True)
    scheduled_hours = serializers.FloatField(read_only=True, default=0.0)
    remaining_hours = serializers.FloatField(read_only=True, default=0.0)

    class Meta:
        model = CurriculumEntry
        fields = (
            'id', 'curriculum', 'subject', 'subject_details', 'teacher', 'teacher_details',
            'study_period', 'study_period_details', 'planned_hours',
            'scheduled_hours', 'remaining_hours'
        )
        extra_kwargs = {
            'curriculum': {'write_only': True, 'queryset': Curriculum.objects.all()},
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'teacher': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'study_period': {'write_only': True, 'queryset': StudyPeriod.objects.all()},
        }

class CurriculumSerializer(serializers.ModelSerializer):
    academic_year_details = AcademicYearSerializer(source='academic_year', read_only=True)
    student_group_details = StudentGroupSerializer(source='student_group', read_only=True)
    entries = CurriculumEntrySerializer(many=True, read_only=True) # Для чтения
    # Для записи entries лучше использовать отдельный эндпоинт или вложенную запись с кастомной логикой

    class Meta:
        model = Curriculum
        fields = (
            'id', 'name', 'academic_year', 'academic_year_details',
            'student_group', 'student_group_details',
            'description', 'is_active', 'entries'
        )
        extra_kwargs = {
            'academic_year': {'write_only': True, 'queryset': AcademicYear.objects.all()},
            'student_group': {'write_only': True, 'queryset': StudentGroup.objects.all()},
        }

# --- Сериализаторы для Расписания ---

class LessonSerializer(serializers.ModelSerializer):
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True)
    student_group_details = StudentGroupSerializer(source='student_group', read_only=True) # Краткий StudentGroup
    subject_details = SubjectSerializer(source='subject', read_only=True) # Краткий Subject
    teacher_details = EduUserSerializer(source='teacher', read_only=True)
    classroom_details = ClassroomSerializer(source='classroom', read_only=True, allow_null=True)
    curriculum_entry_details = CurriculumEntrySerializer(source='curriculum_entry', read_only=True, allow_null=True)
    created_by_details = EduUserSerializer(source='created_by', read_only=True, allow_null=True)
    duration_hours = serializers.FloatField(read_only=True)

    class Meta:
        model = Lesson
        fields = (
            'id', 'study_period', 'study_period_details', 'student_group', 'student_group_details',
            'subject', 'subject_details', 'teacher', 'teacher_details',
            'classroom', 'classroom_details', 'lesson_type', 'start_time', 'end_time',
            'curriculum_entry', 'curriculum_entry_details',
            'created_at', 'updated_at', 'created_by', 'created_by_details', 'duration_hours'
        )
        read_only_fields = ('created_at', 'updated_at', 'created_by', 'created_by_details', 'duration_hours')
        extra_kwargs = {
            'study_period': {'write_only': True, 'queryset': StudyPeriod.objects.all()},
            'student_group': {'write_only': True, 'queryset': StudentGroup.objects.all()},
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'teacher': {'write_only': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'classroom': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': Classroom.objects.all()},
            'curriculum_entry': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': CurriculumEntry.objects.all()},
        }

    def validate(self, data):
        instance = self.instance or Lesson()
        # Собираем данные для clean(), учитывая, что некоторые поля могут быть не переданы при PATCH
        cleaned_data = {}
        for field in Lesson._meta.fields:
            if field.name in data:
                cleaned_data[field.name] = data[field.name]
            elif instance and hasattr(instance, field.name):
                cleaned_data[field.name] = getattr(instance, field.name)
        
        # Пропускаем поля, которых нет ни в data, ни в instance (для PATCH)
        # и которые не являются обязательными для clean
        temp_instance = Lesson(**cleaned_data)

        try:
            temp_instance.clean()
        except ValidationError as e:
            raise serializers.ValidationError(serializers.as_serializer_error(e))
        return data

class LessonListSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    group_name = serializers.CharField(source='student_group.name', read_only=True)
    classroom_identifier = serializers.CharField(source='classroom.identifier', read_only=True, allow_null=True)
    duration_hours = serializers.FloatField(read_only=True)

    class Meta:
        model = Lesson
        fields = (
            'id', 'subject_name', 'teacher_name', 'group_name', 'classroom_identifier',
            'lesson_type', 'start_time', 'end_time', 'duration_hours'
        )

# --- Сериализаторы для Журнала, ДЗ, Посещаемости, Оценок, Библиотеки ---

class LessonJournalEntrySerializer(serializers.ModelSerializer):
    lesson_details = LessonListSerializer(source='lesson', read_only=True)
    # Можно добавить детали ДЗ и посещаемости, если нужно все в одном месте
    # homework_assignments = HomeworkSerializer(many=True, read_only=True)
    # attendances_summary = serializers.SerializerMethodField()

    class Meta:
        model = LessonJournalEntry
        fields = ('id', 'lesson', 'lesson_details', 'topic_covered', 'teacher_notes', 'date_filled')
        extra_kwargs = {
            'lesson': {'write_only': True, 'queryset': Lesson.objects.all()},
        }

class SubjectMaterialSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    student_group_name = serializers.CharField(source='student_group.name', read_only=True, allow_null=True)
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True, allow_null=True)
    file_url = serializers.FileField(source='file', read_only=True)

    class Meta:
        model = SubjectMaterial
        fields = (
            'id', 'subject', 'subject_name', 'student_group', 'student_group_name',
            'title', 'description', 'file', 'file_url', 'uploaded_by', 'uploaded_by_name', 'uploaded_at'
        )
        read_only_fields = ('uploaded_by_name', 'uploaded_at', 'file_url')
        extra_kwargs = {
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'student_group': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': StudentGroup.objects.all()},
            'file': {'write_only': True, 'required': True},
        }

class HomeworkAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.FileField(source='file', read_only=True)
    class Meta:
        model = HomeworkAttachment
        fields = ('id', 'homework', 'file', 'file_url', 'description', 'uploaded_at')
        read_only_fields = ('uploaded_at', 'file_url')
        extra_kwargs = {
            'homework': {'write_only': True, 'queryset': Homework.objects.all()},
            'file': {'write_only': True, 'required': True},
        }

class HomeworkSerializer(serializers.ModelSerializer):
    lesson_id = serializers.IntegerField(source='journal_entry.lesson.id', read_only=True)
    lesson_subject = serializers.CharField(source='journal_entry.lesson.subject.name', read_only=True)
    author_details = EduUserSerializer(source='author', read_only=True, allow_null=True)
    attachments = HomeworkAttachmentSerializer(many=True, read_only=True) # ЯВНОЕ ОПРЕДЕЛЕНИЕ
    related_materials_details = SubjectMaterialSerializer(source='related_materials', many=True, read_only=True) # ЯВНОЕ ОПРЕДЕЛЕНИЕ
    files_to_upload = serializers.ListField(child=serializers.FileField(allow_empty_file=False, use_url=False), write_only=True, required=False)
    material_ids_to_link = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = Homework
        fields = ( # Включите сюда все явно определенные поля
            'id', 'journal_entry', 'lesson_id', 'lesson_subject', 'title', 'description', 'due_date',
            'created_at', 'author', 'author_details', # 'author' для записи ID
            'attachments', 'related_materials', 'related_materials_details', # 'related_materials' для записи ID
            'files_to_upload', 'material_ids_to_link'
        )
        read_only_fields = ('created_at', 'author_details', 'attachments', 'related_materials_details', 'lesson_id', 'lesson_subject')
        extra_kwargs = {
            'journal_entry': {'write_only': True, 'queryset': LessonJournalEntry.objects.all()},
            'author': {'write_only': True, 'required': False, 'allow_null': True}, # Позволяем установить автора при создании
            'related_materials': {'write_only': True, 'required': False, 'queryset': SubjectMaterial.objects.all()},
        }

    @transaction.atomic
    def create(self, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', [])
        material_ids = validated_data.pop('material_ids_to_link', [])
        related_materials_qs = validated_data.pop('related_materials', SubjectMaterial.objects.none())

        homework = Homework.objects.create(**validated_data)

        for file_data in files_to_upload:
            HomeworkAttachment.objects.create(homework=homework, file=file_data)
        
        # Объединяем материалы из IDs и queryset
        materials_to_set = list(related_materials_qs)
        if material_ids:
            materials_to_set.extend(list(SubjectMaterial.objects.filter(id__in=material_ids)))
        
        if materials_to_set:
            homework.related_materials.set(list(set(materials_to_set))) # Убираем дубликаты

        return homework

    @transaction.atomic
    def update(self, instance, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', None)
        material_ids = validated_data.pop('material_ids_to_link', None)
        related_materials_qs = validated_data.pop('related_materials', None)

        instance = super().update(instance, validated_data)

        if files_to_upload is not None: # Если передан пустой список - удаляем все старые
            instance.attachments.all().delete()
            for file_data in files_to_upload:
                HomeworkAttachment.objects.create(homework=instance, file=file_data)

        if related_materials_qs is not None:
            instance.related_materials.set(related_materials_qs)
        elif material_ids is not None:
             materials = SubjectMaterial.objects.filter(id__in=material_ids)
             instance.related_materials.set(materials)
        return instance


class SubmissionAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.FileField(source='file', read_only=True)
    class Meta:
        model = SubmissionAttachment
        fields = ('id', 'submission', 'file', 'file_url', 'uploaded_at')
        read_only_fields = ('uploaded_at', 'file_url')
        extra_kwargs = {
            'submission': {'write_only': True, 'queryset': HomeworkSubmission.objects.all()},
            'file': {'write_only': True, 'required': True},
        }

class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    homework_title = serializers.CharField(source='homework.title', read_only=True)
    student_details = EduUserSerializer(source='student', read_only=True)
    attachments = SubmissionAttachmentSerializer(many=True, read_only=True)
    grade_details = serializers.SerializerMethodField()
    files_to_upload = serializers.ListField(child=serializers.FileField(allow_empty_file=False, use_url=False), write_only=True, required=False)

    class Meta:
        model = HomeworkSubmission
        fields = (
            'id', 'homework', 'homework_title', 'student', 'student_details',
            'submitted_at', 'content', 'attachments', 'grade_details', 'files_to_upload'
        )
        read_only_fields = ('submitted_at', 'student', 'student_details', 'attachments', 'grade_details', 'homework_title')
        extra_kwargs = {
            'homework': {'write_only': True, 'queryset': Homework.objects.all()},
            'content': {'required': False, 'allow_blank': True},
        }

    def get_grade_details(self, obj):
        try:
            # Используем related_name 'grade_for_submission'
            grade = obj.grade_for_submission
            return GradeSerializer(grade, context=self.context).data
        except Grade.DoesNotExist: # или AttributeError, если related_name не настроен или объект не существует
            return None

    @transaction.atomic
    def create(self, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', [])
        validated_data['student'] = self.context['request'].user
        submission = HomeworkSubmission.objects.create(**validated_data)
        for file_data in files_to_upload:
            SubmissionAttachment.objects.create(submission=submission, file=file_data)
        return submission


class AttendanceSerializer(serializers.ModelSerializer):
    # journal_entry_details = LessonJournalEntrySerializer(source='journal_entry', read_only=True) # Убрал для краткости
    lesson_id = serializers.IntegerField(source='journal_entry.lesson.id', read_only=True)
    student_details = EduUserSerializer(source='student', read_only=True)
    marked_by_details = EduUserSerializer(source='marked_by', read_only=True, allow_null=True)

    class Meta:
        model = Attendance
        fields = (
            'id', 'journal_entry', 'lesson_id', 'student', 'student_details',
            'status', 'comment', 'marked_at', 'marked_by', 'marked_by_details'
        )
        read_only_fields = ('marked_at', 'marked_by', 'marked_by_details', 'lesson_id')
        extra_kwargs = {
            'journal_entry': {'write_only': True, 'queryset': LessonJournalEntry.objects.all()},
            'student': {'write_only': True, 'queryset': User.objects.filter(role=User.Role.STUDENT)},
        }

class GradeSerializer(serializers.ModelSerializer):
    student_details = EduUserSerializer(source='student', read_only=True)
    subject_details = SubjectSerializer(source='subject', read_only=True)
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True)
    lesson_details = LessonListSerializer(source='lesson', read_only=True, allow_null=True)
    homework_submission_details = HomeworkSubmissionSerializer(source='homework_submission', read_only=True, allow_null=True) # Краткая инфо
    graded_by_details = EduUserSerializer(source='graded_by', read_only=True, allow_null=True)

    class Meta:
        model = Grade
        fields = (
            'id', 'student', 'student_details', 'subject', 'subject_details',
            'study_period', 'study_period_details', 'lesson', 'lesson_details',
            'homework_submission', 'homework_submission_details',
            'grade_value', 'numeric_value', 'grade_type', 'date_given', 'comment',
            'graded_by', 'graded_by_details', 'weight'
        )
        read_only_fields = ('graded_by_details',) # graded_by устанавливается во view
        extra_kwargs = {
            'student': {'write_only': True, 'queryset': User.objects.filter(role=User.Role.STUDENT)},
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'study_period': {'write_only': True, 'queryset': StudyPeriod.objects.all()},
            'lesson': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': Lesson.objects.all()},
            'homework_submission': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': HomeworkSubmission.objects.all()},
            'graded_by': {'write_only':True, 'required':False, 'allow_null':True, 'queryset':User.objects.filter(role=User.Role.TEACHER)} # Для админа
        }

    def validate(self, data):
        grade_type = data.get('grade_type', getattr(self.instance, 'grade_type', None))
        lesson = data.get('lesson', getattr(self.instance, 'lesson', None))
        homework_submission = data.get('homework_submission', getattr(self.instance, 'homework_submission', None))

        if grade_type == Grade.GradeType.LESSON_WORK and not lesson:
            raise serializers.ValidationError({"lesson": _("Для оценки за работу на занятии необходимо указать занятие.")})
        if grade_type == Grade.GradeType.HOMEWORK_GRADE and not homework_submission:
            raise serializers.ValidationError({"homework_submission": _("Для оценки за ДЗ необходимо указать сданную работу.")})
        if grade_type in [Grade.GradeType.PERIOD_FINAL, Grade.GradeType.YEAR_FINAL] and (lesson or homework_submission):
            raise serializers.ValidationError(_("Итоговые оценки не должны быть привязаны к конкретному занятию или ДЗ."))
        return data


# --- Сериализаторы для Ролевых Представлений ---

class MyGradeSerializer(GradeSerializer): # Наследование самого сериализатора - нормально
    class Meta: # Определяем Meta ЗАНОВО
        model = Grade # Обязательно указываем модель
        # Явно перечисляем поля, которые хотим видеть, ИСКЛЮЧАЯ 'student' и 'student_details'
        fields = (
            'id',
            # 'student', 'student_details', # Исключены
            'subject', 'subject_details',
            'study_period', 'study_period_details',
            'lesson', 'lesson_details',
            'homework_submission', 'homework_submission_details',
            'grade_value', 'numeric_value', 'grade_type', 'date_given', 'comment',
            'graded_by_details', # graded_by уже был в read_only_fields родителя, graded_by_details - тоже
            'weight'
        )
        # Все поля, перечисленные в 'fields', будут по умолчанию read_only,
        # так как мы не указываем обратного.
        # Если нужно явно сделать какие-то из них writeable (что вряд ли для MyGradeSerializer),
        # их нужно убрать из read_only_fields.
        # Для "Мои оценки" обычно все поля только для чтения.
        read_only_fields = fields

class MyAttendanceSerializer(AttendanceSerializer): # Наследуем от основного
     class Meta: # Определяем Meta заново, не наследуя от AttendanceSerializer.Meta напрямую
         model = Attendance # Обязательно указываем модель
         # Явно перечисляем поля, которые нужны, ИСКЛЮЧАЯ те, что были в 'exclude'
         fields = (
             'id',
             'journal_entry', # или 'journal_entry_details', если он есть в AttendanceSerializer и нужен
             'lesson_id',     # Если он есть в AttendanceSerializer
             # 'student', 'student_details', # Исключены
             'status',
             'comment',
             'marked_at',
             # 'marked_by', 'marked_by_details' # Исключены
         )
         # Все поля в 'fields' будут read_only для этого сериализатора
         read_only_fields = fields 

class MyHomeworkSerializer(HomeworkSerializer):
    submission_status = serializers.SerializerMethodField()
    my_submission = serializers.SerializerMethodField() # Ссылка на свою сдачу

    class Meta: # Определяем Meta заново
         model = Homework # Указываем модель
         # Явно перечисляем поля, которые хотим видеть,
         # и которые уже определены в HomeworkSerializer или являются полями модели
         fields = (
             'id',
             # Поля из HomeworkSerializer (или напрямую из модели Homework)
             'lesson_id',         # Это SerializerMethodField или source в HomeworkSerializer
             'lesson_subject',    # Это SerializerMethodField или source в HomeworkSerializer
             'title',
             'description',
             'due_date',
             'created_at',
             'author_details',    # Это поле должно быть определено в HomeworkSerializer
             'attachments',       # Это поле должно быть определено в HomeworkSerializer (как вложенный сериализатор)
             'related_materials_details', # Это поле должно быть определено в HomeworkSerializer
             # Новые поля для этого сериализатора
             'submission_status',
             'my_submission',
         )
         read_only_fields = fields 

    def get_submission_status(self, obj):
        user = self.context['request'].user
        # Определяем целевого студента (сам пользователь или его ребенок)
        target_student = user
        if user.is_parent:
            child_id = self.context.get('child_id_for_status') # ViewSet родителя должен передать это
            if child_id:
                try: target_student = User.objects.get(pk=child_id, role=User.Role.STUDENT, children__pk=user.pk) # Проверка связи
                except User.DoesNotExist: return "N/A"
            else: return "N/A" # Не можем определить ребенка для родителя

        if target_student.is_student:
            submission = HomeworkSubmission.objects.filter(homework=obj, student=target_student).first()
            if submission:
                if hasattr(submission, 'grade_for_submission') and submission.grade_for_submission:
                    return _("Сдано (Оценено: %(grade)s)") % {'grade': submission.grade_for_submission.grade_value}
                return _("Сдано (Ожидает проверки)")
            elif obj.due_date and timezone.now() > obj.due_date:
                return _("Не сдано (Срок истек)")
            return _("Не сдано")
        return "N/A"

    def get_my_submission(self, obj):
        user = self.context['request'].user
        target_student = user
        if user.is_parent:
            child_id = self.context.get('child_id_for_status')
            if child_id:
                try: target_student = User.objects.get(pk=child_id, role=User.Role.STUDENT, children__pk=user.pk)
                except User.DoesNotExist: return None
            else: return None

        if target_student.is_student:
            submission = HomeworkSubmission.objects.filter(homework=obj, student=target_student).first()
            if submission:
                # Возвращаем ID сдачи для перехода или краткую информацию
                return {'id': submission.id, 'submitted_at': submission.submitted_at}
        return None


class StudentHomeworkSubmissionSerializer(HomeworkSubmissionSerializer):
    class Meta(HomeworkSubmissionSerializer.Meta):
        read_only_fields = ('submitted_at', 'student', 'student_details', 'attachments', 'grade_details', 'homework_title', 'homework')
        extra_kwargs = {
            'homework_id': {'write_only': True, 'required': True, 'source': 'homework'}, # Для создания по ID
            'content': {'required': False, 'allow_blank': True},
        }
        # Убираем homework_details из полей, т.к. используем homework_id для создания
        fields = tuple(f for f in HomeworkSubmissionSerializer.Meta.fields if f not in ['homework_details']) + ('homework_id',)


# --- Сериализаторы для Импорта (оставляем как примеры, требуют доработки под CSV) ---

class TeacherImportSerializer(serializers.Serializer):
    email = serializers.EmailField()
    last_name = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150)
    patronymic = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def create_or_update_teacher(self, data): # Метод для View
        user, created = User.objects.update_or_create(
            email=data['email'],
            defaults={
                'first_name': data['first_name'],
                'last_name': data['last_name'],
                'patronymic': data.get('patronymic', ''),
                'role': User.Role.TEACHER, 'is_active': True, 'is_role_confirmed': True,
            }
        )
        if created: user.set_password(User.objects.make_random_password()); user.save()
        return user

class SubjectImportSerializer(serializers.ModelSerializer):
    subject_type_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    class Meta: model = Subject; fields = ('name', 'code', 'description', 'subject_type_name')
    def create(self, validated_data): # Переопределяем create
        subject_type_name = validated_data.pop('subject_type_name', None)
        subject_type = None
        if subject_type_name: subject_type, _ = SubjectType.objects.get_or_create(name=subject_type_name)
        validated_data['subject_type'] = subject_type
        subject, _ = Subject.objects.update_or_create(name=validated_data['name'], defaults=validated_data)
        return subject

class StudentGroupImportSerializer(serializers.Serializer):
    group_name = serializers.CharField()
    academic_year_name = serializers.CharField() # Имя года, например "2024-2025"
    curator_email = serializers.EmailField(required=False, allow_null=True)
    student_emails = serializers.CharField(help_text="Emails через точку с запятой (;)")

    def create_or_update_group(self, data): # Метод для View
        try:
            academic_year = AcademicYear.objects.get(name=data['academic_year_name'])
        except AcademicYear.DoesNotExist:
            raise serializers.ValidationError(f"Учебный год '{data['academic_year_name']}' не найден.")
        
        curator = None
        if data.get('curator_email'):
            try: curator = User.objects.get(email=data['curator_email'], role=User.Role.TEACHER)
            except User.DoesNotExist: raise serializers.ValidationError(f"Куратор с email '{data['curator_email']}' не найден или не является преподавателем.")
        
        group, created = StudentGroup.objects.update_or_create(
            name=data['group_name'], academic_year=academic_year,
            defaults={'curator': curator}
        )
        
        student_emails_list = [email.strip() for email in data.get('student_emails', '').split(';') if email.strip()]
        students_to_add = []
        for email in student_emails_list:
            student, stud_created = User.objects.get_or_create(
                email=email,
                defaults={'role': User.Role.STUDENT, 'is_active': True, 'is_role_confirmed': True} # Упрощенно
            )
            if stud_created: student.set_password(User.objects.make_random_password()); student.save()
            students_to_add.append(student)
        if students_to_add: group.students.set(students_to_add)
        return group

# class ScheduleImportSerializer(serializers.Serializer): # Очень сложный, требует детальной проработки

# --- Сериализаторы для Статистики ---

class TeacherLoadSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, source='pk')
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    email = serializers.EmailField(read_only=True)
    total_planned_hours = serializers.FloatField(read_only=True, default=0.0)
    scheduled_lesson_count = serializers.IntegerField(read_only=True, default=0)
    total_scheduled_hours_float = serializers.FloatField(read_only=True, default=0.0)

class GroupSubjectPerformanceStatSerializer(serializers.Serializer):
    # group_id = serializers.IntegerField() # Не нужно, т.к. это часть TeacherSubjectPerformanceSerializer
    # group_name = serializers.CharField()
    subject_id = serializers.IntegerField()
    subject_name = serializers.CharField()
    average_grade = serializers.DecimalField(max_digits=4, decimal_places=2, allow_null=True)
    grades_count = serializers.IntegerField()

class TeacherSubjectPerformanceSerializer(serializers.Serializer):
    teacher_id = serializers.IntegerField()
    teacher_name = serializers.CharField()
    # Это поле будет списком словарей, а не объектов, поэтому SerializerMethodField или кастомная логика во View
    groups_data = GroupSubjectPerformanceStatSerializer(many=True, read_only=True)

class StudentOverallPerformanceInGroupSerializer(EduUserSerializer): # Для GroupPerformanceSerializer
    average_grade_for_period = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True, allow_null=True)
    subject_performance_details = serializers.SerializerMethodField(read_only=True) # Переименовал для ясности

    class Meta(EduUserSerializer.Meta):
        fields = EduUserSerializer.Meta.fields + ('average_grade_for_period', 'subject_performance_details')

    def get_subject_performance_details(self, obj):
        # obj - экземпляр User (студент)
        # Ожидаем, что к obj прикреплен атрибут 'period_grades_for_stats' через Prefetch
        # или study_period_id передан в контексте для прямого запроса
        period_grades_qs = getattr(obj, 'period_grades_for_stats', None)
        study_period_id = self.context.get('study_period_id')

        if period_grades_qs is None and study_period_id: # Если prefetch не сработал, делаем запрос
            period_grades_qs = Grade.objects.filter(
                student=obj,
                study_period_id=study_period_id,
                numeric_value__isnull=False
            ).select_related('subject')
        elif period_grades_qs is None:
            return []

        performance_by_subject = {}
        for grade in period_grades_qs:
            subject_id = grade.subject.id
            subject_name = grade.subject.name
            if subject_id not in performance_by_subject:
                performance_by_subject[subject_id] = {
                    'subject_name': subject_name,
                    'weighted_sum': 0,
                    'total_weight': 0,
                    'grades_count':0
                }
            if grade.numeric_value is not None and grade.weight > 0:
                performance_by_subject[subject_id]['weighted_sum'] += grade.numeric_value * grade.weight
                performance_by_subject[subject_id]['total_weight'] += grade.weight
                performance_by_subject[subject_id]['grades_count'] +=1
        
        result = []
        for subject_id, data in performance_by_subject.items():
            avg = round(data['weighted_sum'] / data['total_weight'], 2) if data['total_weight'] > 0 else None
            result.append({
                'subject_id': subject_id,
                'subject_name': data['subject_name'],
                'average_grade': avg,
                'grades_count': data['grades_count']
            })
        return sorted(result, key=lambda x: x['subject_name'])


class GroupPerformanceSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)
    curator_details = EduUserSerializer(source='curator', read_only=True, allow_null=True)
    students_performance = StudentOverallPerformanceInGroupSerializer(source='students_with_grades_for_stats', many=True, read_only=True)
    group_average_grade = serializers.SerializerMethodField()

    class Meta:
        model = StudentGroup
        fields = ('id', 'name', 'academic_year_name', 'curator_details', 'students_performance', 'group_average_grade')

    def get_group_average_grade(self, obj):
        # obj - StudentGroup
        # students_with_grades_for_stats - атрибут из prefetch во ViewSet
        students_performance_data = getattr(obj, 'students_with_grades_for_stats_data', None) # Используем кэшированные данные, если есть

        if students_performance_data is None: # Если нет кэшированных, считаем заново
            study_period_id = self.context.get('study_period_id')
            if not study_period_id: return None

            all_numeric_grades = Grade.objects.filter(
                student__student_group_memberships=obj,
                study_period_id=study_period_id,
                numeric_value__isnull=False,
                weight__gt=0
            ).aggregate(
                total_weighted_sum=Sum(F('numeric_value') * F('weight')),
                total_sum_weight=Sum('weight')
            )
            students_performance_data = all_numeric_grades # Кэшируем (хотя это не совсем то, что нужно)

        total_weighted_sum = students_performance_data.get('total_weighted_sum')
        total_sum_weight = students_performance_data.get('total_sum_weight')

        if total_sum_weight and total_sum_weight > 0:
            return round(total_weighted_sum / total_sum_weight, 2)
        return None