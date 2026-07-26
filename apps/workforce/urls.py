# apps/workforce/urls.py
from django.urls import path, include

from .profile_update_views import (
    professional_profile_update_queue,
    professional_profile_update_request,
    review_professional_profile_update_request,
)

from .views import (
    ImportDataView,
    PublicRegistrationView,
    ProfessionalDetailView,
    ApplicationDetailView,
    ApplicationUpdateView,
    admin_dashboard,
    approve_application,
    approve_deceased_notification_view,
    complete_supervisor_assignment_view,
    create_supervisor_assignment_view,
    generate_application_checklist_view,
    issue_application_document,
    nursing_workflow_tools,
    professional_dashboard,
    public_medical_board_register_search,
    public_nursing_register_search,
    registrar_dashboard,
    reject_application,
    review_application_checklist_item,
    upload_professional_media,
    verify_application_payment_view,
)

urlpatterns = [
    # API endpoints
    path('api/', include(('apps.workforce.api_urls', 'workforce_legacy_api'), namespace='workforce_legacy_api')),

    # Import data
    path('import/', ImportDataView.as_view(), name='import_data'),

    # Public registration
    path('register/', PublicRegistrationView.as_view(), name='public_register'),
    path('register/forms/<str:form_code>/', PublicRegistrationView.as_view(), name='public_form_code_register'),
    path('register/medical-board/', PublicRegistrationView.as_view(), name='medical_board_register'),
    path('register/medical-board/<str:form_code>/', PublicRegistrationView.as_view(), name='medical_board_form_register'),
    path('register/nursing/provisional/', PublicRegistrationView.as_view(), name='public_nurse_provisional_register'),
    path('register/nursing/full-license/', PublicRegistrationView.as_view(), name='public_nurse_full_license'),
    path('register/nursing/renewal/', PublicRegistrationView.as_view(), name='public_nurse_renewal'),
    path('register/nursing/', PublicRegistrationView.as_view(), name='public_nurse_register'),
    path('register/chw/', PublicRegistrationView.as_view(), name='public_chw_register'),
    path('register/doctor/', PublicRegistrationView.as_view(), name='public_doctor_register'),
    path('register/graduand/', PublicRegistrationView.as_view(), name='public_graduand_register'),
    path('register/student/', PublicRegistrationView.as_view(), name='public_student_register'),
    path('register/nurse-aide/', PublicRegistrationView.as_view(), name='public_nurse_aide_register'),

    # Professional details
    path('professional/<int:pk>/', ProfessionalDetailView.as_view(), name='professional_detail'),
    path('professional/<int:pk>/media/', upload_professional_media, name='professional_media_upload'),
    path('application/<int:pk>/', ApplicationDetailView.as_view(), name='application_detail'),
    path('application/<int:pk>/edit/', ApplicationUpdateView.as_view(), name='application_update'),
    path('application/<int:pk>/checklist/generate/', generate_application_checklist_view, name='application_generate_checklist'),
    path('application/<int:pk>/checklist/<int:item_id>/review/', review_application_checklist_item, name='application_review_checklist_item'),
    path('application/<int:pk>/payment/verify/', verify_application_payment_view, name='application_verify_payment'),
    path('application/<int:pk>/supervisor/assign/', create_supervisor_assignment_view, name='application_supervisor_assign'),
    path('application/<int:pk>/issue-document/', issue_application_document, name='application_issue_document'),
    path('supervisor-assignment/<int:assignment_id>/complete/', complete_supervisor_assignment_view, name='supervisor_assignment_complete'),

    # Dashboards
    path('professional-dashboard/', professional_dashboard, name='professional_dashboard'),
    path('professional/profile-updates/', professional_profile_update_request, name='professional_profile_update_request'),
    path('professional/profile-updates/queue/', professional_profile_update_queue, name='professional_profile_update_queue'),
    path('professional/profile-updates/<int:pk>/review/', review_professional_profile_update_request, name='review_professional_profile_update_request'),
    path('admin-dashboard/', admin_dashboard, name='legacy_admin_dashboard'),
    path('registrar-dashboard/', registrar_dashboard, name='legacy_registrar_dashboard'),

    # Approval
    path('approve/<int:pk>/', approve_application, name='approve_application'),
    path('reject/<int:pk>/', reject_application, name='reject_application'),
    path('nursing/workflow-tools/', nursing_workflow_tools, name='nursing_workflow_tools'),
    path('nursing/deceased/<int:pk>/approve/', approve_deceased_notification_view, name='approve_deceased_notification'),
    path('public/medical-board/register/search/', public_medical_board_register_search, name='public_medical_board_register_search'),
    path('public/nursing-council/register/search/', public_nursing_register_search, name='public_nursing_register_search'),
]
