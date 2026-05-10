from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views


router = DefaultRouter()
router.register(r"staff", api_views.StaffViewSet, basename="staff")

urlpatterns = [
    path("nursing/pathways/", api_views.nursing_pathways, name="nursing_pathways"),
    path("nursing/dashboard/operations/", api_views.nursing_dashboard_operations, name="nursing_dashboard_operations"),
    path("nursing/public-register/search/", api_views.nursing_public_register_search, name="nursing_public_register_search"),
    path("", include(router.urls)),
]
