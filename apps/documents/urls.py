from django.urls import path

from . import views


urlpatterns = [
    path("", views.repository_home, name="repository_home"),
    path("search/", views.repository_search, name="repository_search"),
    path("upload/", views.repository_upload, name="repository_upload"),
    path("<int:pk>/", views.repository_detail, name="repository_detail"),
    path("<int:pk>/update/", views.repository_update_metadata, name="repository_update_metadata"),
    path("<int:pk>/approval/<str:action>/", views.repository_approval_action, name="repository_approval_action"),
    path("<int:pk>/versions/add/", views.repository_add_version, name="repository_add_version"),
    path("<int:pk>/versions/<int:version_id>/download/", views.repository_download, name="repository_download"),
]
