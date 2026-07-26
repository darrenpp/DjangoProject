from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views
from apps.workforce.views import PublicRegistrationView, public_medical_board_register_search, public_nursing_register_search

SYSTEM_NAME = "The National Department Of Health Regulatory Bodies Nursing Council & The Medical Board Online Workforce System"
admin.site.site_header = SYSTEM_NAME
admin.site.site_title = SYSTEM_NAME
admin.site.index_title = SYSTEM_NAME


def _system_admin_has_permission(request):
    user = request.user
    return (
        user.is_active
        and user.is_staff
        and user.is_superuser
        and getattr(user, "role", "") == "admin"
    )


admin.site.has_permission = _system_admin_has_permission

urlpatterns = [
    # Root path - portal selection home page
    path('', views.home_view, name='portal_home'),
    # keep a backwards-compatible 'home' name for templates/links that still reference it
    path('home/', views.home_view, name='home'),
    path('nursing/forms/', PublicRegistrationView.as_view(), name='nursing_forms_portal'),
    path('public/medical-board/register/search/', public_medical_board_register_search, name='public_medical_board_register_search_root'),
    path('public/nursing-council/register/search/', public_nursing_register_search, name='public_nursing_register_search_root'),

    # API endpoints
    path('api/mobile/v1/', include('apps.mobile_intake.urls')),
    path('api/', include(('apps.workforce.api_urls', 'workforce_api'), namespace='workforce_api')),

    # Admin
    path('admin/', admin.site.urls),

    # Dashboard app
    path('board/nursing/', include('apps.board_portal.urls')),
    path('dashboard/nhwa-workbooks/', include('apps.nhwa_workbooks.urls')),
    path('dashboard/complaints/', include('apps.complaints.urls')),
    path('dashboard/', include('apps.dashboard.urls')),

    # Records (common app)
    path('records/', include('apps.common.record_urls')),

    # Workforce app
    path('workforce/', include('apps.workforce.urls')),

    # Accounts (authentication)
    path('accounts/', include('apps.accounts.urls')),

    # OCR app
    path('ocr/', include('apps.ocr.urls')),

    # Document repository
    path('documents/', include('apps.documents.urls')),

    # Notifications and enquiry messaging
    path('notifications/', include('apps.notifications.urls')),
]

# Media files (dev only)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
