from django.urls import path

from .record_views import (
    PopulationGuideView,
    RecordCreateView,
    RecordDeleteView,
    RecordDetailView,
    RecordListDataView,
    RecordListView,
    RecordUpdateView,
    RecordsHomeView,
    RegistryArchiveView,
)

urlpatterns = [
    path("", RecordsHomeView.as_view(), name="records_home"),
    path("archives/", RegistryArchiveView.as_view(), name="registry_archive"),
    path("population-guide/", PopulationGuideView.as_view(), name="population_guide"),
    path("<slug:model_slug>/", RecordListView.as_view(), name="record_list"),
    path("<slug:model_slug>/data/", RecordListDataView.as_view(), name="record_list_data"),
    path("<slug:model_slug>/add/", RecordCreateView.as_view(), name="record_create"),
    path("<slug:model_slug>/<int:pk>/", RecordDetailView.as_view(), name="record_detail"),
    path("<slug:model_slug>/<int:pk>/edit/", RecordUpdateView.as_view(), name="record_update"),
    path("<slug:model_slug>/<int:pk>/delete/", RecordDeleteView.as_view(), name="record_delete"),
]
