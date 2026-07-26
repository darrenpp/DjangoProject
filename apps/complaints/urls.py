from django.urls import path

from . import views


urlpatterns = [
    path("", views.complaint_case_list, name="complaint_case_list"),
    path("new/", views.complaint_case_create, name="complaint_case_create"),
    path("submit/", views.complaint_public_submit, name="complaint_public_submit"),
    path("discipline/", views.disciplinary_case_list, name="disciplinary_case_list"),
    path("discipline/new/", views.disciplinary_case_create, name="disciplinary_case_create"),
    path("discipline/<uuid:discipline_uuid>/", views.disciplinary_case_detail, name="disciplinary_case_detail"),
    path("decisions/", views.regulatory_decision_list, name="regulatory_decision_list"),
    path("decisions/<uuid:decision_uuid>/", views.regulatory_decision_detail, name="regulatory_decision_detail"),
    path("<uuid:case_uuid>/", views.complaint_case_detail, name="complaint_case_detail"),
    path("<uuid:case_uuid>/acknowledge/", views.complaint_case_acknowledge, name="complaint_case_acknowledge"),
]
