from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.contenttypes.models import ContentType

from .models import (
    NursingProfessional, MedicalDoctor, CommunityHealthWorker,
    ProfessionalDocument, ProfessionalPhoto, Application
)
from .serializers import StaffSerializer
from apps.dashboard.access import (
    can_access_professional_record,
    is_medical_board_user,
    is_nursing_council_user,
)
from apps.workforce.services.nursing_council_workflows import (
    build_nursing_workflow_rows,
    get_nursing_pathways,
    search_public_nursing_register,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def nursing_pathways(request):
    rows = []
    for pathway in get_nursing_pathways(public_only=False):
        rows.append({
            "pathway_code": pathway.pathway_code,
            "pathway_name": pathway.pathway_name,
            "primary_form_code": pathway.primary_form_code,
            "checklist_code": pathway.checklist_code,
            "competency_framework_code": pathway.competency_framework_code,
            "requires_payment": pathway.requires_payment,
            "requires_employer": pathway.requires_employer,
            "requires_institution": pathway.requires_institution,
            "requires_supervisor": pathway.requires_supervisor,
            "creates_licence_type": pathway.creates_licence_type,
            "public_visible": pathway.public_visible,
            "active": pathway.active,
        })
    return Response({"count": len(rows), "results": rows})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def nursing_dashboard_operations(request):
    rows = build_nursing_workflow_rows()
    return Response({"count": len(rows), "results": rows})


@api_view(["GET"])
@permission_classes([AllowAny])
def nursing_public_register_search(request):
    rows = search_public_nursing_register(
        query=request.GET.get("name", "") or request.GET.get("q", ""),
        registration_number=request.GET.get("registration_number", ""),
        practitioner_number=request.GET.get("practitioner_number", ""),
        professional_category=request.GET.get("professional_category", ""),
        licence_status=request.GET.get("licence_status", ""),
    )
    return Response({"count": len(rows), "results": rows})


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class StaffViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing medical staff data
    """
    serializer_class = StaffSerializer
    pagination_class = StandardResultsSetPagination
    authentication_classes = [SessionAuthentication, JWTAuthentication]
    permission_classes = [IsAuthenticated]

    PROFESSIONAL_MODELS = {
        "nursingprofessional": NursingProfessional,
        "medicaldoctor": MedicalDoctor,
        "communityhealthworker": CommunityHealthWorker,
    }

    def _base_queryset(self):
        user = self.request.user
        if getattr(user, "role", "") == "admin":
            return (
                list(NursingProfessional.objects.filter(is_active=True))
                + list(MedicalDoctor.objects.filter(is_active=True))
                + list(CommunityHealthWorker.objects.filter(is_active=True))
            )
        if is_medical_board_user(user) and not is_nursing_council_user(user):
            return (
                list(MedicalDoctor.objects.filter(is_active=True))
                + list(CommunityHealthWorker.objects.filter(is_active=True))
            )
        if is_nursing_council_user(user) and not is_medical_board_user(user):
            return list(NursingProfessional.objects.filter(is_active=True))
        return []

    def _encode_staff_id(self, professional):
        return f"{professional._meta.model_name}:{professional.id}"

    def _decode_staff_id(self, value):
        if ":" not in str(value):
            return None, None
        model_name, object_id = str(value).split(":", 1)
        try:
            return self.PROFESSIONAL_MODELS.get(model_name), int(object_id)
        except (TypeError, ValueError):
            return None, None

    def _find_professional(self, value):
        model, object_id = self._decode_staff_id(value)
        if model is None:
            return None
        try:
            professional = model.objects.get(id=object_id, is_active=True)
        except model.DoesNotExist:
            return None
        if not can_access_professional_record(self.request.user, professional):
            return None
        return professional

    def get_queryset(self):
        all_professionals = self._base_queryset()

        # Apply search filter
        search = self.request.query_params.get('search', '')
        if search:
            filtered_professionals = []
            for prof in all_professionals:
                if (search.lower() in prof.first_name.lower() or
                    search.lower() in prof.last_name.lower() or
                    search.lower() in (prof.registration_no or "").lower()):
                    filtered_professionals.append(prof)
            all_professionals = filtered_professionals

        # Apply status filter
        status_filter = self.request.query_params.get('status', '')
        if status_filter:
            if status_filter == 'active':
                all_professionals = [p for p in all_professionals if p.is_active]
            elif status_filter == 'inactive':
                all_professionals = [p for p in all_professionals if not p.is_active]

        # Apply role filter
        role_filter = self.request.query_params.get('role', '')
        if role_filter:
            if role_filter == 'chw':
                all_professionals = [p for p in all_professionals if isinstance(p, CommunityHealthWorker)]
            elif role_filter == 'nurse':
                all_professionals = [p for p in all_professionals if isinstance(p, NursingProfessional)]
            elif role_filter == 'doctor':
                all_professionals = [p for p in all_professionals if isinstance(p, MedicalDoctor)]

        # Convert to dict format for serialization
        result = []
        for prof in all_professionals:
            content_type = ContentType.objects.get_for_model(prof)

            # Get photo
            try:
                photo_obj = ProfessionalPhoto.objects.filter(
                    content_type=content_type,
                    object_id=prof.id,
                    is_primary=True
                ).first()
                photo = self.request.build_absolute_uri(photo_obj.image.url) if photo_obj and photo_obj.image else None
            except:
                photo = None

            # Get document count
            doc_count = ProfessionalDocument.objects.filter(
                content_type=content_type,
                object_id=prof.id
            ).count()

            # Get cadre info
            cadre_name = prof.cadre.name if prof.cadre else 'Staff'
            cadre_category = prof.cadre.category if prof.cadre else 'other'

            result.append({
                'id': self._encode_staff_id(prof),
                'first_name': prof.first_name,
                'last_name': prof.last_name,
                'registration_no': prof.registration_no,
                'applicant_type': getattr(prof, 'applicant_type', 'national'),
                'email': prof.email,
                'primary_phone': prof.primary_phone,
                'cadre': cadre_name,
                'cadre_category': cadre_category,
                'is_active': prof.is_active,
                'photo': photo,
                'document_count': doc_count,
                'location': getattr(prof, 'facility', None).name if hasattr(prof, 'facility') and prof.facility else None,
                'professional_type': prof.__class__.__name__,
                'created_at': prof.created_at,
                'updated_at': prof.updated_at,
            })

        return result

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # Apply pagination
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def documents(self, request, pk=None):
        """Get documents for a specific staff member"""
        try:
            professional = self._find_professional(pk)
            if not professional:
                return Response({'error': 'Professional not found'}, status=status.HTTP_404_NOT_FOUND)

            content_type = ContentType.objects.get_for_model(professional)
            documents = ProfessionalDocument.objects.filter(
                content_type=content_type,
                object_id=professional.id
            ).select_related('document_type')

            docs_data = []
            for doc in documents:
                docs_data.append({
                    'id': doc.id,
                    'document_type': doc.document_type.name if doc.document_type else 'Unknown',
                    'file_url': request.build_absolute_uri(doc.file.url) if doc.file else None,
                    'uploaded_at': doc.uploaded_at,
                })

            return Response(docs_data)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def details(self, request, pk=None):
        """Get detailed information for a specific staff member"""
        try:
            professional = self._find_professional(pk)
            if not professional:
                return Response({'error': 'Professional not found'}, status=status.HTTP_404_NOT_FOUND)

            content_type = ContentType.objects.get_for_model(professional)

            # Get photo
            try:
                photo_obj = ProfessionalPhoto.objects.filter(
                    content_type=content_type,
                    object_id=professional.id,
                    is_primary=True
                ).first()
                photo_url = request.build_absolute_uri(photo_obj.image.url) if photo_obj and photo_obj.image else None
            except:
                photo_url = None

            # Get applications
            applications = Application.objects.filter(
                content_type=content_type,
                object_id=professional.id
            ).order_by('-submitted_date')

            apps_data = []
            for app in applications:
                apps_data.append({
                    'id': app.id,
                    'form_code': app.form_code,
                    'status': app.status,
                    'submitted_date': app.submitted_date,
                    'approved_date': app.approved_date,
                    'reviewer_notes': app.reviewer_notes,
                })

            # Get qualifications
            from .models import Qualification
            qualifications = Qualification.objects.filter(
                content_type=content_type,
                object_id=professional.id
            )

            qual_data = []
            for qual in qualifications:
                qual_data.append({
                    'id': qual.id,
                    'name': qual.qualification_name,
                    'institution': qual.institution.name if qual.institution else None,
                    'completion_year': qual.completion_year,
                    'type': qual.qualification_type,
                })

            data = {
                'id': self._encode_staff_id(professional),
                'first_name': professional.first_name,
                'last_name': professional.last_name,
                'registration_no': professional.registration_no,
                'email': professional.email,
                'primary_phone': professional.primary_phone,
                'gender': professional.gender,
                'date_of_birth': professional.date_of_birth,
                'cadre': professional.cadre.name if professional.cadre else None,
                'is_active': professional.is_active,
                'registration_number': professional.registration_number,
                'photo': photo_url,
                'location': getattr(professional, 'facility', None).name if hasattr(professional, 'facility') and professional.facility else None,
                'professional_type': professional.__class__.__name__,
                'created_at': professional.created_at,
                'updated_at': professional.updated_at,
                'applications': apps_data,
                'qualifications': qual_data,
            }

            # Add type-specific fields
            if isinstance(professional, NursingProfessional):
                data.update({
                    'qualification_level': professional.qualification_level,
                    'license_expiry_date': professional.license_expiry_date,
                    'date_issued': professional.date_issued,
                })
            elif isinstance(professional, MedicalDoctor):
                data.update({
                    'specialty': professional.specialty,
                    'license_expiry_date': professional.license_expiry_date,
                    'date_issued': professional.date_issued,
                })
            elif isinstance(professional, CommunityHealthWorker):
                data.update({
                    'community_id': professional.community_id,
                    'training_level': professional.training_level,
                })

            return Response(data)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
