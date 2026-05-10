from django.urls import path

from .record_views import (
    PopulationGuideView,
    RecordCreateView,
    RecordDeleteView,
    RecordDetailView,
    RecordListView,
    RecordUpdateView,
    RecordsHomeView,
)

urlpatterns = [
    path("", RecordsHomeView.as_view(), name="records_home"),
    path("population-guide/", PopulationGuideView.as_view(), name="population_guide"),
    path("<slug:model_slug>/", RecordListView.as_view(), name="record_list"),
    path("<slug:model_slug>/add/", RecordCreateView.as_view(), name="record_create"),
    path("<slug:model_slug>/<int:pk>/", RecordDetailView.as_view(), name="record_detail"),
    path("<slug:model_slug>/<int:pk>/edit/", RecordUpdateView.as_view(), name="record_update"),
    path("<slug:model_slug>/<int:pk>/delete/", RecordDeleteView.as_view(), name="record_delete"),
]
