from django.urls import path

from .views import OCRDetailView, OCRImportView

urlpatterns = [
    path("import/", OCRImportView.as_view(), name="ocr_import"),
    path("documents/<int:pk>/", OCRDetailView.as_view(), name="ocr_detail"),
]
