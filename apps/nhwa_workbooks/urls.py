from django.urls import path

from . import views

urlpatterns = [
    path("alignment-centre/", views.alignment_centre, name="nhwa_alignment_centre"),
    path("alignment-centre/action/", views.alignment_action, name="nhwa_alignment_action"),
    path("alignment-centre/export/", views.export_submission_pack, name="nhwa_submission_pack_export"),
    path("", views.workbook_index, name="nhwa_workbook_index"),
    path("<slug:slug>/", views.workbook_detail, name="nhwa_workbook_detail"),
]
