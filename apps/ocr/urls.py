from django.urls import path

from .views import OCRImportView

urlpatterns = [
    path("import/", OCRImportView.as_view(), name="ocr_import"),
]
