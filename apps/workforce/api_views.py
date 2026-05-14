from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import (
    Application,
    ApplicationFormResponse,
    AuditLog,
    Cadre,
    CommunityHealthWorker,
    DocumentType,
    DynamicFormDefinition,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    ProfessionalDocument,
    ProfessionalPhoto,
    TrainingInstitution,
)
from .serializers import StaffSerializer
from apps.documents.models import Document, DocumentVersion
from apps.dashboard.access import (
    MEDICAL_BOARD_FORM_CODES,
    can_access_application_record,
    can_access_professional_record,
    can_manage_regulatory_operations,
    is_medical_board_user,
    is_medical_board_staff,
    is_nursing_council_user,
    is_nursing_council_staff,
)
from apps.workforce.services.nursing_council_workflows import (
    build_nursing_workflow_rows,
    get_nursing_pathways,
    search_public_nursing_register,
)


MOBILE_NURSING_FORM_CODES = {
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "G6",
    "G7",
    "NC1",
    "NC2",
    "NC3",
    "NC4",
    "NC5",
    "NC6",
    "NC7",
    "NC8",
    "NC9",
    "NC10",
    "NC11",
}
MOBILE_MEDICAL_FORM_CODES = set(MEDICAL_BOARD_FORM_CODES)
MOBILE_TARGET_MODELS = {
    "medical": {"medicaldoctor", "communityhealthworker", "facility", "traininginstitution", "alliedhealth", "other", ""},
    "nursing": {"nursingprofessional", "midwife", "nurseaide", "healthstudent", "graduand", "other", ""},
}
MOBILE_FORM_DEFAULTS = {
    "MD1": ("medical_board", "medical_doctor"),
    "MD2": ("medical_board", "medical_renewal"),
    "CHW1": ("medical_board", "community_health_worker"),
    "MBSP": ("medical_board", "medical_specialist"),
    "MBRN": ("medical_board", "medical_renewal"),
    "MBAC": ("medical_facility", "medical_facility"),
    "MBPF": ("medical_facility", "medical_facility"),
    "MBTC": ("medical_training", "medical_training_facility"),
    "G1": ("local_nursing_graduate", "nursing_graduand"),
    "G2": ("local_nursing_graduate", "nursing_graduand"),
    "G3": ("local_nursing_graduate", "nursing_graduand"),
    "G4": ("local_nursing_graduate", "nursing"),
    "G5": ("local_midwifery_graduate", "midwifery"),
    "G6": ("local_midwifery_graduate", "midwifery_graduand"),
    "G7": ("local_midwifery_graduate", "midwifery_graduand"),
    "NC1": ("local_nursing_graduate", "nursing"),
    "NC2": ("other", "nursing"),
    "NC3": ("other", "nursing"),
    "NC4": ("local_nursing_graduate", "nursing"),
    "NC5": ("overseas_nurse", "overseas"),
    "NC6": ("other", "nursing"),
    "NC7": ("other", "midwifery"),
    "NC8": ("overseas_nurse", "temporary"),
    "NC9": ("overseas_nurse", "temporary"),
    "NC10": ("other", "child_nursing"),
    "NC11": ("special_case", "double_major"),
}


def _is_active_mobile_sync_user(user):
    return (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and can_manage_regulatory_operations(user)
    )


def _normalise_office_scope(value):
    scope = str(value or "").strip().lower().replace("-", "_")
    if scope in {"medical", "medical_board", "mb"}:
        return "medical"
    if scope in {"nursing", "nursing_council", "nc"}:
        return "nursing"
    return ""


def _assigned_mobile_scopes(user):
    if not _is_active_mobile_sync_user(user):
        return set()
    if getattr(user, "role", "") == "admin":
        return {"medical", "nursing"}
    scopes = set()
    if is_medical_board_staff(user):
        scopes.add("medical")
    if is_nursing_council_staff(user):
        scopes.add("nursing")
    return scopes


def _mobile_scope_error(user, requested_scope=""):
    assigned_scopes = _assigned_mobile_scopes(user)
    if not assigned_scopes:
        return "", Response(
            {"detail": "Mobile sync is restricted to approved registrar or operations staff."},
            status=status.HTTP_403_FORBIDDEN,
        )
    requested = _normalise_office_scope(requested_scope)
    if requested:
        if requested not in assigned_scopes:
            return "", Response(
                {"detail": f"Your account cannot submit {requested} mobile records."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return requested, None
    if len(assigned_scopes) == 1:
        return next(iter(assigned_scopes)), None
    return "", Response(
        {"detail": "office_scope is required for accounts assigned to more than one office."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _mobile_form_codes_for_scope(scope):
    if scope == "medical":
        return MOBILE_MEDICAL_FORM_CODES
    if scope == "nursing":
        return MOBILE_NURSING_FORM_CODES
    if scope == "all":
        return MOBILE_MEDICAL_FORM_CODES | MOBILE_NURSING_FORM_CODES
    return set()


def _validate_mobile_form(scope, form_code):
    code = str(form_code or "").strip().upper()
    if not code:
        return "", Response({"detail": "form_code is required."}, status=status.HTTP_400_BAD_REQUEST)
    if code not in _mobile_form_codes_for_scope(scope):
        return "", Response(
            {"detail": f"{code} is not allowed for the {scope} office."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return code, None


def _validate_mobile_target(scope, target_model):
    target = str(target_model or "").strip().lower()
    if target == "healthstudent":
        target = "healthstudent"
    if target == "graduand":
        target = "healthstudent"
    if target not in MOBILE_TARGET_MODELS.get(scope, set()):
        return "", Response(
            {"detail": f"{target_model} is not a valid mobile target for the {scope} office."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return target, None


def _document_type_queryset_for_scope(scope):
    queryset = DocumentType.objects.all()
    medical_filter = (
        Q(description__icontains="Medical Board")
        | Q(name__icontains="Medical Board")
        | Q(documentrequirement__pathway__regulatory_body__name__icontains="Medical Board")
        | Q(documentrequirement__pathway__regulatory_body__code__icontains="medical")
    )
    nursing_filter = (
        Q(description__icontains="Nursing Council")
        | Q(name__icontains="Nursing Council")
        | Q(documentrequirement__pathway__regulatory_body__name__icontains="Nursing Council")
        | Q(documentrequirement__pathway__regulatory_body__code__icontains="nursing")
    )
    if scope == "medical":
        return queryset.filter(medical_filter).exclude(nursing_filter).distinct()
    if scope == "nursing":
        return queryset.filter(nursing_filter).exclude(medical_filter).distinct()
    return queryset


def _training_institution_queryset_for_scope(scope):
    queryset = TrainingInstitution.objects.filter(is_active=True)
    nursing_terms = Q(name__icontains="nursing") | Q(name__icontains="midwife") | Q(type__icontains="nursing")
    if scope == "medical":
        return queryset.exclude(nursing_terms)
    return queryset


def _serialise_form_definitions(form_codes):
    definitions = DynamicFormDefinition.objects.filter(active=True, form_code__in=form_codes).order_by("form_code", "-version")
    seen = set()
    rows = []
    for definition in definitions:
        if definition.form_code in seen:
            continue
        seen.add(definition.form_code)
        rows.append({
            "form_code": definition.form_code,
            "form_name": definition.form_name,
            "version": definition.version,
            "sections": definition.sections,
            "fields": definition.fields,
            "required_documents": definition.required_documents,
            "validation_rules": definition.validation_rules,
        })
    return rows


def _application_for_client_record(client_record_id):
    if not client_record_id:
        return None
    return (
        Application.objects.filter(payload__client_record_id=client_record_id).first()
        or Application.objects.filter(payload__mobile__client_record_id=client_record_id).first()
    )


def _audit_mobile_sync(action, application, request, values):
    return AuditLog.objects.create(
        actor=request.user,
        action=action,
        entity_type="Application",
        entity_id=str(application.pk),
        new_values_json=values,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _duplicate_candidate_models(scope, target_model=""):
    target = str(target_model or "").strip().lower()
    if target == "graduand":
        target = "healthstudent"
    medical_models = {
        "medicaldoctor": [MedicalDoctor],
        "communityhealthworker": [CommunityHealthWorker],
    }
    nursing_models = {
        "nursingprofessional": [NursingProfessional],
        "midwife": [Midwife],
        "nurseaide": [NurseAide],
        "healthstudent": [HealthStudent],
    }
    if scope == "medical":
        return medical_models.get(target) or [MedicalDoctor, CommunityHealthWorker]
    if scope == "nursing":
        return nursing_models.get(target) or [NursingProfessional, Midwife, NurseAide, HealthStudent]
    return []


def _duplicate_score(record, *, registration_no, email, first_name, last_name, date_of_birth, primary_phone):
    if registration_no and registration_no.lower() in {
        str(getattr(record, "registration_no", "") or "").lower(),
        str(getattr(record, "registration_number", "") or "").lower(),
    }:
        return 0.98
    if email and email.lower() == str(getattr(record, "email", "") or "").lower():
        return 0.9
    same_name = (
        first_name
        and last_name
        and first_name.lower() == str(getattr(record, "first_name", "") or "").lower()
        and last_name.lower() == str(getattr(record, "last_name", "") or "").lower()
    )
    if same_name and date_of_birth and str(getattr(record, "date_of_birth", "") or "") == str(date_of_birth):
        return 0.86
    if same_name:
        return 0.65
    if primary_phone and primary_phone == str(getattr(record, "primary_phone", "") or ""):
        return 0.55
    return 0.4


@api_view(["GET"])
@authentication_classes([SessionAuthentication, JWTAuthentication])
@permission_classes([IsAuthenticated])
def mobile_bootstrap(request):
    assigned_scopes = _assigned_mobile_scopes(request.user)
    if not assigned_scopes:
        return Response(
            {"detail": "Mobile sync is restricted to approved registrar or operations staff."},
            status=status.HTTP_403_FORBIDDEN,
        )
    requested_scope = _normalise_office_scope(request.query_params.get("office_scope"))
    if requested_scope:
        if requested_scope not in assigned_scopes:
            return Response({"detail": f"Your account cannot access {requested_scope} mobile lookups."}, status=status.HTTP_403_FORBIDDEN)
        scope = requested_scope
    else:
        scope = next(iter(assigned_scopes)) if len(assigned_scopes) == 1 else "all"

    form_codes = sorted(_mobile_form_codes_for_scope(scope))
    cadre_categories = {"medical", "chw"} if scope == "medical" else {"nursing", "midwifery"} if scope == "nursing" else {"medical", "chw", "nursing", "midwifery"}
    location_rows = Location.objects.exclude(province="").order_by("province", "district").values("province", "district").distinct()[:1000]
    institution_rows = _training_institution_queryset_for_scope(scope).order_by("name").values("id", "name", "type")[:500]
    facility_rows = Facility.objects.order_by("name").values("id", "name", "type", "ownership", "level")[:500]
    document_rows = _document_type_queryset_for_scope(scope).order_by("name").values("id", "name", "description", "is_required")[:300]

    return Response({
        "server_time": timezone.now().isoformat(),
        "officer": {
            "username": request.user.username,
            "office_scope": scope,
            "department": getattr(request.user, "department", ""),
            "assigned_scopes": sorted(assigned_scopes),
        },
        "enabled_forms": form_codes,
        "form_definitions": _serialise_form_definitions(form_codes),
        "lookups": {
            "provinces": sorted({row["province"] for row in location_rows if row["province"]}),
            "districts": list(location_rows),
            "institutions": list(institution_rows),
            "facilities": list(facility_rows),
            "cadres": list(Cadre.objects.filter(category__in=cadre_categories).order_by("name").values("id", "name", "category")),
            "document_types": list(document_rows),
        },
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication, JWTAuthentication])
@permission_classes([IsAuthenticated])
def mobile_duplicate_check(request):
    scope, error_response = _mobile_scope_error(request.user, request.data.get("office_scope"))
    if error_response:
        return error_response
    form_code, error_response = _validate_mobile_form(scope, request.data.get("form_code"))
    if error_response:
        return error_response

    registration_no = str(request.data.get("registration_no") or request.data.get("registration_number") or "").strip()
    email = str(request.data.get("email") or "").strip()
    first_name = str(request.data.get("first_name") or "").strip()
    last_name = str(request.data.get("last_name") or "").strip()
    date_of_birth = str(request.data.get("date_of_birth") or "").strip()
    primary_phone = str(request.data.get("primary_phone") or request.data.get("phone") or "").strip()

    if not any([registration_no, email, first_name and last_name, primary_phone]):
        return Response({"result": "needs_more_information", "matches": []})

    matches = []
    for model in _duplicate_candidate_models(scope, request.data.get("target_model")):
        query = Q()
        if registration_no:
            query |= Q(registration_no__iexact=registration_no) | Q(registration_number__iexact=registration_no)
        if email:
            query |= Q(email__iexact=email)
        if first_name and last_name:
            query |= Q(first_name__iexact=first_name, last_name__iexact=last_name)
        if primary_phone:
            query |= Q(primary_phone=primary_phone)
        for record in model.objects.filter(query).order_by("-updated_at")[:10]:
            matches.append({
                "model": model.__name__,
                "id": record.pk,
                "display_name": f"{record.first_name} {record.last_name}".strip(),
                "registration_no": record.registration_no or record.registration_number or "",
                "match_score": _duplicate_score(
                    record,
                    registration_no=registration_no,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=date_of_birth,
                    primary_phone=primary_phone,
                ),
            })

    matches = sorted(matches, key=lambda row: row["match_score"], reverse=True)[:10]
    return Response({
        "result": "possible_duplicate" if matches else "new_record",
        "form_code": form_code,
        "matches": matches,
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication, JWTAuthentication])
@permission_classes([IsAuthenticated])
def mobile_sync_batch(request):
    records = request.data.get("records") or []
    if not isinstance(records, list):
        return Response({"detail": "records must be a list."}, status=status.HTTP_400_BAD_REQUEST)

    accepted = []
    rejected = []
    needs_correction = []
    for index, record in enumerate(records):
        client_record_id = str(record.get("client_record_id") or "").strip()
        if not client_record_id:
            needs_correction.append({"index": index, "detail": "client_record_id is required."})
            continue

        scope, error_response = _mobile_scope_error(request.user, record.get("office_scope"))
        if error_response:
            rejected.append({"client_record_id": client_record_id, "detail": error_response.data["detail"]})
            continue

        form_code, error_response = _validate_mobile_form(scope, record.get("form_code"))
        if error_response:
            rejected.append({"client_record_id": client_record_id, "detail": error_response.data["detail"]})
            continue

        target_model, error_response = _validate_mobile_target(scope, record.get("target_model", ""))
        if error_response:
            rejected.append({"client_record_id": client_record_id, "detail": error_response.data["detail"]})
            continue

        existing = _application_for_client_record(client_record_id)
        if existing:
            accepted.append({
                "client_record_id": client_record_id,
                "server_application_id": existing.pk,
                "server_status": existing.status,
                "idempotent": True,
            })
            continue

        default_pathway, default_track = MOBILE_FORM_DEFAULTS.get(form_code, ("other", ""))
        payload = {
            "source": "mobile_data_collection",
            "client_record_id": client_record_id,
            "client_batch_id": request.data.get("client_batch_id", ""),
            "device_id": request.data.get("device_id", ""),
            "app_version": request.data.get("app_version", ""),
            "office_scope": scope,
            "form_code": form_code,
            "target_model": target_model,
            "person": record.get("person") or {},
            "qualification": record.get("qualification") or {},
            "employment": record.get("employment") or {},
            "attachments": record.get("attachments") or [],
            "payload": record.get("payload") or {},
            "mobile": {
                "client_record_id": client_record_id,
                "synced_by": request.user.username,
                "synced_at": timezone.now().isoformat(),
            },
        }

        with transaction.atomic():
            application = Application.objects.create(
                form_code=form_code,
                form_title=record.get("form_title", ""),
                pathway=record.get("pathway") or default_pathway,
                profession_track=record.get("profession_track") or default_track,
                status="pending",
                reviewer_notes=f"Synced from Android mobile data collection by {request.user.username}.",
                payload=payload,
            )
            ApplicationFormResponse.objects.update_or_create(
                application=application,
                form_code=form_code,
                form_version=record.get("form_version") or "2026.1",
                defaults={"response_json": payload, "submitted_by": request.user},
            )
            _audit_mobile_sync("MOBILE_RECORD_SYNCED", application, request, {
                "client_record_id": client_record_id,
                "office_scope": scope,
                "form_code": form_code,
                "target_model": target_model,
            })

        accepted.append({
            "client_record_id": client_record_id,
            "server_application_id": application.pk,
            "server_status": application.status,
        })

    return Response({"accepted": accepted, "rejected": rejected, "needs_correction": needs_correction})


@api_view(["POST"])
@authentication_classes([SessionAuthentication, JWTAuthentication])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def mobile_attachment_upload(request):
    client_record_id = str(request.data.get("client_record_id") or "").strip()
    server_application_id = request.data.get("server_application_id")
    attachment_id = str(request.data.get("attachment_id") or "").strip()
    document_code = str(request.data.get("document_code") or "").strip()
    uploaded_file = request.FILES.get("file")

    if not all([client_record_id, server_application_id, attachment_id, document_code, uploaded_file]):
        return Response(
            {"detail": "client_record_id, server_application_id, attachment_id, document_code, and file are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    application = Application.objects.filter(pk=server_application_id).first()
    if not application or not can_access_application_record(request.user, application):
        return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
    if str((application.payload or {}).get("client_record_id") or "") != client_record_id:
        return Response({"detail": "client_record_id does not match the server application."}, status=status.HTTP_400_BAD_REQUEST)

    scope = (application.payload or {}).get("office_scope") or "general"
    document_type = DocumentType.objects.filter(Q(name__icontains=document_code) | Q(description__icontains=document_code)).first()
    app_ct = ContentType.objects.get_for_model(application)
    with transaction.atomic():
        document = Document.objects.create(
            title=f"{application.form_code} {document_code} - {client_record_id}",
            description="Uploaded from Android mobile data collection app.",
            office_scope=scope,
            document_type=document_type,
            status="active",
            is_record=True,
            related_content_type=app_ct,
            related_object_id=application.pk,
            created_by=request.user,
            metadata={
                "source": "mobile_data_collection",
                "client_record_id": client_record_id,
                "attachment_id": attachment_id,
                "document_code": document_code,
                "sha256": request.data.get("sha256", ""),
            },
        )
        version = DocumentVersion.objects.create(
            document=document,
            file=uploaded_file,
            original_filename=getattr(uploaded_file, "name", ""),
            mime_type=getattr(uploaded_file, "content_type", ""),
            uploaded_by=request.user,
        )
        payload = dict(application.payload or {})
        attachments = list(payload.get("mobile_uploaded_attachments") or [])
        attachments.append({
            "attachment_id": attachment_id,
            "document_code": document_code,
            "repository_id": str(document.repository_id),
            "version_id": version.pk,
            "sha256": request.data.get("sha256", ""),
            "uploaded_at": timezone.now().isoformat(),
        })
        payload["mobile_uploaded_attachments"] = attachments
        application.payload = payload
        application.save(update_fields=["payload"])
        _audit_mobile_sync("MOBILE_ATTACHMENT_UPLOADED", application, request, attachments[-1])

    return Response({
        "client_record_id": client_record_id,
        "server_application_id": application.pk,
        "document_id": document.pk,
        "repository_id": str(document.repository_id),
        "version_id": version.pk,
    }, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@authentication_classes([SessionAuthentication, JWTAuthentication])
@permission_classes([IsAuthenticated])
def mobile_sync_status(request):
    assigned_scopes = _assigned_mobile_scopes(request.user)
    if not assigned_scopes:
        return Response(
            {"detail": "Mobile sync is restricted to approved registrar or operations staff."},
            status=status.HTTP_403_FORBIDDEN,
        )
    form_codes = set()
    for scope in assigned_scopes:
        form_codes.update(_mobile_form_codes_for_scope(scope))
    queryset = Application.objects.filter(payload__source="mobile_data_collection", form_code__in=form_codes).order_by("-id")
    client_record_id = request.query_params.get("client_record_id")
    if client_record_id:
        queryset = queryset.filter(payload__client_record_id=client_record_id)
    device_id = request.query_params.get("device_id")
    if device_id:
        queryset = queryset.filter(payload__device_id=device_id)

    rows = []
    for application in queryset[:100]:
        payload = application.payload or {}
        rows.append({
            "client_record_id": payload.get("client_record_id", ""),
            "server_application_id": application.pk,
            "form_code": application.form_code,
            "office_scope": payload.get("office_scope", ""),
            "server_status": application.status,
            "submitted_date": application.submitted_date,
            "approved_date": application.approved_date,
            "reviewer_notes": application.reviewer_notes,
        })
    return Response({"count": len(rows), "results": rows})


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
