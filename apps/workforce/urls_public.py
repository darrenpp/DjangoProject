from django.urls import path

from .views import PublicRegistrationView

urlpatterns = [
    path('', PublicRegistrationView.as_view(), name='public_register'),
    path('forms/<str:form_code>/', PublicRegistrationView.as_view(), name='public_form_code_register'),
    path('graduand/', PublicRegistrationView.as_view(), name='public_graduand_register'),
    path('nurse/', PublicRegistrationView.as_view(), name='public_nurse_register'),
    path('chw/', PublicRegistrationView.as_view(), name='public_chw_register'),
    path('nurse-aide/', PublicRegistrationView.as_view(), name='public_nurse_aide_register'),
    path('doctor/', PublicRegistrationView.as_view(), name='public_doctor_register'),
    path('student/', PublicRegistrationView.as_view(), name='public_student_register'),
    path('renewal/', PublicRegistrationView.as_view(), name='public_renewal'),
]
