# edu_core/views.py
from decimal import ROUND_HALF_UP, Decimal
from urllib import request
from rest_framework.views import APIView
from datetime import datetime
import logging
from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch, Count, Avg, Sum, F, Subquery, OuterRef, Exists # Убедимся, что Avg тоже импортирован, если используется
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
import csv
from io import StringIO
from django.http import Http404, HttpResponseBadRequest, StreamingHttpResponse # Убрал Http404, если не используется
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from rest_framework import filters as drf_filters
from rest_framework.exceptions import ValidationError as DRFValidationError, PermissionDenied

from edu_core.exports import JournalExporter
from edu_core.filters import HomeworkFilter, HomeworkSubmissionFilter, LessonFilter


from .models import ( # Этот импорт должен быть
    AcademicYear, StudyPeriod, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)
# Импортируем models еще раз под псевдонимом, если где-то используется models.ModelName
from . import models as edu_core_models # <--- ДОБАВЛЕНО ДЛЯ ИСПРАВЛЕНИЯ ОШИБКИ PYLANCE

from .serializers import (
    AcademicYearSerializer, EduUserSerializer, ScheduleTemplateImportSerializer, StudyPeriodSerializer, SubjectTypeSerializer,
    SubjectSerializer, ClassroomSerializer, StudentGroupSerializer,
    CurriculumSerializer, CurriculumEntrySerializer,
    LessonSerializer, LessonListSerializer,
    LessonJournalEntrySerializer, HomeworkSerializer,
    HomeworkAttachmentSerializer, HomeworkSubmissionSerializer, SubmissionAttachmentSerializer,
    AttendanceSerializer, GradeSerializer, SubjectMaterialSerializer,
    TeacherLoadSerializer, GroupPerformanceSerializer, TeacherSubjectPerformanceSerializer,
    TeacherImportSerializer, SubjectImportSerializer, StudentGroupImportSerializer, # ScheduleImportSerializer,
    MyGradeSerializer, MyAttendanceSerializer, MyHomeworkSerializer, StudentHomeworkSubmissionSerializer
)
from users.permissions import (
    IsAdmin, IsTeacher, IsStudent, IsParent, IsTeacherOrAdmin, IsOwnerOrAdmin
)

# Убираем, т.к. .serializers уже импортирован
# from edu_core import serializers
# Убираем, т.к. .models уже импортирован
# from edu_core import models


from notifications.utils import (
        notify_lesson_change,
        notify_new_homework,
        notify_homework_graded,
        notify_new_grade,
        send_notification,
        # Добавим для уведомления преподавателя о сдаче ДЗ (если он не был определен ранее)
        # notify_assignment_submitted # Вызывается из HomeworkSubmissionViewSet.perform_create
    )
from notifications.models import Notification

from edu_core import models
from rest_framework.pagination import LimitOffsetPagination

from edu_core import serializers # Для Notification.NotificationType


logger = logging.getLogger(__name__) # Инициализация логгера, если еще не было

User = get_user_model()

class Echo:
    def write(self, value):
        return value

class StandardLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 10
    max_limit = 100

# --- АДМИНСКИЕ VIEWSETS ---
class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all().order_by('-start_date')
    serializer_class = AcademicYearSerializer
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def perform_create(self, serializer):
        academic_year_instance = serializer.save()
        try:
            StudyPeriod.objects.create(
                academic_year=academic_year_instance,
                name=academic_year_instance.name,
                start_date=academic_year_instance.start_date,
                end_date=academic_year_instance.end_date
            )
            logger.info(f"Автоматически создан учебный период '{academic_year_instance.name}' для учебного года ID {academic_year_instance.id}")
        except Exception as e:
            logger.error(f"Не удалось автоматически создать учебный период для учебного года ID {academic_year_instance.id}: {e}")
            raise DRFValidationError({ # Используем DRFValidationError
                "study_period_creation_error": _("Учебный год создан, но не удалось автоматически создать идентичный учебный период. Ошибка: %(error)s") % {'error': str(e)}
            })
class StudyPeriodViewSet(viewsets.ModelViewSet):
    queryset = StudyPeriod.objects.select_related('academic_year').all()
    serializer_class = StudyPeriodSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['academic_year']
    ordering_fields = ['start_date', 'name', 'academic_year__name']
    ordering = ['academic_year__start_date', 'start_date']

class SubjectTypeViewSet(viewsets.ModelViewSet):
    queryset = SubjectType.objects.all().order_by('name')
    serializer_class = SubjectTypeSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]

class SubjectViewSet(viewsets.ModelViewSet):
    # Базовый queryset - все предметы, для админа
    queryset = Subject.objects.select_related('subject_type').prefetch_related('lead_teachers__profile').all()
    serializer_class = SubjectSerializer
    # permission_classes будут определены в get_permissions для большей гибкости

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['subject_type'] # Оставляем, если админ/учитель могут фильтровать
    search_fields = ['name', 'code', 'description']
    ordering_fields = ['name', 'code']
    ordering = ['name']

    def get_permissions(self):
        """
        Определяет права доступа:
        - Админы могут делать CRUD.
        - Учителя могут читать (список своих предметов) и, возможно, создавать/редактировать (если разрешено).
          Пока сделаем CRUD только для админов, а чтение для учителей их предметов.
        """
        user = self.request.user
        if not user.is_authenticated:
            return [permissions.IsAuthenticated()] # Сначала базовая проверка

        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            # Только админы могут изменять данные о предметах
            return [IsAdmin()]
        elif self.action in ['list', 'retrieve']:
            # Админы и учителя могут просматривать
            if user.is_admin or user.is_teacher:
                return [permissions.IsAuthenticated()] # Дальнейшая фильтрация в get_queryset
            else:
                # Другие роли не имеют доступа к этому списку
                # Можно вернуть PermissionDenied() или пустой список прав,
                # что приведет к 403, если IsAuthenticated не пройдет.
                # Чтобы явно запретить, можно так:
                class DenyAccess(permissions.BasePermission):
                    def has_permission(self, request, view): return False
                return [DenyAccess()]
        return super().get_permissions()

    def get_queryset(self):
        """
        Фильтрует queryset в зависимости от роли пользователя.
        Вызывается для 'list' и 'retrieve' (и других действий, работающих с queryset).
        """
        user = self.request.user
        # Начинаем с базового queryset, определенного на уровне класса
        queryset = super().get_queryset() 

        if user.is_authenticated:
            if user.is_admin:
                # Админ видит все предметы
                logger.debug(f"SubjectViewSet: Admin {user.email} requesting all subjects.")
                return queryset.distinct()
            elif user.is_teacher:
                # Учитель видит только те предметы, которые он ведет (lead_teachers)
                logger.debug(f"SubjectViewSet: Teacher {user.email} requesting their lead subjects.")
                return queryset.filter(lead_teachers=user).distinct()
            else:
                # Другие аутентифицированные роли (студенты, родители) не видят этот список
                # или видят пустой список по умолчанию для /management/subjects/
                logger.debug(f"SubjectViewSet: Authenticated user {user.email} (role: {user.role}) has no specific access to this list. Returning none.")
                return Subject.objects.none()
        
        # Для неаутентифицированных пользователей (если IsAuthenticatedOrReadOnly было бы)
        return Subject.objects.none() # Или базовый queryset, если разрешено анонимное чтение

    def perform_create(self, serializer):
        # Если разрешим учителям создавать, то здесь можно добавить логику,
        # например, автоматически добавлять создающего учителя в lead_teachers.
        # Сейчас create доступен только админам согласно get_permissions.
        serializer.save()

    def perform_update(self, serializer):
        # Аналогично perform_create
        serializer.save()

class ClassroomViewSet(viewsets.ModelViewSet):
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['type', 'capacity']
    search_fields = ['identifier', 'equipment']
    ordering_fields = ['identifier', 'capacity']
    ordering = ['identifier']

class StudentGroupViewSet(viewsets.ModelViewSet):
    queryset = StudentGroup.objects.select_related(
        'academic_year', 'curator', 'group_monitor'
    ).prefetch_related('students').all()
    serializer_class = StudentGroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['academic_year', 'curator']
    search_fields = ['name', 'academic_year__name', 'curator__last_name', 'curator__first_name', 'curator__email']
    ordering_fields = ['name', 'academic_year__start_date']
    ordering = ['academic_year__start_date', 'name']

    def perform_create(self, serializer):
        data = self.request.data
        academic_year_id = data.get('academic_year')
        if not academic_year_id:
            raise DRFValidationError({'academic_year': _('Учебный год обязателен.')}) # Используем DRFValidationError
        try:
            academic_year = AcademicYear.objects.get(pk=academic_year_id)
        except AcademicYear.DoesNotExist:
            raise DRFValidationError({'academic_year': _('Учебный год с ID %(id)s не найден.') % {'id': academic_year_id}})
        except (ValueError, TypeError):
            raise DRFValidationError({'academic_year': _('Некорректный ID учебного года.')})

        curator_id = data.get('curator')
        curator = None
        if curator_id:
            try:
                curator = User.objects.get(pk=curator_id, role=User.Role.TEACHER)
            except User.DoesNotExist:
                raise DRFValidationError({'curator': _('Куратор (преподаватель) с ID %(id)s не найден.') % {'id': curator_id}})
            except (ValueError, TypeError):
                raise DRFValidationError({'curator': _('Некорректный ID куратора.')})

        students_ids_from_request = data.get('students', [])
        valid_student_ids = []
        if students_ids_from_request is not None:
            if not isinstance(students_ids_from_request, list):
                raise DRFValidationError({'students': _('Поле students должно быть списком ID студентов.')})
            for student_id in students_ids_from_request:
                try:
                    student_pk = int(student_id)
                    valid_student_ids.append(student_pk)
                except (ValueError, TypeError):
                    raise DRFValidationError({'students': _('ID студентов должны быть числами.')})
        
        group_monitor_id = data.get('group_monitor')
        group_monitor = None
        if group_monitor_id:
            try:
                group_monitor_pk = int(group_monitor_id)
                if group_monitor_pk not in valid_student_ids:
                    raise DRFValidationError({'group_monitor': _('Староста должен быть одним из студентов, добавленных в группу.')})
                group_monitor = User.objects.get(pk=group_monitor_pk, role=User.Role.STUDENT)
            except User.DoesNotExist:
                raise DRFValidationError({'group_monitor': _('Студент (староста) с ID %(id)s не найден.') % {'id': group_monitor_id}})
            except (ValueError, TypeError):
                 raise DRFValidationError({'group_monitor': _('Некорректный ID старосты.')})

        try:
            instance = serializer.save(
                academic_year=academic_year,
                curator=curator,
                group_monitor=group_monitor
            )
        except Exception as e:
            logger.error(f"Error saving student group instance via serializer: {e}")
            raise DRFValidationError(_("Не удалось сохранить группу. Проверьте введенные данные."))

        if valid_student_ids:
            instance.students.set(valid_student_ids)
        else:
            instance.students.clear()

class CurriculumViewSet(viewsets.ModelViewSet):
    queryset = Curriculum.objects.select_related('academic_year', 'student_group').prefetch_related('entries__subject', 'entries__teacher', 'entries__study_period').all()
    serializer_class = CurriculumSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['academic_year', 'student_group', 'is_active']
    search_fields = ['name', 'description', 'student_group__name', 'academic_year__name']
    ordering_fields = ['name', 'academic_year__name', 'student_group__name']
    ordering = ['academic_year__start_date', 'student_group__name', 'name']
class CurriculumEntryViewSet(viewsets.ModelViewSet):
    # queryset можно определить более общим или убрать его определение на уровне класса,
    # так как get_queryset() его полностью переопределит для вложенного маршрута.
    # queryset = CurriculumEntry.objects.all() # Можно оставить для не-вложенного доступа, если он нужен
    serializer_class = CurriculumEntrySerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    # filterset_fields можно оставить, если нужен прямой доступ к /curriculum-entries/?curriculum=X
    # но для вложенного он будет избыточен, если get_queryset() фильтрует.
    filterset_fields = { 
        # 'curriculum': ['exact'], # Это поле будет обработано в get_queryset для вложенного
        'subject': ['exact'], 
        'teacher': ['exact'], 
        'study_period': ['exact']
    }
    ordering_fields = ['study_period__start_date', 'subject__name'] # Убрал 'curriculum__name', т.к. curriculum уже один
    ordering = ['study_period__start_date', 'subject__name']

    def get_queryset(self):
        # Получаем curriculum_pk из URL kwargs, предоставленного вложенным роутером
        # Имя kwargs будет <lookup_field_в_роутере>_pk
        curriculum_id = self.kwargs.get('curriculum_pk') # <--- ИСПОЛЬЗУЕМ ПРАВИЛЬНЫЙ lookup kwarg

        if curriculum_id:
            # Фильтруем записи учебного плана по ID родительского учебного плана
            # и делаем все необходимые select_related/prefetch_related здесь
            return CurriculumEntry.objects.filter(curriculum_id=curriculum_id).select_related(
                'curriculum__academic_year', 
                'curriculum__student_group', 
                'subject', 
                'teacher__profile', # Добавил __profile для EduUserSerializer
                'study_period__academic_year' # Добавил __academic_year для StudyPeriodSerializer
            ).prefetch_related(
                'subject__lead_teachers__profile' # Пример prefetch для M2M
            )
        else:
            # Если ViewSet доступен не только как вложенный, а, например, по
            # /api/edu-core/management/curriculum-entries/ (без ID учебного плана),
            # то здесь можно вернуть все записи (если это нужно и разрешено правами)
            # или вернуть пустой queryset, если доступ только через вложенный URL.
            # Для админки часто возвращают .all() или фильтруют по другим параметрам.
            # Если предполагается ТОЛЬКО вложенный доступ:
            return CurriculumEntry.objects.none() 
            # Или, если хотите, чтобы общий список работал с фильтром ?curriculum=ID:
            # return CurriculumEntry.objects.select_related(...).all()
            # DjangoFilterBackend тогда отработает по ?curriculum=ID из filterset_fields.

    # perform_create нужно обновить, чтобы curriculum_id брался из URL, если не передан в теле
    def perform_create(self, serializer):
        curriculum_id = self.kwargs.get('curriculum_pk')
        if curriculum_id:
            # Получаем объект Curriculum, чтобы убедиться, что он существует
            curriculum_instance = get_object_or_404(Curriculum, pk=curriculum_id)
            # Передаем curriculum_instance, если сериализатор ожидает объект,
            # или curriculum_id, если сериализатор ожидает ID.
            # Ваш CurriculumEntrySerializer ожидает ID через 'curriculum' в extra_kwargs
            # или объект через source='curriculum'
            # Лучше передать объект, если extra_kwargs 'curriculum' настроен на ForeignKey,
            # или ID, если он настроен как PrimaryKeyRelatedField для записи.
            # В вашем случае 'curriculum': {'write_only': True, 'queryset': Curriculum.objects.all()}
            # значит, он ожидает ID или объект. Передача объекта надежнее.
            serializer.save(curriculum=curriculum_instance) 
        else:
            # Если curriculum_id не пришел из URL (например, прямой POST на /curriculum-entries/)
            # то он должен быть в request.data и будет обработан сериализатором.
            # Если он обязателен, сериализатор выдаст ошибку.
            serializer.save()
class LessonViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления Занятиями (Lessons).
    Предоставляет CRUD для админов/учителей и кастомный эндпоинт 'my-schedule'
    для получения персонального расписания студентов, учителей и родителей.
    """
    queryset = Lesson.objects.select_related(
        'study_period__academic_year', 
        'student_group', 
        'subject', 
        'teacher',  # Убедитесь, что teacher - это FK на вашу модель User
        'classroom', 
        'curriculum_entry', 
        'created_by' # Убедитесь, что created_by - это FK на вашу модель User
    ).prefetch_related(
        'journal_entry',
        'student_group__students' # Для быстрой проверки принадлежности студента к группе
    ).all()
    
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = LessonFilter # Используем наш кастомный FilterSet
    
    search_fields = [
        'subject__name', 
        'teacher__last_name', 'teacher__first_name', # Искать и по имени преподавателя
        'student_group__name', 
        'classroom__identifier', 
        'journal_entry__topic_covered'
    ]
    ordering_fields = ['start_time', 'end_time', 'subject__name', 'student_group__name']
    ordering = ['start_time'] # Сортировка по умолчанию

    def get_serializer_class(self):
        # Для списков (включая my_schedule) используем более легкий LessonListSerializer
        if self.action in ['list', 'my_schedule']:
            return LessonListSerializer
        return LessonSerializer # Для retrieve, create, update используем полный LessonSerializer

    def get_permissions(self):
        """
        Права доступа:
        - CRUD операции (create, update, partial_update, destroy): Только аутентифицированные Учителя или Админы.
        - list (общий список всех занятий): Только аутентифицированные Админы. Учителя видят только свои.
        - my_schedule: Только аутентифицированные пользователи (Студенты, Учителя, Родители, Админы - логика фильтрации внутри).
        - retrieve (просмотр одного занятия): Все аутентифицированные (но queryset может быть ограничен ролью).
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        elif self.action == 'my_schedule':
            # Достаточно IsAuthenticated, так как my_schedule фильтрует по пользователю.
            # Можно добавить IsStudent, IsTeacher, IsParent, IsAdmin через OR, но IsAuthenticated проще.
            return [permissions.IsAuthenticated()] 
        elif self.action == 'list':
            # Для общего списка /lessons/ - только админы или учителя (учителя видят свои)
            return [permissions.IsAuthenticated()] # Дальнейшая фильтрация в get_queryset
        # Для retrieve (просмотр одного занятия)
        return [permissions.IsAuthenticated()]


    def get_queryset(self):
        """
        Возвращает queryset в зависимости от action и роли пользователя.
        Базовый queryset уже определен на уровне класса.
        """
        user = self.request.user
        # Используем queryset, определенный на уровне класса (с select_related и prefetch_related)
        queryset = super().get_queryset() 

        # Для action 'list' (GET /lessons/)
        if self.action == 'list':
            if not user.is_admin: # Админ видит все (базовый queryset)
                if user.is_teacher:
                    # Учитель видит только свои занятия в общем списке
                    return queryset.filter(teacher=user).distinct()
                else:
                    # Студенты, родители и другие не-админы/не-учителя не должны видеть общий список всех занятий
                    return Lesson.objects.none()
        
        # Для action 'retrieve' (GET /lessons/{id}/)
        # Можно добавить логику, чтобы пользователь мог видеть только те занятия, к которым имеет отношение
        # Например, студент - только занятия своей группы, учитель - свои и т.д.
        # Пока оставляем так, что если ID известен, его можно получить (IsAuthenticated).
        # Если нужно ограничить, то:
        # if self.action == 'retrieve':
        #     # ... логика проверки доступа к конкретному занятию ...
        #     pass

        return queryset.distinct() # distinct() на случай дубликатов из-за M2M в фильтрах или prefetch

    @action(detail=False, methods=['get'], url_path='my-schedule', permission_classes=[permissions.IsAuthenticated])
    def my_schedule(self, request):
        """
        Возвращает персонализированное расписание для текущего пользователя.
        Фильтры (включая даты) применяются через DjangoFilterBackend с использованием self.filterset_class.
        """
        user = request.user
        # Используем queryset, определенный на уровне класса (он уже оптимизирован)
        base_queryset = super().get_queryset() 

        # 1. Фильтруем базовый queryset по роли пользователя
        if hasattr(user, 'is_student') and user.is_student:
            # Для студента: занятия его группы
            queryset = base_queryset.filter(student_group__students=user)
        elif hasattr(user, 'is_teacher') and user.is_teacher:
            # Для учителя: занятия, которые он ведет
            queryset = base_queryset.filter(teacher=user)
        elif hasattr(user, 'is_parent') and user.is_parent:
            # Для родителя: занятия групп его детей
            # Убедитесь, что у User есть корректная связь с детьми (например, user.children M2M на User)
            # или через профили детей.
            if hasattr(user, 'children') and user.children.exists(): # ПРОВЕРЬТЕ ИМЯ СВЯЗИ
                children_ids = user.children.values_list('id', flat=True)
                # Находим группы, в которых состоят дети
                student_groups_of_children = StudentGroup.objects.filter(students__id__in=children_ids).distinct()
                queryset = base_queryset.filter(student_group__in=student_groups_of_children)
            else:
                queryset = Lesson.objects.none() # У родителя нет привязанных детей
        elif hasattr(user, 'is_admin') and user.is_admin:
            # Для админа (если он зачем-то зашел на my-schedule):
            # Можно показать все занятия или его личные, если он еще и учитель.
            # Для консистентности, если админ не учитель, его "my-schedule" будет пустым.
            if hasattr(user, 'is_teacher') and user.is_teacher:
                 queryset = base_queryset.filter(teacher=user)
            else:
                 queryset = base_queryset # Или Lesson.objects.none() если админ не может иметь "свое" расписание
        else:
            # Неизвестная роль или пользователь без специфических прав на "мое расписание"
            queryset = Lesson.objects.none()

        # 2. Применяем фильтры из запроса (включая даты, поиск и т.д.)
        # DjangoFilterBackend сделает это автоматически, используя self.filterset_class (LessonFilter)
        print(f"Request query_params: {request.query_params}")

        filtered_queryset = self.filter_queryset(queryset.distinct())
        
        # 3. Пагинация
        page = self.paginate_queryset(filtered_queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(filtered_queryset, many=True, context={'request': request})
        return Response(serializer.data)

    # --- CRUD Методы (perform_create, perform_update, perform_destroy) ---
    # Эти методы вызываются стандартными actions ModelViewSet: create, update, partial_update, destroy
    # Они будут работать для эндпоинтов /lessons/ (POST, PUT, PATCH, DELETE)

    def perform_create(self, serializer):
        user = self.request.user
        teacher_for_lesson = serializer.validated_data.get('teacher')
        
        # Учитель может создавать занятия только для себя, если он не админ
        if user.is_teacher and not user.is_admin and teacher_for_lesson != user:
            self.permission_denied(self.request, message=_("Вы можете создавать занятия только для себя."))
        
        lesson = serializer.save(created_by=user)
        notify_lesson_change(lesson, action="создано")

    def perform_update(self, serializer):
        instance = serializer.instance
        user = self.request.user
        
        # Учитель может изменять только свои занятия или созданные им, если он не админ
        if user.is_teacher and not user.is_admin and instance.teacher != user and instance.created_by != user:
            self.permission_denied(self.request, message=_('Вы можете изменять только свои или созданные вами занятия.'))
        
        lesson = serializer.save()
        notify_lesson_change(lesson, action="изменено")

    def perform_destroy(self, instance):
        user = self.request.user
        
        # Учитель может удалять только свои занятия или созданные им, если он не админ
        if user.is_teacher and not user.is_admin and instance.teacher != user and instance.created_by != user:
            self.permission_denied(self.request, message=_('Вы можете удалять только свои или созданные вами занятия.'))
        
        # Копируем данные для уведомления перед удалением
        lesson_copy_for_notification = {
            'id': instance.id,
            'subject_name': getattr(instance.subject, 'name', 'N/A'),
            'group_name': getattr(instance.student_group, 'name', 'N/A'), # Исправлено на student_group
            'start_time_str': instance.start_time.strftime('%d.%m %H:%M') if instance.start_time else 'N/A',
            'teacher': instance.teacher,
            'group_students': list(instance.student_group.students.filter(is_active=True)) if hasattr(instance.student_group, 'students') else [],
        }
        
        instance.delete()
        
        message = f"Удалено занятие: {lesson_copy_for_notification['subject_name']} для {lesson_copy_for_notification['group_name']} ({lesson_copy_for_notification['start_time_str']})"
        recipients = set()
        if lesson_copy_for_notification['teacher']: 
            recipients.add(lesson_copy_for_notification['teacher'])
        recipients.update(lesson_copy_for_notification['group_students'])
        # TODO: Добавить логику для уведомления родителей студентов из группы
        
        for r_user in recipients:
            send_notification(r_user, message, Notification.NotificationType.SCHEDULE, related_object=None)

class LessonJournalEntryViewSet(viewsets.ModelViewSet):
    queryset = LessonJournalEntry.objects.select_related('lesson__subject', 'lesson__student_group', 'lesson__teacher', 'lesson__study_period__academic_year').prefetch_related('homework_assignments', 'attendances').all()
    serializer_class = LessonJournalEntrySerializer
    # permission_classes определены в get_permissions
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = {'lesson': ['exact'], 'lesson__study_period': ['exact'], 'lesson__study_period__academic_year': ['exact'], 'lesson__student_group': ['exact'], 'lesson__teacher': ['exact'], 'lesson__subject': ['exact'], 'date_filled': ['gte', 'lte', 'date__exact']}
    ordering_fields = ['lesson__start_time', 'date_filled']; ordering = ['-lesson__start_time']

    def _check_teacher_lesson_permission(self, lesson, user, action_verb="изменять"):
        if user.is_teacher and not user.is_admin and lesson.teacher != user:
            # Используем PermissionDenied из DRF
            raise PermissionDenied(detail=_("Вы можете %(action)s журнал только для своих занятий.") % {'action': action_verb})

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return [permissions.IsAuthenticated()] # Для list, retrieve

    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if self.action == 'list': # Применяем фильтры для списка
            if user.is_teacher and not user.is_admin: queryset = queryset.filter(lesson__teacher=user)
            elif user.is_student: queryset = queryset.filter(lesson__student_group__students=user)
            elif user.is_parent and hasattr(user, 'children') and user.children.exists():
                children_groups_ids = StudentGroup.objects.filter(students__in=user.children.all()).values_list('id', flat=True).distinct()
                queryset = queryset.filter(lesson__student_group_id__in=children_groups_ids)
            elif not user.is_admin: return LessonJournalEntry.objects.none()
        return queryset.distinct()

    def perform_create(self, serializer):
        lesson = serializer.validated_data.get('lesson')
        self._check_teacher_lesson_permission(lesson, self.request.user, action_verb="заполнять")
        if LessonJournalEntry.objects.filter(lesson=lesson).exists():
            raise DRFValidationError({'lesson': _("Для этого занятия уже существует запись в журнале.")})
        serializer.save()

    def perform_update(self, serializer):
        self._check_teacher_lesson_permission(serializer.instance.lesson, self.request.user, action_verb="изменять")
        serializer.save()

    def perform_destroy(self, instance):
        self._check_teacher_lesson_permission(instance.lesson, self.request.user, action_verb="удалять")
        instance.delete()

class HomeworkViewSet(viewsets.ModelViewSet):
    
    queryset = Homework.objects.select_related('journal_entry__lesson__subject', 'author', 'journal_entry__lesson__student_group').prefetch_related('attachments', 'related_materials', 'submissions__student').all()
    serializer_class = HomeworkSerializer
    # permission_classes определены в get_permissions
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    pagination_class = StandardLimitOffsetPagination

        # Указываем наш кастомный класс фильтра
    filterset_class = HomeworkFilter 
    search_fields = ['title', 'description']; ordering_fields = ['due_date', 'created_at', 'title']; ordering = ['-due_date']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        logger.debug(f"ENTERING HomeworkViewSet.get_queryset for action: {self.action}, view: {type(self).__name__}")
        user = self.request.user
        qs = super().get_queryset() # Получаем базовый queryset, к которому применятся фильтры
        logger.debug(f"Initial queryset count from class attribute (or super): {qs.count()}")
        logger.debug(f"URL kwargs: {self.kwargs}")

        journal_entry_pk_from_url = self.kwargs.get('journal_entry_pk')
        
        if journal_entry_pk_from_url:
            # Эта часть для вложенных URL, фильтр по ?lesson=ID будет работать и здесь
            logger.debug(f"Nested route detected. Filtering by journal_entry_pk: {journal_entry_pk_from_url}")
            try:
                journal_entry_id_int = int(journal_entry_pk_from_url)
                qs = qs.filter(journal_entry_id=journal_entry_id_int)
                # ... остальная ваша логика для вложенных маршрутов ...
            except (ValueError, Exception) as e:
                logger.error(f"Error in nested route processing for HomeworkViewSet: {e}", exc_info=True)
                return Homework.objects.none()
        
        elif self.action == 'list':
            # Общая логика фильтрации по ролям для НЕ вложенного маршрута
            logger.debug("Non-nested 'list' action. Applying role-based filters.")
            if hasattr(user, 'is_student') and user.is_student:
                qs = qs.filter(journal_entry__lesson__student_group__students=user)
            elif hasattr(user, 'is_parent') and user.is_parent and hasattr(user, 'children') and user.children.exists():
                children_groups_ids = StudentGroup.objects.filter(students__in=user.children.all()).values_list('id', flat=True).distinct()
                qs = qs.filter(journal_entry__lesson__student_group_id__in=children_groups_ids)
            elif hasattr(user, 'is_teacher') and user.is_teacher and not (hasattr(user, 'is_admin') and user.is_admin):
                qs = qs.filter(Q(author=user) | Q(journal_entry__lesson__teacher=user))
            elif not (hasattr(user, 'is_admin') and user.is_admin):
                logger.debug("User is not admin/teacher/student/parent for 'list' action. Returning empty.")
                return Homework.objects.none()
        
        final_qs = qs.distinct()
        logger.debug(f"Final queryset before DRF filters apply (count: {final_qs.count()}): {str(final_qs.query)}")
        logger.debug(f"EXITING HomeworkViewSet.get_queryset for view: {type(self).__name__}")
        return final_qs # DjangoFilterBackend применит фильтры к этому queryset

    def perform_create(self, serializer):
        journal_entry = serializer.validated_data.get('journal_entry')
        user = self.request.user
        if user.is_teacher and not user.is_admin and journal_entry.lesson.teacher != user:
             raise PermissionDenied(detail=_("Вы можете создавать ДЗ только для своих занятий."))
        homework = serializer.save(author=user)
        # --- УВЕДОМЛЕНИЕ О НОВОМ ДЗ ---
        notify_new_homework(homework)

class StudentMyHomeworkDetailView(generics.RetrieveAPIView):

    serializer_class = MyHomeworkSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]
    lookup_url_kwarg = 'homework_id'

    def get_object(self):
        user = self.request.user
        homework_id = self.kwargs.get(self.lookup_url_kwarg)
        try:
            homework = Homework.objects.select_related(
                'journal_entry__lesson__subject', 'author', 'journal_entry__lesson__student_group'
            ).prefetch_related(
                'attachments', 'related_materials',
                Prefetch('submissions', queryset=HomeworkSubmission.objects.filter(student=user), to_attr='my_current_submission_list')
            ).get(pk=homework_id, journal_entry__lesson__student_group__students=user)
            if hasattr(homework, 'my_current_submission_list') and homework.my_current_submission_list:
                homework.my_single_submission_for_serializer = homework.my_current_submission_list[0]
            else:
                homework.my_single_submission_for_serializer = None
            return homework
        except Homework.DoesNotExist:
            raise Http404(_("Домашнее задание не найдено или недоступно для вас.")) # Http404 из django.http
        except Exception as e: # Ловим другие ошибки, например, если homework_id не число
            logger.error(f"Error in StudentMyHomeworkDetailView.get_object: {e}")
            raise Http404(_("Ошибка при получении домашнего задания."))


    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

class HomeworkAttachmentViewSet(viewsets.ModelViewSet):
    queryset = HomeworkAttachment.objects.select_related(
        'homework__author', # Автор самого ДЗ
        'homework__journal_entry__lesson__teacher' # Учитель урока, к которому привязано ДЗ
    ).all()
    serializer_class = HomeworkAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated] # Базовые права

    def get_permissions(self):
        user = self.request.user
        # Создавать файлы к ДЗ могут учителя или админы
        if self.action == 'create':
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        
        # Редактировать (хотя обычно не используется для файлов) или удалять
        # могут учителя (с проверкой принадлежности ДЗ) или админы.
        # IsOwnerOrAdmin здесь не совсем подходит, т.к. у HomeworkAttachment нет поля 'user'.
        # Права на объект (attachment) будут проверяться в perform_update/perform_destroy.
        if self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()] 
            # В perform_destroy/update будет дополнительная проверка, может ли 
            # конкретный учитель удалить/изменить вложение для КОНКРЕТНОГО ДЗ.
            
        # Для list, retrieve - IsAuthenticated достаточно, get_queryset сделает остальное.
        return super().get_permissions()

    def _can_user_access_homework_for_attachment(self, user, homework_instance):
        """
        Проверяет, имеет ли пользователь доступ к ДЗ, к которому относится вложение.
        Это нужно для list/retrieve вложений, чтобы не показывать лишнего.
        """
        if user.is_admin: return True
        if user.is_teacher and (homework_instance.author == user or 
                                (hasattr(homework_instance, 'journal_entry') and 
                                 hasattr(homework_instance.journal_entry, 'lesson') and 
                                 homework_instance.journal_entry.lesson.teacher == user)):
            return True
        # Студенты и родители видят вложения, если видят само ДЗ
        if hasattr(homework_instance, 'journal_entry') and hasattr(homework_instance.journal_entry, 'lesson'):
            lesson = homework_instance.journal_entry.lesson
            if user.is_student and lesson.student_group.students.filter(pk=user.pk).exists():
                return True
            if user.is_parent and hasattr(user, 'children') and user.children.exists() and \
               lesson.student_group.students.filter(pk__in=user.children.all().values_list('id',flat=True)).exists():
                return True
        return False

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset() # Берем self.queryset
        homework_id_param = self.request.query_params.get('homework_id')

        if homework_id_param:
            try:
                homework_id = int(homework_id_param)
                # Проверяем, существует ли такое ДЗ и имеет ли пользователь к нему доступ
                homework_instance = get_object_or_404(Homework, pk=homework_id)
                if not self._can_user_access_homework_for_attachment(user, homework_instance):
                    return HomeworkAttachment.objects.none()
                queryset = queryset.filter(homework_id=homework_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid homework_id format: {homework_id_param}")
                return HomeworkAttachment.objects.none()
            except Homework.DoesNotExist: # Уже обработано get_object_or_404
                return HomeworkAttachment.objects.none()
        elif not user.is_admin:
            # Если homework_id не указан, то не-админы не видят список ВСЕХ вложений
            # Можно было бы фильтровать по всем ДЗ, к которым у них есть доступ, но это сложнее
            # и потенциально медленнее. Проще требовать homework_id.
            logger.debug(f"User {user.email} (not admin) trying to list all attachments without homework_id. Returning none.")
            return HomeworkAttachment.objects.none()
        
        return queryset.distinct()

    def perform_create(self, serializer):
        user = self.request.user
        # homework должен быть в validated_data, т.к. это FK в HomeworkAttachment
        homework_instance = serializer.validated_data.get('homework')

        if not homework_instance:
            # Это не должно произойти, если сериализатор требует homework
            raise serializers.ValidationError({"homework": "Необходимо указать домашнее задание."})

        # Проверка прав: создавать вложение может админ или учитель,
        # который является автором ДЗ или учителем урока, к которому относится ДЗ.
        can_create = False
        if user.is_admin:
            can_create = True
        elif user.is_teacher:
            if homework_instance.author == user or \
               (hasattr(homework_instance, 'journal_entry') and 
                hasattr(homework_instance.journal_entry, 'lesson') and 
                homework_instance.journal_entry.lesson.teacher == user):
                can_create = True
        
        if not can_create:
            raise PermissionDenied(detail=_("Вы не можете добавлять файлы к этому домашнему заданию."))
        
        serializer.save()
        logger.info(f"HomeworkAttachment created for HW ID {homework_instance.id} by user {user.email}")

    def perform_update(self, serializer):
        # Обновление файлов обычно не делают, их заменяют (удаляют старый, добавляют новый).
        # Но если логика обновления нужна:
        user = self.request.user
        attachment_instance = serializer.instance
        homework_instance = attachment_instance.homework

        can_update = False
        if user.is_admin:
            can_update = True
        elif user.is_teacher:
            if homework_instance.author == user or \
               (hasattr(homework_instance, 'journal_entry') and 
                hasattr(homework_instance.journal_entry, 'lesson') and 
                homework_instance.journal_entry.lesson.teacher == user):
                can_update = True
        
        if not can_update:
            raise PermissionDenied(detail=_("Вы не можете изменять этот файл."))
            
        serializer.save()
        logger.info(f"HomeworkAttachment ID {attachment_instance.id} for HW ID {homework_instance.id} updated by user {user.email}")

    def perform_destroy(self, instance):
        """
        Переопределяем для проверки прав перед удалением вложения.
        `instance` здесь - это объект HomeworkAttachment.
        """
        user = self.request.user
        homework_instance = instance.homework # Получаем ДЗ, к которому относится вложение

        # Проверка прав: удалить вложение может админ или учитель,
        # который является автором ДЗ или учителем урока, к которому относится ДЗ.
        can_delete = False
        if user.is_admin:
            can_delete = True
        elif user.is_teacher:
            # Учитель, который автор ДЗ
            if homework_instance.author == user:
                can_delete = True
            # ИЛИ учитель, который ведет урок, к которому привязано ДЗ (через journal_entry)
            elif hasattr(homework_instance, 'journal_entry') and \
                 hasattr(homework_instance.journal_entry, 'lesson') and \
                 homework_instance.journal_entry.lesson.teacher == user:
                can_delete = True
        
        if not can_delete:
            # Выбрасываем исключение, если прав нет
            raise PermissionDenied(detail=_("У вас нет прав на удаление этого файла."))
            # Или можно вернуть Response(status=status.HTTP_403_FORBIDDEN), но DRF обычно сам это делает

        attachment_id_for_log = instance.id # Сохраняем ID для логирования
        file_path_for_log = str(instance.file.path) if instance.file else "No file path"

        # Django автоматически удалит файл с диска при instance.delete()
        instance.delete()

        logger.info(f"HomeworkAttachment ID {attachment_id_for_log} (file: {file_path_for_log}) "
                    f"for Homework ID {homework_instance.id} deleted by user {user.email}")
class HomeworkSubmissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления сдачами домашних заданий (HomeworkSubmission).
    - Админы видят все.
    - Учителя видят сдачи по своим ДЗ или ДЗ для своих занятий.
    - Студенты (если этот ViewSet используется и для них) видят только свои сдачи.
    Поддерживает фильтрацию через HomeworkSubmissionFilter.
    """
    pagination_class = StandardLimitOffsetPagination

    # Атрибут queryset на уровне класса: базовый набор данных
    queryset = HomeworkSubmission.objects.select_related(
        'homework__journal_entry__lesson__subject', 
        'student__profile', 
        'homework__author__profile', # Автор самого ДЗ
        'grade_for_submission' # Для быстрого доступа к оценке (если OneToOne)
    ).prefetch_related(
        'attachments' # Файлы, прикрепленные к сдаче
    ).order_by('-submitted_at') # Сортировка по умолчанию

    # serializer_class будет определен в get_serializer_class
    permission_classes = [permissions.IsAuthenticated] # Базовые права, уточняются в get_permissions
    
    filter_backends = [
        DjangoFilterBackend, 
        drf_filters.SearchFilter,
        drf_filters.OrderingFilter
    ]
    filterset_class = HomeworkSubmissionFilter # Используем наш кастомный FilterSet
    
    search_fields = [
        'student__last_name', 
        'student__first_name', 
        'student__email',
        'homework__title', 
        'content'
    ]
    ordering_fields = ['submitted_at', 'student__last_name', 'homework__title']
    # ordering уже задан в self.queryset

    def get_serializer_class(self):
        """
        Определяет, какой сериализатор использовать в зависимости от действия.
        """
        # Если это эндпоинт для студента, который создает/обновляет свою сдачу
        # (например, /student/my-homework-submissions/), то используем StudentHomeworkSubmissionSerializer
        # Если это общий /management/homework-submissions/, то HomeworkSubmissionSerializer
        # Здесь мы предполагаем, что ViewSet используется для /management/homework-submissions/
        # и для возможных действий студента, если они реализованы здесь.
        # Для простоты пока оставим один, но это место для разделения.
        
        # if self.request.user.is_student and self.action in ['create', 'update', 'partial_update', 'retrieve', 'list']:
        #     return StudentHomeworkSubmissionSerializer # Или ваш MyHomeworkSubmissionSerializer
        
        if self.action == 'grade_submission':
             return GradeSerializer # Для действия оценки используем GradeSerializer
        
        return HomeworkSubmissionSerializer # По умолчанию

    def get_permissions(self):
        """Определяет права доступа в зависимости от действия."""
        logger.debug(f"HomeworkSubmissionViewSet.get_permissions called for action: {self.action}")
        user = self.request.user

        if self.action == 'create':
            # Создавать сдачу могут только студенты (если это эндпоинт для студента)
            # Если это админский эндпоинт, то, возможно, админ может создать сдачу от имени студента (сложно)
            # Пока предположим, что create здесь не для студентов, а для админов/учителей (что странно для сдачи)
            # Либо этот ViewSet не должен иметь 'create' для админов.
            # Оставим IsTeacherOrAdmin, если они могут как-то инициировать "сдачу".
             return [permissions.IsAuthenticated(), IsTeacherOrAdmin()] # Или IsStudent(), если это студенческий эндпоинт

        if self.action in ['update', 'partial_update']:
            # Редактировать могут:
            # 1. Админ
            # 2. Учитель (если это ДЗ по его предмету/уроку или он автор ДЗ)
            # 3. Студент-владелец (если работа еще не оценена)
            return [permissions.IsAuthenticated()] # Проверка владельца/прав будет в perform_update

        if self.action == 'destroy':
            # Удалять могут админ, учитель (с проверкой) или студент-владелец (если не оценена)
            return [permissions.IsAuthenticated()] # Проверка в perform_destroy

        if self.action == 'grade_submission':
            # Оценивать могут учителя или админы
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
            
        # Для list, retrieve - базовых прав IsAuthenticated достаточно,
        # get_queryset далее отфильтрует по роли.
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """
        Формирует queryset на основе роли пользователя.
        Фильтры из URL (через HomeworkSubmissionFilter) будут применены ПОСЛЕ этого метода.
        """
        logger.debug(f"ENTERING HomeworkSubmissionViewSet.get_queryset for action: {self.action}")
        user = self.request.user
        # Используем queryset, определенный на уровне класса, как отправную точку.
        qs = self.queryset.all() # Создаем копию
        
        logger.debug(f"Initial queryset model: {type(qs.model).__name__}, count: {qs.count()}")

        # Логика фильтрации по ролям для действия 'list' (GET /management/homework-submissions/)
        # Для retrieve (GET /management/homework-submissions/{id}/) права проверяются пермишенами объекта.
        if self.action == 'list':
            if hasattr(user, 'is_teacher') and user.is_teacher and not (hasattr(user, 'is_admin') and user.is_admin):
                # Учитель видит сдачи по ДЗ, где он автор ИЛИ учитель занятия, к которому привязано ДЗ
                qs = qs.filter(
                    Q(homework__author=user) | 
                    Q(homework__journal_entry__lesson__teacher=user)
                )
            elif hasattr(user, 'is_student') and user.is_student:
                # Если этот ViewSet используется для эндпоинта, где студент видит ВСЕ сдачи,
                # то этот фильтр нужен. Если только для /student/my-submissions/, то эта ветка не нужна тут.
                # Предположим, для /management/... студент не должен видеть ничего без ?student=ID
                # Но если это какой-то общий список, где и студент может быть, то:
                # qs = qs.filter(student=user)
                logger.debug(f"User is Student, but this is likely a management endpoint. No automatic student filter applied here for 'list'. Filter by ?student=ID if needed.")
                # Чтобы студент вообще ничего не видел в общем списке /management/homework-submissions/ без ?student=ID:
                # return HomeworkSubmission.objects.none()
                pass # Фильтр по ?student=ID сделает свое дело
            elif hasattr(user, 'is_parent') and user.is_parent:
                 # Родитель в этом общем списке ничего не видит без фильтра по ребенку
                 logger.debug("User is Parent. No data shown in general list. Filter by ?student=CHILD_ID.")
                 return HomeworkSubmission.objects.none()
            elif not (hasattr(user, 'is_admin') and user.is_admin):
                # Другие не-админские роли не видят общий список
                logger.debug("User is not Admin/Teacher/Student with special list view. Returning empty.")
                return HomeworkSubmission.objects.none()
            # Админ видит всё (qs не меняется дополнительно)
        
        final_qs = qs.distinct()
        logger.debug(f"Final queryset before DRF filters apply (count: {final_qs.count()}): {str(final_qs.query if final_qs.exists() else 'Queryset is empty')}")
        logger.debug(f"EXITING HomeworkSubmissionViewSet.get_queryset")
        return final_qs

    def perform_create(self, serializer):
        """
        Вызывается при создании новой сдачи ДЗ (POST /management/homework-submissions/).
        Этот метод обычно не используется студентами через этот админский ViewSet.
        Если админ/учитель создает сдачу ОТ ИМЕНИ студента.
        """
        logger.debug(f"ENTERING HomeworkSubmissionViewSet.perform_create")
        user_creating = self.request.user # Тот, кто делает запрос (админ/учитель)
        
        # Получаем студента и ДЗ из validated_data (сериализатор должен их требовать)
        student_for_submission = serializer.validated_data.get('student')
        homework_for_submission = serializer.validated_data.get('homework')

        if not student_for_submission or not homework_for_submission:
            raise DRFValidationError(_("Необходимо указать студента и домашнее задание для создания сдачи."))

        # Проверка, что студент принадлежит группе этого ДЗ
        if not homework_for_submission.journal_entry.lesson.student_group.students.filter(pk=student_for_submission.pk).exists():
            raise PermissionDenied(detail=_("Студент не принадлежит группе, для которой это домашнее задание."))

        # Проверка на повторную сдачу
        if HomeworkSubmission.objects.filter(homework=homework_for_submission, student=student_for_submission).exists():
            raise DRFValidationError(_(f"Студент {student_for_submission.get_full_name()} уже сдавал это домашнее задание. Вы можете отредактировать существующую сдачу."))
        
        submission = serializer.save() # student и homework уже должны быть установлены сериализатором
        logger.info(f"Submission ID {submission.id} created by {user_creating.email} for student {student_for_submission.email}, HW ID {homework_for_submission.id}")
        # Уведомление преподавателю о сдаче (если создавал не он сам)
        teacher_to_notify = homework_for_submission.author
        if teacher_to_notify and teacher_to_notify != user_creating and teacher_to_notify.is_active:
            student_name = student_for_submission.get_full_name() or student_for_submission.email
            message = f"Студент {student_name} сдал(а) ДЗ: '{homework_for_submission.title}' (добавлено администратором/другим учителем)"
            send_notification(teacher_to_notify, message, Notification.NotificationType.ASSIGNMENT_SUBMITTED, submission)


    def perform_update(self, serializer):
        logger.debug(f"ENTERING HomeworkSubmissionViewSet.perform_update, instance: {serializer.instance.id}")
        user_updating = self.request.user
        submission = serializer.instance

        # Проверка прав на редактирование
        can_edit = False
        if user_updating.is_admin:
            can_edit = True
        elif user_updating.is_teacher:
            # Учитель может редактировать, если он автор ДЗ или учитель урока
            if submission.homework.author == user_updating or \
               submission.homework.journal_entry.lesson.teacher == user_updating:
                can_edit = True
        elif user_updating.is_student and submission.student == user_updating:
            # Студент может редактировать свою работу, если она не оценена
            if not (hasattr(submission, 'grade_for_submission') and submission.grade_for_submission):
                can_edit = True
        
        if not can_edit:
            raise PermissionDenied(detail=_("У вас нет прав на редактирование этой сдачи домашнего задания."))

        serializer.save()
        logger.info(f"Submission ID {submission.id} updated by {user_updating.email}")
        # TODO: Уведомление об изменении сдачи (если нужно)

    def perform_destroy(self, instance):
        logger.debug(f"ENTERING HomeworkSubmissionViewSet.perform_destroy, instance: {instance.id}")
        user_destroying = self.request.user
        
        # Проверка прав на удаление (аналогично редактированию)
        can_delete = False
        if user_destroying.is_admin:
            can_delete = True
        elif user_destroying.is_teacher:
            if instance.homework.author == user_destroying or \
               instance.homework.journal_entry.lesson.teacher == user_destroying:
                can_delete = True
        elif user_destroying.is_student and instance.student == user_destroying:
            if not (hasattr(instance, 'grade_for_submission') and instance.grade_for_submission):
                can_delete = True

        if not can_delete:
            raise PermissionDenied(detail=_("У вас нет прав на удаление этой сдачи домашнего задания."))
            
        # Копируем данные для уведомления перед удалением
        student_name_for_notification = instance.student.get_full_name()
        homework_title_for_notification = instance.homework.title
        teacher_to_notify = instance.homework.author

        instance.delete()
        logger.info(f"Submission ID {instance.id} deleted by {user_destroying.email}")

        # Уведомление преподавателю (если удалял не он)
        if teacher_to_notify and teacher_to_notify != user_destroying and teacher_to_notify.is_active:
            message = f"Сдача ДЗ '{homework_title_for_notification}' студентом {student_name_for_notification} была удалена."
            send_notification(teacher_to_notify, message, Notification.NotificationType.SYSTEM, instance.homework) # Ссылка на ДЗ


    @action(detail=True, methods=['post'], url_path='grade', serializer_class=GradeSerializer)
    def grade_submission(self, request, pk=None):
        """
        Выставление или обновление оценки для сдачи домашнего задания.
        """
        submission = self.get_object() # Получаем HomeworkSubmission по pk
        user_grading = self.request.user

        # Проверка прав на выставление оценки
        can_grade = False
        if user_grading.is_admin:
            can_grade = True
        elif user_grading.is_teacher:
            # Учитель, который автор ДЗ или учитель урока, к которому привязано ДЗ
            if submission.homework.author == user_grading or \
               submission.homework.journal_entry.lesson.teacher == user_grading:
                can_grade = True
        
        if not can_grade:
            raise PermissionDenied(detail=_("У вас нет прав на выставление оценки для этой работы."))

        grade_data = request.data.copy()
        grade_data.update({
            'student': submission.student.id,
            'subject': submission.homework.journal_entry.lesson.subject.id,
            'study_period': submission.homework.journal_entry.lesson.study_period.id,
            'homework_submission': submission.id,
            'grade_type': Grade.GradeType.HOMEWORK_GRADE,
            # graded_by будет установлен в сериализаторе или здесь
        })

        # Пытаемся найти существующую оценку для этой сдачи
        existing_grade = None
        try:
            existing_grade = submission.grade_for_submission # Используем reverse OneToOne
        except Grade.DoesNotExist: # Или AttributeError если поле не существует или null
            pass
        
        serializer_kwargs = {'data': grade_data, 'context': {'request': request}}
        if existing_grade:
            serializer_kwargs['instance'] = existing_grade
        
        serializer = self.get_serializer(**serializer_kwargs) # GradeSerializer

        if serializer.is_valid():
            grade_instance = serializer.save(graded_by=user_grading) # Устанавливаем graded_by
            
            # Уведомление студенту об оценке
            notify_homework_graded(submission) # Функция должна внутри себя найти студента и отправить уведомление
            
            return Response(serializer.data, status=status.HTTP_200_OK if existing_grade else status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SubmissionAttachmentViewSet(viewsets.ModelViewSet):
    # ... (без изменений, т.к. здесь нет событий для уведомлений) ...
    queryset = SubmissionAttachment.objects.select_related('submission__homework', 'submission__student').all()
    serializer_class = SubmissionAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_permissions(self):
        if self.action == 'create': return [permissions.IsAuthenticated(), IsStudent()]
        if self.action == 'destroy': return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)] # Владелец сдачи или модератор
        return super().get_permissions()
    def _can_user_access_submission(self, user, submission):
        if user.is_admin: return True
        if user.is_student and submission.student == user: return True
        if user.is_teacher and (submission.homework.author == user or (hasattr(submission.homework, 'journal_entry') and hasattr(submission.homework.journal_entry, 'lesson') and submission.homework.journal_entry.lesson.teacher == user)): return True
        return False
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset(); submission_id = self.request.query_params.get('submission_id')
        if submission_id:
            try:
                submission = HomeworkSubmission.objects.get(pk=submission_id)
                if not self._can_user_access_submission(user, submission): return SubmissionAttachment.objects.none()
                queryset = queryset.filter(submission_id=submission_id)
            except HomeworkSubmission.DoesNotExist: return SubmissionAttachment.objects.none()
            except (ValueError, TypeError): return SubmissionAttachment.objects.none()
        elif not user.is_admin:
            if user.is_student: queryset = queryset.filter(submission__student=user)
            else: return SubmissionAttachment.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer):
        submission = serializer.validated_data.get('submission'); user = self.request.user
        if submission.student != user: raise PermissionDenied(detail=_("Вы можете добавлять файлы только к своей сдаче ДЗ."))
        serializer.save()

class AttendanceViewSet(viewsets.ModelViewSet):
    # ... (без изменений, если не требуются уведомления об отметке посещаемости) ...
    queryset = Attendance.objects.select_related('journal_entry__lesson__subject', 'student', 'marked_by').all()
    serializer_class = AttendanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = {'journal_entry__lesson': ['exact'], 'journal_entry': ['exact'], 'student': ['exact'], 'status': ['exact', 'in'], 'journal_entry__lesson__start_time': ['date__gte', 'date__lte', 'date__exact']}
    ordering_fields = ['journal_entry__lesson__start_time', 'student__last_name']; ordering = ['-journal_entry__lesson__start_time', 'student__last_name']
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'batch_mark_attendance']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if self.action == 'list':
            if user.is_teacher and not user.is_admin: queryset = queryset.filter(journal_entry__lesson__teacher=user)
            elif user.is_student: queryset = queryset.filter(student=user)
            elif user.is_parent and hasattr(user, 'children') and user.children.exists(): queryset = queryset.filter(student__in=user.children.all())
            elif not user.is_admin: return Attendance.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer):
        journal_entry = serializer.validated_data.get('journal_entry'); user = self.request.user
        if user.is_teacher and not user.is_admin and journal_entry.lesson.teacher != user: raise PermissionDenied(detail=_("Вы можете отмечать посещаемость только на своих занятиях."))
        serializer.save(marked_by=user)
    @action(detail=False, methods=['post'], url_path='batch-mark')
    def batch_mark_attendance(self, request):
        journal_entry_id = request.data.get('journal_entry_id'); attendances_data = request.data.get('attendances')
        if not journal_entry_id or not isinstance(attendances_data, list): return Response({"error": _("Требуется 'journal_entry_id' и список 'attendances'.")}, status=status.HTTP_400_BAD_REQUEST)
        try: journal_entry = LessonJournalEntry.objects.get(pk=journal_entry_id)
        except LessonJournalEntry.DoesNotExist: return Response({"error": _("Запись в журнале не найдена.")}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        if user.is_teacher and not user.is_admin and journal_entry.lesson.teacher != user: return Response({'error': _("Вы можете отмечать посещаемость только на своих занятиях.")}, status=status.HTTP_403_FORBIDDEN)
        results = []; errors = []
        with transaction.atomic():
            for item_data in attendances_data:
                student_id = item_data.get('student_id'); status_val = item_data.get('status'); comment_val = item_data.get('comment', '')
                if not student_id or not status_val: errors.append({"student_id": student_id, "error": "Отсутствует student_id или status."}); continue
                # Проверяем, что студент принадлежит группе этого занятия
                if not journal_entry.lesson.student_group.students.filter(pk=student_id).exists():
                    errors.append({"student_id": student_id, "error": "Студент не из группы этого занятия."}); continue
                obj, created = Attendance.objects.update_or_create(journal_entry=journal_entry, student_id=student_id, defaults={'status': status_val, 'comment': comment_val, 'marked_by': user})
                results.append(AttendanceSerializer(obj).data)
        if errors: return Response({"results": results, "errors": errors}, status=status.HTTP_207_MULTI_STATUS)
        return Response({"results": results, "message": _("Посещаемость обновлена.")}, status=status.HTTP_200_OK)

class GradeViewSet(viewsets.ModelViewSet):
    queryset = Grade.objects.select_related('student', 'subject', 'study_period', 'academic_year', 'lesson__teacher', 'homework_submission__homework__author', 'graded_by').all()
    serializer_class = GradeSerializer
    # permission_classes определены в get_permissions
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = {
        'student': ['exact'], 'subject': ['exact'], 'study_period': ['exact'], 'academic_year': ['exact'],
        'lesson': ['exact'], 'grade_type': ['exact', 'in'], 'date_given': ['gte', 'lte', 'exact'],
        'homework_submission': ['exact']
    }
    search_fields = ['student__last_name', 'subject__name', 'comment', 'grade_value']
    ordering_fields = ['date_given', 'student__last_name', 'subject__name', 'grade_type']; ordering = ['-date_given']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return [permissions.IsAuthenticated()] # Для list, retrieve

    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if self.action == 'list': # Применяем фильтры для списка
            if user.is_teacher and not user.is_admin:
                queryset = queryset.filter(
                    Q(graded_by=user) |
                    Q(lesson__teacher=user) |
                    Q(homework_submission__homework__author=user) |
                    Q(homework_submission__homework__journal_entry__lesson__teacher=user) # Учитель занятия, к которому ДЗ
                ).distinct()
            elif user.is_student:
                queryset = queryset.filter(student=user)
            elif user.is_parent and hasattr(user, 'children') and user.children.exists():
                queryset = queryset.filter(student__in=user.children.all())
            elif not user.is_admin:
                return Grade.objects.none()
        return queryset.distinct()

    def perform_create(self, serializer):
        user = self.request.user
        validated_data = serializer.validated_data
        # ... (логика проверки can_grade, как была) ...
        can_grade = False
        if user.is_admin: can_grade = True
        elif user.is_teacher:
            lesson = validated_data.get('lesson')
            homework_submission = validated_data.get('homework_submission')
            subject = validated_data.get('subject')
            student_for_grade = validated_data.get('student')
            if lesson and lesson.teacher == user: can_grade = True
            elif homework_submission:
                hw_author = homework_submission.homework.author
                hw_lesson_teacher = getattr(getattr(getattr(homework_submission.homework, 'journal_entry', None), 'lesson', None), 'teacher', None)
                if hw_author == user or hw_lesson_teacher == user: can_grade = True
            elif not lesson and not homework_submission and subject and student_for_grade:
                target_study_period = validated_data.get('study_period')
                target_academic_year = validated_data.get('academic_year')
                group_ids = student_for_grade.student_group_memberships.values_list('id', flat=True)
                curriculum_exists_query = Q(curriculum__student_group_id__in=group_ids, subject=subject, teacher=user)
                if target_study_period: curriculum_exists_query &= Q(study_period=target_study_period)
                elif target_academic_year: curriculum_exists_query &= Q(study_period__academic_year=target_academic_year)
                else: curriculum_exists_query = Q(pk__isnull=True) # False condition
                if CurriculumEntry.objects.filter(curriculum_exists_query).exists(): can_grade = True
        
        if not can_grade:
            raise PermissionDenied(detail=_("У вас нет прав на выставление этой оценки."))
        
        grade = serializer.save(graded_by=user)
        # --- УВЕДОМЛЕНИЕ О НОВОЙ ОЦЕНКЕ ---
        # Избегаем дублирования, если это оценка за ДЗ, т.к. notify_homework_graded уже отправит
        if grade.grade_type != Grade.GradeType.HOMEWORK_GRADE or not grade.homework_submission:
            notify_new_grade(grade)


    def perform_update(self, serializer):
        user = self.request.user
        # Повторяем логику проверки прав, аналогично perform_create
        # (или выносим в отдельный метод проверки прав на объект)
        instance = serializer.instance
        can_grade = False # Логика как в perform_create, но для instance
        if user.is_admin: can_grade = True
        elif user.is_teacher:
            if instance.lesson and instance.lesson.teacher == user: can_grade = True
            elif instance.homework_submission:
                 hw_author = instance.homework_submission.homework.author
                 hw_lesson_teacher = getattr(getattr(getattr(instance.homework_submission.homework, 'journal_entry', None), 'lesson', None), 'teacher', None)
                 if hw_author == user or hw_lesson_teacher == user: can_grade = True
            elif not instance.lesson and not instance.homework_submission and instance.subject and instance.student:
                # Для итоговых (проверка по CurriculumEntry)
                group_ids = instance.student.student_group_memberships.values_list('id', flat=True)
                curriculum_exists_query = Q(curriculum__student_group_id__in=group_ids, subject=instance.subject, teacher=user)
                if instance.study_period: curriculum_exists_query &= Q(study_period=instance.study_period)
                elif instance.academic_year: curriculum_exists_query &= Q(study_period__academic_year=instance.academic_year)
                else: curriculum_exists_query = Q(pk__isnull=True)
                if CurriculumEntry.objects.filter(curriculum_exists_query).exists(): can_grade = True

        if not can_grade:
            raise PermissionDenied(detail=_("У вас нет прав на изменение этой оценки."))

        grade = serializer.save() # graded_by уже должен быть установлен
        # --- УВЕДОМЛЕНИЕ ОБ ИЗМЕНЕНИИ ОЦЕНКИ ---
        if grade.grade_type != Grade.GradeType.HOMEWORK_GRADE or not grade.homework_submission:
            notify_new_grade(grade) # Используем ту же функцию, текст будет "Новая оценка: ..."

class SubjectMaterialViewSet(viewsets.ModelViewSet):
    # ... (без изменений, если не нужны уведомления о новых материалах) ...
    queryset = SubjectMaterial.objects.select_related('subject', 'student_group', 'uploaded_by').prefetch_related('attachments').all()
    serializer_class = SubjectMaterialSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['subject', 'student_group', 'uploaded_by']
    search_fields = ['title', 'description', 'subject__name', 'attachments__file']
    ordering_fields = ['uploaded_at', 'title', 'subject__name']; ordering = ['-uploaded_at']
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if self.action == 'list':
            if user.is_student:
                user_groups = user.student_group_memberships.all()
                queryset = queryset.filter(Q(student_group__in=user_groups) | Q(student_group__isnull=True)).distinct()
            elif user.is_parent and hasattr(user, 'children') and user.children.exists():
                children_groups = StudentGroup.objects.filter(students__in=user.children.all()).distinct()
                queryset = queryset.filter(Q(student_group__in=children_groups) | Q(student_group__isnull=True)).distinct()
            elif user.is_teacher and not user.is_admin:
                queryset = queryset.filter(Q(uploaded_by=user) | Q(student_group__isnull=True) | Q(subject__lead_teachers=user)).distinct()
        return queryset
    def perform_create(self, serializer): serializer.save(uploaded_by=self.request.user)


# --- ПАНЕЛИ ПОЛЬЗОВАТЕЛЕЙ (без изменений логики уведомлений в них) ---
# ... (TeacherMyScheduleViewSet, TeacherMyGroupsView, и т.д. остаются как были) ...
# TeacherMyScheduleViewSet, TeacherMyGroupsView, TeacherLessonJournalViewSet, TeacherHomeworkViewSet, TeacherHomeworkSubmissionViewSet, TeacherAttendanceViewSet, TeacherGradeViewSet, TeacherSubjectMaterialViewSet
# CuratorManagedGroupsViewSet, CuratorGroupPerformanceView
# StudentMyScheduleListView, StudentMyGradesListView, StudentMyAttendanceListView, StudentMyHomeworkListView, StudentMyHomeworkSubmissionViewSet
# ParentChildScheduleListView, ParentChildGradesListView, ParentChildAttendanceListView, ParentChildHomeworkListView
# ImportDataView, ExportJournalView, TeacherLoadStatsView, TeacherSubjectPerformanceStatsView, GroupPerformanceView
# Копирую без изменений, т.к. они в основном для чтения или специфических действий, не требующих новых уведомлений
# --- ПАНЕЛЬ ПРЕПОДАВАТЕЛЯ ---
class TeacherMyScheduleViewSet(LessonViewSet): # Наследуемся от вашего основного LessonViewSet
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    serializer_class = LessonListSerializer # Используем легковесный сериализатор для списка
    http_method_names = ['get', 'head', 'options'] # Только чтение

    def get_queryset(self):
        # Вызываем get_queryset родителя, чтобы получить все оптимизации (select_related и т.д.)
        # Затем дополнительно фильтруем по текущему учителю.
        # queryset = super().get_queryset() # Осторожно, если родительский get_queryset сложный
                                        # и сам зависит от action или роли.
                                        # Проще явно определить queryset здесь.

        user = self.request.user
        # Важно: не вызывайте super().get_queryset() если он уже содержит логику фильтрации
        # по пользователю, которая может конфликтовать.
        # Вместо этого, строим queryset с нуля или от базового менеджера.
        queryset = Lesson.objects.filter(teacher=user).select_related(
            'study_period', 
            'student_group', 
            'subject', 
            'classroom',
            # Учителя не нужно select_related, т.к. это self.request.user
        ).prefetch_related(
            'journal_entry' # Если используется
        )
        
        # distinct() и order_by() будут применены OrderingFilter и базовым ViewSet,
        # если ordering определен. Но явное order_by здесь не повредит, если нужно.
        # DRF фильтры (дата, группа, предмет, поиск) будут применены к этому queryset.
        return queryset.distinct() # .order_by('start_time') - сортировка будет от OrderingFilter

class TeacherMyGroupsView(generics.ListAPIView):
    serializer_class = StudentGroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'academic_year__name']
    ordering = ['name']
    def get_queryset(self):
        user = self.request.user
        current_active_year = AcademicYear.objects.filter(is_current=True).first()
        if not current_active_year: return StudentGroup.objects.none()
        teaching_group_ids = Lesson.objects.filter(teacher=user, study_period__academic_year=current_active_year).values_list('student_group_id', flat=True).distinct()
        queryset = StudentGroup.objects.filter(Q(academic_year=current_active_year) & (Q(curator=user) | Q(id__in=list(teaching_group_ids)))).select_related('academic_year', 'curator', 'group_monitor').prefetch_related('students').distinct()
        return queryset
    
class TeacherLessonJournalViewSet(LessonJournalEntryViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherHomeworkViewSet(HomeworkViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherHomeworkSubmissionViewSet(HomeworkSubmissionViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherAttendanceViewSet(AttendanceViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherGradeViewSet(GradeViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherSubjectMaterialViewSet(SubjectMaterialViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]

# --- ПАНЕЛЬ КУРАТОРА ---
class CuratorManagedGroupsViewSet(StudentGroupViewSet):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    http_method_names = ['get', 'retrieve', 'put', 'patch', 'head', 'options'] # Разрешаем редактирование
    def get_queryset(self): return StudentGroup.objects.filter(curator=self.request.user).select_related('academic_year', 'curator', 'group_monitor').prefetch_related('students').order_by('name')
    def perform_update(self, serializer):
        allowed_fields = {'group_monitor', 'students'} # Поля, которые куратор может менять
        # Проверяем, что изменяются только разрешенные поля
        if not set(serializer.validated_data.keys()).issubset(allowed_fields):
            raise DRFValidationError(_("Куратор может изменять только старосту и состав студентов."))
        # Запрещаем изменение куратора или учебного года через этот эндпоинт
        if 'curator' in serializer.validated_data and serializer.validated_data['curator'] != self.request.user:
            raise DRFValidationError(_("Вы не можете изменить куратора этой группы."))
        if 'academic_year' in serializer.validated_data:
            raise DRFValidationError(_("Изменение учебного года группы не разрешено."))
        super().perform_update(serializer)

class CuratorGroupPerformanceView(generics.ListAPIView):
    serializer_class = GroupPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    filter_backends = [] # Явные параметры запроса
    def get_queryset(self):
        user = self.request.user; group_pk = self.kwargs.get('group_pk')
        # Куратор может смотреть только свои группы
        group = get_object_or_404(StudentGroup, pk=group_pk, curator=user)
        study_period_id = self.request.query_params.get('study_period_id')
        if not study_period_id: raise DRFValidationError(_("Необходимо указать 'study_period_id' в параметрах запроса."))
        return StudentGroup.objects.filter(pk=group.pk).prefetch_related(Prefetch('students',queryset=User.objects.filter(role=User.Role.STUDENT).prefetch_related(Prefetch('grades_received',queryset=Grade.objects.filter(study_period_id=study_period_id, numeric_value__isnull=False).select_related('subject'),to_attr='period_grades_for_stats')),to_attr='students_with_grades_for_stats'))
    def get_serializer_context(self): context = super().get_serializer_context(); context['study_period_id'] = self.request.query_params.get('study_period_id'); return context
    def list(self, request, *args, **kwargs):
        # --- Валидация параметров ---
        group_id_str = request.query_params.get('group_id') # Для GroupPerformanceView
        if not group_id_str and 'group_pk' in self.kwargs: # Для CuratorGroupPerformanceView
             group_id_str = str(self.kwargs.get('group_pk'))
        
        study_period_id_str = request.query_params.get('study_period_id')

        if not group_id_str or not study_period_id_str:
            return Response(
                {"detail": _("Параметры 'group_id' (или group_pk в URL) и 'study_period_id' обязательны.")},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            # group_id уже будет получен из URL kwargs для CuratorGroupPerformanceView,
            # или из query_params для общего GroupPerformanceView
            group_id = int(group_id_str) # Пере-валидация, если из query_params
            study_period_id = int(study_period_id_str)
        except ValueError:
            return Response(
                {"detail": _("ID группы и периода должны быть числами.")},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        queryset = self.get_queryset() # get_queryset уже отфильтрует по правам
        
        if not queryset.exists():
            return Response(
                {"detail": _("Группа не найдена, нет данных или у вас нет прав доступа к этой группе.")}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # get_queryset возвращает queryset из одного StudentGroup (или пустой)
        instance = queryset.first() # instance - это объект StudentGroup

        # --- РАСЧЕТ 'average_grade_for_period' для каждого студента ПЕРЕД СЕРИАЛИЗАЦИЕЙ ---
        if instance and hasattr(instance, 'students_with_grades_for_stats'):
            for student_obj in instance.students_with_grades_for_stats:
                # 'period_grades_for_stats' уже должен быть на student_obj благодаря Prefetch
                grades_for_student_period = getattr(student_obj, 'period_grades_for_stats', [])
                
                weighted_sum = Decimal('0.0')
                total_weight = Decimal('0.0')
                
                for grade in grades_for_student_period:
                    if grade.numeric_value is not None and grade.weight > 0:
                        # Убедимся, что numeric_value это Decimal
                        numeric_val_decimal = grade.numeric_value if isinstance(grade.numeric_value, Decimal) else Decimal(str(grade.numeric_value))
                        weighted_sum += numeric_val_decimal * Decimal(str(grade.weight))
                        total_weight += Decimal(str(grade.weight))
                
                if total_weight > Decimal('0.0'):
                    # Добавляем рассчитанный атрибут к объекту студента
                    student_obj.average_grade_for_period = (weighted_sum / total_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                else:
                    student_obj.average_grade_for_period = None
        # --- КОНЕЦ РАСЧЕТА ---

        serializer_context = self.get_serializer_context()
        # Обновляем контекст, если study_period_id был определен только что
        if 'study_period_id' not in serializer_context and study_period_id:
             serializer_context['study_period_id'] = study_period_id
        if 'group_id' not in serializer_context and group_id:
             serializer_context['group_id'] = group_id

        serializer = self.get_serializer(instance, context=serializer_context)
        return Response(serializer.data)

# --- ПАНЕЛЬ СТУДЕНТА ---
class StudentMyScheduleListView(generics.ListAPIView):
    """
    Возвращает список занятий (расписание) для аутентифицированного студента.
    Поддерживает фильтрацию по диапазону дат, ID предмета и ID преподавателя.
    """
    serializer_class = LessonListSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]
    
    # Используем DjangoFilterBackend для обработки фильтров
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter]
    
    # Указываем наш кастомный FilterSet класс
    filterset_class = LessonFilter
    
    # filterset_fields больше не нужен, так как все определяется в LessonStudentScheduleFilter.
    # Если бы мы не использовали filterset_class, то filterset_fields был бы:
    # filterset_fields = {
    #     'start_time': ['date__exact'], # DjangoFilterBackend не поймет 'date__gte' здесь без кастомного FilterSet
    #     'subject': ['exact'],
    #     'teacher': ['exact'],
    # }
    
    ordering_fields = ['start_time', 'subject__name']
    ordering = ['start_time'] # Сортировка по умолчанию

    def get_queryset(self):
        """
        Возвращает базовый queryset, отфильтрованный по текущему студенту.
        Дальнейшая фильтрация по query параметрам (даты, предмет, преподаватель)
        будет выполнена DjangoFilterBackend с использованием LessonStudentScheduleFilter.
        """
        user = self.request.user
        return Lesson.objects.filter(
            student_group__students=user
        ).select_related(
            'study_period', 'subject', 'teacher', 'classroom'
        ).distinct().order_by(*self.ordering) # Используем self.ordering для сортировки
class StudentMyGradesListView(generics.ListAPIView):
    serializer_class = MyGradeSerializer; permission_classes = [permissions.IsAuthenticated, IsStudent]; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'subject': ['exact'], 'study_period': ['exact'], 'academic_year': ['exact'], 'grade_type': ['exact', 'in'], 'date_given': ['gte', 'lte']}; ordering_fields = ['-date_given', 'subject__name']; ordering = ['-date_given']
    def get_queryset(self): return Grade.objects.filter(student=self.request.user).select_related('subject', 'study_period', 'academic_year', 'lesson', 'graded_by').distinct()

class StudentMyAttendanceListView(generics.ListAPIView):
    serializer_class = MyAttendanceSerializer; permission_classes = [permissions.IsAuthenticated, IsStudent]; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'status': ['exact'], 'journal_entry__lesson__start_time': ['date__gte', 'date__lte'], 'journal_entry__lesson__subject':['exact']}; ordering_fields = ['-journal_entry__lesson__start_time']; ordering = ['-journal_entry__lesson__start_time']
    def get_queryset(self): return Attendance.objects.filter(student=self.request.user).select_related('journal_entry__lesson__subject', 'student').distinct()

class StudentMyHomeworkListView(generics.ListAPIView):
    serializer_class = MyHomeworkSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]
    pagination_class = StandardLimitOffsetPagination

    # Обновляем filter_backends
    filter_backends = [
        DjangoFilterBackend, 
        drf_filters.SearchFilter, # <--- ДОБАВЛЯЕМ SearchFilter
        drf_filters.OrderingFilter
    ]
    
    # Поля для DjangoFilterBackend (если нужны специфичные фильтры, кроме поиска)
    filterset_fields = {
        'due_date': ['gte', 'lte', 'isnull', 'exact', 'date'], # Фильтры по сроку сдачи
        'journal_entry__lesson__subject': ['exact'], # Фильтр по ID предмета
        # Можно добавить другие фильтры, например, по статусу сдачи, если это поле есть в MyHomeworkSerializer
        # 'submission_status': ['exact'], # Если submission_status - это аннотированное поле или реальное поле
    }

    # Поля, по которым будет производиться поиск SearchFilter
    search_fields = [
        'title',                                  # Заголовок ДЗ
        'description',                            # Описание ДЗ
        'journal_entry__lesson__subject__name',   # Название предмета
        'author__first_name',                     # Имя автора ДЗ (учителя)
        'author__last_name',                      # Фамилия автора ДЗ
        'journal_entry__topic_covered'            # Тема урока из журнала (если есть)
    ]
    
    ordering_fields = ['-due_date', 'created_at', 'title', 'journal_entry__lesson__subject__name']
    ordering = ['-due_date', '-created_at'] # Сортировка по умолчанию (сначала актуальные)

    def get_queryset(self):
        user = self.request.user # Текущий пользователь (студент)
        
        # Базовый queryset: все ДЗ для групп, в которых состоит студент
        queryset = Homework.objects.filter(
            journal_entry__lesson__student_group__students=user
        ).select_related(
            'journal_entry__lesson__subject', 
            'author__profile', # Добавил profile, если он используется в EduUserSerializer для author_details
            'journal_entry__lesson__student_group' # Для информации о группе, если нужна
        ).prefetch_related(
            'attachments', 
            'related_materials', # Можно добавить .select_related('subject') и сюда
            # Prefetch для получения СВОЕЙ сдачи (одной) для каждого ДЗ
            Prefetch(
                'submissions', 
                queryset=HomeworkSubmission.objects.filter(student=user), # Только сдачи текущего студента
                to_attr='my_current_submission_list' # Атрибут, куда сохранится список (из одного элемента)
            )
        )
        
        # DjangoFilterBackend и SearchFilter будут применены к этому queryset АВТОМАТИЧЕСКИ
        # OrderingFilter также будет применен.
        
        return queryset.distinct() # distinct() важен из-за M2M связи со студентами

    def get_serializer_context(self):
        # Передаем request в контекст, чтобы MyHomeworkSerializer мог получить user
        # и определить my_submission и submission_status
        context = super().get_serializer_context()
        context['request'] = self.request
        # context['user'] = self.request.user # Можно и так, но request обычно достаточно
        return context
class StudentMyHomeworkSubmissionViewSet(viewsets.ModelViewSet): # Можно наследовать от ModelViewSet напрямую
    serializer_class = StudentHomeworkSubmissionSerializer # Используем студенческий сериализатор
    permission_classes = [permissions.IsAuthenticated, IsStudent] # Права на уровне класса

    def get_queryset(self):
        # Студент видит только свои сдачи
        user = self.request.user
        logger.debug(f"StudentMyHomeworkSubmissionViewSet.get_queryset for user: {user}")
        return HomeworkSubmission.objects.filter(student=user).select_related(
            'homework__journal_entry__lesson__subject', 'student__profile', 'homework__author__profile'
        ).prefetch_related('attachments', 'grade_for_submission').order_by('-submitted_at')

    def get_permissions(self):
        logger.debug(f"StudentMyHomeworkSubmissionViewSet.get_permissions for action: {self.action}")
        # Переопределяем, чтобы уточнить права для студента
        if self.action == 'create': # POST /student/homework-submissions/
            return [permissions.IsAuthenticated(), IsStudent()]
        if self.action in ['update', 'partial_update']:
            # Студент может редактировать свою сдачу, только если она еще не оценена
            # и он является владельцем. IsOwnerOrAdmin проверит владельца.
            return [permissions.IsAuthenticated(), IsStudent(), IsOwnerOrAdmin()] 
        if self.action == 'destroy':
            # Студент может удалить свою сдачу, только если она еще не оценена
            return [permissions.IsAuthenticated(), IsStudent(), IsOwnerOrAdmin()]
        # Для list, retrieve - права IsAuthenticated, IsStudent из permission_classes класса.
        return super().get_permissions()


    def perform_create(self, serializer):
        user = self.request.user # Это студент
        homework = serializer.validated_data.get('homework')
        
        logger.debug(f"Student {user.email} attempting to submit homework_id: {homework.id if homework else 'None'}")

        if not homework:
             raise DRFValidationError({'homework': _("Необходимо указать домашнее задание.")})

        # Проверка, что студент принадлежит группе, для которой это ДЗ
        if not homework.journal_entry.lesson.student_group.students.filter(pk=user.pk).exists():
            logger.warning(f"Student {user.email} tried to submit HW for a group they are not in. HW: {homework.id}")
            raise PermissionDenied(detail=_("Вы не можете сдавать ДЗ для этой группы/занятия."))

        # Проверка срока сдачи
        if homework.due_date and timezone.now() > homework.due_date:
            logger.warning(f"Student {user.email} is submitting homework '{homework.title}' (ID: {homework.id}) after the due date.")
        
        # Проверка на повторную сдачу
        if HomeworkSubmission.objects.filter(homework=homework, student=user).exists():
            logger.warning(f"Student {user.email} tried to re-submit homework_id: {homework.id}")
            raise DRFValidationError(_("Вы уже сдавали это домашнее задание. Вы можете отредактировать существующую сдачу, если это разрешено."))
        
        submission = serializer.save(student=user) # homework уже будет в validated_data из сериализатора
        logger.info(f"Student {user.email} successfully submitted homework_id: {homework.id}, submission_id: {submission.id}")

        # Уведомление преподавателю
        teacher = homework.author
        if teacher and teacher.is_active:
            student_name = user.get_full_name() or user.email
            message = f"Студент {student_name} сдал(а) ДЗ: '{homework.title}'"
            send_notification(teacher, message, Notification.NotificationType.ASSIGNMENT_SUBMITTED, submission)

    def perform_update(self, serializer):
        # Студент может обновлять свою сдачу, если она еще не оценена
        submission = serializer.instance
        if hasattr(submission, 'grade_for_submission') and submission.grade_for_submission is not None:
            raise PermissionDenied(detail=_("Нельзя редактировать уже оцененную работу."))
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        # Студент может удалять свою сдачу, если она еще не оценена
        if hasattr(instance, 'grade_for_submission') and instance.grade_for_submission is not None:
            raise PermissionDenied(detail=_("Нельзя удалять уже оцененную работу."))
        super().perform_destroy(instance)
# --- ПАНЕЛЬ РОДИТЕЛЯ ---
class ParentChildDataMixin:
    permission_classes = [permissions.IsAuthenticated, IsParent]; http_method_names = ['get', 'head', 'options']
    def get_target_children_ids(self):
        user = self.request.user;
        if not hasattr(user, 'children') or not user.children.exists(): return [] # Проверка hasattr
        child_id_param = self.request.query_params.get('child_id')
        if child_id_param:
            try:
                child_id = int(child_id_param)
                if user.children.filter(pk=child_id).exists(): return [child_id]
                return [] # Запрошенный ребенок не принадлежит этому родителю
            except (ValueError, TypeError): return [] # Неверный child_id
        return user.children.values_list('id', flat=True)

class ParentChildScheduleListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = LessonListSerializer
    permission_classes = [permissions.IsAuthenticated, IsParent] # Убедимся, что пермишен IsParent есть

    # Фильтр бэкенды: DjangoFilterBackend для полей, SearchFilter для поиска
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]

    # Поля для DjangoFilterBackend (включая даты)
    filterset_fields = {
        'start_time': ['exact', 'date', 'date__gte', 'date__lte', 'year', 'month', 'day'],
        'end_time': ['exact', 'date', 'date__gte', 'date__lte'],
        'subject': ['exact'], # Фильтр по ID предмета
        'teacher': ['exact']  # Фильтр по ID преподавателя
    }

    # Поля для SearchFilter (по каким полям будет производиться поиск ?search=...)
    search_fields = [
        'subject__name',        # Название предмета
        'teacher__first_name',  # Имя преподавателя
        'teacher__last_name',   # Фамилия преподавателя
        'classroom__identifier',# Номер/название аудитории
        # 'student_group__name' # Имя группы (если нужно искать по группе, хотя уже фильтруется по ребенку)
    ]
    
    ordering_fields = ['start_time', 'subject__name']
    ordering = ['start_time'] # Сортировка по умолчанию

    def get_queryset(self):
        children_ids = self.get_target_children_ids()
        if not children_ids:
            return Lesson.objects.none()
        
        # Находим группы, в которых состоят дети
        # Делаем distinct на уровне этого запроса, чтобы избежать дублирования групп
        student_groups_of_children = StudentGroup.objects.filter(students__id__in=children_ids).distinct()
        
        if not student_groups_of_children.exists():
             return Lesson.objects.none()

        # Формируем queryset на основе групп детей
        queryset = Lesson.objects.filter(
            student_group__in=student_groups_of_children
        ).select_related(
            'study_period', 
            'student_group', 
            'subject', 
            'teacher__profile', # Добавил profile, если он используется в EduUserSerializer для ФИО
            'classroom'
        ).prefetch_related(
            'journal_entry' # Если используется
        )
        
        # distinct() лучше применять после всех фильтров,
        # но если prefetch_related или M2M в фильтрах вызывают дубли, он может понадобиться и здесь.
        # Однако, SearchFilter и DjangoFilterBackend сами должны корректно работать.
        # Оставим distinct() в конце, после применения всех фильтров DRF.
        return queryset.distinct() # Применяем distinct в конце
class ParentChildGradesListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = MyGradeSerializer; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'subject': ['exact'], 'study_period': ['exact'], 'academic_year': ['exact'], 'grade_type': ['exact', 'in'], 'date_given': ['gte', 'lte']}; ordering_fields = ['-date_given', 'subject__name']; ordering = ['-date_given']
    def get_queryset(self):
        children_ids = self.get_target_children_ids();
        if not children_ids: return Grade.objects.none()
        return Grade.objects.filter(student_id__in=children_ids).select_related('student', 'subject', 'study_period', 'academic_year', 'lesson', 'graded_by').distinct()

class ParentChildAttendanceListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = MyAttendanceSerializer; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'status': ['exact'], 'journal_entry__lesson__start_time': ['date__gte', 'date__lte'], 'journal_entry__lesson__subject':['exact']}; ordering_fields = ['-journal_entry__lesson__start_time']; ordering = ['-journal_entry__lesson__start_time']
    def get_queryset(self):
        children_ids = self.get_target_children_ids();
        if not children_ids: return Attendance.objects.none()
        return Attendance.objects.filter(student_id__in=children_ids).select_related('journal_entry__lesson__subject', 'student').distinct()

class ParentChildHomeworkListView(ParentChildDataMixin, generics.ListAPIView):
    pagination_class = StandardLimitOffsetPagination
    serializer_class = MyHomeworkSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, drf_filters.SearchFilter] # Добавил SearchFilter, если нужен
    filterset_fields = {
        'due_date': ['gte', 'lte', 'isnull', 'exact', 'date'], 
        'journal_entry__lesson__subject':['exact']
    }
    search_fields = ['title', 'description', 'journal_entry__lesson__subject__name'] # Если нужен поиск
    ordering_fields = ['-due_date', 'created_at'] # Было так, уже есть due_date
    ordering = ['-due_date'] # Было так, уже есть due_dateИспользуем ordering, а не queryset.order_by() для DRF фильтра

    def get_queryset(self):
        children_ids = self.get_target_children_ids()
        if not children_ids: 
            return Homework.objects.none()
        
        # Группы, в которых состоят целевые дети
        children_groups_ids = StudentGroup.objects.filter(students__id__in=children_ids).values_list('id', flat=True).distinct()
        if not children_groups_ids.exists():
            return Homework.objects.none()

        # ДЗ для этих групп
        homework_qs = Homework.objects.filter(
            journal_entry__lesson__student_group_id__in=children_groups_ids
        ).select_related(
            'journal_entry__lesson__subject', 
            'author__profile' # Добавил profile для EduUserSerializer
        ).prefetch_related(
            'attachments', 
            'related_materials__subject', # Оптимизация для SubjectMaterialSerializer
            Prefetch(
                'submissions', 
                # Фильтруем сдачи только для целевых детей.
                # Это важно, чтобы child_submissions_for_list содержал только нужные данные.
                queryset=HomeworkSubmission.objects.filter(student_id__in=children_ids).select_related(
                    'student__profile', # Для информации о студенте в сдаче
                    'grade_for_submission' # Для оценки
                ).prefetch_related('attachments'), # Файлы сдачи
                to_attr='child_submissions_for_list' 
            )
        ).distinct()
        
        # Ordering будет применен OrderingFilter на основе self.ordering или ?ordering=
        return homework_qs # Не вызываем .order_by() здесь, если используется OrderingFilter

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        # Передаем ID детей, для которых запрошены данные.
        # Если ?child_id= был, то здесь будет список с одним ID.
        # Если ?child_id= не было, то список всех ID детей родителя.
        context['target_children_ids_for_serializer'] = self.get_target_children_ids()
        return context

# --- ИМПОРТ ---
class ImportDataView(generics.GenericAPIView):
    # ... (без изменений) ...
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get_serializer_class_for_import(self, import_type):
        if import_type == 'teachers': return TeacherImportSerializer
        if import_type == 'subjects': return SubjectImportSerializer
        if import_type == 'student-groups': return StudentGroupImportSerializer
        return None
    # В ImportDataView
    @transaction.atomic
    def post(self, request, import_type, *args, **kwargs):
        if import_type == 'schedule_template':
            file_obj = request.FILES.get('file')
            if not file_obj: return Response({"error": "Файл шаблона не предоставлен."}, status=status.HTTP_400_BAD_REQUEST)
            if not file_obj.name.endswith('.csv'): return Response({"error": "Неверный формат файла. Требуется CSV."}, status=status.HTTP_400_BAD_REQUEST)
            
            # --- ЛОГИРОВАНИЕ СОДЕРЖИМОГО ФАЙЛА ---
            try:
                # Прочитать файл для логирования, затем "перемотать" его для DictReader
                file_content_for_log = file_obj.read().decode('utf-8-sig')
                print("----------- RECEIVED CSV CONTENT START -----------")
                print(file_content_for_log)
                print("------------ RECEIVED CSV CONTENT END ------------")
                file_obj.seek(0) # Возвращаем указатель в начало файла для DictReader
            except Exception as log_e:
                print(f"Error trying to log file content: {log_e}")
            # --- КОНЕЦ ЛОГИРОВАНИЯ ---

            try:
                decoded_file = file_obj.read().decode('utf-8-sig')
                csv_data = csv.DictReader(StringIO(decoded_file))
                template_data_list = list(csv_data)
                if not template_data_list:
                    return Response({"error": "CSV файл пуст или не содержит данных."}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": f"Ошибка чтения CSV: {e}"}, status=status.HTTP_400_BAD_REQUEST)

            # Извлечение метаданных из request.data (не из файла)
            period_start_date_str = request.data.get('period_start_date')
            period_end_date_str = request.data.get('period_end_date')
            student_group_id_str = request.data.get('student_group_id') # Общий ID группы
            academic_year_id_str = request.data.get('academic_year_id') # Опционально
            clear_existing_value_from_request = request.data.get('clear_existing_schedule') # Имя ключа, которое вы используете на клиенте
            print(f"!!!!!!!!!! ImportDataView - clear_existing_schedule from request.data: '{clear_existing_value_from_request}' (type: {type(clear_existing_value_from_request)}) !!!!!!!!!!")
            if not period_start_date_str or not period_end_date_str:
                return Response({"error": "Необходимо указать 'period_start_date' и 'period_end_date'."}, status=status.HTTP_400_BAD_REQUEST)
            
            # Валидация ID, если переданы
            student_group_id = None
            if student_group_id_str:
                try: student_group_id = int(student_group_id_str)
                except ValueError: return Response({"error": "Некорректный ID учебной группы."}, status=status.HTTP_400_BAD_REQUEST)
            
            academic_year_id = None
            if academic_year_id_str:
                try: academic_year_id = int(academic_year_id_str)
                except ValueError: return Response({"error": "Некорректный ID учебного года."}, status=status.HTTP_400_BAD_REQUEST)


            context = {
                'request': request,
                'period_start_date': period_start_date_str,
                'period_end_date': period_end_date_str,
                'student_group_id': student_group_id,
                'academic_year_id': academic_year_id,
                'clear_existing_schedule': clear_existing_value_from_request             }

            serializer = ScheduleTemplateImportSerializer(data=template_data_list, context=context)
            if serializer.is_valid(raise_exception=False): # Изменим на raise_exception=False, чтобы обработать ошибки is_valid отдельно
                try:
                    # serializer.save() вызовет serializer.create()
                    # serializer.create() может выбросить serializers.ValidationError, если есть конфликты
                    created_count = serializer.save() 
                    
                    return Response({
                        "message": "Импорт шаблона расписания успешно завершен.",
                        "created_lessons_count": created_count
                    }, status=status.HTTP_201_CREATED)

                # 1. Сначала ловим ValidationError, который может быть выброшен из serializer.create() (через serializer.save())
                except DRFValidationError as e:
                    logger.warning(f"Schedule Import - Validation Error during serializer.save() or create(): {e.detail}")
                    return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
                
                # 2. Затем ловим IntegrityError, если bulk_create не удался из-за ограничений БД
                except IntegrityError as e:
                    logger.error(f"Schedule Import - IntegrityError during bulk_create: {e}", exc_info=True)
                    # Пытаемся получить более детальную информацию об ошибке БД, если это возможно
                    db_error_detail = getattr(e, 'args', None)
                    if db_error_detail and len(db_error_detail) > 0:
                        db_error_message = str(db_error_detail[0])
                    else:
                        db_error_message = str(e)
                    return Response({
                        "error": _("Ошибка базы данных при сохранении занятий. Проверьте на дублирование или нарушение уникальных ограничений."),
                        "details": db_error_message
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 3. Для всех остальных непредвиденных ошибок во время выполнения serializer.save()
                except Exception as e:
                    logger.error(f"Schedule Import - Unhandled error in serializer.save() or processing: {e}", exc_info=True)
                    return Response({
                        "error": _("Внутренняя ошибка сервера при генерации расписания."),
                        "details": f"{type(e).__name__}: {str(e)}" # Более информативно
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            else: # Если serializer.is_valid() сам по себе вернул False (ошибки на уровне LessonTemplateItemSerializer)
                logger.warning(f"Schedule Import - Initial serializer validation failed: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        else: # Обработка других типов импорта (как было)
            serializer_class = self.get_serializer_class_for_import(import_type)
            # ... (ваша существующая логика для других импортов)
            if not serializer_class: return Response({"error": f"Неизвестный тип импорта: {import_type}"}, status=status.HTTP_400_BAD_REQUEST)
            file_obj = request.FILES.get('file')
            if not file_obj: return Response({"error": "Файл не предоставлен."}, status=status.HTTP_400_BAD_REQUEST)
            if not file_obj.name.endswith('.csv'): return Response({"error": "Неверный формат файла. Требуется CSV."}, status=status.HTTP_400_BAD_REQUEST)
            try: decoded_file = file_obj.read().decode('utf-8-sig'); csv_data = csv.DictReader(StringIO(decoded_file)); data_to_serialize = list(csv_data)
            except Exception as e: return Response({"error": f"Ошибка чтения CSV: {e}"}, status=status.HTTP_400_BAD_REQUEST)
            serializer = serializer_class(data=data_to_serialize, many=True, context={'request': request})
            if serializer.is_valid():
                try:
                    created_instances = []
                    if hasattr(serializer.child, 'create_or_update_teacher'): created_instances = [serializer.child.create_or_update_teacher(item_data) for item_data in serializer.validated_data]
                    elif hasattr(serializer.child, 'create_or_update_subject'): created_instances = [serializer.child.create_or_update_subject(item_data) for item_data in serializer.validated_data]
                    elif hasattr(serializer.child, 'create_or_update_group'): created_instances = [serializer.child.create_or_update_group(item_data) for item_data in serializer.validated_data]
                    else: created_instances = serializer.save() # Общий случай, если нет кастомных методов
                    return Response({"message": f"Импорт '{import_type}' успешно завершен.","processed_count": len(data_to_serialize),"created_or_updated_count": len(created_instances)}, status=status.HTTP_201_CREATED)
                except serializers.ValidationError as e: # Явно ловим ошибки валидации из create/update
                    return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e: return Response({"error": f"Ошибка во время сохранения данных: {e}", "details": getattr(e, 'detail', str(e))}, status=status.HTTP_400_BAD_REQUEST)
            else: return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ExportJournalView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated] # Общее, уточняется в методе

    def _parse_date_param(self, param_name):
        date_str = self.request.query_params.get(param_name)
        if date_str:
            try:
                return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                raise HttpResponseBadRequest(f"Некорректный формат даты для параметра '{param_name}'. Ожидается YYYY-MM-DD.")
        return None

    def get(self, request, *args, **kwargs):
        user = request.user
        
        # Собираем фильтры из query_params
        filters = {}
        for param in ['academic_year_id', 'study_period_id', 'student_group_id', 'subject_id', 'teacher_id']:
            value = request.query_params.get(param)
            if value:
                try: filters[param] = int(value)
                except ValueError: return HttpResponseBadRequest(f"Параметр '{param}' должен быть числом.")
        
        filters['date_from'] = self._parse_date_param('date_from')
        filters['date_to'] = self._parse_date_param('date_to')
        
        # Для асинхронной генерации (Celery)
        # use_async = str(request.query_params.get('async', 'false')).lower() == 'true'
        # if use_async:
        #     if not current_app.conf.broker_url:
        #          return Response({"error": "Асинхронная генерация не настроена (Celery broker не найден)."}, status=status.HTTP_501_NOT_IMPLEMENTED)
        #     task = generate_journal_export_task.delay(user.id, filters)
        #     return Response({"message": "Запрос на экспорт журнала принят. Он будет сгенерирован в фоновом режиме.", "task_id": task.id}, status=status.HTTP_202_ACCEPTED)

        # Синхронная генерация
        exporter = JournalExporter(user, filters)
        
        if user.is_admin:
            response = exporter.export_admin_journal()
        elif user.is_teacher: # Включая кураторов
            response = exporter.export_teacher_journal()
        else:
            # Студенты и родители не могут экспортировать полный журнал
            logger.warning(f"User {user.email} (role: {user.role}) attempted to export journal, denied.")
            return Response({"error": "Экспорт журнала недоступен для вашей роли."}, status=status.HTTP_403_FORBIDDEN)
        
        return response


class TeacherLoadStatsView(generics.ListAPIView):
    serializer_class = TeacherLoadSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get_queryset(self):
        academic_year_id = self.request.query_params.get('academic_year_id')
        study_period_id = self.request.query_params.get('study_period_id')
        teachers_qs = User.objects.filter(role=User.Role.TEACHER).order_by('last_name', 'first_name')
        planned_hours_filter = Q(teacher=OuterRef('pk'))
        scheduled_lessons_filter = Q(teacher=OuterRef('pk'))
        if academic_year_id:
            planned_hours_filter &= Q(curriculum__academic_year_id=academic_year_id)
            scheduled_lessons_filter &= Q(study_period__academic_year_id=academic_year_id)
        if study_period_id:
            planned_hours_filter &= Q(study_period_id=study_period_id)
            scheduled_lessons_filter &= Q(study_period_id=study_period_id)
        planned_hours_subquery = CurriculumEntry.objects.filter(planned_hours_filter).values('teacher').annotate(total_planned=Sum('planned_hours')).values('total_planned')
        teachers_qs = teachers_qs.annotate(
            total_planned_hours=Subquery(planned_hours_subquery, output_field=models.FloatField()),
            scheduled_lesson_count=Count('lessons_taught_in_core', filter=scheduled_lessons_filter),
            total_scheduled_duration=Sum(F('lessons_taught_in_core__end_time') - F('lessons_taught_in_core__start_time'), filter=scheduled_lessons_filter)
        )
        return teachers_qs
    def list(self, request, *args, **kwargs): # Переопределяем для передачи обработанных данных в сериализатор
        queryset = self.filter_queryset(self.get_queryset())
        results = []
        for teacher in queryset:
            data = {
                'id': teacher.pk, 'full_name': teacher.get_full_name(), 'email': teacher.email,
                'total_planned_hours': teacher.total_planned_hours or 0.0,
                'scheduled_lesson_count': teacher.scheduled_lesson_count or 0,
                'total_scheduled_hours_float': (teacher.total_scheduled_duration.total_seconds() / 3600) if teacher.total_scheduled_duration else 0.0
            }
            results.append(data)
        page = self.paginate_queryset(results)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(results, many=True)
        return Response(serializer.data)

class TeacherSubjectPerformanceStatsView(generics.ListAPIView):
    serializer_class = TeacherSubjectPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        user = self.request.user; academic_year_id = self.request.query_params.get('academic_year_id'); study_period_id = self.request.query_params.get('study_period_id'); teacher_id_param = self.request.query_params.get('teacher_id')
        if not academic_year_id or not study_period_id: raise DRFValidationError(str(_("Необходимо указать 'academic_year_id' и 'study_period_id'.")))
        target_teachers_qs = User.objects.filter(role=User.Role.TEACHER)
        if user.is_teacher and not user.is_admin: target_teachers_qs = target_teachers_qs.filter(pk=user.pk)
        elif user.is_admin and teacher_id_param: target_teachers_qs = target_teachers_qs.filter(pk=teacher_id_param)
        elif not user.is_admin: return [] # Возвращаем пустой список, если нет прав и не указан teacher_id
        results = []
        for teacher in target_teachers_qs:
            # Получаем информацию о предметах и группах, которые ведет учитель в данном периоде
            lessons_info = Lesson.objects.filter(
                teacher=teacher,
                study_period_id=study_period_id,
                # study_period__academic_year_id=academic_year_id # Это уже включено в study_period_id
            ).values(
                'subject_id', 'subject__name', 'student_group_id', 'student_group__name'
            ).distinct()

            teacher_data = {'teacher_id': teacher.id, 'teacher_name': teacher.get_full_name(), 'groups_data': []}
            for lesson_info in lessons_info:
                group_id = lesson_info['student_group_id']; subject_id = lesson_info['subject_id']
                # Считаем средний балл для группы по предмету в периоде
                avg_grade_data = Grade.objects.filter(
                    student__student_group_memberships__id=group_id, # Студенты из этой группы
                    subject_id=subject_id,
                    study_period_id=study_period_id,
                    numeric_value__isnull=False,
                    weight__gt=0 # Учитываем только оценки с весом > 0
                ).aggregate(
                    weighted_sum=Sum(F('numeric_value') * F('weight')),
                    total_weight=Sum('weight')
                )
                avg_grade = round(avg_grade_data['weighted_sum'] / avg_grade_data['total_weight'], 2) if avg_grade_data['total_weight'] and avg_grade_data['total_weight'] > 0 else None
                grades_count = Grade.objects.filter(student__student_group_memberships__id=group_id, subject_id=subject_id, study_period_id=study_period_id, numeric_value__isnull=False).count()

                teacher_data['groups_data'].append({
                    'group_id': group_id, 'group_name': lesson_info['student_group__name'],
                    'subject_id': subject_id, 'subject_name': lesson_info['subject__name'],
                    'average_grade': avg_grade,
                    'grades_count': grades_count
                })
            if teacher_data['groups_data']: results.append(teacher_data)
        return results
    def list(self, request, *args, **kwargs):
        queryset_data = self.get_queryset() # get_queryset теперь возвращает список словарей
        page = self.paginate_queryset(queryset_data)
        if page is not None:
            # Сериализатор нужен для правильной структуры ответа и документации Swagger
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset_data, many=True)
        return Response(serializer.data)
    
class GroupPerformanceView(generics.ListAPIView):
    serializer_class = GroupPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin] # Кураторы (учителя) или Админы
    filter_backends = []

    def get_queryset(self):
        group_id = self.request.query_params.get('group_id')
        study_period_id = self.request.query_params.get('study_period_id')
        user = self.request.user

        if not group_id or not study_period_id:
            # Не поднимаем исключение здесь, а возвращаем None или пустой queryset,
            # чтобы list мог обработать и вернуть 400
            return StudentGroup.objects.none()

        try:
            group_id = int(group_id)
            study_period_id = int(study_period_id)
        except ValueError:
            return StudentGroup.objects.none() # Невалидные ID

        # Проверка прав: админ видит любую группу, учитель - только если он куратор
        if user.is_teacher and not user.is_admin:
            group_qs = StudentGroup.objects.filter(pk=group_id, curator=user)
        else: # Админ видит все
            group_qs = StudentGroup.objects.filter(pk=group_id)

        if not group_qs.exists():
            # Не поднимаем Http404, пусть list вернет 404 или пустой ответ
            return StudentGroup.objects.none()

        return group_qs.prefetch_related(
            Prefetch(
                'students',
                queryset=User.objects.filter(role=User.Role.STUDENT).prefetch_related(
                    Prefetch(
                        'grades_received',
                        queryset=Grade.objects.filter(
                            study_period_id=study_period_id,
                            numeric_value__isnull=False
                        ).select_related('subject'),
                        to_attr='period_grades_for_stats'
                    )
                ).order_by('last_name', 'first_name'), # Сортируем студентов
                to_attr='students_with_grades_for_stats'
            )
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['study_period_id'] = self.request.query_params.get('study_period_id')
        context['group_id'] = self.request.query_params.get('group_id')
        return context

    def list(self, request, *args, **kwargs):
        group_id = self.request.query_params.get('group_id')
        study_period_id = self.request.query_params.get('study_period_id')
        if not group_id or not study_period_id:
            return Response(
                {"detail": _("Параметры 'group_id' и 'study_period_id' обязательны.")},
                status=status.HTTP_400_BAD_REQUEST
            )
        queryset = self.get_queryset()
        if not queryset.exists():
            return Response({"detail": _("Группа не найдена, нет данных или у вас нет прав доступа к этой группе.")}, status=status.HTTP_404_NOT_FOUND)
        
        # get_queryset возвращает queryset, берем первый элемент
        instance = queryset.first()
        serializer = self.get_serializer(instance, context=self.get_serializer_context())
        return Response(serializer.data)

class ComprehensiveJournalDataView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        logger.debug("="*30 + " ComprehensiveJournalDataView START " + "="*30)
        user = request.user

        group_id_str = request.query_params.get('group_id')
        subject_id_str = request.query_params.get('subject_id')
        period_id_str = request.query_params.get('period_id')
        child_id_str_for_parent = request.query_params.get('child_id')
        
        date_str = request.query_params.get('date')
        date_from_str = request.query_params.get('date_from')
        date_to_str = request.query_params.get('date_to')
        
        logger.debug(
            f"User: {user.email} (Role: {user.role}), Request query params: group_id='{group_id_str}', "
            f"subject_id='{subject_id_str}', period_id='{period_id_str}', child_id='{child_id_str_for_parent}', "
            f"date='{date_str}', date_from='{date_from_str}', date_to='{date_to_str}'"
        )

        if not group_id_str or not subject_id_str or not period_id_str:
            logger.warning("Missing required query parameters: group_id, subject_id, or period_id.")
            return Response(
                {"error": _("Параметры 'group_id', 'subject_id' и 'period_id' обязательны.")},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            group_id = int(group_id_str)
            subject_id = int(subject_id_str)
            period_id = int(period_id_str)
        except ValueError:
            logger.warning("Invalid ID format for group, subject, or period.")
            return Response(
                {"error": _("ID группы, предмета и периода должны быть числами.")},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- 1. Получение базовых объектов ---
        try:
            student_group = StudentGroup.objects.select_related('academic_year', 'curator__profile').get(pk=group_id)
            subject = Subject.objects.select_related('subject_type').prefetch_related('lead_teachers__profile').get(pk=subject_id)
            study_period = StudyPeriod.objects.select_related('academic_year').get(pk=period_id)
            academic_year = study_period.academic_year
        except (StudentGroup.DoesNotExist, Subject.DoesNotExist, StudyPeriod.DoesNotExist) as e:
            logger.warning(f"One of the base entities not found: {e}")
            return Response({"error": _("Указанная группа, предмет или учебный период не найдены.")}, status=status.HTTP_404_NOT_FOUND)
        
        # --- 2. Проверка прав доступа ---
        can_access_data = False
        if user.is_admin:
            can_access_data = True
        elif user.is_teacher:
            is_curator = student_group.curator == user
            teaches_this = Lesson.objects.filter(
                teacher=user, 
                student_group=student_group, 
                subject=subject, 
                study_period=study_period
            ).exists()
            if is_curator or teaches_this:
                can_access_data = True
        elif user.is_student:
            if student_group.students.filter(pk=user.pk).exists():
                can_access_data = True
        elif user.is_parent:
            if user.children.filter(student_group_memberships=student_group).exists():
                can_access_data = True
        
        if not can_access_data:
            logger.warning(f"User {user.email} (Role: {user.role}) permission denied for Group ID {group_id}, Subject ID {subject_id}, Period ID {period_id}.")
            return Response({"error": _("У вас нет прав для просмотра этих данных.")}, status=status.HTTP_403_FORBIDDEN)

        logger.info(f"Access granted. Base entities: Group='{student_group.name}', Subject='{subject.name}', Period='{study_period.name}', Year='{academic_year.name}'")

        # --- 3. Определение студентов в scope и для итоговых оценок ---
        students_in_scope_qs = User.objects.none()
        target_student_ids_for_final_grades = []

        if user.is_admin or user.is_teacher:
            students_in_scope_qs = student_group.students.select_related('profile').order_by('last_name', 'first_name')
        elif user.is_student:
            if student_group.students.filter(pk=user.pk).exists():
                students_in_scope_qs = User.objects.filter(pk=user.pk).select_related('profile')
                target_student_ids_for_final_grades = [user.id]
        elif user.is_parent:
            if child_id_str_for_parent:
                try:
                    child_id = int(child_id_str_for_parent)
                    target_child = user.children.filter(
                        pk=child_id, 
                        role=User.Role.STUDENT, 
                        student_group_memberships=student_group
                    ).select_related('profile').first()
                    if target_child:
                        students_in_scope_qs = User.objects.filter(pk=child_id).select_related('profile')
                        target_student_ids_for_final_grades = [child_id]
                    else:
                        logger.warning(f"Parent {user.email} requested invalid child_id: {child_id_str_for_parent} "
                                     f"or child not in group '{student_group.name}' or not their child.")
                        return Response({"error": _("Указанный ребенок не найден, не принадлежит вам или не состоит в этой группе.")}, status=status.HTTP_404_NOT_FOUND)
                except ValueError:
                    return Response({"error": _("Некорректный ID ребенка.")}, status=status.HTTP_400_BAD_REQUEST)
            else:
                students_in_scope_qs = student_group.students.filter(
                    pk__in=user.children.all().values_list('id', flat=True)
                ).select_related('profile').order_by('last_name', 'first_name')
                target_student_ids_for_final_grades = list(students_in_scope_qs.values_list('id', flat=True))
        
        students_data = EduUserSerializer(students_in_scope_qs, many=True, context={'request': request}).data
        student_ids_for_lesson_data = list(students_in_scope_qs.values_list('id', flat=True))
        
        logger.info(f"Students in scope for lessons/attendance/lesson_grades: IDs {student_ids_for_lesson_data}")
        logger.info(f"Target student IDs for final/period grades: {target_student_ids_for_final_grades}")

        # --- 4. Получаем занятия ---
        lessons_qs_base = Lesson.objects.filter(
            student_group=student_group,
            subject=subject,
            study_period=study_period
        )
        if date_str:
            try: specific_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date(); lessons_qs_base = lessons_qs_base.filter(start_time__date=specific_date)
            except ValueError: return Response({"error": _("Некорректный формат 'date'.")}, status=status.HTTP_400_BAD_REQUEST)
        elif date_from_str or date_to_str:
            if date_from_str:
                try: date_from = datetime.datetime.strptime(date_from_str, '%Y-%m-%d').date(); lessons_qs_base = lessons_qs_base.filter(start_time__date__gte=date_from)
                except ValueError: return Response({"error": _("Некорректный формат 'date_from'.")}, status=status.HTTP_400_BAD_REQUEST)
            if date_to_str:
                try: date_to = datetime.datetime.strptime(date_to_str, '%Y-%m-%d').date(); lessons_qs_base = lessons_qs_base.filter(start_time__date__lte=date_to)
                except ValueError: return Response({"error": _("Некорректный формат 'date_to'.")}, status=status.HTTP_400_BAD_REQUEST)
        
        lessons_qs_optimized = lessons_qs_base.select_related(
            'teacher__profile', 'classroom'
        ).prefetch_related(
            Prefetch(
                'journal_entry', 
                queryset=LessonJournalEntry.objects.prefetch_related(
                    Prefetch(
                        'attendances', 
                        queryset=Attendance.objects.filter(student_id__in=student_ids_for_lesson_data).select_related('student__profile', 'marked_by__profile'),
                        to_attr='prefetched_attendances_for_journal'
                    )
                ).select_related('lesson'), # Добавил select_related('lesson') для LessonJournalEntry
                to_attr='prefetched_journal_entry_single' 
            )
        ).order_by('start_time')
        
        lessons_list_from_db = list(lessons_qs_optimized)
        lessons_data = LessonListSerializer(lessons_list_from_db, many=True, context={'request': request}).data
        lesson_ids_in_scope = [lesson.id for lesson in lessons_list_from_db]

        # --- 5. Собираем оценки ---
        base_grades_qs = Grade.objects.filter(
            student_id__in=student_ids_for_lesson_data,
            subject=subject
        )
        all_grades_q_filter = Q(lesson_id__in=lesson_ids_in_scope)
        
        if target_student_ids_for_final_grades:
            logger.debug(f"Building final grades filter for students: {target_student_ids_for_final_grades}")
            all_grades_q_filter |= Q(
                student_id__in=target_student_ids_for_final_grades, 
                subject=subject,
                study_period=study_period,
                grade_type__in=[Grade.GradeType.PERIOD_FINAL, Grade.GradeType.PERIOD_AVERAGE]
            )
            all_grades_q_filter |= Q(
                student_id__in=target_student_ids_for_final_grades,
                subject=subject,
                academic_year=academic_year,
                grade_type__in=[Grade.GradeType.YEAR_FINAL, Grade.GradeType.YEAR_AVERAGE]
            )
            
        all_grades_qs = base_grades_qs.filter(all_grades_q_filter).select_related(
            'student__profile', 'graded_by__profile', 'lesson', 
            'study_period', 'academic_year', 'homework_submission__homework'
        ).distinct().order_by('student__last_name', 'student__first_name', 'date_given', 'grade_type')

        grades_data = GradeSerializer(all_grades_qs, many=True, context={'request': request}).data
        logger.info(f"Collected {all_grades_qs.count()} grades in total for the scope.")

        # --- 6. Сборка посещаемости и записей журнала ---
        attendances_data = []
        journal_entries_data = []
        for lesson_obj in lessons_list_from_db: 
            # Исправлено: journal_entry_obj теперь объект или None
            journal_entry_obj = getattr(lesson_obj, 'prefetched_journal_entry_single', None)
            
            # Дополнительная проверка на случай, если prefetch вернул список (маловероятно для OneToOne)
            if isinstance(journal_entry_obj, list):
                journal_entry_obj = journal_entry_obj[0] if journal_entry_obj else None

            if journal_entry_obj: 
                journal_entries_data.append(LessonJournalEntrySerializer(journal_entry_obj, context={'request': request}).data)
                prefetched_attendances = getattr(journal_entry_obj, 'prefetched_attendances_for_journal', [])
                if prefetched_attendances:
                    attendances_data.extend(AttendanceSerializer(prefetched_attendances, many=True, context={'request': request}).data)
        
        response_data = {
            "group_info": StudentGroupSerializer(student_group, context={'request': request}).data,
            "subject_info": SubjectSerializer(subject, context={'request': request}).data,
            "period_info": StudyPeriodSerializer(study_period, context={'request': request}).data,
            "academic_year_info": AcademicYearSerializer(academic_year, context={'request': request}).data,
            "students": students_data,
            "lessons": lessons_data,
            "grades": grades_data, 
            "attendances": attendances_data,
            "journal_entries": journal_entries_data
        }
        logger.debug("="*30 + " ComprehensiveJournalDataView END " + "="*30)
        return Response(response_data)