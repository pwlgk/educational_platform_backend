# Generated by Django 5.1.7 on 2025-05-19 09:46

import edu_core.models
import edu_core.storages
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('edu_core', '0005_grade_academic_year_alter_grade_study_period_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='homeworkattachment',
            name='file',
            field=models.FileField(storage=edu_core.storages.UniquePathAndOriginalNameStorage(), upload_to=edu_core.models.homework_attachment_upload_path, verbose_name='файл'),
        ),
        migrations.AlterField(
            model_name='submissionattachment',
            name='file',
            field=models.FileField(storage=edu_core.storages.UniquePathAndOriginalNameStorage(), upload_to=edu_core.models.submission_attachment_upload_path, verbose_name='файл'),
        ),
    ]
