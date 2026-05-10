from django.urls import path

from . import views

urlpatterns = [
    path('helpdesk/', views.helpdesk, name='helpdesk'),
    path('helpdesk/api/', views.helpdesk_api, name='helpdesk_api'),
    path('communications/', views.staff_communications, name='staff_communications'),
    path('enquiries/', views.enquiry_inbox, name='enquiry_inbox'),
    path('enquiries/new/', views.enquiry_create, name='enquiry_create'),
    path('enquiries/<int:pk>/', views.enquiry_thread, name='enquiry_thread'),
]
