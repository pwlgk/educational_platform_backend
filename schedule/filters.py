# schedule/filters.py
from django_filters import rest_framework as filters
from .models import Lesson
from datetime import timedelta

class LessonDateRangeFilter(filters.FilterSet):
    # Определяем кастомные поля фильтрации
    start_date = filters.DateFilter(field_name='start_time', lookup_expr='gte', label='Start Date (YYYY-MM-DD)')
    end_date = filters.DateFilter(method='filter_end_date', label='End Date (YYYY-MM-DD)')

    class Meta:
        model = Lesson
        # Указываем поля модели, которые можно фильтровать напрямую (если нужно)
        fields = {
            # 'subject': ['exact'], # Например
        }

    def filter_end_date(self, queryset, name, value):
        # Фильтруем по start_time < (end_date + 1 день)
        # Это включит все занятия, начинающиеся в течение end_date
        end_date_plus_one = value + timedelta(days=1)
        return queryset.filter(start_time__lt=end_date_plus_one)

        # Альтернатива: включать те, что пересекают диапазон
        # start_date = self.form.cleaned_data.get('start_date') # Получаем start_date из формы фильтра
        # if start_date:
        #    return queryset.filter(
        #        start_time__lt=end_date_plus_one,
        #        end_time__gte=start_date # Занятие заканчивается после начала диапазона
        #    )
        # else: # Если start_date не задан, просто фильтруем по концу
        #    return queryset.filter(start_time__lt=end_date_plus_one)