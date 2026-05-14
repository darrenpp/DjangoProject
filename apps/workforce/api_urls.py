from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views


router = DefaultRouter()
router.register(r"staff", api_views.StaffViewSet, basename="staff")

urlpatterns = [
    path("mobile/bootstrap/", api_views.mobile_bootstrap, name="mobile_bootstrap"),
    path("mobile/duplicate-check/", api_views.mobile_duplicate_check, name="mobile_duplicate_check"),
    path("mobile/sync/batch/", api_views.mobile_sync_batch, name="mobile_sync_batch"),
    path("mobile/attachments/", api_views.mobile_attachment_upload, name="mobile_attachment_upload"),
    path("mobile/sync/status/", api_views.mobile_sync_status, name="mobile_sync_status"),
    path("nursing/pathways/", api_views.nursing_pathways, name="nursing_pathways"),
    path("nursing/dashboard/operations/", api_views.nursing_dashboard_operations, name="nursing_dashboard_operations"),
    path("nursing/public-register/search/", api_views.nursing_public_register_search, name="nursing_public_register_search"),
    path("", include(router.urls)),
]
