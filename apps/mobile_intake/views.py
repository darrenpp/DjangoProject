from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import MobileDevice, MobileFormSchema, MobileLocalAccountRequest, MobileSubmission
from .permissions import (
    IsMobileApiUser,
    can_decide_mobile_submission,
    can_review_mobile_intake,
    can_use_mobile_api,
    user_mobile_office_scopes,
)
from .serializers import (
    DuplicateCheckSerializer,
    MobileAccountRegistrationSerializer,
    MobileLoginSerializer,
    MobileSubmissionSerializer,
)
from .services.accounts import get_or_create_device, mobile_capabilities, primary_office_scope
from .services.attachments import receive_attachment
from .services.audit import log_audit, log_security_event, log_sync_event
from .services.bootstrap import bootstrap_payload, enabled_forms_for_user, mobile_lookups_for_user
from .services.duplicate_check import duplicate_check
from .services.promotion import link_attachments_to_repository, promote_submission
from .services.review import (
    accept_submission,
    mark_superseded,
    reject_submission,
    request_correction,
    run_duplicate_check,
    run_validation,
    visible_submissions_for_user,
)
from .services.sync import receive_submission, status_payload_for_user


class MobileLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MobileLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = authenticate(request, username=data["username"], password=data["password"])
        if not user:
            log_security_event("MOBILE_LOGIN_FAILED", request=request, username=data["username"], details={"reason": "bad_credentials"})
            return Response({"detail": "Authentication failed.", "code": "AUTH_FAILED"}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.is_active:
            log_security_event("MOBILE_LOGIN_FAILED", request=request, user=user, details={"reason": "disabled_user"})
            return Response({"detail": "User is disabled.", "code": "AUTH_FAILED"}, status=status.HTTP_403_FORBIDDEN)
        if not can_use_mobile_api(user):
            log_security_event("ACCESS_DENIED", request=request, user=user, details={"reason": "mobile_permission_denied"})
            return Response({"detail": "Account is not approved for mobile intake.", "code": "ACCOUNT_NOT_APPROVED"}, status=status.HTTP_403_FORBIDDEN)

        device = get_or_create_device(
            data.get("device_id"),
            device_name=data.get("device_name", ""),
            platform=data.get("platform", "android"),
            app_version=data.get("app_version", ""),
            user=user,
        )
        refresh = RefreshToken.for_user(user)
        log_security_event("MOBILE_LOGIN_SUCCESS", request=request, user=user, details={"device_uuid": getattr(device, "device_uuid", "")})
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.pk,
                "username": user.username,
                "role": user.role,
                "office_scope": primary_office_scope(user),
                "operational_approved": bool(getattr(user, "operations_approved", False) or getattr(user, "role_approved", False)),
            },
            "mobile_capabilities": mobile_capabilities(user),
        })


class BootstrapView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def get(self, request):
        log_security_event("MOBILE_BOOTSTRAP_REQUEST", request=request, user=request.user)
        return Response(bootstrap_payload(request.user))


class FormsView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def get(self, request):
        return Response({"enabled_forms": enabled_forms_for_user(request.user)})


class LookupsView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def get(self, request):
        return Response({"lookups": mobile_lookups_for_user(request.user)})


class DuplicateCheckView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def post(self, request):
        serializer = DuplicateCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["office_scope"] not in user_mobile_office_scopes(request.user):
            return Response({"detail": "Office scope denied.", "code": "OFFICE_SCOPE_DENIED"}, status=status.HTTP_403_FORBIDDEN)
        result = duplicate_check(data["office_scope"], data["form_code"], data)
        log_audit("MOBILE_DUPLICATE_CHECK_RUN", None, request=request, actor=request.user, new_values=result)
        return Response(result)


class SubmissionCreateView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def post(self, request):
        serializer = MobileSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission, errors, idempotent = receive_submission(request.user, serializer.validated_data, request=request)
        if errors:
            return Response({"detail": "Submission failed validation.", "errors": errors, "code": "VALIDATION_FAILED"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "server_submission_id": str(submission.submission_uuid),
            "status": submission.status,
            "validation_status": "FAILED" if submission.validation_errors else "PASSED",
            "next_action": "UPLOAD_ATTACHMENTS" if not submission.attachments.exists() else "WAIT_FOR_REVIEW",
            "idempotent": idempotent,
        }, status=status.HTTP_200_OK if idempotent else status.HTTP_201_CREATED)


class AttachmentUploadView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, submission_uuid):
        submission = get_object_or_404(MobileSubmission, submission_uuid=submission_uuid)
        if submission.office_scope not in user_mobile_office_scopes(request.user):
            return Response({"detail": "Office scope denied.", "code": "OFFICE_SCOPE_DENIED"}, status=status.HTTP_403_FORBIDDEN)
        uploaded_file = request.FILES.get("file")
        local_attachment_uuid = request.data.get("local_attachment_uuid") or request.data.get("attachment_id")
        document_type = request.data.get("document_type") or request.data.get("document_code") or "supporting_document"
        if not uploaded_file or not local_attachment_uuid:
            return Response({"detail": "file and local_attachment_uuid are required.", "code": "VALIDATION_FAILED"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            attachment, duplicate_count = receive_attachment(
                submission,
                local_attachment_uuid=local_attachment_uuid,
                uploaded_file=uploaded_file,
                document_type=document_type,
                request=request,
            )
        except ValidationError as exc:
            message = "; ".join(exc.messages)
            code = "ATTACHMENT_TYPE_NOT_ALLOWED" if "type" in message.lower() else "ATTACHMENT_TOO_LARGE"
            return Response({"detail": message, "code": code}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "server_attachment_id": str(attachment.pk),
            "status": attachment.upload_status,
            "sha256_checksum": attachment.sha256_checksum,
            "duplicate_checksum_count": duplicate_count,
            "message": "Attachment received.",
        }, status=status.HTTP_201_CREATED)


class SubmissionStatusView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def get(self, request):
        since = parse_datetime(request.query_params.get("since", "")) if request.query_params.get("since") else None
        submissions = status_payload_for_user(request.user, device_id=request.query_params.get("device_id", ""), since=since)
        account_queryset = MobileLocalAccountRequest.objects.filter(office_scope__in=user_mobile_office_scopes(request.user))
        if request.query_params.get("device_id"):
            account_queryset = account_queryset.filter(device__device_uuid=request.query_params["device_id"])
        return Response({
            "submissions": submissions,
            "local_accounts": [
                {
                    "local_account_uuid": account.local_account_uuid,
                    "status": account.status,
                    "linked_username": account.linked_user.username if account.linked_user else "",
                    "review_note": account.review_note,
                }
                for account in account_queryset.order_by("-updated_at")[:250]
            ],
        })


class MobileAccountRegisterView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def post(self, request):
        serializer = MobileAccountRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["office_scope"] not in user_mobile_office_scopes(request.user):
            return Response({"detail": "Office scope denied.", "code": "OFFICE_SCOPE_DENIED"}, status=status.HTTP_403_FORBIDDEN)
        device = get_or_create_device(data.get("device_id"), user=request.user)
        account, created = MobileLocalAccountRequest.objects.get_or_create(
            local_account_uuid=data["local_account_uuid"],
            defaults={
                "full_name": data["full_name"],
                "username": data["username"],
                "email": data.get("email", ""),
                "phone": data.get("phone", ""),
                "requested_role": data.get("requested_role", "mobile_collector"),
                "requested_cadre": data.get("requested_cadre", ""),
                "office_scope": data["office_scope"],
                "device": device,
            },
        )
        log_sync_event(device=device, user=request.user, event_type="MOBILE_ACCOUNT_REQUESTED", message=account.username, request=request)
        return Response({
            "local_account_uuid": account.local_account_uuid,
            "status": account.status,
            "review_note": account.review_note,
            "created": created,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class MobileAccountStatusView(APIView):
    permission_classes = [IsAuthenticated, IsMobileApiUser]

    def get(self, request):
        queryset = MobileLocalAccountRequest.objects.filter(office_scope__in=user_mobile_office_scopes(request.user))
        if request.query_params.get("local_account_uuid"):
            queryset = queryset.filter(local_account_uuid=request.query_params["local_account_uuid"])
        return Response({
            "local_accounts": [
                {
                    "local_account_uuid": account.local_account_uuid,
                    "status": account.status,
                    "linked_username": account.linked_user.username if account.linked_user else "",
                    "review_note": account.review_note,
                }
                for account in queryset.order_by("-updated_at")[:250]
            ]
        })


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "status": "ok",
            "api_version": "v1",
            "server_time": timezone.localtime().isoformat(),
            "enabled_schema_count": MobileFormSchema.objects.filter(is_enabled=True).count(),
            "pending_submissions": MobileSubmission.objects.exclude(status__in=["PROMOTED", "REJECTED", "SUPERSEDED"]).count(),
        })


@login_required
def mobile_intake_queue(request):
    if not can_review_mobile_intake(request.user):
        raise Http404("Mobile intake queue not available")
    queryset = visible_submissions_for_user(request.user)
    filters = {
        "office_scope": request.GET.get("office_scope", ""),
        "form_code": request.GET.get("form_code", ""),
        "status": request.GET.get("status", ""),
        "duplicate_risk": request.GET.get("duplicate_risk", ""),
        "province": request.GET.get("province", ""),
        "facility": request.GET.get("facility", ""),
        "submitted_by": request.GET.get("submitted_by", ""),
    }
    if filters["office_scope"]:
        queryset = queryset.filter(office_scope=filters["office_scope"])
    if filters["form_code"]:
        queryset = queryset.filter(form_code__iexact=filters["form_code"])
    if filters["status"]:
        queryset = queryset.filter(status=filters["status"])
    if filters["duplicate_risk"]:
        queryset = queryset.filter(duplicate_summary__duplicate_risk=filters["duplicate_risk"])
    if filters["province"]:
        queryset = queryset.filter(normalized_payload_json__province__icontains=filters["province"])
    if filters["facility"]:
        queryset = queryset.filter(normalized_payload_json__facility__icontains=filters["facility"])
    if filters["submitted_by"]:
        queryset = queryset.filter(submitted_by__username__icontains=filters["submitted_by"])
    if request.GET.get("missing_fields"):
        queryset = queryset.exclude(validation_errors=[])
    paginator = Paginator(queryset.prefetch_related("attachments"), int(request.GET.get("per_page") or 25))
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "mobile_intake/queue.html", {
        "page_obj": page_obj,
        "filters": filters,
        "status_choices": MobileSubmission.STATUS_CHOICES,
        "form_codes": MobileFormSchema.objects.filter(is_enabled=True, office_scope__in=user_mobile_office_scopes(request.user)).order_by("form_code").values_list("form_code", flat=True).distinct(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def mobile_intake_detail(request, submission_uuid):
    submission = get_object_or_404(MobileSubmission.objects.select_related("submitted_by", "device", "reviewed_by", "accepted_by"), submission_uuid=submission_uuid)
    if not can_review_mobile_intake(request.user, submission.office_scope):
        raise Http404("Mobile intake submission not available")
    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("note", "").strip()
        try:
            if action == "validate":
                run_validation(submission, request.user, request=request)
                messages.success(request, "Validation refreshed.")
            elif action == "duplicate":
                run_duplicate_check(submission, request.user, request=request)
                messages.success(request, "Duplicate check completed.")
            elif action == "correction":
                request_correction(submission, request.user, note, request=request)
                messages.success(request, "Correction request sent to the Android sync queue.")
            elif action == "reject":
                reject_submission(submission, request.user, note, request=request)
                messages.success(request, "Submission rejected.")
            elif action == "accept":
                accept_submission(submission, request.user, note, request=request)
                messages.success(request, "Submission accepted.")
            elif action == "link_documents":
                if not can_decide_mobile_submission(request.user, submission.office_scope):
                    raise PermissionError("You cannot link repository documents for this submission.")
                link_attachments_to_repository(submission, request.user, request=request)
                messages.success(request, "Attachments linked to the repository.")
            elif action == "promote":
                promote_submission(
                    submission,
                    request.user,
                    note=note,
                    waive_missing=bool(request.POST.get("waive_missing")),
                    waive_duplicate=bool(request.POST.get("waive_duplicate")),
                    request=request,
                )
                messages.success(request, "Submission promoted.")
            elif action == "supersede":
                mark_superseded(submission, request.user, note, request=request)
                messages.success(request, "Submission marked superseded.")
            else:
                messages.error(request, "Unknown mobile intake action.")
        except (PermissionError, ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
        return redirect("mobile_intake_detail", submission_uuid=submission.submission_uuid)
    return render(request, "mobile_intake/detail.html", {
        "submission": submission,
        "payload": submission.normalized_payload_json or submission.payload_json,
        "can_decide": can_decide_mobile_submission(request.user, submission.office_scope),
        "queue_url": reverse("mobile_intake_queue"),
    })


@login_required
def mobile_production_readiness(request):
    if not can_review_mobile_intake(request.user):
        raise Http404("Mobile readiness dashboard not available")
    scopes = user_mobile_office_scopes(request.user)
    submissions = MobileSubmission.objects.filter(office_scope__in=scopes)
    devices = MobileDevice.objects.filter(last_seen_at__gte=timezone.now() - timedelta(days=7))
    return render(request, "mobile_intake/readiness.html", {
        "schema_count": MobileFormSchema.objects.filter(is_enabled=True, office_scope__in=scopes).count(),
        "pending_submissions": submissions.filter(status__in=["RECEIVED", "VALIDATING", "NEEDS_REVIEW", "DUPLICATE_RISK"]).count(),
        "failed_submissions": submissions.filter(status="FAILED").count(),
        "pending_account_requests": MobileLocalAccountRequest.objects.filter(office_scope__in=scopes, status="PENDING").count(),
        "rejected_submissions": submissions.filter(status="REJECTED").count(),
        "needs_correction": submissions.filter(status="NEEDS_CORRECTION").count(),
        "duplicate_risk": submissions.filter(duplicate_summary__duplicate_risk="HIGH").count(),
        "attachment_failures": submissions.filter(attachments__upload_status="FAILED").distinct().count(),
        "schema_mismatch_count": submissions.filter(validation_errors__icontains="schema").count(),
        "devices_seen_7_days": devices.count(),
        "app_versions": devices.exclude(app_version="").values_list("app_version", flat=True).distinct(),
        "health_url": "/api/mobile/v1/health/",
    })
