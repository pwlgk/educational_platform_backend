
import logging
from django.forms import ValidationError
from rest_framework import serializers
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_lazy 
from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.db.models import Avg, Sum, F # Для агрегаций
from django.utils import timezone
import datetime
from .models import (
    AcademicYear, StudyPeriod, SubjectMaterialAttachment, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)
from django.db.models import Q
# Импортируем UserSerializer для отображения связанных пользователей
# Предполагаем, что он есть в users.serializers и содержит нужные поля
from users.serializers import UserSerializer as BaseUserSerializer # Переименуем, чтобы избежать конфликта имен
logger = logging.getLogger(__name__) # Инициализация логгера, если еще не было

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
        # extra_kwargs = {
        #     'academic_year': {'write_only': True, 'queryset': AcademicYear.objects.all()} # Добавил queryset
        # }

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
    # Для students_details, если UserSerializer используется для EduUserSerializer, убедитесь, что он не слишком тяжелый
    students_details = EduUserSerializer(source='students', many=True, read_only=True, allow_null=True, required=False) # Добавил allow_null и required=False
    group_monitor_details = EduUserSerializer(source='group_monitor', read_only=True, allow_null=True)
    student_count = serializers.IntegerField(source='students.count', read_only=True)

    # academic_year здесь будет ID для записи, и сериализуется как ID при чтении по умолчанию
    academic_year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all())


    class Meta:
        model = StudentGroup
        fields = (
            'id', 'name', 
            'academic_year',        # ID для записи, ID при чтении
            'academic_year_name',   # Имя для чтения
            'curator',              # ID для записи, ID при чтении
            'curator_details',      # Объект для чтения
            'students',             # Массив ID для записи, массив ID при чтении
            'students_details',     # Массив объектов для чтения
            'group_monitor',        # ID для записи, ID при чтении
            'group_monitor_details',# Объект для чтения
            'student_count'
        )
        read_only_fields = (
            'academic_year_name', 'curator_details', 
            'students_details', 'group_monitor_details', 'student_count'
        )
        # Убираем extra_kwargs, если PrimaryKeyRelatedField используется выше
        # или оставляем, если хотим кастомизировать queryset только здесь
        extra_kwargs = {
            # 'academic_year': {'queryset': AcademicYear.objects.all()}, # Уже определено выше
            'curator': {'required': False, 'allow_null': True, 'queryset': User.objects.filter(role=User.Role.TEACHER)},
            'students': {'required': False, 'queryset': User.objects.filter(role=User.Role.STUDENT)}, # queryset для валидации ID
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
    
    # Добавляем поле curriculum_id для чтения
    curriculum_id = serializers.IntegerField(source='curriculum.id', read_only=True) 
    # ИЛИ чтобы видеть полный объект curriculum (может быть избыточно во вложенном ответе):
    # curriculum_details = CurriculumSerializer(source='curriculum', read_only=True)

    class Meta:
        model = CurriculumEntry
        fields = (
            'id', 
            'curriculum', # Это ID для записи (если не write_only)
            'curriculum_id', # Это ID для чтения
            # 'curriculum_details', # Если нужен полный объект
            'subject', 'subject_details', 'teacher', 'teacher_details',
            'study_period', 'study_period_details', 'planned_hours',
            'scheduled_hours', 'remaining_hours'
        )
        extra_kwargs = {
            # Теперь 'curriculum' можно использовать и для записи, и для чтения ID
            'curriculum': {'queryset': Curriculum.objects.all()}, 
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

class SubjectMaterialAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.URLField(source='file.url', read_only=True)
    file_name = serializers.CharField(source='file.name', read_only=True)

    class Meta:
        model = SubjectMaterialAttachment
        fields = ('id', 'file_name', 'file_url', 'description', 'uploaded_at')
        read_only_fields = ('id', 'file_name', 'file_url', 'uploaded_at') # Описание можно редактировать

# ИЗМЕНЕННЫЙ SubjectMaterialSerializer
class SubjectMaterialSerializer(serializers.ModelSerializer):
    subject_details = SubjectSerializer(source='subject', read_only=True)
    student_group_details = StudentGroupSerializer(source='student_group', read_only=True, allow_null=True)
    uploaded_by_details = EduUserSerializer(source='uploaded_by', read_only=True, allow_null=True)

    # Поле для отображения списка прикрепленных файлов
    attachments = SubjectMaterialAttachmentSerializer(many=True, read_only=True)

    # Поле для загрузки файлов при создании/обновлении
    files_to_upload = serializers.ListField(
        child=serializers.FileField(allow_empty_file=False, use_url=False),
        write_only=True,
        required=False # Можно создать материал без файлов и добавить их позже
    )
    # Опционально: поле для удаления существующих файлов по ID при обновлении
    # attachments_to_delete = serializers.ListField(
    #     child=serializers.IntegerField(),
    #     write_only=True,
    #     required=False
    # )

    class Meta:
        model = SubjectMaterial
        fields = (
            'id', 'subject', 'subject_details', 'student_group', 'student_group_details',
            'title', 'description', 'uploaded_by', 'uploaded_by_details', 'uploaded_at',
            'attachments', # Для чтения
            'files_to_upload', # Для записи
            # 'attachments_to_delete' # Если нужно удаление
        )
        read_only_fields = (
            'uploaded_by_details', 'uploaded_at', 'attachments',
            'subject_details', 'student_group_details'
        )
        extra_kwargs = {
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'student_group': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': StudentGroup.objects.all()},
            'uploaded_by': {'write_only': True, 'required': False, 'allow_null': True}, # Обычно устанавливается во View
        }

    @transaction.atomic
    def create(self, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', [])
        # Устанавливаем uploaded_by из контекста, если не передан
        if 'uploaded_by' not in validated_data and self.context['request'].user.is_authenticated:
            validated_data['uploaded_by'] = self.context['request'].user

        material = SubjectMaterial.objects.create(**validated_data)

        for file_data in files_to_upload:
            # Описание для файла можно передавать вместе с файлом, если фронтенд это поддерживает
            # Например, files_to_upload может быть списком словарей: [{'file': file_obj, 'description': '...'}]
            # Для простоты пока без описания при массовой загрузке.
            SubjectMaterialAttachment.objects.create(subject_material=material, file=file_data)
        return material

    @transaction.atomic
    def update(self, instance, validated_data):
        files_to_upload = validated_data.pop('files_to_upload', None) # None чтобы отличить от пустого списка
        # attachments_to_delete = validated_data.pop('attachments_to_delete', None)

        # Обновляем основные поля материала
        instance = super().update(instance, validated_data)

        # # Логика удаления файлов (если нужна)
        # if attachments_to_delete is not None:
        #     SubjectMaterialAttachment.objects.filter(id__in=attachments_to_delete, subject_material=instance).delete()

        # Логика добавления новых файлов
        # Если files_to_upload это пустой список [], значит клиент хочет удалить все существующие файлы.
        # Если files_to_upload это None, значит клиент не передавал это поле, и файлы не трогаем.
        if files_to_upload is not None:
            if not files_to_upload: # Пустой список - удалить все
                instance.attachments.all().delete()
            else:
                # Здесь можно добавить более сложную логику:
                # удалить те, что не пришли, добавить новые, обновить существующие (если передавать ID в files_to_upload)
                # Для простоты: если переданы файлы, то это НОВЫЙ набор файлов, старые можно удалить.
                # Или просто добавлять к существующим. Давайте просто добавим.
                # instance.attachments.all().delete() # Раскомментировать, если новая загрузка должна заменять все старые файлы
                for file_data in files_to_upload:
                    SubjectMaterialAttachment.objects.create(subject_material=instance, file=file_data)
        return instance
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
    attachments_to_remove_ids = serializers.ListField(
        child=serializers.IntegerField(), # Ожидаем список ID
        write_only=True,      # Это поле только для записи (для PATCH/PUT запросов)
        required=False,       # Не обязательно передавать при каждом обновлении
        help_text="Список ID вложений (HomeworkAttachment), которые нужно удалить."
    )

    class Meta:
        model = Homework
        fields = ( # Включите сюда все явно определенные поля
            'id', 'journal_entry', 'lesson_id', 'lesson_subject', 'title', 'description', 'due_date',
            'created_at', 'author', 'author_details', # 'author' для записи ID
            'attachments', 'related_materials', 'related_materials_details', # 'related_materials' для записи ID
            'files_to_upload', 'material_ids_to_link', 'attachments_to_remove_ids'
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

    @transaction.atomic # Важно для операций с файлами и связями
    def update(self, instance, validated_data):
        # Обработка новых файлов (если есть)
        files_to_upload = validated_data.pop('files_to_upload', None)
        
        # Обработка связей с материалами (если есть)
        material_ids_to_link = validated_data.pop('material_ids_to_link', None)
        related_materials_qs = validated_data.pop('related_materials', None) # Если передается queryset
        
        # --- ОБРАБОТКА УДАЛЕНИЯ ВЛОЖЕНИЙ ---
        attachments_to_remove_ids = validated_data.pop('attachments_to_remove_ids', None)
        if attachments_to_remove_ids is not None: # Если поле было передано
            if not isinstance(attachments_to_remove_ids, list):
                raise serializers.ValidationError({'attachments_to_remove_ids': _("Должен быть список ID.")})
            
            # Удаляем вложения, которые принадлежат этому ДЗ и их ID есть в списке
            # Django автоматически удалит файлы с диска
            attachments_to_delete_qs = instance.attachments.filter(id__in=attachments_to_remove_ids)
            
            # Логирование удаляемых файлов (опционально)
            for att in attachments_to_delete_qs:
                logger.info(f"HomeworkSerializer: Removing attachment ID {att.id} (file: {att.file.name if att.file else 'N/A'}) for Homework ID {instance.id}")
            
            deleted_count, _ = attachments_to_delete_qs.delete()
            logger.info(f"HomeworkSerializer: Removed {deleted_count} attachments for Homework ID {instance.id}")

        # Обновляем основные поля самого ДЗ
        # super().update() должен быть вызван ПОСЛЕ pop() всех кастомных полей
        instance = super().update(instance, validated_data)

        # Добавление новых файлов (если files_to_upload был передан и не None)
        if files_to_upload is not None:
            # Если передан пустой список files_to_upload, это может означать "удалить все существующие и не добавлять новые"
            # или "не трогать существующие и не добавлять новые". Уточните логику.
            # Текущая логика: если files_to_upload - пустой список, то НИЧЕГО не добавляется.
            # Если files_to_upload содержит файлы, они добавляются.
            # Если нужно удалить все старые перед добавлением новых:
            # if files_to_upload: # Только если есть что загружать
            #     instance.attachments.all().delete() # Удалить все старые
            for file_data in files_to_upload: # files_to_upload это список файлов, а не пустой список
                HomeworkAttachment.objects.create(homework=instance, file=file_data)

        # Обновление связей с материалами (если material_ids_to_link был передан и не None)
        if related_materials_qs is not None: # Если передали queryset (например, при полном PUT)
            instance.related_materials.set(related_materials_qs)
        elif material_ids_to_link is not None: # Если передали список ID (например, при PATCH)
            # Если material_ids_to_link - пустой список [], это означает "удалить все связи"
            materials = SubjectMaterial.objects.filter(id__in=material_ids_to_link) if material_ids_to_link else []
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

class LiteHomeworkSubmissionSerializer(serializers.ModelSerializer):
    homework_title = serializers.CharField(source='homework.title', read_only=True)
    student_details = EduUserSerializer(source='student', read_only=True)
    attachments = SubmissionAttachmentSerializer(many=True, read_only=True)
    # УБИРАЕМ grade_details отсюда

    class Meta:
        model = HomeworkSubmission
        fields = (
            'id', 'homework_title', 'student_details',
            'submitted_at', 'content', 'attachments' # Убираем grade_details
        )
        read_only_fields = fields

class GradeSerializer(serializers.ModelSerializer):
    student_details = EduUserSerializer(source='student', read_only=True)
    subject_details = SubjectSerializer(source='subject', read_only=True)
    study_period_details = StudyPeriodSerializer(source='study_period', read_only=True, allow_null=True)
    academic_year_details = AcademicYearSerializer(source='academic_year', read_only=True, allow_null=True)
    lesson_details = LessonListSerializer(source='lesson', read_only=True, allow_null=True)
    homework_submission_details = LiteHomeworkSubmissionSerializer(source='homework_submission', read_only=True, allow_null=True)
    graded_by_details = EduUserSerializer(source='graded_by', read_only=True, allow_null=True)
    lesson_id = serializers.IntegerField(
        source='lesson.id', # Получаем ID из связанного объекта lesson
        read_only=True,
        allow_null=True    # Если lesson может быть null
    )
    class Meta:
        model = Grade
        fields = (
            'id', 'student', 'student_details', 'subject', 'subject_details',
            'study_period', 'study_period_details', # study_period - ID для записи
            'academic_year', 'academic_year_details', # academic_year - ID для записи
            'lesson', # Это поле для ЗАПИСИ (ID урока)
            'lesson_id','lesson_details',
            'homework_submission', 'homework_submission_details',
            'grade_value', 'numeric_value', 'grade_type', 'date_given', 'comment',
            'graded_by', 'graded_by_details', 'weight'
        )
        read_only_fields = (
            'student_details', 'subject_details', 'study_period_details',
            'academic_year_details', 'lesson_details', 'homework_submission_details',
            'graded_by_details','lesson_id'
        )
        extra_kwargs = {
            # ID полей для записи
            'student': {'write_only': True, 'queryset': User.objects.filter(role=User.Role.STUDENT)},
            'subject': {'write_only': True, 'queryset': Subject.objects.all()},
            'study_period': {
                'write_only': True, 'queryset': StudyPeriod.objects.all(),
                'required': False, 'allow_null': True # Теперь может быть не указан
            },
            'academic_year': {
                'write_only': True, 'queryset': AcademicYear.objects.all(),
                'required': False, 'allow_null': True # Теперь может быть не указан
            },
            'lesson': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': Lesson.objects.all()},
            'homework_submission': {'write_only': True, 'required': False, 'allow_null': True, 'queryset': HomeworkSubmission.objects.all()},
            'graded_by': {'write_only':True, 'required':False, 'allow_null':True, 'queryset':User.objects.filter(role=User.Role.TEACHER)}
        }

    def validate(self, data):
        """
        Валидация данных перед сохранением.
        Метод clean() модели также будет вызван при ModelSerializer.save().
        Здесь можно добавить специфичную для API валидацию или предварительную обработку.
        """
        # Получаем значения, учитывая, что это может быть частичное обновление (PATCH)
        # и некоторые поля могут отсутствовать в `data`, но присутствовать в `self.instance`.
        # Однако, для новой валидации лучше брать из `data` или `None`.
        grade_type = data.get('grade_type')
        study_period = data.get('study_period')
        academic_year = data.get('academic_year')
        lesson = data.get('lesson')
        homework_submission = data.get('homework_submission')

        # 1. Если это обновление и поле не передано, берем из instance
        if self.instance:
            grade_type = grade_type or self.instance.grade_type
            # study_period, academic_year, lesson, homework_submission
            # могут быть изменены на None, поэтому берем из data если есть,
            # иначе из instance если обновляем, иначе None если создаем
            study_period = data.get('study_period', self.instance.study_period if 'study_period' in data else None)
            academic_year = data.get('academic_year', self.instance.academic_year if 'academic_year' in data else None)
            lesson = data.get('lesson', self.instance.lesson if 'lesson' in data else None)
            homework_submission = data.get('homework_submission', self.instance.homework_submission if 'homework_submission' in data else None)


        # 2. Логика автоматического определения study_period и academic_year (если они не переданы)
        if lesson:
            if not study_period:
                study_period = lesson.study_period
                data['study_period'] = study_period # Обновляем data для передачи в model.clean()
            if not academic_year and study_period: # study_period мог только что установиться
                academic_year = study_period.academic_year
                data['academic_year'] = academic_year
        elif study_period and not academic_year:
            academic_year = study_period.academic_year
            data['academic_year'] = academic_year

        # 3. Вызов валидации из модели Grade (clean метод)
        # Создаем временный экземпляр или обновляем существующий для вызова clean
        # Это немного громоздко, но позволяет использовать валидацию модели.
        # Альтернатива - дублировать всю логику clean() здесь.
        temp_instance_data = data.copy() # Копируем, чтобы не изменять исходные данные для super().validate()
        
        # Удаляем '_details' поля и другие read_only поля, которых нет в модели
        # Это нужно, если мы будем создавать временный объект модели Grade
        model_fields = {f.name for f in Grade._meta.get_fields()}
        data_for_model_instance = {k: v for k, v in temp_instance_data.items() if k in model_fields}


        if self.instance: # Обновление существующего экземпляра
            # Применяем изменения к копии instance для вызова clean
            # Это сложнее, так как нужно правильно обработать M2M и ForeignKey
            # Для простоты, можно дублировать часть логики clean() здесь
            # или полностью полагаться на clean() при вызове save() модели,
            # но тогда ошибки валидации модели всплывут позже.

            # Пока что здесь мы проверим основные моменты, которые не требуют полного экземпляра
            pass # Основные проверки ниже
            
        else: # Создание нового экземпляра
            # Можно создать временный объект Grade для вызова clean, но это потребует
            # разрешения всех ForeignKey на реальные объекты, что data может не содержать
            # (например, student, subject - это ID).
            # Вместо этого, дублируем ключевые проверки из model.clean() здесь:
            if grade_type in [Grade.GradeType.YEAR_FINAL, Grade.GradeType.YEAR_AVERAGE]:
                if study_period:
                    raise serializers.ValidationError({'study_period': _("Для годовых оценок учебный период не указывается.")})
                if not academic_year:
                    raise serializers.ValidationError({'academic_year': _("Для годовых оценок необходимо указать учебный год.")})
                if lesson or homework_submission:
                    raise serializers.ValidationError(_("Годовые оценки не должны быть привязаны к конкретному занятию или ДЗ."))

            elif grade_type in [Grade.GradeType.PERIOD_FINAL, Grade.GradeType.PERIOD_AVERAGE]:
                if not study_period:
                    raise serializers.ValidationError({'study_period': _("Для итоговых оценок за период необходимо указать учебный период.")})
                if lesson or homework_submission:
                    raise serializers.ValidationError(_("Итоговые оценки за период не должны быть привязаны к конкретному занятию или ДЗ."))
            else: # Текущие оценки
                if not study_period:
                    raise serializers.ValidationError({'study_period': _("Для текущих оценок необходимо указать учебный период.")})
                if grade_type == Grade.GradeType.LESSON_WORK and not lesson:
                    raise serializers.ValidationError({'lesson': _("Для оценки за работу на занятии необходимо указать занятие.")})
                if grade_type == Grade.GradeType.HOMEWORK_GRADE and not homework_submission:
                    raise serializers.ValidationError({'homework_submission': _("Для оценки за ДЗ необходимо указать сданную работу.")})

            if academic_year and study_period:
                if study_period.academic_year != academic_year:
                    raise serializers.ValidationError(
                        _("Указанный учебный период (%(period_id)s) не принадлежит указанному учебному году (%(year_id)s).") %
                        {'period_id': study_period.id, 'year_id': academic_year.id}
                    )
        
        return data

    def create(self, validated_data):
        # graded_by устанавливается во ViewSet через perform_create
        # или можно добавить логику здесь, если пользователь передается в контексте
        request = self.context.get('request')
        if request and hasattr(request, "user") and request.user.is_authenticated:
           if 'graded_by' not in validated_data or not validated_data['graded_by']:
               # Устанавливаем graded_by, если текущий юзер - учитель и поле не передано
               if request.user.role == User.Role.TEACHER: # или is_teacher
                   validated_data['graded_by'] = request.user
        
        # Важно: Логика из model.clean() по установке academic_year/study_period из lesson
        # должна быть либо здесь, либо в model.save() (уже есть в model.clean, но model.save не вызывает clean)
        # Либо view должна передать все необходимые данные.
        # Дополним validated_data перед созданием
        lesson = validated_data.get('lesson')
        study_period = validated_data.get('study_period')
        academic_year = validated_data.get('academic_year')

        if lesson:
            if not study_period: validated_data['study_period'] = lesson.study_period
            if not academic_year and validated_data.get('study_period'):
                 validated_data['academic_year'] = validated_data['study_period'].academic_year
        elif study_period and not academic_year:
            validated_data['academic_year'] = study_period.academic_year

        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Аналогично create, можно добавить логику для graded_by и автозаполнения
        # study_period/academic_year при обновлении
        request = self.context.get('request')
        if request and hasattr(request, "user") and request.user.is_authenticated:
            if 'graded_by' in validated_data and not validated_data['graded_by']:
                if request.user.role == User.Role.TEACHER:
                    validated_data['graded_by'] = request.user
            elif 'graded_by' not in validated_data and instance.graded_by is None: # Если поле не передано и было пусто
                if request.user.role == User.Role.TEACHER:
                    validated_data['graded_by'] = request.user


        lesson = validated_data.get('lesson', instance.lesson) # Берем новое значение или из instance
        study_period = validated_data.get('study_period', instance.study_period)
        academic_year = validated_data.get('academic_year', instance.academic_year)

        if lesson:
            current_sp = validated_data.get('study_period') # Если study_period изменяется в этом же запросе
            if current_sp is None: # Если study_period не передается в PUT/PATCH явно
                validated_data['study_period'] = lesson.study_period
            
            current_ay = validated_data.get('academic_year')
            current_sp_for_ay = validated_data.get('study_period', lesson.study_period) # Берем актуальный SP для AY
            if current_ay is None and current_sp_for_ay:
                 validated_data['academic_year'] = current_sp_for_ay.academic_year

        elif study_period and validated_data.get('academic_year') is None: # Если AY не передан, но SP есть
            validated_data['academic_year'] = study_period.academic_year
        
        # Если study_period удаляется (передан null), а academic_year нет, то academic_year тоже нужно сбросить,
        # если тип оценки не годовой.
        grade_type = validated_data.get('grade_type', instance.grade_type)
        if 'study_period' in validated_data and validated_data['study_period'] is None and \
           grade_type not in [Grade.GradeType.YEAR_FINAL, Grade.GradeType.YEAR_AVERAGE]:
            if 'academic_year' not in validated_data: # Если academic_year не изменяется явно
                validated_data['academic_year'] = None


        return super().update(instance, validated_data)


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

class MyHomeworkSerializer(HomeworkSerializer): # Наследуемся от вашего основного HomeworkSerializer
    # Статусы можно вынести в константы или enum, если их много
    STATUS_SUBMITTED_GRADED = _("Сдано (Оценено: {grade})")
    STATUS_SUBMITTED_PENDING = _("Сдано (Ожидает проверки)")
    STATUS_NOT_SUBMITTED_EXPIRED = _("Не сдано (Срок истек)")
    STATUS_NOT_SUBMITTED = _("Не сдано")
    STATUS_NO_HOMEWORK_DATA = _("N/A") # Если нет данных о ДЗ или ребенке

    # Эти поля будут содержать информацию о сдаче КОНКРЕТНОГО ребенка,
    # если родитель запросил ДЗ для одного ребенка, или если текущий пользователь - студент.
    submission_details_for_child = serializers.SerializerMethodField() 
    submission_status_for_child = serializers.SerializerMethodField()
    grade_for_child_submission = serializers.SerializerMethodField()

    class Meta(HomeworkSerializer.Meta): # Наследуем Meta от родительского HomeworkSerializer
        # Явно перечисляем поля, которые хотим видеть.
        # Берем поля из родителя и добавляем новые.
        # Убедитесь, что все нужные поля из HomeworkSerializer.Meta.fields здесь есть.
        fields = (
            'id',
            'lesson_id', # Должно быть определено в HomeworkSerializer (например, source='journal_entry.lesson.id')
            'lesson_subject', # Должно быть определено в HomeworkSerializer (например, source='journal_entry.lesson.subject.name')
            'title',
            'description',
            'due_date',
            'created_at',
            'author_details', 
            'attachments', 
            'related_materials_details',
            # Новые поля для этого сериализатора
            'submission_details_for_child', # Заменит 'my_submission'
            'submission_status_for_child',  # Заменит 'submission_status'
            'grade_for_child_submission',   # Новое поле для оценки
        )
        # read_only_fields наследуются, но можно и переопределить, если нужно
        # Убедимся, что все поля только для чтения
        read_only_fields = fields

    def _get_target_student_for_homework(self, homework_obj):
        """
        Определяет целевого студента на основе контекста.
        Для родителя: берет child_id из ?child_id= (если есть) или первого из target_children_ids.
        Для студента: берет request.user.
        """
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        
        user = request.user

        if user.is_student:
            return user
        
        if user.is_parent:
            # target_children_ids_for_serializer будет списком.
            # Если ?child_id= был указан, там будет один ID.
            # Если не был, там будут все дети. В этом случае мы не сможем показать
            # статус для "всех" сразу в одном поле, MyHomeworkSerializer предназначен для одного ДЗ.
            # ParentChildHomeworkListView должен передавать данные по каждому ДЗ,
            # а сериализатор должен показать статус для *релевантного* ребенка этому ДЗ.
            #
            # child_submissions_for_list на homework_obj уже отфильтрован по target_children_ids.
            # Если target_children_ids содержит одного ребенка (из-за ?child_id=),
            # то child_submissions_for_list будет содержать сдачу только этого ребенка (если она есть).
            
            target_children_ids = self.context.get('target_children_ids_for_serializer', [])
            if len(target_children_ids) == 1:
                # Если родитель запросил данные для конкретного ребенка
                try:
                    return User.objects.get(pk=target_children_ids[0], role=User.Role.STUDENT)
                except User.DoesNotExist:
                    return None
            elif not target_children_ids: # Если у родителя нет детей или child_id был неверный
                 return None
            else:
                # Родитель запросил ДЗ для ВСЕХ детей, но этот сериализатор обрабатывает ОДНО ДЗ.
                # В этом случае мы не можем выбрать "одного" ребенка для отображения статуса
                # в полях submission_status_for_child и т.д.
                # Это означает, что если родитель не фильтрует по ?child_id, эти поля будут N/A.
                # Либо ParentChildHomeworkListView должен возвращать по одному "ДЗ+статус для ребенка" на каждую пару.
                # Текущий подход: если не указан ?child_id, эти поля будут N/A.
                logger.debug(f"MyHomeworkSerializer: Parent {user.email} requested HW list for multiple children. "
                             f"Specific submission status will be N/A for HW ID {homework_obj.id}.")
                return None 
        return None

    def _get_submission_for_student(self, homework_obj, student):
        """Находит сдачу данного студента для данного ДЗ из prefetched данных."""
        if not student or not hasattr(homework_obj, 'my_current_submission_list'): # <--- ИЗМЕНИТЬ ЗДЕСЬ
            return None
        
        # my_current_submission_list будет содержать список (возможно, пустой или с одним элементом)
        for submission in homework_obj.my_current_submission_list: # <--- ИЗМЕНИТЬ ЗДЕСЬ
            # Мы уже отфильтровали по student=user в Prefetch, поэтому эта проверка student_id избыточна,
            # но оставим на всякий случай, если Prefetch-фильтр изменится.
            if submission.student_id == student.id: 
                return submission
        return None

    def get_submission_details_for_child(self, obj: Homework):
        target_student = self._get_target_student_for_homework(obj)
        if not target_student:
            return None
        
        submission = self._get_submission_for_student(obj, target_student)
        if submission:
            # Можно вернуть больше деталей, если нужно, используя HomeworkSubmissionSerializer
            return {
                'id': submission.id,
                'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None, # Форматируем дату
                'content': submission.content,
                # 'attachments': SubmissionAttachmentSerializer(submission.attachments.all(), many=True).data # Если нужны файлы
            }
        return None

    def get_submission_status_for_child(self, obj: Homework):
        target_student = self._get_target_student_for_homework(obj)
        if not target_student:
            return self.STATUS_NO_HOMEWORK_DATA
        
        submission = self._get_submission_for_student(obj, target_student)
        
        if submission:
            # hasattr(submission, 'grade_for_submission') может быть True, но значение None
            # grade = getattr(submission, 'grade_for_submission', None) # Получаем оценку из prefetched
            grade = None
            try:
                grade = submission.grade_for_submission # Доступ через reverse OneToOne
            except Grade.DoesNotExist: # Или AttributeError, если related_name не 'grade_for_submission'
                pass # Оценки нет

            if grade:
                return str(self.STATUS_SUBMITTED_GRADED).format(grade=grade.grade_value)
            return str(self.STATUS_SUBMITTED_PENDING)
        elif obj.due_date and timezone.now() > obj.due_date:
            return str(self.STATUS_NOT_SUBMITTED_EXPIRED)
        return str(self.STATUS_NOT_SUBMITTED)

    def get_grade_for_child_submission(self, obj: Homework):
        target_student = self._get_target_student_for_homework(obj)
        if not target_student:
            return None
            
        submission = self._get_submission_for_student(obj, target_student)
        if submission:
            grade = None
            try:
                grade = submission.grade_for_submission
            except Grade.DoesNotExist:
                pass
            
            if grade:
                # Возвращаем нужные поля оценки
                return {
                    'grade_value': grade.grade_value,
                    'numeric_value': grade.numeric_value,
                    'comment': grade.comment,
                    'date_given': grade.date_given.isoformat() if grade.date_given else None,
                    'graded_by': EduUserSerializer(grade.graded_by, context=self.context).data if grade.graded_by else None
                }
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
    


class LessonTemplateItemSerializer(serializers.Serializer):
    day_of_week = serializers.IntegerField(min_value=0, max_value=6, help_text=_("День недели: 0 для Понедельника, ..., 6 для Воскресенья"))
    start_time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M'], help_text=_("Время начала в формате ЧЧ:ММ"))
    end_time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M'], help_text=_("Время окончания в формате ЧЧ:ММ"))
    
    # Используем PrimaryKeyRelatedField для валидации существования ID
    subject_id = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(), source='subject', # source='subject' чтобы в validated_data был объект Subject
        help_text=_("ID существующего предмета")
    )
    teacher_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.TEACHER), source='teacher', # source='teacher'
        help_text=_("ID существующего преподавателя")
    )
    classroom_id = serializers.PrimaryKeyRelatedField(
        queryset=Classroom.objects.all(), source='classroom', # source='classroom'
        allow_null=True, required=False, 
        help_text=_("ID существующей аудитории (опционально)")
    )
    lesson_type = serializers.ChoiceField(
        choices=Lesson.LessonType.choices, 
        help_text=_("Тип занятия (например, LECTURE, PRACTICE)")
    )
    # student_group_id - если он должен быть в каждой строке CSV, а не общий
    # student_group_id = serializers.PrimaryKeyRelatedField(
    #     queryset=StudentGroup.objects.all(), source='student_group',
    #     required=False, # Если может быть общий из контекста
    #     help_text=_("ID учебной группы (если не указан общий для шаблона)")
    # )
    curriculum_entry_id = serializers.PrimaryKeyRelatedField(
        queryset=CurriculumEntry.objects.all(), source='curriculum_entry',
        allow_null=True, required=False,
        help_text=_("ID связанной записи учебного плана (опционально)")
    )

    def validate(self, data):
        if data['start_time'] >= data['end_time']:
            raise serializers.ValidationError({
                "time_conflict": _("Время начала '%(start_time)s' должно быть раньше времени окончания '%(end_time)s' в строке шаблона.") % 
                                 {'start_time': data['start_time'], 'end_time': data['end_time']}
            })
        # Дополнительные валидации для строки шаблона, если нужны
        # Например, если curriculum_entry указан, проверить, что он соответствует предмету/преподавателю/группе
        # curriculum_entry = data.get('curriculum_entry')
        # subject = data.get('subject')
        # if curriculum_entry and subject and curriculum_entry.subject != subject:
        #     raise serializers.ValidationError(_("Запись учебного плана не соответствует выбранному предмету."))
        return data

class ScheduleTemplateImportSerializer(serializers.ListSerializer):
    child = LessonTemplateItemSerializer()

    def _parse_date_from_context(self, date_str_key: str, field_name_readable: str): # field_name_readable теперь просто описание
        date_str = self.context.get(date_str_key)
        if not date_str:
            # Строка для перевода
            error_msg = gettext_lazy("Параметр '%(field_name)s' обязателен.") % {'field_name': field_name_readable}
            raise serializers.ValidationError({date_str_key: error_msg})
        try:
            return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            error_msg = gettext_lazy("Некорректный формат даты для '%(field_name)s'. Ожидается YYYY-MM-DD.") % {'field_name': field_name_readable}
            raise serializers.ValidationError({date_str_key: error_msg})

    def _get_academic_year_from_context(self, period_start_date):
        academic_year_id = self.context.get('academic_year_id')
        if academic_year_id:
            try:
                return AcademicYear.objects.get(pk=academic_year_id)
            except AcademicYear.DoesNotExist:
                raise serializers.ValidationError(
                    {"academic_year_id": gettext_lazy("Учебный год с ID %(id)s не найден.") % {'id': academic_year_id}}
                )
        try:
            return AcademicYear.objects.get(start_date__lte=period_start_date, end_date__gte=period_start_date)
        except AcademicYear.DoesNotExist:
            raise serializers.ValidationError(
                gettext_lazy("Не удалось определить учебный год для даты %(date)s. Пожалуйста, укажите ID учебного года.") % {'date': period_start_date}
            )
        except AcademicYear.MultipleObjectsReturned:
             raise serializers.ValidationError(
                gettext_lazy("Найдено несколько учебных годов для даты %(date)s. Уточните ID учебного года.") % {'date': period_start_date}
            )

    def _get_student_group_from_context(self):
        student_group_id = self.context.get('student_group_id')
        if not student_group_id:
            raise serializers.ValidationError({"student_group_id": gettext_lazy("ID учебной группы (общий для шаблона) не предоставлен в контексте.")})
        try:
            return StudentGroup.objects.select_related('academic_year').get(pk=student_group_id)
        except StudentGroup.DoesNotExist:
            raise serializers.ValidationError(
                {"student_group_id": gettext_lazy("Учебная группа с ID %(id)s не найдена.") % {'id': student_group_id}}
            )
    @transaction.atomic # Гарантируем атомарность операции
    def create(self, validated_data):
        context = self.context
        request_user = context['request'].user
        
        # Используем описательные строки для передачи в _parse_date_from_context
        period_start_date = self._parse_date_from_context('period_start_date', gettext_lazy("Дата начала периода"))
        period_end_date = self._parse_date_from_context('period_end_date', gettext_lazy("Дата окончания периода"))

        if period_start_date > period_end_date:
            raise serializers.ValidationError(gettext_lazy("Дата начала периода не может быть позже даты окончания."))

        student_group_obj = self._get_student_group_from_context() # Этот метод тоже может использовать gettext_lazy
        academic_year_obj = self.context.get('academic_year_object')
        if not academic_year_obj:
            academic_year_obj = self._get_academic_year_from_context(period_start_date) # И этот

        if not (academic_year_obj.start_date <= period_start_date <= academic_year_obj.end_date and
                academic_year_obj.start_date <= period_end_date <= academic_year_obj.end_date):
            raise serializers.ValidationError(
                gettext_lazy("Диапазон дат импорта (%(start)s - %(end)s) выходит за пределы выбранного учебного года '%(year_name)s' (%(year_start)s - %(year_end)s).") %
                {
                    'start': period_start_date.strftime('%d.%m.%Y'), 'end': period_end_date.strftime('%d.%m.%Y'),
                    'year_name': academic_year_obj.name,
                    'year_start': academic_year_obj.start_date.strftime('%d.%m.%Y'),
                    'year_end': academic_year_obj.end_date.strftime('%d.%m.%Y')
                }
            )
        
        # Идемпотентность: Очистка существующих занятий (если флаг установлен)
        clear_existing = str(self.context.get('clear_existing_schedule', 'false')).lower() == 'true'
        if clear_existing and student_group_obj:
            logger.info(f"Импорт расписания (clear_existing=True): Удаление существующих занятий для группы '{student_group_obj.name}' "
                        f"в учебном году '{academic_year_obj.name}' которые пересекаются с периодом {period_start_date} - {period_end_date}.")
            
            # Фильтр для занятий, которые хоть как-то пересекаются с указанным периодом дат
            # Занятие пересекается с периодом [P_start, P_end], если:
            # (Lesson_start < P_end) И (Lesson_end > P_start)
            delete_filter = Q(student_group=student_group_obj) & \
                            Q(study_period__academic_year=academic_year_obj) & \
                            Q(start_time__date__lte=period_end_date) & \
                            Q(end_time__date__gte=period_start_date)
            
            # Альтернативный, более точный фильтр пересечения с периодом, если start_time и end_time это DateTimeField:
            # delete_filter = Q(student_group=student_group_obj) & \
            #                 Q(study_period__academic_year=academic_year_obj) & \
            #                 Q(start_time__lt=datetime.datetime.combine(period_end_date, datetime.time.max)) & \
            #                 Q(end_time__gt=datetime.datetime.combine(period_start_date, datetime.time.min))


            lessons_to_delete_qs = Lesson.objects.filter(delete_filter)
            
            # Логируем, какие занятия будут удалены, перед удалением
            if lessons_to_delete_qs.exists():
                logger.info(f"Будут удалены следующие занятия (ID): {[lesson.id for lesson in lessons_to_delete_qs]}")
            else:
                logger.info("Не найдено существующих занятий для удаления по заданным критериям.")

            deleted_count, deleted_types_details = lessons_to_delete_qs.delete()
            logger.info(f"Удалено {deleted_count} существующих занятий. Детали по типам: {deleted_types_details}")


        # 2. Генерация списка словарей с данными для создания объектов Lesson
        lessons_to_generate_data = [] # Список словарей для _check_lesson_conflict_batch
        
        current_date = period_start_date
        while current_date <= period_end_date:
            day_of_week_django = current_date.weekday() # 0 для Понедельника

            try:
                study_period_obj = StudyPeriod.objects.get(
                    academic_year=academic_year_obj,
                    start_date__lte=current_date,
                    end_date__gte=current_date
                )
            except StudyPeriod.DoesNotExist:
                logger.info(f"Для даты {current_date.strftime('%Y-%m-%d')} не найден учебный период в году '{academic_year_obj.name}'. Занятия на эту дату не будут созданы.")
                current_date += datetime.timedelta(days=1)
                continue
            except StudyPeriod.MultipleObjectsReturned:
                raise serializers.ValidationError(
                    gettext_lazy("Найдено несколько учебных периодов для даты %(date)s в году '%(year)s'. Проверьте конфигурацию.") %
                    {'date': current_date.strftime('%Y-%m-%d'), 'year': academic_year_obj.name}
                )

            for template_item in validated_data: # validated_data - это список провалидированных данных из CSV
                if template_item['day_of_week'] == day_of_week_django:
                    
                    lesson_start_dt_naive = datetime.datetime.combine(current_date, template_item['start_time'])
                    lesson_end_dt_naive = datetime.datetime.combine(current_date, template_item['end_time'])

                    lesson_start_dt_aware = timezone.make_aware(lesson_start_dt_naive) if settings.USE_TZ else lesson_start_dt_naive
                    lesson_end_dt_aware = timezone.make_aware(lesson_end_dt_naive) if settings.USE_TZ else lesson_end_dt_naive
                    
                    lesson_data = {
                        'subject': template_item['subject'], # Объект Subject
                        'teacher': template_item['teacher'], # Объект User (Teacher)
                        'classroom': template_item.get('classroom'), # Объект Classroom или None
                        'lesson_type': template_item['lesson_type'],
                        'start_time': lesson_start_dt_aware,
                        'end_time': lesson_end_dt_aware,
                        'student_group': student_group_obj, # Общая группа для шаблона
                        'study_period': study_period_obj,
                        'created_by': request_user,
                        'curriculum_entry': template_item.get('curriculum_entry'), # Объект CurriculumEntry или None
                    }
                    lessons_to_generate_data.append(lesson_data)
            current_date += datetime.timedelta(days=1)
        
        # 3. Пакетная проверка на конфликты
        if lessons_to_generate_data:
            conflicts = self._check_lesson_conflict_batch(lessons_to_generate_data)
            if conflicts:
                error_messages = self._format_conflict_messages(conflicts)
                raise serializers.ValidationError({"schedule_conflicts": error_messages})

        # 4. Создание объектов Lesson и bulk_create
        generated_lesson_objects = [Lesson(**data) for data in lessons_to_generate_data]
            
        if generated_lesson_objects:
            try:
                Lesson.objects.bulk_create(generated_lesson_objects, batch_size=500)
                # --- УВЕДОМЛЕНИЯ ---
                # Отправка уведомлений после успешного bulk_create
                # Это может быть много уведомлений, возможно, лучше обобщенное уведомление или фоновая задача
                 # for lesson_obj in generated_lesson_objects:
                #    notify_lesson_change(lesson_obj, action="создано (импорт)")

            except IntegrityError as e:
                logger.error(f"Импорт расписания - IntegrityError при bulk_create: {e}")
                raise serializers.ValidationError(_("Ошибка базы данных при сохранении занятий. Возможно, дублирование или нарушение уникальных ограничений."))
            except Exception as e:
                    logger.error(f"Импорт расписания - Неизвестная ошибка при bulk_create: {e}", exc_info=True)
                    raise serializers.ValidationError(_("Неизвестная ошибка при массовом создании занятий."))
            
            return len(generated_lesson_objects)
        return 0 # Нет занятий для создания

    def _check_lesson_conflict_batch(self, lessons_to_generate_data: list[dict]):
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

        temp_generated_cache = {'teacher': {}, 'group': {}, 'classroom': {}} # Для проверки конфликтов внутри пакета

        for new_lesson_data in lessons_to_generate_data:
            ns = new_lesson_data['start_time']
            ne = new_lesson_data['end_time']
            
            # Ресурсы текущего нового урока
            current_teacher = new_lesson_data.get('teacher')
            current_group = new_lesson_data.get('student_group')
            current_classroom = new_lesson_data.get('classroom')

            # Проверка с БД
            if current_teacher:
                for existing_lesson in db_conflict_cache['teacher'].get(current_teacher.id, []):
                    if max(ns, existing_lesson.start_time) < min(ne, existing_lesson.end_time):
                        conflicts.append({'new_lesson':new_lesson_data, 'type': 'teacher', 'with': 'db', 'existing_lesson': existing_lesson}); break
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == 'teacher': continue # Если уже есть конфликт с БД по этому ресурсу

            if current_group:
                for existing_lesson in db_conflict_cache['group'].get(current_group.id, []):
                    if max(ns, existing_lesson.start_time) < min(ne, existing_lesson.end_time):
                        conflicts.append({'new_lesson':new_lesson_data, 'type': 'group', 'with': 'db', 'existing_lesson': existing_lesson}); break
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == 'group': continue
            
            if current_classroom:
                for existing_lesson in db_conflict_cache['classroom'].get(current_classroom.id, []):
                    if max(ns, existing_lesson.start_time) < min(ne, existing_lesson.end_time):
                        conflicts.append({'new_lesson':new_lesson_data, 'type': 'classroom', 'with': 'db', 'existing_lesson': existing_lesson}); break
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == 'classroom': continue


            # Проверка с уже "добавленными" в этот же пакет (внутренние конфликты)
            if current_teacher:
                for temp_lesson_data in temp_generated_cache['teacher'].get(current_teacher.id, []):
                    if max(ns, temp_lesson_data['start_time']) < min(ne, temp_lesson_data['end_time']):
                        conflicts.append({'new_lesson':new_lesson_data, 'type': 'teacher', 'with': 'batch', 'conflicting_batch_lesson': temp_lesson_data}); break # Достаточно одного
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == 'teacher': continue

            if current_group:
                for temp_lesson_data in temp_generated_cache['group'].get(current_group.id, []):
                    if max(ns, temp_lesson_data['start_time']) < min(ne, temp_lesson_data['end_time']):
                        conflicts.append({'new_lesson':new_lesson_data, 'type': 'group', 'with': 'batch', 'conflicting_batch_lesson': temp_lesson_data}); break
            if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == 'group': continue

            if current_classroom:
                for temp_lesson_data in temp_generated_cache['classroom'].get(current_classroom.id, []):
                    if max(ns, temp_lesson_data['start_time']) < min(ne, temp_lesson_data['end_time']):
                        conflicts.append({'new_lesson':new_lesson_data, 'type': 'classroom', 'with': 'batch', 'conflicting_batch_lesson': temp_lesson_data}); break
            # if conflicts and conflicts[-1].get('new_lesson') == new_lesson_data and conflicts[-1].get('type') == 'classroom': continue # Эта проверка может быть лишней или неточной


            # Если нет конфликтов с БД для этого урока, добавляем его в временный кэш для проверки внутренних пересечений
            # Добавляем, только если для него еще не было найдено конфликтов с БД, чтобы не проверять его дальше с пакетом
            is_already_db_conflicted = any(
                c.get('new_lesson') == new_lesson_data and c.get('with') == 'db' for c in conflicts
            )
            if not is_already_db_conflicted:
                if current_teacher: temp_generated_cache['teacher'].setdefault(current_teacher.id, []).append(new_lesson_data)
                if current_group: temp_generated_cache['group'].setdefault(current_group.id, []).append(new_lesson_data)
                if current_classroom: temp_generated_cache['classroom'].setdefault(current_classroom.id, []).append(new_lesson_data)
        
        # Уникализация конфликтов (базовая)
        final_conflicts = []
        seen_conflict_signatures = set()
        for c_info in conflicts:
            nl_data = c_info['new_lesson']
            res_id = None
            if c_info['type'] == 'teacher': res_id = nl_data['teacher'].id
            elif c_info['type'] == 'group': res_id = nl_data['student_group'].id
            elif c_info['type'] == 'classroom' and nl_data.get('classroom'): res_id = nl_data['classroom'].id
            
            signature = (
                nl_data['start_time'].isoformat(), 
                nl_data['end_time'].isoformat(),
                nl_data['subject'].id, # Добавляем предмет для большей уникальности подписи
                res_id, 
                c_info['type']
            )
            if signature not in seen_conflict_signatures:
                final_conflicts.append(c_info)
                seen_conflict_signatures.add(signature)
        return final_conflicts

    def _format_conflict_messages(self, conflicts_data_list: list[dict]) -> list[str]:
        """Формирует читаемые сообщения об ошибках из списка словарей конфликтов."""
        error_messages = []
        for conflict_info in conflicts_data_list:
            new_lesson_info = conflict_info['new_lesson']
            
            subject_name = new_lesson_info['subject'].name
            group_name = new_lesson_info['student_group'].name
            date_str = new_lesson_info['start_time'].strftime('%d.%m.%Y')
            time_str = f"{new_lesson_info['start_time'].strftime('%H:%M')}-{new_lesson_info['end_time'].strftime('%H:%M')}"

            base_msg = gettext_lazy("Конфликт для планируемого занятия: %(subject)s (Группа: %(group)s) на %(date)s в %(time)s.") % {
                'subject': subject_name, 'group': group_name, 'date': date_str, 'time': time_str
            }
            
            details = ""
            if conflict_info['with'] == 'db':
                existing = conflict_info['existing_lesson']
                details = gettext_lazy("Пересекается с существующим занятием ID %(id)s: %(subj)s (Группа: %(gr)s) %(dt)s.") % {
                    'id': existing.id, 
                    'subj': existing.subject.name, 
                    'gr': existing.student_group.name,
                    'dt': existing.start_time.strftime('%d.%m %H:%M')
                }
            elif conflict_info['with'] == 'batch':
                batch_conflict = conflict_info['conflicting_batch_lesson']
                details = gettext_lazy("Пересекается с другим занятием из этого же шаблона: %(subj)s (Группа: %(gr)s) на %(dt)s.") % {
                    'subj': batch_conflict['subject'].name,
                    'gr': batch_conflict['student_group'].name,
                    'dt': batch_conflict['start_time'].strftime('%d.%m.%Y %H:%M')
                }
            
            conflict_type_readable = {
                'teacher': gettext_lazy("по преподавателю '%(name)s'") % {'name': new_lesson_info['teacher'].get_full_name()},
                'group': gettext_lazy("по группе '%(name)s'") % {'name': group_name},
                'classroom': gettext_lazy("по аудитории '%(name)s'") % {'name': new_lesson_info['classroom'].identifier if new_lesson_info.get('classroom') else 'N/A'},
            }.get(conflict_info['type'], conflict_info['type'])

            error_messages.append(f"{base_msg} Тип конфликта: {conflict_type_readable}. {details}")
        
        return sorted(list(set(error_messages))) # Уникальные сообщения, отсортированные