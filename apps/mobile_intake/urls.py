from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.MobileLoginView.as_view(), name="mobile_v1_login"),
    path("bootstrap/", views.BootstrapView.as_view(), name="mobile_v1_bootstrap"),
    path("forms/", views.FormsView.as_view(), name="mobile_v1_forms"),
    path("lookups/", views.LookupsView.as_view(), name="mobile_v1_lookups"),
    path("duplicates/check/", views.DuplicateCheckView.as_view(), name="mobile_v1_duplicate_check"),
    path("submissions/", views.SubmissionCreateView.as_view(), name="mobile_v1_submission_create"),
    path("submissions/<uuid:submission_uuid>/attachments/", views.AttachmentUploadView.as_view(), name="mobile_v1_attachment_upload"),
    path("submissions/status/", views.SubmissionStatusView.as_view(), name="mobile_v1_submission_status"),
    path("accounts/register/", views.MobileAccountRegisterView.as_view(), name="mobile_v1_account_register"),
    path("accounts/status/", views.MobileAccountStatusView.as_view(), name="mobile_v1_account_status"),
    path("health/", views.HealthView.as_view(), name="mobile_v1_health"),
]
