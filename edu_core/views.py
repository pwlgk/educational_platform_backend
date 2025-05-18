from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Prefetch, Count, Avg, Sum, F, Subquery, OuterRef, Exists
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
import csv
from io import StringIO
from django.http import StreamingHttpResponse
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model


from .models import (
    AcademicYear, StudyPeriod, SubjectType, Subject, Classroom, StudentGroup,
    Curriculum, CurriculumEntry, Lesson, LessonJournalEntry, Homework,
    HomeworkAttachment, HomeworkSubmission, SubmissionAttachment, Attendance, Grade,
    SubjectMaterial
)
from .serializers import (
    AcademicYearSerializer, StudyPeriodSerializer, SubjectTypeSerializer,
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

from edu_core import serializers

from edu_core import models

User = get_user_model()

class Echo:
    def write(self, value):
        return value

# --- АДМИНСКИЕ VIEWSETS ---
class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all().order_by('-start_date')
    serializer_class = AcademicYearSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]

class StudyPeriodViewSet(viewsets.ModelViewSet):
    queryset = StudyPeriod.objects.select_related('academic_year').all()
    serializer_class = StudyPeriodSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['academic_year']
    ordering_fields = ['start_date', 'name', 'academic_year__name']
    ordering = ['academic_year__start_date', 'start_date']

class SubjectTypeViewSet(viewsets.ModelViewSet):
    queryset = SubjectType.objects.all().order_by('name')
    serializer_class = SubjectTypeSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]

class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.select_related('subject_type').prefetch_related('lead_teachers').all()
    serializer_class = SubjectSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['subject_type']
    search_fields = ['name', 'code', 'description']
    ordering_fields = ['name', 'code']
    ordering = ['name']

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
    queryset = StudentGroup.objects.select_related('academic_year', 'curator', 'group_monitor').prefetch_related('students').all()
    serializer_class = StudentGroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['academic_year', 'curator']
    search_fields = ['name', 'curator__last_name', 'curator__email', 'students__last_name', 'students__email']
    ordering_fields = ['name', 'academic_year__name']
    ordering = ['academic_year__start_date', 'name']

    def perform_create(self, serializer):
        academic_year_id = self.request.data.get('academic_year')
        if not academic_year_id:
             raise serializers.ValidationError({'academic_year': _('Это поле обязательно при создании группы.')})
        try:
            academic_year = AcademicYear.objects.get(pk=academic_year_id)
            curator_id = self.request.data.get('curator')
            group_monitor_id = self.request.data.get('group_monitor')
            students_ids = self.request.data.getlist('students')

            curator = User.objects.get(pk=curator_id) if curator_id else None
            group_monitor = User.objects.get(pk=group_monitor_id) if group_monitor_id else None
            
            instance = serializer.save(
                academic_year=academic_year,
                curator=curator,
                group_monitor=group_monitor
            )
            if students_ids:
                instance.students.set(students_ids)
            # Сигнал (edu_core.signals.create_or_update_group_chat_on_save) создаст чат
        except AcademicYear.DoesNotExist:
            raise serializers.ValidationError({'academic_year': _('Учебный год с таким ID не найден.')})
        except User.DoesNotExist:
            raise serializers.ValidationError({'user': _('Один из указанных пользователей (куратор/староста) не найден.')})

class CurriculumViewSet(viewsets.ModelViewSet):
    queryset = Curriculum.objects.select_related('academic_year', 'student_group').prefetch_related('entries__subject', 'entries__teacher', 'entries__study_period').all()
    serializer_class = CurriculumSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['academic_year', 'student_group', 'is_active']
    search_fields = ['name', 'description', 'student_group__name', 'academic_year__name']
    ordering_fields = ['name', 'academic_year__name', 'student_group__name']
    ordering = ['academic_year__start_date', 'student_group__name', 'name']

class CurriculumEntryViewSet(viewsets.ModelViewSet):
    queryset = CurriculumEntry.objects.select_related('curriculum__academic_year', 'curriculum__student_group', 'subject', 'teacher', 'study_period').all()
    serializer_class = CurriculumEntrySerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacherOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['curriculum', 'subject', 'teacher', 'study_period']
    ordering_fields = ['study_period__start_date', 'subject__name', 'curriculum__name']
    ordering = ['curriculum', 'study_period__start_date', 'subject__name']

class LessonViewSet(viewsets.ModelViewSet):
    queryset = Lesson.objects.select_related(
        'study_period__academic_year', 'student_group', 'subject', 'teacher', 'classroom', 'curriculum_entry', 'created_by'
    ).prefetch_related('journal_entry').all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'study_period': ['exact'], 'student_group': ['exact'], 'teacher': ['exact'],
        'subject': ['exact'], 'classroom': ['exact'], 'lesson_type': ['exact', 'in'],
        'start_time': ['gte', 'lte', 'date__exact', 'date__gte', 'date__lte'],
        'end_time': ['gte', 'lte', 'date__exact', 'date__gte', 'date__lte'],
    }
    search_fields = ['subject__name', 'teacher__last_name', 'student_group__name', 'classroom__identifier', 'journal_entry__topic_covered']
    ordering_fields = ['start_time', 'end_time', 'subject__name', 'student_group__name']
    ordering = ['start_time']

    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'my_schedule':
            return LessonListSerializer
        return LessonSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if self.action == 'list' and not user.is_admin:
            if user.is_teacher: return queryset.filter(teacher=user).distinct()
            return Lesson.objects.none()
        return queryset.distinct()

    def perform_create(self, serializer):
        user = self.request.user
        teacher_for_lesson = serializer.validated_data.get('teacher')
        if user.is_teacher and teacher_for_lesson != user:
            self.permission_denied(self.request, message=_("Вы можете создавать занятия только для себя."))
        serializer.save(created_by=user)

    def perform_update(self, serializer):
        instance = serializer.instance; user = self.request.user
        if user.is_teacher and not user.is_admin and instance.teacher != user and instance.created_by != user:
            self.permission_denied(self.request, message=_('Вы можете изменять только свои или созданные вами занятия.'))
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if user.is_teacher and not user.is_admin and instance.teacher != user and instance.created_by != user:
            self.permission_denied(self.request, message=_('Вы можете удалять только свои или созданные вами занятия.'))
        instance.delete()

    @action(detail=False, methods=['get'], url_path='my-schedule', permission_classes=[permissions.IsAuthenticated])
    def my_schedule(self, request):
        user = request.user; queryset = self.queryset
        if user.is_student: queryset = queryset.filter(student_group__students=user)
        elif user.is_teacher: queryset = queryset.filter(teacher=user)
        elif user.is_parent and user.children.exists():
            children_groups_ids = StudentGroup.objects.filter(students__in=user.children.all()).values_list('id', flat=True).distinct()
            queryset = queryset.filter(student_group_id__in=children_groups_ids)
        elif not user.is_admin: queryset = Lesson.objects.none()
        queryset = self.filter_queryset(queryset.distinct())
        if not request.query_params.get('start_time__date__gte') and not request.query_params.get('start_time__date__lte'):
            queryset = queryset.filter(start_time__date=timezone.localdate())
        page = self.paginate_queryset(queryset)
        serializer = LessonListSerializer(page if page is not None else queryset, many=True, context={'request': request})
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

class LessonJournalEntryViewSet(viewsets.ModelViewSet):
    queryset = LessonJournalEntry.objects.select_related('lesson__subject', 'lesson__student_group', 'lesson__teacher', 'lesson__study_period__academic_year').prefetch_related('homework_assignments', 'attendances').all()
    serializer_class = LessonJournalEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = {'lesson': ['exact'], 'lesson__study_period': ['exact'], 'lesson__study_period__academic_year': ['exact'], 'lesson__student_group': ['exact'], 'lesson__teacher': ['exact'], 'lesson__subject': ['exact'], 'date_filled': ['gte', 'lte', 'date__exact']}
    ordering_fields = ['lesson__start_time', 'date_filled']; ordering = ['-lesson__start_time']
    def _check_teacher_lesson_permission(self, lesson, user, action_verb="изменять"):
        if user.is_teacher and not user.is_admin and lesson.teacher != user:
            self.permission_denied(self.request, message=_("Вы можете %(action)s журнал только для своих занятий.") % {'action': action_verb})
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if user.is_teacher and not user.is_admin: queryset = queryset.filter(lesson__teacher=user)
        elif user.is_student: queryset = queryset.filter(lesson__student_group__students=user)
        elif user.is_parent and user.children.exists():
            children_groups_ids = StudentGroup.objects.filter(students__in=user.children.all()).values_list('id', flat=True).distinct()
            queryset = queryset.filter(lesson__student_group_id__in=children_groups_ids)
        elif not user.is_admin: return LessonJournalEntry.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer):
        lesson = serializer.validated_data.get('lesson')
        self._check_teacher_lesson_permission(lesson, self.request.user, action_verb="заполнять")
        if LessonJournalEntry.objects.filter(lesson=lesson).exists():
            raise serializers.ValidationError({'lesson': _("Для этого занятия уже существует запись в журнале.")})
        serializer.save()
    def perform_update(self, serializer): self._check_teacher_lesson_permission(serializer.instance.lesson, self.request.user, action_verb="изменять"); serializer.save()
    def perform_destroy(self, instance): self._check_teacher_lesson_permission(instance.lesson, self.request.user, action_verb="удалять"); instance.delete()

class HomeworkViewSet(viewsets.ModelViewSet):
    queryset = Homework.objects.select_related('journal_entry__lesson__subject', 'author', 'journal_entry__lesson__student_group').prefetch_related('attachments', 'related_materials', 'submissions').all()
    serializer_class = HomeworkSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = {'journal_entry__lesson__subject': ['exact'], 'journal_entry__lesson__student_group': ['exact'], 'author': ['exact'], 'due_date': ['gte', 'lte', 'exact']}
    search_fields = ['title', 'description']; ordering_fields = ['due_date', 'created_at', 'title']; ordering = ['-due_date']
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if user.is_student: queryset = queryset.filter(journal_entry__lesson__student_group__students=user)
        elif user.is_parent and user.children.exists():
            children_groups_ids = StudentGroup.objects.filter(students__in=user.children.all()).values_list('id', flat=True).distinct()
            queryset = queryset.filter(journal_entry__lesson__student_group_id__in=children_groups_ids)
        elif user.is_teacher and not user.is_admin: queryset = queryset.filter(Q(author=user) | Q(journal_entry__lesson__teacher=user)).distinct()
        elif not user.is_admin: return Homework.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer):
        journal_entry = serializer.validated_data.get('journal_entry'); user = self.request.user
        if user.is_teacher and not user.is_admin and journal_entry.lesson.teacher != user:
             self.permission_denied(self.request, message=_("Вы можете создавать ДЗ только для своих занятий."))
        serializer.save(author=user)

class HomeworkAttachmentViewSet(viewsets.ModelViewSet):
    queryset = HomeworkAttachment.objects.select_related('homework__author', 'homework__journal_entry__lesson').all()
    serializer_class = HomeworkAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_permissions(self):
        if self.action in ['create', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        if self.action in ['update', 'partial_update']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def _can_user_access_homework(self, user, homework):
        if user.is_admin or (user.is_teacher and homework.author == user): return True
        if user.is_student and homework.journal_entry.lesson.student_group.students.filter(pk=user.pk).exists(): return True
        if user.is_parent and user.children.exists() and homework.journal_entry.lesson.student_group.students.filter(pk__in=user.children.all().values_list('id',flat=True)).exists(): return True
        return False
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        homework_id = self.request.query_params.get('homework_id')
        if homework_id:
            try:
                homework = Homework.objects.get(pk=homework_id)
                if not self._can_user_access_homework(user, homework): return HomeworkAttachment.objects.none()
                queryset = queryset.filter(homework_id=homework_id)
            except Homework.DoesNotExist: return HomeworkAttachment.objects.none()
        elif not user.is_admin: return HomeworkAttachment.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer):
        homework = serializer.validated_data.get('homework'); user = self.request.user
        if user.is_teacher and not user.is_admin and homework.author != user:
            self.permission_denied(self.request, message=_("Вы можете добавлять файлы только к своим ДЗ."))
        serializer.save()

class HomeworkSubmissionViewSet(viewsets.ModelViewSet):
    queryset = HomeworkSubmission.objects.select_related('homework__journal_entry__lesson__subject', 'student', 'homework__author').prefetch_related('attachments', 'grade_for_submission').all()
    serializer_class = HomeworkSubmissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = {'homework': ['exact'], 'student': ['exact'], 'submitted_at': ['gte', 'lte', 'date__exact'], 'homework__journal_entry__lesson__student_group': ['exact']}
    ordering_fields = ['submitted_at', 'student__last_name']; ordering = ['-submitted_at']
    def get_serializer_class(self):
        if self.action == 'create' or \
           (hasattr(self.request.user, 'is_student') and self.request.user.is_student and \
            self.action in ['retrieve', 'update', 'partial_update', 'destroy', 'my_submissions_list', 'my_submissions_create']): # Добавил my_submissions_create
            return StudentHomeworkSubmissionSerializer
        return HomeworkSubmissionSerializer
    def get_queryset(self):
        user = self.request.user; queryset = super().get_queryset()
        if self.action == 'my_submissions_list':
             if user.is_student: queryset = queryset.filter(student=user)
             else: return HomeworkSubmission.objects.none()
        elif user.is_student: queryset = queryset.filter(student=user)
        elif user.is_teacher and not user.is_admin: queryset = queryset.filter(Q(homework__author=user) | Q(homework__journal_entry__lesson__teacher=user)).distinct()
        elif user.is_parent and user.children.exists(): queryset = queryset.filter(student__in=user.children.all())
        elif not user.is_admin: return HomeworkSubmission.objects.none()
        return queryset.distinct()
    def get_permissions(self):
        if self.action == 'create' or self.action == 'my_submissions_create': return [permissions.IsAuthenticated(), IsStudent()]
        if self.action in ['update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        if self.action == 'grade_submission': return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        homework = serializer.validated_data.get('homework'); user = self.request.user
        if not homework.journal_entry.lesson.student_group.students.filter(pk=user.pk).exists():
            self.permission_denied(self.request, message=_("Вы не можете сдавать ДЗ для этой группы."))
        if homework.due_date and timezone.now() > homework.due_date: print(f"Студент {user.email} сдает ДЗ '{homework.title}' после срока.")
        if HomeworkSubmission.objects.filter(homework=homework, student=user).exists(): raise serializers.ValidationError(_("Вы уже сдавали это домашнее задание."))
        serializer.save(student=user)
    @action(detail=False, methods=['get'], url_path='my-submissions', permission_classes=[permissions.IsAuthenticated, IsStudent])
    def my_submissions_list(self, request): self.action = 'my_submissions_list'; return self.list(request)
    @action(detail=False, methods=['post'], url_path='my-submissions', permission_classes=[permissions.IsAuthenticated, IsStudent])
    def my_submissions_create(self, request): self.action = 'my_submissions_create'; return self.create(request)
    @action(detail=True, methods=['post'], url_path='grade-submission', serializer_class=GradeSerializer)
    def grade_submission(self, request, pk=None):
        submission = self.get_object(); user = request.user
        if not (user.is_admin or (submission.homework.author == user) or (submission.homework.journal_entry.lesson.teacher == user)):
            self.permission_denied(request, message=_("Вы не можете оценивать эту работу."))
        grade_data = request.data.copy(); grade_data.update({'student': submission.student.id, 'subject': submission.homework.journal_entry.lesson.subject.id, 'study_period': submission.homework.journal_entry.lesson.study_period.id, 'homework_submission': submission.id, 'grade_type': Grade.GradeType.HOMEWORK_GRADE, 'graded_by': user.id})
        grade_instance = Grade.objects.filter(homework_submission=submission).first()
        serializer_kwargs = {'data': grade_data, 'context': {'request': request}};
        if grade_instance: serializer_kwargs['instance'] = grade_instance
        serializer = self.get_serializer(**serializer_kwargs)
        if serializer.is_valid(): serializer.save(); return Response(serializer.data, status=status.HTTP_200_OK if grade_instance else status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SubmissionAttachmentViewSet(viewsets.ModelViewSet):
    queryset = SubmissionAttachment.objects.select_related('submission__homework', 'submission__student').all()
    serializer_class = SubmissionAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_permissions(self):
        if self.action == 'create': return [permissions.IsAuthenticated(), IsStudent()]
        if self.action == 'destroy': return [permissions.IsAuthenticated(), (IsOwnerOrAdmin | IsTeacherOrAdmin)]
        return super().get_permissions()
    def _can_user_access_submission(self, user, submission): # ... (как раньше)
        if user.is_admin: return True
        if user.is_student and submission.student == user: return True
        if user.is_teacher and (submission.homework.author == user or submission.homework.journal_entry.lesson.teacher == user): return True
        return False
    def get_queryset(self): # ... (как раньше)
        user = self.request.user; queryset = super().get_queryset(); submission_id = self.request.query_params.get('submission_id')
        if submission_id:
            try:
                submission = HomeworkSubmission.objects.get(pk=submission_id)
                if not self._can_user_access_submission(user, submission): return SubmissionAttachment.objects.none()
                queryset = queryset.filter(submission_id=submission_id)
            except HomeworkSubmission.DoesNotExist: return SubmissionAttachment.objects.none()
        elif not user.is_admin:
            if user.is_student: queryset = queryset.filter(submission__student=user)
            else: return SubmissionAttachment.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer): # ... (как раньше)
        submission = serializer.validated_data.get('submission'); user = self.request.user
        if submission.student != user: self.permission_denied(self.request, message=_("Вы можете добавлять файлы только к своей сдаче ДЗ."))
        serializer.save()

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.select_related('journal_entry__lesson__subject', 'student', 'marked_by').all()
    serializer_class = AttendanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = {'journal_entry__lesson': ['exact'], 'journal_entry': ['exact'], 'student': ['exact'], 'status': ['exact', 'in'], 'journal_entry__lesson__start_time': ['date__gte', 'date__lte', 'date__exact']}
    ordering_fields = ['journal_entry__lesson__start_time', 'student__last_name']; ordering = ['-journal_entry__lesson__start_time', 'student__last_name']
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'batch_mark_attendance']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self): # ... (как раньше)
        user = self.request.user; queryset = super().get_queryset()
        if user.is_teacher and not user.is_admin: queryset = queryset.filter(journal_entry__lesson__teacher=user)
        elif user.is_student: queryset = queryset.filter(student=user)
        elif user.is_parent and user.children.exists(): queryset = queryset.filter(student__in=user.children.all())
        elif not user.is_admin: return Attendance.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer): # ... (как раньше)
        journal_entry = serializer.validated_data.get('journal_entry'); user = self.request.user
        if user.is_teacher and not user.is_admin and journal_entry.lesson.teacher != user: self.permission_denied(self.request, message=_("Вы можете отмечать посещаемость только на своих занятиях."))
        serializer.save(marked_by=user)
    @action(detail=False, methods=['post'], url_path='batch-mark')
    def batch_mark_attendance(self, request): # ... (как раньше)
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
                if not journal_entry.lesson.student_group.students.filter(pk=student_id).exists(): errors.append({"student_id": student_id, "error": "Студент не из группы этого занятия."}); continue
                obj, created = Attendance.objects.update_or_create(journal_entry=journal_entry, student_id=student_id, defaults={'status': status_val, 'comment': comment_val, 'marked_by': user})
                results.append(AttendanceSerializer(obj).data)
        if errors: return Response({"results": results, "errors": errors}, status=status.HTTP_207_MULTI_STATUS)
        return Response({"results": results, "message": _("Посещаемость обновлена.")}, status=status.HTTP_200_OK)

class GradeViewSet(viewsets.ModelViewSet):
    queryset = Grade.objects.select_related('student', 'subject', 'study_period', 'lesson__teacher', 'homework_submission__homework__author', 'graded_by').all()
    serializer_class = GradeSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = {'student': ['exact'], 'subject': ['exact'], 'study_period': ['exact'], 'lesson': ['exact'], 'grade_type': ['exact', 'in'], 'date_given': ['gte', 'lte', 'exact'], 'homework_submission': ['exact']}
    search_fields = ['student__last_name', 'subject__name', 'comment', 'grade_value']
    ordering_fields = ['date_given', 'student__last_name', 'subject__name', 'grade_type']; ordering = ['-date_given']
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self): # ... (как раньше)
        user = self.request.user; queryset = super().get_queryset()
        if user.is_teacher and not user.is_admin: queryset = queryset.filter(Q(graded_by=user) | Q(lesson__teacher=user) | Q(homework_submission__homework__author=user)).distinct()
        elif user.is_student: queryset = queryset.filter(student=user)
        elif user.is_parent and user.children.exists(): queryset = queryset.filter(student__in=user.children.all())
        elif not user.is_admin: return Grade.objects.none()
        return queryset.distinct()
    def perform_create(self, serializer): # ... (как раньше)
        user = self.request.user; lesson = serializer.validated_data.get('lesson'); homework_submission = serializer.validated_data.get('homework_submission'); subject = serializer.validated_data.get('subject'); student_for_grade = serializer.validated_data.get('student'); study_period = serializer.validated_data.get('study_period')
        can_grade = False
        if user.is_admin: can_grade = True
        elif user.is_teacher:
            if lesson and lesson.teacher == user: can_grade = True
            elif homework_submission and homework_submission.homework.author == user : can_grade = True
            elif not lesson and not homework_submission and subject and student_for_grade and study_period:
                if CurriculumEntry.objects.filter(curriculum__student_group__students=student_for_grade, subject=subject, teacher=user, study_period=study_period).exists(): can_grade = True
        if not can_grade: self.permission_denied(self.request, message=_("У вас нет прав на выставление этой оценки."))
        serializer.save(graded_by=user)

class SubjectMaterialViewSet(viewsets.ModelViewSet):
    queryset = SubjectMaterial.objects.select_related('subject', 'student_group', 'uploaded_by').all()
    serializer_class = SubjectMaterialSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['subject', 'student_group', 'uploaded_by']
    search_fields = ['title', 'description', 'subject__name']
    ordering_fields = ['uploaded_at', 'title', 'subject__name']; ordering = ['-uploaded_at']
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']: return [permissions.IsAuthenticated(), IsTeacherOrAdmin()]
        return super().get_permissions()
    def get_queryset(self): # ... (как раньше)
        user = self.request.user; queryset = super().get_queryset()
        if user.is_student: user_groups = user.student_group_memberships.all(); queryset = queryset.filter(Q(student_group__in=user_groups) | Q(student_group__isnull=True)).distinct()
        elif user.is_parent and user.children.exists(): children_groups = StudentGroup.objects.filter(students__in=user.children.all()).distinct(); queryset = queryset.filter(Q(student_group__in=children_groups) | Q(student_group__isnull=True)).distinct()
        elif user.is_teacher and not user.is_admin: queryset = queryset.filter(Q(uploaded_by=user) | Q(student_group__isnull=True)).distinct()
        return queryset
    def perform_create(self, serializer): serializer.save(uploaded_by=self.request.user)

# --- ПАНЕЛЬ ПРЕПОДАВАТЕЛЯ ---
class TeacherMyScheduleViewSet(LessonViewSet):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    serializer_class = LessonListSerializer
    http_method_names = ['get', 'head', 'options']
    def get_queryset(self): return Lesson.objects.filter(teacher=self.request.user).select_related('study_period', 'student_group', 'subject', 'classroom').prefetch_related('journal_entry').distinct().order_by('start_time')

class TeacherMyGroupsView(generics.ListAPIView): # ИСПРАВЛЕНО: Это ListAPIView
    serializer_class = StudentGroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']
    def get_queryset(self):
        user = self.request.user; current_academic_year = AcademicYear.objects.filter(is_current=True).first()
        if not current_academic_year: return StudentGroup.objects.none()
        teaching_group_ids = Lesson.objects.filter(teacher=user, study_period__academic_year=current_academic_year).values_list('student_group_id', flat=True).distinct()
        return StudentGroup.objects.filter(Q(curator=user, academic_year=current_academic_year) | Q(id__in=list(teaching_group_ids))).select_related('academic_year', 'curator').prefetch_related('students').distinct().order_by('name')

class TeacherLessonJournalViewSet(LessonJournalEntryViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherHomeworkViewSet(HomeworkViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherHomeworkSubmissionViewSet(HomeworkSubmissionViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherAttendanceViewSet(AttendanceViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherGradeViewSet(GradeViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]
class TeacherSubjectMaterialViewSet(SubjectMaterialViewSet): permission_classes = [permissions.IsAuthenticated, IsTeacher]

# --- ПАНЕЛЬ КУРАТОРА ---
class CuratorManagedGroupsViewSet(StudentGroupViewSet):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    http_method_names = ['get', 'retrieve', 'put', 'patch', 'head', 'options']
    def get_queryset(self): return StudentGroup.objects.filter(curator=self.request.user).select_related('academic_year', 'curator', 'group_monitor').prefetch_related('students').order_by('name')
    def perform_update(self, serializer):
        allowed_fields = {'group_monitor', 'students'}
        if not set(serializer.validated_data.keys()).issubset(allowed_fields): raise serializers.ValidationError(_("Куратор может изменять только старосту и состав студентов."))
        if 'curator' in serializer.validated_data and serializer.validated_data['curator'] != self.request.user: raise serializers.ValidationError(_("Вы не можете изменить куратора этой группы."))
        if 'academic_year' in serializer.validated_data: raise serializers.ValidationError(_("Изменение учебного года группы не разрешено."))
        super().perform_update(serializer)

class CuratorGroupPerformanceView(generics.ListAPIView):
    serializer_class = GroupPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacher]
    filter_backends = [DjangoFilterBackend]
    def get_queryset(self):
        user = self.request.user; group_pk = self.kwargs.get('group_pk')
        group = get_object_or_404(StudentGroup, pk=group_pk, curator=user)
        study_period_id = self.request.query_params.get('study_period_id')
        if not study_period_id: raise serializers.ValidationError(_("Необходимо указать 'study_period_id' в параметрах запроса."))
        return StudentGroup.objects.filter(pk=group.pk).prefetch_related(Prefetch('students',queryset=User.objects.filter(role=User.Role.STUDENT).prefetch_related(Prefetch('grades_received',queryset=Grade.objects.filter(study_period_id=study_period_id, numeric_value__isnull=False).select_related('subject'),to_attr='period_grades_for_stats')),to_attr='students_with_grades_for_stats'))
    def get_serializer_context(self): context = super().get_serializer_context(); context['study_period_id'] = self.request.query_params.get('study_period_id'); return context
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if not queryset.exists(): return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(queryset.first(), context=self.get_serializer_context()); return Response(serializer.data)

# --- ПАНЕЛЬ СТУДЕНТА ---
class StudentMyScheduleListView(generics.ListAPIView):
    serializer_class = LessonListSerializer; permission_classes = [permissions.IsAuthenticated, IsStudent]; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'start_time': ['gte', 'lte', 'date__exact'], 'subject': ['exact'], 'teacher': ['exact']}; ordering_fields = ['start_time', 'subject__name']; ordering = ['start_time']
    def get_queryset(self): return Lesson.objects.filter(student_group__students=self.request.user).select_related('study_period', 'subject', 'teacher', 'classroom').distinct().order_by('start_time')

class StudentMyGradesListView(generics.ListAPIView):
    serializer_class = MyGradeSerializer; permission_classes = [permissions.IsAuthenticated, IsStudent]; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'subject': ['exact'], 'study_period': ['exact'], 'grade_type': ['exact', 'in'], 'date_given': ['gte', 'lte']}; ordering_fields = ['-date_given', 'subject__name']; ordering = ['-date_given']
    def get_queryset(self): return Grade.objects.filter(student=self.request.user).select_related('subject', 'study_period', 'lesson', 'graded_by').distinct()

class StudentMyAttendanceListView(generics.ListAPIView):
    serializer_class = MyAttendanceSerializer; permission_classes = [permissions.IsAuthenticated, IsStudent]; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'status': ['exact'], 'journal_entry__lesson__start_time': ['date__gte', 'date__lte'], 'journal_entry__lesson__subject':['exact']}; ordering_fields = ['-journal_entry__lesson__start_time']; ordering = ['-journal_entry__lesson__start_time']
    def get_queryset(self): return Attendance.objects.filter(student=self.request.user).select_related('journal_entry__lesson__subject', 'student').distinct()

class StudentMyHomeworkListView(generics.ListAPIView):
    serializer_class = MyHomeworkSerializer; permission_classes = [permissions.IsAuthenticated, IsStudent]; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'due_date': ['gte', 'lte', 'isnull'], 'journal_entry__lesson__subject':['exact']}; ordering_fields = ['-due_date', 'created_at']; ordering = ['-due_date']
    def get_queryset(self): return Homework.objects.filter(journal_entry__lesson__student_group__students=self.request.user).select_related('journal_entry__lesson__subject', 'author').prefetch_related('attachments', 'related_materials').distinct()
    def get_serializer_context(self): return {'request': self.request}

class StudentMyHomeworkSubmissionViewSet(HomeworkSubmissionViewSet): permission_classes = [permissions.IsAuthenticated, IsStudent]

# --- ПАНЕЛЬ РОДИТЕЛЯ ---
class ParentChildDataMixin:
    permission_classes = [permissions.IsAuthenticated, IsParent]; http_method_names = ['get', 'head', 'options']
    def get_target_children_ids(self):
        user = self.request.user;
        if not user.children.exists(): return []
        child_id = self.request.query_params.get('child_id')
        if child_id:
            try:
                if user.children.filter(pk=child_id).exists(): return [int(child_id)]
                return []
            except (ValueError, User.DoesNotExist): return []
        return user.children.values_list('id', flat=True)

class ParentChildScheduleListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = LessonListSerializer; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'start_time': ['gte', 'lte', 'date__exact'], 'subject': ['exact'], 'teacher': ['exact']}; ordering_fields = ['start_time', 'subject__name']; ordering = ['start_time']
    def get_queryset(self):
        children_ids = self.get_target_children_ids();
        if not children_ids: return Lesson.objects.none()
        children_groups_ids = StudentGroup.objects.filter(students__id__in=children_ids).values_list('id', flat=True).distinct()
        return Lesson.objects.filter(student_group_id__in=children_groups_ids).select_related('study_period', 'student_group', 'subject', 'teacher', 'classroom').prefetch_related('journal_entry').distinct()

class ParentChildGradesListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = MyGradeSerializer; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'subject': ['exact'], 'study_period': ['exact'], 'grade_type': ['exact', 'in'], 'date_given': ['gte', 'lte']}; ordering_fields = ['-date_given', 'subject__name']; ordering = ['-date_given']
    def get_queryset(self):
        children_ids = self.get_target_children_ids();
        if not children_ids: return Grade.objects.none()
        return Grade.objects.filter(student_id__in=children_ids).select_related('student', 'subject', 'study_period', 'lesson', 'graded_by').distinct()

class ParentChildAttendanceListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = MyAttendanceSerializer; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'status': ['exact'], 'journal_entry__lesson__start_time': ['date__gte', 'date__lte'], 'journal_entry__lesson__subject':['exact']}; ordering_fields = ['-journal_entry__lesson__start_time']; ordering = ['-journal_entry__lesson__start_time']
    def get_queryset(self):
        children_ids = self.get_target_children_ids();
        if not children_ids: return Attendance.objects.none()
        return Attendance.objects.filter(student_id__in=children_ids).select_related('journal_entry__lesson__subject', 'student').distinct()

class ParentChildHomeworkListView(ParentChildDataMixin, generics.ListAPIView):
    serializer_class = MyHomeworkSerializer; filter_backends = [DjangoFilterBackend, filters.OrderingFilter]; filterset_fields = {'due_date': ['gte', 'lte', 'isnull'], 'journal_entry__lesson__subject':['exact']}; ordering_fields = ['-due_date', 'created_at']; ordering = ['-due_date']
    def get_queryset(self):
        children_ids = self.get_target_children_ids();
        if not children_ids: return Homework.objects.none()
        children_groups_ids = StudentGroup.objects.filter(students__id__in=children_ids).values_list('id', flat=True).distinct()
        return Homework.objects.filter(journal_entry__lesson__student_group_id__in=children_groups_ids).select_related('journal_entry__lesson__subject', 'author').prefetch_related('attachments', 'related_materials').distinct()
    def get_serializer_context(self): context = super().get_serializer_context(); return context

# --- ИМПОРТ ---
class ImportDataView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    def get_serializer_class_for_import(self, import_type):
        if import_type == 'teachers': return TeacherImportSerializer
        if import_type == 'subjects': return SubjectImportSerializer
        if import_type == 'student-groups': return StudentGroupImportSerializer
        return None
    @transaction.atomic
    def post(self, request, import_type, *args, **kwargs):
        serializer_class = self.get_serializer_class_for_import(import_type)
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
                else: created_instances = serializer.save()
                return Response({"message": f"Импорт '{import_type}' успешно завершен.","processed_count": len(data_to_serialize),"created_or_updated_count": len(created_instances)}, status=status.HTTP_201_CREATED)
            except Exception as e: return Response({"error": f"Ошибка во время сохранения данных: {e}", "details": getattr(e, 'detail', str(e))}, status=status.HTTP_400_BAD_REQUEST)
        else: return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# --- ЭКСПОРТ И СТАТИСТИКА ---
class ExportJournalView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request, *args, **kwargs):
        user = request.user; group_id = request.query_params.get('group_id'); subject_id = request.query_params.get('subject_id'); period_id = request.query_params.get('period_id')
        queryset = LessonJournalEntry.objects.select_related('lesson__student_group', 'lesson__subject', 'lesson__teacher').prefetch_related('attendances__student', Prefetch('lesson__grades_for_lesson_instance', queryset=Grade.objects.select_related('student'))).order_by('lesson__start_time', 'lesson__student_group__name')
        if user.is_admin:
            if group_id: queryset = queryset.filter(lesson__student_group_id=group_id)
            if subject_id: queryset = queryset.filter(lesson__subject_id=subject_id)
            if period_id: queryset = queryset.filter(lesson__study_period_id=period_id)
        elif user.is_teacher:
            queryset = queryset.filter(lesson__teacher=user)
            if group_id:
                can_export = Lesson.objects.filter(teacher=user, student_group_id=group_id)
                if subject_id: can_export = can_export.filter(subject_id=subject_id)
                if not can_export.exists(): return Response({"error": _("У вас нет прав на экспорт журнала для этой группы/предмета.")}, status=status.HTTP_403_FORBIDDEN)
                queryset = queryset.filter(lesson__student_group_id=group_id)
            if subject_id: queryset = queryset.filter(lesson__subject_id=subject_id)
            if period_id: queryset = queryset.filter(lesson__study_period_id=period_id)
        elif user.is_student or user.is_parent: return Response({"error": _("Экспорт журнала недоступен для вашей роли.")}, status=status.HTTP_403_FORBIDDEN)
        else: return Response({"error": _("Недостаточно прав.")}, status=status.HTTP_403_FORBIDDEN)
        pseudo_buffer = Echo(); writer = csv.writer(pseudo_buffer)
        header = ['ID Занятия', 'Дата', 'Время начала', 'Время окончания', 'Группа', 'Предмет', 'Преподаватель', 'Тема занятия', 'Студент ФИО', 'ID Студента', 'Статус посещ.', 'Ком. к посещ.', 'Оценка за урок (тип: значение)', 'Ком. к оценке', 'Домашнее задание']
        response = StreamingHttpResponse((writer.writerow(row) for row in self.generate_journal_rows(queryset, header)), content_type="text/csv")
        response['Content-Disposition'] = f'attachment; filename="journal_export_{timezone.now().strftime("%Y%m%d%H%M%S")}.csv"'; return response
    def generate_journal_rows(self, queryset, header):
        yield header
        for entry in queryset:
            lesson = entry.lesson
            homework_for_lesson = Homework.objects.filter(journal_entry=entry).first()
            homework_text = homework_for_lesson.title if homework_for_lesson else "-"
            for student_in_group in lesson.student_group.students.all().order_by('last_name', 'first_name'):
                attendance_record = entry.attendances.filter(student=student_in_group).first()
                grade_record = lesson.grades_for_lesson_instance.filter(student=student_in_group, grade_type=Grade.GradeType.LESSON_WORK).first()
                row = [ lesson.id, lesson.start_time.strftime('%Y-%m-%d'), lesson.start_time.strftime('%H:%M'), lesson.end_time.strftime('%H:%M'), lesson.student_group.name, lesson.subject.name, lesson.teacher.get_full_name(), entry.topic_covered, student_in_group.get_full_name(), student_in_group.id, attendance_record.get_status_display() if attendance_record else '-', attendance_record.comment if attendance_record else '-', f"{grade_record.get_grade_type_display()}: {grade_record.grade_value}" if grade_record else '-', grade_record.comment if grade_record else '-', homework_text ]
                yield row

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
            # Сериализатор здесь для валидации структуры ответа и документации Swagger
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data) # Передаем данные, а не queryset
        serializer = self.get_serializer(results, many=True)
        return Response(serializer.data)



class TeacherSubjectPerformanceStatsView(generics.ListAPIView):
    
    serializer_class = TeacherSubjectPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        user = self.request.user; academic_year_id = self.request.query_params.get('academic_year_id'); study_period_id = self.request.query_params.get('study_period_id'); teacher_id_param = self.request.query_params.get('teacher_id')
        if not academic_year_id or not study_period_id: raise serializers.ValidationError(str(_("Необходимо указать 'academic_year_id' и 'study_period_id'.")))
        target_teachers_qs = User.objects.filter(role=User.Role.TEACHER)
        if user.is_teacher and not user.is_admin: target_teachers_qs = target_teachers_qs.filter(pk=user.pk)
        elif user.is_admin and teacher_id_param: target_teachers_qs = target_teachers_qs.filter(pk=teacher_id_param)
        elif not user.is_admin: return []
        results = []
        for teacher in target_teachers_qs:
            lessons_info = Lesson.objects.filter(teacher=teacher, study_period_id=study_period_id, study_period__academic_year_id=academic_year_id).values('subject_id', 'subject__name', 'student_group_id', 'student_group__name').distinct()
            teacher_data = {'teacher_id': teacher.id, 'teacher_name': teacher.get_full_name(), 'groups_data': []}
            for lesson_info in lessons_info:
                group_id = lesson_info['student_group_id']; subject_id = lesson_info['subject_id']
                avg_grade_data = Grade.objects.filter(student__student_group_memberships__id=group_id, subject_id=subject_id, study_period_id=study_period_id, numeric_value__isnull=False, weight__gt=0).aggregate(weighted_sum=Sum(F('numeric_value') * F('weight')), total_weight=Sum('weight'))
                avg_grade = round(avg_grade_data['weighted_sum'] / avg_grade_data['total_weight'], 2) if avg_grade_data['total_weight'] and avg_grade_data['total_weight'] > 0 else None
                teacher_data['groups_data'].append({'group_id': group_id, 'group_name': lesson_info['student_group__name'], 'subject_id': subject_id, 'subject_name': lesson_info['subject__name'], 'average_grade': avg_grade, 'grades_count': Grade.objects.filter(student__student_group_memberships__id=group_id, subject_id=subject_id, study_period_id=study_period_id, numeric_value__isnull=False).count()})
            if teacher_data['groups_data']: results.append(teacher_data)
        return results
    def list(self, request, *args, **kwargs): # Переопределяем list
        queryset_data = self.get_queryset()
        page = self.paginate_queryset(queryset_data) # Пагинируем уже список словарей
        if page is not None:
            serializer = self.get_serializer(page, many=True) # Сериализуем для Swagger и структуры
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset_data, many=True)
        return Response(serializer.data)
    
class GroupPerformanceView(generics.ListAPIView):
    """
    Статистика успеваемости по указанной группе (для Администратора).
    Фильтры: ?group_id=X&study_period_id=Y
    """
    serializer_class = GroupPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [] # Явные параметры запроса

    def get_queryset(self):
        group_id = self.request.query_params.get('group_id')
        study_period_id = self.request.query_params.get('study_period_id')

        if not group_id:
            # В ListAPIView лучше возвращать пустой queryset или ошибку, если параметр обязателен
            # raise serializers.ValidationError(_("Необходимо указать 'group_id' в параметрах запроса."))
            return StudentGroup.objects.none()
        if not study_period_id:
            # raise serializers.ValidationError(_("Необходимо указать 'study_period_id' в параметрах запроса."))
            return StudentGroup.objects.none()

        group = get_object_or_404(StudentGroup, pk=group_id)
        
        return StudentGroup.objects.filter(pk=group.pk).prefetch_related(
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
                ),
                to_attr='students_with_grades_for_stats'
            )
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['study_period_id'] = self.request.query_params.get('study_period_id')
        # Передаем group_id, если сериализатору это нужно (хотя он получает StudentGroup)
        context['group_id'] = self.request.query_params.get('group_id')
        return context

    def list(self, request, *args, **kwargs):
        # Валидация обязательных параметров перед вызовом get_queryset
        group_id = self.request.query_params.get('group_id')
        study_period_id = self.request.query_params.get('study_period_id')
        if not group_id or not study_period_id:
            return Response(
                {"detail": _("Параметры 'group_id' и 'study_period_id' обязательны.")},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        queryset = self.get_queryset()
        if not queryset.exists():
            return Response({"detail": _("Группа не найдена или нет данных для указанных параметров.")}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = self.get_serializer(queryset.first(), context=self.get_serializer_context())
        return Response(serializer.data)