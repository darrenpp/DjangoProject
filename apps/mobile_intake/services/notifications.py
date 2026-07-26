from apps.accounts.models import User
from apps.mobile_intake.permissions import can_review_mobile_intake
from apps.notifications.models import Notification


def mobile_review_recipients(submission):
    candidates = User.objects.filter(
        is_active=True,
        role__in=["registrar", "reviewer"],
        role_approved=True,
        system_admin_approved=True,
    ).order_by("username")
    return [
        user
        for user in candidates
        if can_review_mobile_intake(user, submission.office_scope)
    ]


def notify_mobile_submission_ready_for_review(submission):
    applicant = submission.applicant_name or submission.registration_number or submission.local_draft_id
    subject = f"Mobile intake review required: {submission.form_code} {str(submission.submission_uuid)[:8]}"
    office_label = {
        "nursing": "Nursing Council",
        "medical": "Medical Board",
        "general": "General Registry",
    }.get(submission.office_scope, submission.office_scope.title())
    message = (
        f"{submission.submitted_by.get_full_name() if submission.submitted_by else 'A mobile collector'} "
        f"synced {submission.form_code} for {applicant or 'an applicant'} to the {office_label} desktop review queue. "
        f"Current status: {submission.get_status_display()}."
    )

    created = 0
    for recipient in mobile_review_recipients(submission):
        _, was_created = Notification.objects.get_or_create(
            user=recipient,
            subject=subject,
            defaults={"message": message},
        )
        if was_created:
            created += 1
    return created
