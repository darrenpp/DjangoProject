# apps/accounts/urls_public.py
from django.urls import path
from .views import public_register

urlpatterns = [
    path('', public_register, name='public_register'),
    # Optional specific routes for different roles
    path('graduand/', public_register, name='public_graduand_register'),
    path('nurse/', public_register, name='public_nurse_register'),
    path('chw/', public_register, name='public_chw_register'),
    path('nurse-aide/', public_register, name='public_nurse_aide_register'),
    path('doctor/', public_register, name='public_doctor_register'),
    path('student/', public_register, name='public_student_register'),
]
