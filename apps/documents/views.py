from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .access import (
    can_access_document_repository,
    can_download_document,
    can_edit_document,
    can_manage_document_repository,
    can_upload_to_folder,
    can_view_document,
    primary_document_scope_for_user,
    visible_document_scopes_for_user,
)
from .forms import DocumentUpdateForm, DocumentUploadForm, DocumentVersionUploadForm
from .models import Document, DocumentAuditEvent, DocumentVersion
from .services import document_matches_query, duplicate_checksums


def _forbidden(request, message="You do not have permission to use the document repository."):
    return render(request, "documents/search.html", {"forbidden": True, "forbidden_message": message}, status=403)


def _scoped_documents_for_user(user):
    return Document.objects.select_related("folder", "document_type").prefetch_related("versions").filter(
        office_scope__in=visible_document_scopes_for_user(user)
    )


def _audit(document, user, event_type, version=None, details=None):
    DocumentAuditEvent.objects.create(
        document=document,
        version=version,
        user=user if getattr(user, "is_authenticated", False) else None,
        event_type=event_type,
        details=details or {},
    )


@login_required
def repository_home(request):
    return redirect("repository_search")


@login_required
def repository_search(request):
    if not can_access_document_repository(request.user):
        return _forbidden(request)

    query = " ".join(request.GET.get("q", "").strip().split())
    status_filter = request.GET.get("status", "").strip()
    scope_filter = request.GET.get("scope", "").strip()
    visible_scopes = visible_document_scopes_for_user(request.user)

    queryset = _scoped_documents_for_user(request.user).order_by("-updated_at")
    if scope_filter and scope_filter in visible_scopes:
        queryset = queryset.filter(office_scope=scope_filter)
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    documents = list(queryset)
    if query:
        documents = [document for document in documents if document_matches_query(document, query)]

    duplicate_map = duplicate_checksums(documents)
    for document in documents:
        document.current_duplicate_count = 0
        version = document.current_version
        if version and version.checksum in duplicate_map:
            document.current_duplicate_count = len(duplicate_map[version.checksum]) - 1

    paginator = Paginator(documents, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "documents/search.html", {
        "query": query,
        "status_filter": status_filter,
        "scope_filter": scope_filter,
        "scope": ", ".join(scope.title() for scope in visible_scopes),
        "visible_scopes": visible_scopes,
        "page_obj": page_obj,
        "total_results": len(documents),
        "duplicate_groups": len(duplicate_map),
        "can_upload_documents": can_manage_document_repository(request.user),
    })


@login_required
def repository_upload(request):
    if not can_manage_document_repository(request.user):
        return _forbidden(request, "You need approved registrar, reviewer, or System Admin access to upload repository documents.")

    visible_scopes = visible_document_scopes_for_user(request.user)
    initial_scope = primary_document_scope_for_user(request.user) or "general"
    form = DocumentUploadForm(
        request.POST or None,
        request.FILES or None,
        visible_scopes=visible_scopes,
        initial={"office_scope": initial_scope if initial_scope in visible_scopes else visible_scopes[0]},
    )

    if request.method == "POST" and form.is_valid():
        folder = form.cleaned_data.get("folder")
        office_scope = form.cleaned_data["office_scope"]
        if not can_upload_to_folder(request.user, folder=folder, office_scope=office_scope):
            return _forbidden(request, "You do not have upload permission for that repository scope.")

        with transaction.atomic():
            document = Document.objects.create(
                office_scope=office_scope,
                folder=folder,
                document_type=form.cleaned_data.get("document_type"),
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description", ""),
                status=form.cleaned_data["status"],
                metadata=form.cleaned_data.get("metadata_text") or {},
                is_record=form.cleaned_data.get("is_record", False),
                retention_years=form.cleaned_data.get("retention_years"),
                related_content_type=form.cleaned_data.get("linked_content_type"),
                related_object_id=form.cleaned_data.get("related_object_id"),
                created_by=request.user,
            )
            version = DocumentVersion.objects.create(
                document=document,
                version_number=1,
                file=form.cleaned_data["file"],
                notes=form.cleaned_data.get("version_notes", ""),
                uploaded_by=request.user,
            )
            version.refresh_from_db()
            _audit(document, request.user, "created", details={"source": "repository_upload"})
            _audit(document, request.user, "uploaded", version=version, details={"version_number": version.version_number})
            if document.related_content_type_id and document.related_object_id:
                _audit(document, request.user, "linked", details={
                    "content_type": str(document.related_content_type),
                    "object_id": document.related_object_id,
                })

        messages.success(request, "Repository document uploaded and indexed for controlled review.")
        return redirect("repository_detail", pk=document.pk)

    return render(request, "documents/upload.html", {
        "form": form,
        "visible_scopes": visible_scopes,
    })


@login_required
def repository_detail(request, pk):
    document = get_object_or_404(Document.objects.select_related("folder", "document_type"), pk=pk)
    if not can_view_document(request.user, document):
        _audit(document, request.user, "access_denied", details={"action": "detail"})
        return _forbidden(request, "You do not have permission to view this repository document.")

    _audit(document, request.user, "viewed", details={"action": "detail"})
    visible_scopes = visible_document_scopes_for_user(request.user)

    return render(request, "documents/detail.html", {
        "document": document,
        "versions": document.versions.select_related("uploaded_by").all(),
        "audit_events": document.audit_events.select_related("user", "version")[:20],
        "update_form": DocumentUpdateForm(instance=document, visible_scopes=visible_scopes),
        "version_form": DocumentVersionUploadForm(),
        "can_edit_document": can_edit_document(request.user, document),
        "can_download_document": can_download_document(request.user, document),
    })


@login_required
@require_POST
def repository_update_metadata(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if not can_edit_document(request.user, document):
        _audit(document, request.user, "access_denied", details={"action": "metadata_update"})
        return _forbidden(request, "You do not have permission to update this repository document.")

    old_status = document.status
    old_metadata = dict(document.metadata or {})
    form = DocumentUpdateForm(
        request.POST,
        instance=document,
        visible_scopes=visible_document_scopes_for_user(request.user),
    )
    if form.is_valid():
        updated = form.save()
        if old_status != updated.status:
            _audit(updated, request.user, "status_changed", details={"old": old_status, "new": updated.status})
        if old_metadata != (updated.metadata or {}):
            _audit(updated, request.user, "metadata_updated", details={"old": old_metadata, "new": updated.metadata})
        messages.success(request, "Repository document metadata updated.")
    else:
        messages.error(request, "Metadata update failed. Please check the form fields.")
    return redirect("repository_detail", pk=document.pk)


@login_required
@require_POST
def repository_add_version(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if not can_edit_document(request.user, document):
        _audit(document, request.user, "access_denied", details={"action": "version_upload"})
        return _forbidden(request, "You do not have permission to add a document version.")

    form = DocumentVersionUploadForm(request.POST, request.FILES)
    if form.is_valid():
        next_number = (document.versions.aggregate(max_number=Max("version_number"))["max_number"] or 0) + 1
        version = DocumentVersion.objects.create(
            document=document,
            version_number=next_number,
            file=form.cleaned_data["file"],
            notes=form.cleaned_data.get("notes", ""),
            uploaded_by=request.user,
        )
        version.refresh_from_db()
        _audit(document, request.user, "uploaded", version=version, details={"version_number": version.version_number})
        messages.success(request, f"Version {version.version_number} uploaded and marked as current.")
    else:
        messages.error(request, "Version upload failed. Please select a valid file.")
    return redirect("repository_detail", pk=document.pk)


@login_required
def repository_download(request, pk, version_id):
    document = get_object_or_404(Document, pk=pk)
    version = get_object_or_404(DocumentVersion, pk=version_id, document=document)
    if not can_download_document(request.user, document):
        _audit(document, request.user, "access_denied", version=version, details={"action": "download"})
        return _forbidden(request, "You do not have permission to download this repository document.")
    if not version.file:
        raise Http404("Document version file is missing.")

    _audit(document, request.user, "downloaded", version=version, details={"version_number": version.version_number})
    return FileResponse(version.file.open("rb"), as_attachment=True, filename=version.original_filename or version.file.name)
