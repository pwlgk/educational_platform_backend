from edu_core.models import Lesson, LessonJournalEntry, Attendance, StudentGroup, Subject, StudyPeriod
from django.db.models import Prefetch

# Замените на ваши ID
group_id = 45
subject_id = 59
period_id = 36

student_group = StudentGroup.objects.get(pk=group_id)
students_qs = student_group.students.all()

lessons = Lesson.objects.filter(
    student_group_id=group_id,
    subject_id=subject_id,
    study_period_id=period_id
).prefetch_related(
    Prefetch(
        'journal_entry',
        queryset=LessonJournalEntry.objects.prefetch_related(
            Prefetch(
                'attendances',
                queryset=Attendance.objects.filter(student__in=students_qs), # Фильтр по студентам
                to_attr='prefetched_attendances_for_journal'
            )
        ),
        to_attr='prefetched_journal_entry_single'
    )
)

for lesson in lessons:
    print(f"Lesson: {lesson.id}")
    journal_entry = getattr(lesson, 'prefetched_journal_entry_single', None)
    if journal_entry:
        print(f"  Journal Entry: {journal_entry.id}")
        attendances = getattr(journal_entry, 'prefetched_attendances_for_journal', None)
        if attendances:
            print(f"  Attendances count: {len(attendances)}")
            for att in attendances:
                print(f"    Student: {att.student.id}, Status: {att.status}")
        else:
            print("    No prefetched attendances for this journal entry or attribute 'prefetched_attendances_for_journal' not found.")
    else:
        print("  No journal entry for this lesson.")