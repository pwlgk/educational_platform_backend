import logging
from django.forms import ValidationError
from rest_framework import serializers
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_lazy 
from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.db.models import Avg, Sum, F 
from django.utils import timezone
import datetime
from .models import (
    AcademicYear, StudyPeriod, SubjectMaterialAttachment, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)
from django.db.models import Q
from users.serializers import UserSerializer as BaseUserSerializer

logger = logging.getLogger(__name__)
User = get_user_model()

# Класс EduUserSerializer представляет собой урезанную версию основного UserSerializer,
# предназначенную для отображения информации о пользователях (студентах, преподавателях)
# в контексте образовательного модуля. Включает ID, email, ФИО, роль и профиль.
# Наследуется от BaseUserSerializer (предполагается, что это основной сериализатор пользователя).
class EduUserSerializer(BaseUserSerializer):
    class Meta(BaseUserSerializer.Meta):
        fields = ('id', 'email', 'first_name', 'last_name', 'patronymic', 'role', 'profile')

# --- Сериализаторы для Базовых Сущностей Учебного Процесса ---

# Сериализатор для модели AcademicYear (Учебный год).
# Включает все основные поля модели.
class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ('id', 'name', 'start_date', 'end_date', 'is_current')

# Сериализатор для модели StudyPeriod (Учебный период).
# - academic_year_name: Поле только для чтения, отображающее имя связанного учебного года.
# Поле academic_year используется для записи ID учебного года.
class StudyPeriodSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)

    class Meta:
        model = StudyPeriod
        fields = ('id', 'academic_year', 'academic_year_name', 'name', 'start_date', 'end_date')

# Сериализатор для модели SubjectType (Тип предмета).
class SubjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectType
        fields = ('id', 'name', 'description')

# Сериализатор для модели Subject (Учебный предмет).
# - subject_type_name: Имя связанного типа предмета (read-only).
# - lead_teachers_details: Детализированная информация о ведущих преподавателях (использует EduUserSerializer, read-only).
# Поля subject_type и lead_teachers используются для записи ID связанных объектов.
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

# Сериализатор для модели Classroom (Аудитория).
class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = ('id', 'identifier', 'capacity', 'type', 'equipment')

# Сериализатор для модели StudentGroup (Учебная группа).
# Отображает детализированную информацию о связанных объектах (учебный год, куратор, студенты, староста)
# и количество студентов (student_count) только для чтения.
# Для записи используются ID связанных объектов (academic_year, curator, students, group_monitor).
# Содержит валидацию для полей curator и group_monitor (должны иметь соответствующие роли),
# а также общую валидацию (староста должен быть студентом группы).
# Методы create и update переопределены для корректной обработки M2M-связи students.
class StudentGroupSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)
    curator_details = EduUserSerializer(source='curator', read_only=True, allow_null=True)
    students_details = EduUserSerializer(source='students', many=True, read_only=True, allow_null=True, required=False)
    group_monitor_details = EduUserSerializer(source='group_monitor', read_only=True, allow_null=True)
    student_count = serializers.IntegerField(source='students.count', read_only=True)
    academic_year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())

    class Meta:
        model = StudentGroup
        fields = (
            'id', 'name', 
            'academic_year', 'academic_year_name',
            'curator', 'curator_details',
            'students', 'students_details',
            'group_monitor', 'group_monitor_details',
            'student_count'
        )
        read_only_fields = (
            'academic_year_name', 'curator_details', 
            'students_details', 'group_monitor_details', 'student_count'
        )
        extra_kwargs = {
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
        group_monitor = data.get('group_monitor')
        students_qs_or_list = data.get('students')

        if group_monitor and students_qs_or_list:
            if isinstance(students_qs_or_list, list) and not any(s.pk == group_monitor.pk for s in students_qs_or_list if hasattr(s, 'pk')):
                 is_monitor_in_list = False
                 for s_obj in students_qs_or_list:
                     if hasattr(s_obj, 'pk') and s_obj.pk == group_monitor.pk: # Добавлена проверка hasattr
                         is_monitor_in_list = True
                         break
                 if not is_monitor_in_list:
                      raise serializers.ValidationError({'group_monitor': _("Староста должен быть одним из выбранных студентов группы.")})
        return data

    def create(self, validated_data):
        students_data = validated_data.pop('students', [])
        group = StudentGroup.objects.create(**validated_data)
        if students_data:
            group.students.set(students_data)
        return group

    def update(self, instance, validated_data):
        students_data = validated_data.pop('students', None)
        validated_data.pop('academic_year', None) # Запрет изменения учебного года
        instance = super().update(instance, validated_data)
        if students_data is not None:
            instance.students.set(students_data)
        return instance

# --- Сериализаторы для Учебных Планов ---

# Сериализатор для CurriculumEntry (Запись учебного плана).
# Отображает детали связанных объектов (предмет, преподаватель, учебный период) только для чтения.
# Вычисляет и отображает scheduled_hours (запланировано в расписании) и remaining_hours (осталось по плану).
# curriculum_id - ID учебного плана для чтения. Поля curriculum, subject, teacher, study_period - для записи ID.
class CurriculumEntrySerializer(serializers.ModelSerializer):
    subject_details = SubjectSerializer(source='subject', read_only=True)
    teacher_details = EduUserSerializer(source='teacher', read_only=True, allow_null=True)
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True)
    scheduled_hours = serializers.FloatField(read_only=True, default=0.0)
    remaining_hours = serializers.FloatField(read_only=True, default=0.0)
    curriculum_id = serializers.IntegerField(source='curriculum.id', read_only=True) 

    class Meta:
        model = CurriculumEntry
        fields = (
            'id', 'curriculum', 'curriculum_id',
            'subject', 'subject_details', 'teacher', 'teacher_details',
            'study_period', 'study_period_details', 'planned_hours',
            'scheduled_hours', 'remaining_hours'
        )
        extra_kwargs = {
            'curriculum': {'queryset': Curriculum.objects.all()}, 
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'teacher': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'study_period': {'write_only': True, 'queryset': StudyPeriod.objects.all()},
        }

# Сериализатор для Curriculum (Учебный план).
# - academic_year_details, student_group_details: Детализированная информация (read-only).
# - entries: Список записей учебного плана (использует CurriculumEntrySerializer, read-only).
# Поля academic_year, student_group используются для записи ID.
class CurriculumSerializer(serializers.ModelSerializer):
    academic_year_details = AcademicYearSerializer(source='academic_year', read_only=True)
    student_group_details = StudentGroupSerializer(source='student_group', read_only=True)
    entries = CurriculumEntrySerializer(many=True, read_only=True)

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

# Сериализатор для Lesson (Занятие).
# Отображает детали связанных объектов (учебный период, группа, предмет, преподаватель, аудитория,
# запись уч. плана, создатель) только для чтения.
# duration_hours - вычисляемая продолжительность занятия (read-only).
# Для записи используются ID связанных объектов.
# Метод validate вызывает метод clean() модели Lesson для комплексной валидации данных занятия.
class LessonSerializer(serializers.ModelSerializer):
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True)
    student_group_details = StudentGroupSerializer(source='student_group', read_only=True)
    subject_details = SubjectSerializer(source='subject', read_only=True)
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
        read_only_fields = ('created_at', 'updated_at', 'created_by_details', 'duration_hours') # created_by может устанавливаться во view
        extra_kwargs = {
            'study_period': {'write_only': True, 'queryset': StudyPeriod.objects.all()},
            'student_group': {'write_only': True, 'queryset': StudentGroup.objects.all()},
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'teacher': {'write_only': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'classroom': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': Classroom.objects.all()},
            'curriculum_entry': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': CurriculumEntry.objects.all()},
            'created_by': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': User.objects.all()} # Обычно устанавливается автоматически
        }

    def validate(self, data):
        instance = self.instance # Если это update, instance будет доступен
        
        # Собираем данные для clean() модели
        # Если поле есть в data -> берем его
        # Если поля нет в data, но есть instance (обновление) -> берем из instance
        # Если поля нет ни там, ни там (создание, поле не передано) -> будет None или default модели
        model_data = {
            field.name: data.get(field.name, getattr(instance, field.name, None))
            for field in Lesson._meta.fields
        }
        # Убираем None значения для полей, которые не были переданы и не имеют значения в instance,
        # чтобы не передавать их в конструктор модели, если у них есть default.
        # Или же можно передавать их как есть, если конструктор модели это корректно обработает.
        final_model_data = {k: v for k, v in model_data.items() if v is not None or k in data}


        # Создаем временный экземпляр Lesson (или используем существующий) для вызова clean
        # Важно! ForeignKey поля в final_model_data должны быть экземплярами моделей, а не ID,
        # если мы хотим корректно вызвать clean() на временном объекте.
        # Сериализатор DRF обычно преобразует ID в объекты в validated_data для FK.
        
        # Для создания нового экземпляра:
        temp_lesson = Lesson(**final_model_data)
        if instance: # Если это обновление, pk должен быть сохранен
            temp_lesson.pk = instance.pk

        try:
            temp_lesson.clean() # Вызов валидации модели
        except ValidationError as e:
            # Преобразуем ошибку валидации Django в ошибку DRF
            raise serializers.ValidationError(serializers.as_serializer_error(e))
        return data

# Сериализатор LessonListSerializer для краткого отображения занятий в списках.
# Отображает имена связанных объектов и вычисляемую продолжительность.
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

# Сериализатор для LessonJournalEntry (Запись в журнале занятия).
# - lesson_details: Краткая информация о связанном занятии (использует LessonListSerializer, read-only).
# Поле lesson используется для записи ID.
class LessonJournalEntrySerializer(serializers.ModelSerializer):
    lesson_details = LessonListSerializer(source='lesson', read_only=True)

    class Meta:
        model = LessonJournalEntry
        fields = ('id', 'lesson', 'lesson_details', 'topic_covered', 'teacher_notes', 'date_filled')
        extra_kwargs = {
            'lesson': {'write_only': True, 'queryset': Lesson.objects.all()},
        }

# Сериализатор для SubjectMaterialAttachment (Вложение к учебному материалу).
# - file_url, file_name: URL и имя файла (read-only).
class SubjectMaterialAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.URLField(source='file.url', read_only=True) # Было FileField, изменил на URLField
    file_name = serializers.CharField(source='file.name', read_only=True)

    class Meta:
        model = SubjectMaterialAttachment
        fields = ('id','subject_material', 'file', 'file_name', 'file_url', 'description', 'uploaded_at') # Добавил subject_material и file
        read_only_fields = ('id', 'file_name', 'file_url', 'uploaded_at')
        extra_kwargs = { # Для создания через вложенные операции или отдельные эндпоинты
            'subject_material': {'write_only': True, 'queryset': SubjectMaterial.objects.all()},
            'file': {'write_only': True, 'required': True}
        }


# Сериализатор для SubjectMaterial (Учебный материал).
# - Отображает детали связанных объектов (предмет, группа, загрузивший) только для чтения.
# - attachments: Список прикрепленных файлов (использует SubjectMaterialAttachmentSerializer, read-only).
# - files_to_upload: Поле для загрузки файлов при создании/обновлении (write-only).
# Методы create и update переопределены для обработки загрузки файлов и их связи с материалом.
class SubjectMaterialSerializer(serializers.ModelSerializer):
    subject_details = SubjectSerializer(source='subject', read_only=True)
    student_group_details = StudentGroupSerializer(source='student_group', read_only=True, allow_null=True)
    uploaded_by_details = EduUserSerializer(source='uploaded_by', read_only=True, allow_null=True)
    attachments = SubjectMaterialAttachmentSerializer(many=True, read_only=True)
    files_to_upload = serializers.ListField(
        child=serializers.FileField(allow_empty_file=False, use_url=False),
        write_only=True, required=False
    )

    class Meta:
        model = SubjectMaterial
        fields = (
            'id', 'subject', 'subject_details', 'student_group', 'student_group_details',
            'title', 'description', 'uploaded_by', 'uploaded_by_details', 'uploaded_at',
            'attachments', 'files_to_upload',
        )
        read_only_fields = (
            'uploaded_by_details', 'uploaded_at', 'attachments',
            'subject_details', 'student_group_details'
        )
        extra_kwargs = {
            'subject': {'queryset': Subject.objects.all()}, # Убрал write_only, если нужно и читать ID
            'student_group': {'queryset': StudentGroup.objects.all(), 'required': False, 'allow_null': True},
            'uploaded_by': {'required': False, 'allow_null': True, 'queryset': User.objects.all()},
        }

    @transaction.atomic
    def create(self, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', [])
        if 'uploaded_by' not in validated_data and self.context['request'].user.is_authenticated:
            validated_data['uploaded_by'] = self.context['request'].user
        material = SubjectMaterial.objects.create(**validated_data)
        for file_data in files_to_upload:
            SubjectMaterialAttachment.objects.create(subject_material=material, file=file_data)
        return material

    @transaction.atomic
    def update(self, instance, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', None)
        instance = super().update(instance, validated_data)
        if files_to_upload is not None:
            # Логика добавления/удаления файлов при обновлении
            # Например, можно удалить старые и добавить новые, или просто добавить новые
            # instance.attachments.all().delete() # Если новая загрузка заменяет старые
            for file_data in files_to_upload:
                SubjectMaterialAttachment.objects.create(subject_material=instance, file=file_data)
        return instance

# Сериализатор для HomeworkAttachment (Вложение к домашнему заданию).
# - file_url: URL файла (read-only). Поля homework и file - для записи.
class HomeworkAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.URLField(source='file.url', read_only=True) # Было FileField
    class Meta:
        model = HomeworkAttachment
        fields = ('id', 'homework', 'file', 'file_url', 'description', 'uploaded_at')
        read_only_fields = ('uploaded_at', 'file_url')
        extra_kwargs = {
            'homework': {'write_only': True, 'queryset': Homework.objects.all()},
            'file': {'write_only': True, 'required': True},
        }

# Сериализатор для Homework (Домашнее задание).
# Отображает ID и название предмета связанного урока, детали автора, вложения и связанные материалы.
# Поля для записи: journal_entry (ID), author (ID), related_materials (список ID).
# Поля для загрузки файлов и связывания материалов: files_to_upload, material_ids_to_link.
# Поле для удаления вложений: attachments_to_remove_ids.
# Методы create и update переопределены для сложной логики обработки файлов и связей.
class HomeworkSerializer(serializers.ModelSerializer):
    lesson_id = serializers.IntegerField(source='journal_entry.lesson.id', read_only=True)
    lesson_subject = serializers.CharField(source='journal_entry.lesson.subject.name', read_only=True)
    author_details = EduUserSerializer(source='author', read_only=True, allow_null=True)
    attachments = HomeworkAttachmentSerializer(many=True, read_only=True)
    related_materials_details = SubjectMaterialSerializer(source='related_materials', many=True, read_only=True)
    files_to_upload = serializers.ListField(child=serializers.FileField(allow_empty_file=False, use_url=False), write_only=True, required=False)
    material_ids_to_link = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    attachments_to_remove_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False, help_text="Список ID вложений для удаления.")

    class Meta:
        model = Homework
        fields = (
            'id', 'journal_entry', 'lesson_id', 'lesson_subject', 'title', 'description', 'due_date',
            'created_at', 'author', 'author_details',
            'attachments', 'related_materials', 'related_materials_details',
            'files_to_upload', 'material_ids_to_link', 'attachments_to_remove_ids'
        )
        read_only_fields = ('created_at', 'author_details', 'attachments', 'related_materials_details', 'lesson_id', 'lesson_subject')
        extra_kwargs = {
            'journal_entry': {'queryset': LessonJournalEntry.objects.all()}, # Убрал write_only
            'author': {'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)}, # Убрал write_only
            'related_materials': {'required': False, 'queryset': SubjectMaterial.objects.all()}, # Убрал write_only
        }

    @transaction.atomic
    def create(self, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', [])
        material_ids = validated_data.pop('material_ids_to_link', [])
        # related_materials теперь напрямую из validated_data, если оно там есть
        related_materials_input = validated_data.pop('related_materials', [])


        homework = Homework.objects.create(**validated_data)

        for file_data in files_to_upload:
            HomeworkAttachment.objects.create(homework=homework, file=file_data)
        
        materials_to_set = list(related_materials_input) # Используем напрямую, т.к. это уже queryset или список объектов
        if material_ids: # Если переданы ID, добавляем их
            materials_to_set.extend(list(SubjectMaterial.objects.filter(id__in=material_ids)))
        
        if materials_to_set:
            homework.related_materials.set(list(set(materials_to_set))) # Уникализация

        return homework

    @transaction.atomic
    def update(self, instance, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', None)
        material_ids_to_link = validated_data.pop('material_ids_to_link', None)
        # related_materials напрямую из validated_data
        related_materials_input = validated_data.pop('related_materials', None)
        attachments_to_remove_ids = validated_data.pop('attachments_to_remove_ids', None)

        if attachments_to_remove_ids is not None:
            if not isinstance(attachments_to_remove_ids, list):
                raise serializers.ValidationError({'attachments_to_remove_ids': _("Должен быть список ID.")})
            instance.attachments.filter(id__in=attachments_to_remove_ids).delete()
            
        instance = super().update(instance, validated_data) # Обновляем основные поля

        if files_to_upload is not None:
            for file_data in files_to_upload:
                HomeworkAttachment.objects.create(homework=instance, file=file_data)

        if related_materials_input is not None: # Если передан новый queryset/список
            instance.related_materials.set(related_materials_input)
        elif material_ids_to_link is not None: # Если передан список ID
            materials = SubjectMaterial.objects.filter(id__in=material_ids_to_link) if material_ids_to_link else []
            instance.related_materials.set(materials)
            
        return instance

# Сериализатор для SubmissionAttachment (Вложение к сданной работе).
class SubmissionAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.URLField(source='file.url', read_only=True) # Было FileField
    class Meta:
        model = SubmissionAttachment
        fields = ('id', 'submission', 'file', 'file_url', 'uploaded_at')
        read_only_fields = ('uploaded_at', 'file_url')
        extra_kwargs = {
            'submission': {'write_only': True, 'queryset': HomeworkSubmission.objects.all()},
            'file': {'write_only': True, 'required': True},
        }

# Сериализатор для HomeworkSubmission (Сданная работа).
# Отображает название ДЗ, детали студента, вложения и детали оценки.
# files_to_upload - для загрузки файлов студентом.
# Метод create обрабатывает создание сдачи и прикрепление файлов.
class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    homework_title = serializers.CharField(source='homework.title', read_only=True)
    student_details = EduUserSerializer(source='student', read_only=True)
    attachments = SubmissionAttachmentSerializer(many=True, read_only=True)
    grade_details = serializers.SerializerMethodField() # Будет использовать GradeSerializer
    files_to_upload = serializers.ListField(child=serializers.FileField(allow_empty_file=False, use_url=False), write_only=True, required=False)

    class Meta:
        model = HomeworkSubmission
        fields = (
            'id', 'homework', 'homework_title', 'student', 'student_details',
            'submitted_at', 'content', 'attachments', 'grade_details', 'files_to_upload'
        )
        read_only_fields = ('submitted_at', 'student_details', 'attachments', 'grade_details', 'homework_title')
        extra_kwargs = {
            'homework': {'queryset': Homework.objects.all()}, # Убрал write_only
            'student': {'read_only':True, 'required': False, 'allow_null':True}, # Студент устанавливается из request.user
            'content': {'required': False, 'allow_blank': True},
        }

    def get_grade_details(self, obj):
        try:
            grade = obj.grade_for_submission # grade_for_submission - related_name от OneToOneField в Grade
            return GradeSerializer(grade, context=self.context).data
        except Grade.DoesNotExist: # Или AttributeError, если related_name другой
            return None

    @transaction.atomic
    def create(self, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', [])
        # Студент устанавливается во ViewSet из request.user
        # validated_data['student'] = self.context['request'].user 
        submission = HomeworkSubmission.objects.create(**validated_data)
        for file_data in files_to_upload:
            SubmissionAttachment.objects.create(submission=submission, file=file_data)
        return submission

# Сериализатор для Attendance (Посещаемость).
# Отображает ID урока, детали студента и того, кто отметил.
# Поля journal_entry и student - для записи ID.
class AttendanceSerializer(serializers.ModelSerializer):
    lesson_id = serializers.IntegerField(source='journal_entry.lesson.id', read_only=True)
    student_details = EduUserSerializer(source='student', read_only=True)
    marked_by_details = EduUserSerializer(source='marked_by', read_only=True, allow_null=True)

    class Meta:
        model = Attendance
        fields = (
            'id', 'journal_entry', 'lesson_id', 'student', 'student_details',
            'status', 'comment', 'marked_at', 'marked_by', 'marked_by_details'
        )
        read_only_fields = ('marked_at', 'marked_by_details', 'lesson_id') # marked_by может устанавливаться во view
        extra_kwargs = {
            'journal_entry': {'queryset': LessonJournalEntry.objects.all()}, # Убрал write_only
            'student': {'queryset': User.objects.filter(role=User.Role.STUDENT)}, # Убрал write_only
            'marked_by': {'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)} # Убрал write_only
        }

# Сериализатор LiteHomeworkSubmissionSerializer - это легковесная версия для встраивания,
# например, в GradeSerializer, чтобы избежать циклических зависимостей или избыточности данных.
class LiteHomeworkSubmissionSerializer(serializers.ModelSerializer):
    homework_title = serializers.CharField(source='homework.title', read_only=True)
    student_details = EduUserSerializer(source='student', read_only=True)
    attachments = SubmissionAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = HomeworkSubmission
        fields = ('id', 'homework_title', 'student_details', 'submitted_at', 'content', 'attachments')
        read_only_fields = fields

# Сериализатор для Grade (Оценка).
# Отображает детали студента, предмета, периода, урока, сданного ДЗ, и того, кто выставил оценку.
# Содержит логику валидации в методе validate(), которая дублирует и расширяет проверки из model.clean().
# Методы create и update содержат логику для автоматической установки graded_by и связанных периодов/годов.
class GradeSerializer(serializers.ModelSerializer):
    student_details = EduUserSerializer(source='student', read_only=True)
    subject_details = SubjectSerializer(source='subject', read_only=True)
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True, allow_null=True)
    academic_year_details = AcademicYearSerializer(source='academic_year', read_only=True, allow_null=True)
    lesson_details = LessonListSerializer(source='lesson', read_only=True, allow_null=True)
    homework_submission_details = LiteHomeworkSubmissionSerializer(source='homework_submission', read_only=True, allow_null=True)
    graded_by_details = EduUserSerializer(source='graded_by', read_only=True, allow_null=True)
    lesson_id = serializers.IntegerField(source='lesson.id', read_only=True, allow_null=True)

    class Meta:
        model = Grade
        fields = (
            'id', 'student', 'student_details', 'subject', 'subject_details',
            'study_period', 'study_period_details',
            'academic_year', 'academic_year_details',
            'lesson','lesson_id', 'lesson_details', # lesson - для записи ID, lesson_id - для чтения ID
            'homework_submission', 'homework_submission_details',
            'grade_value', 'numeric_value', 'grade_type', 'date_given', 'comment',
            'graded_by', 'graded_by_details', 'weight'
        )
        read_only_fields = (
            'student_details', 'subject_details', 'study_period_details',
            'academic_year_details', 'lesson_id', 'lesson_details', 'homework_submission_details', # Добавил lesson_id
            'graded_by_details'
        )
        extra_kwargs = {
            'student': {'queryset': User.objects.filter(role=User.Role.STUDENT)},
            'subject': {'queryset': Subject.objects.all()},
            'study_period': {'queryset': StudyPeriod.objects.all(), 'required': False, 'allow_null': True},
            'academic_year': {'queryset': AcademicYear.objects.all(), 'required': False, 'allow_null': True},
            'lesson': {'queryset': Lesson.objects.all(), 'required': False, 'allow_null': True},
            'homework_submission': {'queryset': HomeworkSubmission.objects.all(), 'required': False, 'allow_null': True},
            'graded_by': {'required':False, 'allow_null':True, 'queryset':User.objects.filter(role=User.Role.TEACHER)}
        }

    def validate(self, data):
        # Логика валидации, адаптированная из предыдущей версии
        # Необходимо учитывать, что при PATCH не все поля могут быть переданы
        
        # Получаем значения либо из data, либо из instance (если обновление)
        # Для валидации новых или изменяемых значений, приоритет data.
        grade_type = data.get('grade_type', getattr(self.instance, 'grade_type', None))
        study_period = data.get('study_period', getattr(self.instance, 'study_period', None))
        academic_year = data.get('academic_year', getattr(self.instance, 'academic_year', None))
        lesson = data.get('lesson', getattr(self.instance, 'lesson', None))
        homework_submission = data.get('homework_submission', getattr(self.instance, 'homework_submission', None))

        # Переопределяем значения, если они явно переданы в data (даже если это None для сброса)
        if 'study_period' in data: study_period = data['study_period']
        if 'academic_year' in data: academic_year = data['academic_year']
        if 'lesson' in data: lesson = data['lesson']
        if 'homework_submission' in data: homework_submission = data['homework_submission']


        # Авто-определение study_period и academic_year
        if lesson:
            if study_period is None or ('study_period' not in data and self.instance and self.instance.lesson != lesson): # Если урок меняется, а период не передан
                study_period = lesson.study_period
            if academic_year is None and study_period:
                academic_year = study_period.academic_year
        elif study_period and academic_year is None:
             academic_year = study_period.academic_year
        
        # Валидация на основе типа оценки
        if grade_type in [Grade.GradeType.YEAR_FINAL, Grade.GradeType.YEAR_AVERAGE]:
            if study_period: raise serializers.ValidationError({'study_period': _("Для годовых оценок учебный период не указывается.")})
            if not academic_year: raise serializers.ValidationError({'academic_year': _("Для годовых оценок необходимо указать учебный год.")})
            if lesson or homework_submission: raise serializers.ValidationError(_("Годовые оценки не должны быть привязаны к конкретному занятию или ДЗ."))
        elif grade_type in [Grade.GradeType.PERIOD_FINAL, Grade.GradeType.PERIOD_AVERAGE]:
            if not study_period: raise serializers.ValidationError({'study_period': _("Для итоговых оценок за период необходимо указать учебный период.")})
            if lesson or homework_submission: raise serializers.ValidationError(_("Итоговые оценки за период не должны быть привязаны к конкретному занятию или ДЗ."))
        else: # Текущие оценки
            if not study_period: raise serializers.ValidationError({'study_period': _("Для текущих оценок необходимо указать учебный период.")})
            if grade_type == Grade.GradeType.LESSON_WORK and not lesson:
                raise serializers.ValidationError({'lesson': _("Для оценки за работу на занятии необходимо указать занятие.")})
            if grade_type == Grade.GradeType.HOMEWORK_GRADE and not homework_submission:
                raise serializers.ValidationError({'homework_submission': _("Для оценки за ДЗ необходимо указать сданную работу.")})

        if academic_year and study_period:
            if study_period.academic_year != academic_year:
                raise serializers.ValidationError(
                    _("Указанный учебный период (ID: %(period_id)s) не принадлежит указанному учебному году (ID: %(year_id)s).") %
                    {'period_id': study_period.id, 'year_id': academic_year.id}
                )
        return data

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, "user") and request.user.is_authenticated:
           if 'graded_by' not in validated_data or not validated_data['graded_by']:
               if hasattr(request.user, 'role') and request.user.role == User.Role.TEACHER:
                   validated_data['graded_by'] = request.user
        
        lesson = validated_data.get('lesson')
        study_period = validated_data.get('study_period')
        academic_year = validated_data.get('academic_year')

        if lesson: # Если есть урок, берем из него период и год
            validated_data.setdefault('study_period', lesson.study_period)
            if validated_data.get('study_period'): # Убедимся, что study_period теперь есть
                 validated_data.setdefault('academic_year', validated_data['study_period'].academic_year)
        elif study_period and not academic_year: # Если есть период, но нет года
            validated_data['academic_year'] = study_period.academic_year
        
        # Проверяем, что student и subject переданы (они обязательны по модели)
        if 'student' not in validated_data or 'subject' not in validated_data:
            raise serializers.ValidationError(_("Поля 'student' и 'subject' обязательны для создания оценки."))


        return super().create(validated_data)

    def update(self, instance, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, "user") and request.user.is_authenticated:
            if 'graded_by' in validated_data and not validated_data['graded_by']: # Если передали null
                if hasattr(request.user, 'role') and request.user.role == User.Role.TEACHER:
                    validated_data['graded_by'] = request.user
            elif 'graded_by' not in validated_data and instance.graded_by is None: # Если не передали, и было null
                if hasattr(request.user, 'role') and request.user.role == User.Role.TEACHER:
                    validated_data['graded_by'] = request.user
        
        # Логика обновления study_period и academic_year при изменении lesson
        lesson = validated_data.get('lesson', instance.lesson) # Учитываем текущее значение, если не передано
        study_period = validated_data.get('study_period', instance.study_period)
        # academic_year = validated_data.get('academic_year', instance.academic_year) # academic_year зависит от study_period

        if 'lesson' in validated_data: # Если lesson явно изменяется
            if lesson: # Если новый lesson не None
                validated_data.setdefault('study_period', lesson.study_period)
                if validated_data.get('study_period'): # Если study_period теперь есть (из lesson или был передан)
                    validated_data.setdefault('academic_year', validated_data['study_period'].academic_year)
            else: # Если lesson сбрасывается в None
                # study_period и academic_year могут потребовать явного указания или сброса,
                # если они не соответствуют новому состоянию (например, тип оценки не годовой/периодный)
                pass # Оставляем как есть, валидация должна это покрыть

        elif 'study_period' in validated_data: # Если lesson не меняется, но study_period меняется
            if study_period:
                validated_data.setdefault('academic_year', study_period.academic_year)
            else: # study_period сбрасывается в None
                grade_type = validated_data.get('grade_type', instance.grade_type)
                if grade_type not in [Grade.GradeType.YEAR_FINAL, Grade.GradeType.YEAR_AVERAGE]:
                     validated_data['academic_year'] = None # Сбрасываем и год, если не годовая оценка


        return super().update(instance, validated_data)

# --- Сериализаторы для Ролевых Представлений (Студент, Родитель) ---

# Сериализатор MyGradeSerializer для отображения оценок студенту/родителю.
# Исключает поля 'student' и 'student_details', так как оценки показываются для "своего" студента.
class MyGradeSerializer(GradeSerializer):
    class Meta:
        model = Grade
        fields = (
            'id', 'subject', 'subject_details', 'study_period', 'study_period_details',
            'lesson', 'lesson_details', 'lesson_id',
            'homework_submission', 'homework_submission_details',
            'grade_value', 'numeric_value', 'grade_type', 'date_given', 'comment',
            'graded_by_details', 'weight'
        )
        read_only_fields = fields # Все поля только для чтения

# Сериализатор MyAttendanceSerializer для отображения посещаемости студенту/родителю.
# Исключает поля, связанные со студентом и тем, кто отметил.
class MyAttendanceSerializer(AttendanceSerializer):
     class Meta:
         model = Attendance
         fields = (
             'id', 'journal_entry', 'lesson_id',
             'status', 'comment', 'marked_at',
         )
         read_only_fields = fields

# Сериализатор MyHomeworkSerializer для отображения домашних заданий студенту/родителю.
# Добавляет поля submission_details_for_child, submission_status_for_child, grade_for_child_submission
# для отображения статуса сдачи и оценки конкретного ребенка (если применимо).
# Логика определения целевого студента и его сдачи находится во вспомогательных методах.
class MyHomeworkSerializer(HomeworkSerializer):
    STATUS_SUBMITTED_GRADED = _("Сдано (Оценено: {grade})")
    STATUS_SUBMITTED_PENDING = _("Сдано (Ожидает проверки)")
    STATUS_NOT_SUBMITTED_EXPIRED = _("Не сдано (Срок истек)")
    STATUS_NOT_SUBMITTED = _("Не сдано")
    STATUS_NO_HOMEWORK_DATA = _("N/A")

    submission_details_for_child = serializers.SerializerMethodField() 
    submission_status_for_child = serializers.SerializerMethodField()
    grade_for_child_submission = serializers.SerializerMethodField()

    class Meta(HomeworkSerializer.Meta):
        fields = (
            'id', 'lesson_id', 'lesson_subject', 'title', 'description', 'due_date',
            'created_at', 'author_details', 'attachments', 'related_materials_details',
            'submission_details_for_child', 'submission_status_for_child', 'grade_for_child_submission',
        )
        read_only_fields = fields

    def _get_target_student_for_homework(self, homework_obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated: return None
        user = request.user
        if user.is_student: return user
        if user.is_parent:
            target_children_ids = self.context.get('target_children_ids_for_serializer', [])
            if len(target_children_ids) == 1:
                try: return User.objects.get(pk=target_children_ids[0], role=User.Role.STUDENT)
                except User.DoesNotExist: return None
            elif not target_children_ids: return None
            else:
                logger.debug(f"MyHomeworkSerializer: Parent {user.email} HW list for multiple children. Specific status N/A for HW ID {homework_obj.id}.")
                return None 
        return None

    def _get_submission_for_student(self, homework_obj, student):
        if not student or not hasattr(homework_obj, 'my_current_submission_list'): return None
        for submission in homework_obj.my_current_submission_list:
            if submission.student_id == student.id: return submission
        return None

    def get_submission_details_for_child(self, obj: Homework):
        target_student = self._get_target_student_for_homework(obj)
        if not target_student: return None
        submission = self._get_submission_for_student(obj, target_student)
        if submission:
            return {
                'id': submission.id,
                'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
                'content': submission.content,
            }
        return None

    def get_submission_status_for_child(self, obj: Homework):
        target_student = self._get_target_student_for_homework(obj)
        if not target_student: return self.STATUS_NO_HOMEWORK_DATA
        submission = self._get_submission_for_student(obj, target_student)
        if submission:
            grade = None
            try: grade = submission.grade_for_submission
            except Grade.DoesNotExist: pass
            if grade: return str(self.STATUS_SUBMITTED_GRADED).format(grade=grade.grade_value)
            return str(self.STATUS_SUBMITTED_PENDING)
        elif obj.due_date and timezone.now() > obj.due_date:
            return str(self.STATUS_NOT_SUBMITTED_EXPIRED)
        return str(self.STATUS_NOT_SUBMITTED)

    def get_grade_for_child_submission(self, obj: Homework):
        target_student = self._get_target_student_for_homework(obj)
        if not target_student: return None
        submission = self._get_submission_for_student(obj, target_student)
        if submission:
            grade = None
            try: grade = submission.grade_for_submission
            except Grade.DoesNotExist: pass
            if grade:
                return {
                    'grade_value': grade.grade_value, 'numeric_value': grade.numeric_value,
                    'comment': grade.comment, 'date_given': grade.date_given.isoformat() if grade.date_given else None,
                    'graded_by': EduUserSerializer(grade.graded_by, context=self.context).data if grade.graded_by else None
                }
        return None

# Сериализатор StudentHomeworkSubmissionSerializer для создания/обновления сдачи ДЗ студентом.
# Наследуется от HomeworkSubmissionSerializer, но делает поля homework и student read-only,
# так как они обычно устанавливаются из URL и request.user соответственно.
# Добавляет поле homework_id для указания ID ДЗ при создании.
class StudentHomeworkSubmissionSerializer(HomeworkSubmissionSerializer):
    # homework_id = serializers.PrimaryKeyRelatedField(queryset=Homework.objects.all(), source='homework', write_only=True) # Заменил

    class Meta(HomeworkSubmissionSerializer.Meta): # Наследуем Meta
        # Переопределяем поля, делая homework write_only для создания по ID
        # student будет устанавливаться из контекста (request.user)
        fields = tuple(f for f in HomeworkSubmissionSerializer.Meta.fields if f not in ['student', 'student_details', 'homework']) + \
                 ('homework_id',) # Добавляем homework_id
        
        read_only_fields = ('submitted_at', 'attachments', 'grade_details', 'homework_title') # student и homework убраны отсюда
        
        extra_kwargs = {
            # homework_id будет использоваться для связи с Homework при создании
            'homework_id': {'write_only': True, 'required': True, 'source': 'homework', 'queryset': Homework.objects.all()},
            'content': {'required': False, 'allow_blank': True},
            # 'student' здесь не нужен, он будет установлен во ViewSet
        }

# --- Сериализаторы для Импорта (требуют адаптации под конкретный формат CSV/Excel) ---

# Сериализатор TeacherImportSerializer для импорта данных преподавателей.
# Содержит метод create_or_update_teacher для создания/обновления пользователя с ролью TEACHER.
class TeacherImportSerializer(serializers.Serializer):
    email = serializers.EmailField()
    last_name = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150)
    patronymic = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def create_or_update_teacher(self, data):
        user, created = User.objects.update_or_create(
            email=data['email'],
            defaults={
                'first_name': data['first_name'], 'last_name': data['last_name'],
                'patronymic': data.get('patronymic', ''),
                'role': User.Role.TEACHER, 'is_active': True, 'is_role_confirmed': True,
            }
        )
        if created: user.set_password(User.objects.make_random_password()); user.save()
        return user

# Сериализатор SubjectImportSerializer для импорта данных учебных предметов.
# Обрабатывает создание/получение связанного SubjectType по имени.
class SubjectImportSerializer(serializers.ModelSerializer):
    subject_type_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    class Meta: model = Subject; fields = ('name', 'code', 'description', 'subject_type_name')
    def create(self, validated_data):
        subject_type_name = validated_data.pop('subject_type_name', None)
        subject_type = None
        if subject_type_name: subject_type, _ = SubjectType.objects.get_or_create(name=subject_type_name)
        validated_data['subject_type'] = subject_type
        subject, _ = Subject.objects.update_or_create(name=validated_data['name'], defaults=validated_data)
        return subject

# Сериализатор StudentGroupImportSerializer для импорта данных учебных групп.
# Обрабатывает создание/получение учебного года, куратора и студентов по email.
class StudentGroupImportSerializer(serializers.Serializer):
    group_name = serializers.CharField()
    academic_year_name = serializers.CharField()
    curator_email = serializers.EmailField(required=False, allow_null=True)
    student_emails = serializers.CharField(help_text="Emails через точку с запятой (;)")

    def create_or_update_group(self, data):
        try: academic_year = AcademicYear.objects.get(name=data['academic_year_name'])
        except AcademicYear.DoesNotExist: raise serializers.ValidationError(f"Учебный год '{data['academic_year_name']}' не найден.")
        curator = None
        if data.get('curator_email'):
            try: curator = User.objects.get(email=data['curator_email'], role=User.Role.TEACHER)
            except User.DoesNotExist: raise serializers.ValidationError(f"Куратор с email '{data['curator_email']}' не найден или не преподаватель.")
        group, created = StudentGroup.objects.update_or_create(
            name=data['group_name'], academic_year=academic_year, defaults={'curator': curator}
        )
        student_emails_list = [email.strip() for email in data.get('student_emails', '').split(';') if email.strip()]
        students_to_add = []
        for email in student_emails_list:
            student, stud_created = User.objects.get_or_create(
                email=email, defaults={'role': User.Role.STUDENT, 'is_active': True, 'is_role_confirmed': True}
            )
            if stud_created: student.set_password(User.objects.make_random_password()); student.save()
            students_to_add.append(student)
        if students_to_add: group.students.set(students_to_add)
        return group

# --- Сериализаторы для Статистики ---

# Сериализатор TeacherLoadSerializer для отображения нагрузки преподавателя.
class TeacherLoadSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, source='pk')
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    email = serializers.EmailField(read_only=True)
    total_planned_hours = serializers.FloatField(read_only=True, default=0.0)
    scheduled_lesson_count = serializers.IntegerField(read_only=True, default=0)
    total_scheduled_hours_float = serializers.FloatField(read_only=True, default=0.0)

# Сериализатор GroupSubjectPerformanceStatSerializer для статистики успеваемости группы по предмету.
class GroupSubjectPerformanceStatSerializer(serializers.Serializer):
    subject_id = serializers.IntegerField()
    subject_name = serializers.CharField()
    average_grade = serializers.DecimalField(max_digits=4, decimal_places=2, allow_null=True)
    grades_count = serializers.IntegerField()

# Сериализатор TeacherSubjectPerformanceSerializer для успеваемости по предметам у преподавателя.
# Включает список GroupSubjectPerformanceStatSerializer для каждой группы.
class TeacherSubjectPerformanceSerializer(serializers.Serializer):
    teacher_id = serializers.IntegerField()
    teacher_name = serializers.CharField()
    groups_data = GroupSubjectPerformanceStatSerializer(many=True, read_only=True)

# Сериализатор StudentOverallPerformanceInGroupSerializer для общей успеваемости студента в группе.
# Наследуется от EduUserSerializer, добавляя среднюю оценку за период и детали успеваемости по предметам.
class StudentOverallPerformanceInGroupSerializer(EduUserSerializer):
    average_grade_for_period = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True, allow_null=True)
    subject_performance_details = serializers.SerializerMethodField(read_only=True)

    class Meta(EduUserSerializer.Meta):
        fields = EduUserSerializer.Meta.fields + ('average_grade_for_period', 'subject_performance_details')

    def get_subject_performance_details(self, obj):
        period_grades_qs = getattr(obj, 'period_grades_for_stats', None)
        study_period_id = self.context.get('study_period_id')
        if period_grades_qs is None and study_period_id:
            period_grades_qs = Grade.objects.filter(
                student=obj, study_period_id=study_period_id, numeric_value__isnull=False
            ).select_related('subject')
        elif period_grades_qs is None: return []
        performance_by_subject = {}
        for grade in period_grades_qs:
            subject_id = grade.subject.id
            subject_name = grade.subject.name
            if subject_id not in performance_by_subject:
                performance_by_subject[subject_id] = {'subject_name': subject_name, 'weighted_sum': 0, 'total_weight': 0, 'grades_count':0}
            if grade.numeric_value is not None and grade.weight > 0:
                performance_by_subject[subject_id]['weighted_sum'] += grade.numeric_value * grade.weight
                performance_by_subject[subject_id]['total_weight'] += grade.weight
                performance_by_subject[subject_id]['grades_count'] +=1
        result = []
        for subject_id, data in performance_by_subject.items():
            avg = round(data['weighted_sum'] / data['total_weight'], 2) if data['total_weight'] > 0 else None
            result.append({'subject_id': subject_id, 'subject_name': data['subject_name'], 'average_grade': avg, 'grades_count': data['grades_count']})
        return sorted(result, key=lambda x: x['subject_name'])

# Сериализатор GroupPerformanceSerializer для общей успеваемости группы.
# Включает список StudentOverallPerformanceInGroupSerializer для каждого студента и среднюю оценку по группе.
class GroupPerformanceSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)
    curator_details = EduUserSerializer(source='curator', read_only=True, allow_null=True)
    students_performance = StudentOverallPerformanceInGroupSerializer(source='students_with_grades_for_stats', many=True, read_only=True)
    group_average_grade = serializers.SerializerMethodField()

    class Meta:
        model = StudentGroup
        fields = ('id', 'name', 'academic_year_name', 'curator_details', 'students_performance', 'group_average_grade')

    def get_group_average_grade(self, obj):
        students_performance_data = getattr(obj, 'students_with_grades_for_stats_data', None)
        if students_performance_data is None:
            study_period_id = self.context.get('study_period_id')
            if not study_period_id: return None
            students_performance_data = Grade.objects.filter(
                student__student_group_memberships=obj, study_period_id=study_period_id,
                numeric_value__isnull=False, weight__gt=0
            ).aggregate(total_weighted_sum=Sum(F('numeric_value') * F('weight')), total_sum_weight=Sum('weight'))
        total_weighted_sum = students_performance_data.get('total_weighted_sum')
        total_sum_weight = students_performance_data.get('total_sum_weight')
        if total_sum_weight and total_sum_weight > 0:
            return round(total_weighted_sum / total_sum_weight, 2)
        return None

# Сериализатор LessonTemplateItemSerializer для одной строки в шаблоне импорта расписания.
# Валидирует время начала/окончания и существование связанных объектов по ID.
class LessonTemplateItemSerializer(serializers.Serializer):
    day_of_week = serializers.IntegerField(min_value=0, max_value=6, help_text=_("День недели: 0 для Понедельника, ..., 6 для Воскресенья"))
    start_time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M'], help_text=_("Время начала в формате ЧЧ:ММ"))
    end_time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M'], help_text=_("Время окончания в формате ЧЧ:ММ"))
    subject_id = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all(), source='subject', help_text=_("ID существующего предмета"))
    teacher_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.TEACHER), source='teacher', help_text=_("ID существующего преподавателя"))
    classroom_id = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all(), source='classroom', allow_null=True, required=False, help_text=_("ID существующей аудитории (опционально)"))
    lesson_type = serializers.ChoiceField(choices=Lesson.LessonType.choices, help_text=_("Тип занятия (например, LECTURE, PRACTICE)"))
    curriculum_entry_id = serializers.PrimaryKeyRelatedField(queryset=CurriculumEntry.objects.all(), source='curriculum_entry', allow_null=True, required=False, help_text=_("ID связанной записи учебного плана (опционально)"))

    def validate(self, data):
        if data['start_time'] >= data['end_time']:
            raise serializers.ValidationError({"time_conflict": _("Время начала '%(start_time)s' должно быть раньше времени окончания '%(end_time)s' в строке шаблона.") % {'start_time': data['start_time'], 'end_time': data['end_time']}})
        return data

# Сериализатор ScheduleTemplateImportSerializer для импорта расписания из списка объектов LessonTemplateItem.
# Наследуется от ListSerializer.
# Обрабатывает даты начала/окончания периода, учебный год, группу из контекста.
# Реализует логику создания занятий на основе шаблона и указанного диапазона дат,
# пакетную проверку на конфликты и опциональную очистку существующего расписания.
class ScheduleTemplateImportSerializer(serializers.ListSerializer):
    child = LessonTemplateItemSerializer()

    def _parse_date_from_context(self, date_str_key: str, field_name_readable: str):
        date_str = self.context.get(date_str_key)
        if not date_str: raise serializers.ValidationError({date_str_key: gettext_lazy("Параметр '%(field_name)s' обязателен.") % {'field_name': field_name_readable}})
        try: return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError): raise serializers.ValidationError({date_str_key: gettext_lazy("Некорректный формат даты для '%(field_name)s'. Ожидается YYYY-MM-DD.") % {'field_name': field_name_readable}})

    def _get_academic_year_from_context(self, period_start_date):
        academic_year_id = self.context.get('academic_year_id')
        if academic_year_id:
            try: return AcademicYear.objects.get(pk=academic_year_id)
            except AcademicYear.DoesNotExist: raise serializers.ValidationError({"academic_year_id": gettext_lazy("Учебный год с ID %(id)s не найден.") % {'id': academic_year_id}})
        try: return AcademicYear.objects.get(start_date__lte=period_start_date, end_date__gte=period_start_date)
        except AcademicYear.DoesNotExist: raise serializers.ValidationError(gettext_lazy("Не удалось определить учебный год для даты %(date)s. Пожалуйста, укажите ID учебного года.") % {'date': period_start_date})
        except AcademicYear.MultipleObjectsReturned: raise serializers.ValidationError(gettext_lazy("Найдено несколько учебных годов для даты %(date)s. Уточните ID учебного года.") % {'date': period_start_date})

    def _get_student_group_from_context(self):
        student_group_id = self.context.get('student_group_id')
        if not student_group_id: raise serializers.ValidationError({"student_group_id": gettext_lazy("ID учебной группы (общий для шаблона) не предоставлен в контексте.")})
        try: return StudentGroup.objects.select_related('academic_year').get(pk=student_group_id)
        except StudentGroup.DoesNotExist: raise serializers.ValidationError({"student_group_id": gettext_lazy("Учебная группа с ID %(id)s не найдена.") % {'id': student_group_id}})

    @transaction.atomic
    def create(self, validated_data):
        context = self.context
        request_user = context['request'].user
        period_start_date = self._parse_date_from_context('period_start_date', gettext_lazy("Дата начала периода"))
        period_end_date = self._parse_date_from_context('period_end_date', gettext_lazy("Дата окончания периода"))
        if period_start_date > period_end_date: raise serializers.ValidationError(gettext_lazy("Дата начала периода не может быть позже даты окончания."))
        student_group_obj = self._get_student_group_from_context()
        academic_year_obj = context.get('academic_year_object', self._get_academic_year_from_context(period_start_date))
        if not (academic_year_obj.start_date <= period_start_date <= academic_year_obj.end_date and
                academic_year_obj.start_date <= period_end_date <= academic_year_obj.end_date):
            raise serializers.ValidationError(gettext_lazy("Диапазон дат импорта выходит за пределы выбранного учебного года."))
        clear_existing = str(self.context.get('clear_existing_schedule', 'false')).lower() == 'true'
        if clear_existing and student_group_obj:
            delete_filter = Q(student_group=student_group_obj) & Q(study_period__academic_year=academic_year_obj) & \
                            Q(start_time__date__lte=period_end_date) & Q(end_time__date__gte=period_start_date)
            Lesson.objects.filter(delete_filter).delete()
        lessons_to_generate_data = []
        current_date = period_start_date
        while current_date <= period_end_date:
            day_of_week_django = current_date.weekday()
            try: study_period_obj = StudyPeriod.objects.get(academic_year=academic_year_obj, start_date__lte=current_date, end_date__gte=current_date)
            except StudyPeriod.DoesNotExist: current_date += datetime.timedelta(days=1); continue
            except StudyPeriod.MultipleObjectsReturned: raise serializers.ValidationError(gettext_lazy("Найдено несколько учебных периодов для даты %(date)s.") % {'date': current_date.strftime('%Y-%m-%d')})
            for template_item in validated_data:
                if template_item['day_of_week'] == day_of_week_django:
                    lesson_start_dt_naive = datetime.datetime.combine(current_date, template_item['start_time'])
                    lesson_end_dt_naive = datetime.datetime.combine(current_date, template_item['end_time'])
                    lesson_start_dt_aware = timezone.make_aware(lesson_start_dt_naive) if settings.USE_TZ else lesson_start_dt_naive
                    lesson_end_dt_aware = timezone.make_aware(lesson_end_dt_naive) if settings.USE_TZ else lesson_end_dt_naive
                    lessons_to_generate_data.append({
                        'subject': template_item['subject'], 'teacher': template_item['teacher'],
                        'classroom': template_item.get('classroom'), 'lesson_type': template_item['lesson_type'],
                        'start_time': lesson_start_dt_aware, 'end_time': lesson_end_dt_aware,
                        'student_group': student_group_obj, 'study_period': study_period_obj,
                        'created_by': request_user, 'curriculum_entry': template_item.get('curriculum_entry'),
                    })
            current_date += datetime.timedelta(days=1)
        if lessons_to_generate_data:
            conflicts = self._check_lesson_conflict_batch(lessons_to_generate_data)
            if conflicts: raise serializers.ValidationError({"schedule_conflicts": self._format_conflict_messages(conflicts)})
            generated_lesson_objects = [Lesson(**data) for data in lessons_to_generate_data]
            try: Lesson.objects.bulk_create(generated_lesson_objects, batch_size=500)
            except IntegrityError as e: raise serializers.ValidationError(_("Ошибка базы данных при сохранении занятий."))
            except Exception as e: raise serializers.ValidationError(_("Неизвестная ошибка при массовом создании занятий."))
            return len(generated_lesson_objects)
        return 0

    def _check_lesson_conflict_batch(self, lessons_to_generate_data: list[dict]):
        # Реализация пакетной проверки на конфликты (опущена для краткости, но важна)
        # Должна проверять конфликты с существующими занятиями в БД и внутри самого пакета.
        # Возвращает список словарей с информацией о конфликтах.
        conflicts = []
        if not lessons_to_generate_data: return conflicts

        teacher_ids = {ld['teacher'].id for ld in lessons_to_generate_data if ld.get('teacher')}
        group_ids = {ld['student_group'].id for ld in lessons_to_generate_data if ld.get('student_group')}
        classroom_ids = {ld['classroom'].id for ld in lessons_to_generate_data if ld.get('classroom')}
        
        min_start_time = min(ld['start_time'] for ld in lessons_to_generate_data)
        max_end_time = max(ld['end_time'] for ld in lessons_to_generate_data)

        existing_lessons_qs = Lesson.objects.filter(
            start_time__lt=max_end_time, end_time__gt=min_start_time
        ).filter(
            Q(teacher_id__in=teacher_ids) | Q(student_group_id__in=group_ids) | Q(classroom_id__in=classroom_ids)
        ).select_related('teacher', 'student_group', 'classroom', 'subject')
        
        db_conflict_cache = {'teacher': {}, 'group': {}, 'classroom': {}}
        for lesson in existing_lessons_qs:
            if lesson.teacher_id: db_conflict_cache['teacher'].setdefault(lesson.teacher_id, []).append(lesson)
            if lesson.student_group_id: db_conflict_cache['group'].setdefault(lesson.student_group_id, []).append(lesson)
            if lesson.classroom_id: db_conflict_cache['classroom'].setdefault(lesson.classroom_id, []).append(lesson)

        temp_generated_cache = {'teacher': {}, 'group': {}, 'classroom': {}}

        for new_lesson_data in lessons_to_generate_data:
            ns, ne = new_lesson_data['start_time'], new_lesson_data['end_time']
            current_teacher, current_group, current_classroom = new_lesson_data.get('teacher'), new_lesson_data.get('student_group'), new_lesson_data.get('classroom')

            # Проверка с БД
            resource_checks_db = [
                ('teacher', current_teacher, db_conflict_cache['teacher'].get(current_teacher.id if current_teacher else None, [])),
                ('group', current_group, db_conflict_cache['group'].get(current_group.id if current_group else None, [])),
                ('classroom', current_classroom, db_conflict_cache['classroom'].get(current_classroom.id if current_classroom else None, []))
            ]
            for type_name, resource, existing_list in resource_checks_db:
                if resource:
                    for ex_lesson in existing_list:
                        if max(ns, ex_lesson.start_time) < min(ne, ex_lesson.end_time):
                            conflicts.append({'new_lesson':new_lesson_data, 'type': type_name, 'with': 'db', 'existing_lesson': ex_lesson}); break
                if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == type_name: break # Конфликт найден, переходим к след. уроку
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data: continue # Если есть конфликт с БД, не проверяем с пакетом


            # Проверка с пакетом
            resource_checks_batch = [
                ('teacher', current_teacher, temp_generated_cache['teacher'].get(current_teacher.id if current_teacher else None, [])),
                ('group', current_group, temp_generated_cache['group'].get(current_group.id if current_group else None, [])),
                ('classroom', current_classroom, temp_generated_cache['classroom'].get(current_classroom.id if current_classroom else None, []))
            ]
            for type_name, resource, batch_list in resource_checks_batch:
                if resource:
                    for batch_lesson_data in batch_list:
                         if max(ns, batch_lesson_data['start_time']) < min(ne, batch_lesson_data['end_time']):
                            conflicts.append({'new_lesson':new_lesson_data, 'type': type_name, 'with': 'batch', 'conflicting_batch_lesson': batch_lesson_data}); break
                if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == type_name: break
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data: continue
            
            # Добавляем в кэш для проверки внутренних конфликтов
            if current_teacher: temp_generated_cache['teacher'].setdefault(current_teacher.id, []).append(new_lesson_data)
            if current_group: temp_generated_cache['group'].setdefault(current_group.id, []).append(new_lesson_data)
            if current_classroom: temp_generated_cache['classroom'].setdefault(current_classroom.id, []).append(new_lesson_data)
        
        # Уникализация конфликтов
        final_conflicts, seen_signatures = [], set()
        for c in conflicts:
            nl = c['new_lesson']
            res_id = (nl['teacher'].id if c['type'] == 'teacher' else
                      nl['student_group'].id if c['type'] == 'group' else
                      nl.get('classroom').id if c['type'] == 'classroom' and nl.get('classroom') else None)
            sig = (nl['start_time'].isoformat(), nl['end_time'].isoformat(), nl['subject'].id, res_id, c['type'])
            if sig not in seen_signatures: final_conflicts.append(c); seen_signatures.add(sig)
        return final_conflicts


    def _format_conflict_messages(self, conflicts_data_list: list[dict]) -> list[str]:
        # Формирует читаемые сообщения об ошибках
        error_messages = []
        for c_info in conflicts_data_list:
            nl_info = c_info['new_lesson']
            base_msg = gettext_lazy("Конфликт для: %(subj)s (Группа: %(grp)s) на %(date)s в %(time)s.") % {
                'subj': nl_info['subject'].name, 'grp': nl_info['student_group'].name,
                'date': nl_info['start_time'].strftime('%d.%m.%Y'),
                'time': f"{nl_info['start_time'].strftime('%H:%M')}-{nl_info['end_time'].strftime('%H:%M')}"
            }
            details = ""
            if c_info['with'] == 'db':
                ex = c_info['existing_lesson']
                details = gettext_lazy("Пересекается с существующим ID %(id)s: %(subj)s (Гр: %(gr)s) %(dt)s.") % {
                    'id': ex.id, 'subj': ex.subject.name, 'gr': ex.student_group.name, 'dt': ex.start_time.strftime('%d.%m %H:%M')
                }
            elif c_info['with'] == 'batch':
                b_c = c_info['conflicting_batch_lesson']
                details = gettext_lazy("Пересекается с другим из шаблона: %(subj)s (Гр: %(gr)s) на %(dt)s.") % {
                    'subj': b_c['subject'].name, 'gr': b_c['student_group'].name, 'dt': b_c['start_time'].strftime('%d.%m %H:%M')
                }
            type_readable = {'teacher': gettext_lazy("преподавателю '%(n)s'") % {'n': nl_info['teacher'].get_full_name()},
                             'group': gettext_lazy("группе '%(n)s'") % {'n': nl_info['student_group'].name},
                             'classroom': gettext_lazy("аудитории '%(n)s'") % {'n': nl_info['classroom'].identifier if nl_info.get('classroom') else 'N/A'}
                            }.get(c_info['type'], c_info['type'])
            error_messages.append(f"{base_msg} Тип: {type_readable}. {details}")
        return sorted(list(set(error_messages)))