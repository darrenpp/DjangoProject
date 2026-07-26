from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.common.models import DuplicateReviewQueue
from apps.dashboard.models import Receipt
from apps.documents.models import Document, DocumentFolder
from apps.notifications.models import (
    EnquiryMailboxState,
    EnquiryMessage,
    EnquiryMessageAttachment,
    EnquiryThread,
    Notification,
)
from apps.notifications.views import send_application_status_email
from apps.workforce.models import (
    Application,
    CommunityHealthWorker,
    DataImportBatch,
    MedicalDoctor,
    MissingDataReview,
    NursingProfessional,
    PracticingLicenseRecord,
)


class StaffCommunicationsTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.registrar = user_model.objects.create_user(
            username="registrar.nursing",
            password="testpass123",
            role="registrar",
            department="Nursing Council",
        )
        self.applicant = user_model.objects.create_user(
            username="nurse.user",
            password="testpass123",
            role="nurse",
            email="nurse@example.com",
        )
        self.medical_registrar = user_model.objects.create_user(
            username="registrar.medical",
            password="testpass123",
            role="registrar",
            department="Medical Board",
        )
        self.admin_user = user_model.objects.create_user(
            username="platform.admin",
            password="testpass123",
            role="admin",
            department="Administration",
        )

        self.nursing_professional = NursingProfessional.objects.create(
            first_name="Nursing",
            last_name="Applicant",
            registration_no="NC-1001",
            email="nursing@app.pg",
        )
        self.medical_professional = MedicalDoctor.objects.create(
            first_name="Medical",
            last_name="Doctor",
            registration_no="MD-1001",
            email="medical@app.pg",
        )

        nursing_ct = ContentType.objects.get_for_model(NursingProfessional)
        medical_ct = ContentType.objects.get_for_model(MedicalDoctor)
        Application.objects.create(
            content_type=nursing_ct,
            object_id=self.nursing_professional.id,
            form_code="NC2",
            form_title="Nursing Full Licence",
            status="pending",
        )
        Application.objects.create(
            content_type=medical_ct,
            object_id=self.medical_professional.id,
            form_code="MD1",
            form_title="Medical Registration",
            status="pending",
        )
        self.nursing_application = Application.objects.create(
            content_type=nursing_ct,
            object_id=self.nursing_professional.id,
            form_code="NC3",
            form_title="Nursing Renewal",
            status="approved",
        )
        self.medical_application = Application.objects.create(
            content_type=medical_ct,
            object_id=self.medical_professional.id,
            form_code="MD2",
            form_title="Medical Renewal",
            status="approved",
        )

        Receipt.objects.create(
            user=self.registrar,
            application=self.nursing_application,
            official_receipt_no="NC-REC-100",
            amount="150.00",
            status="completed",
            payment_method="office",
        )
        Receipt.objects.create(
            user=self.medical_registrar,
            application=self.medical_application,
            official_receipt_no="MB-REC-100",
            amount="275.00",
            status="completed",
            payment_method="office",
        )

        nursing_folder = DocumentFolder.objects.create(
            office_scope="nursing",
            name="Nursing Queue",
        )
        medical_folder = DocumentFolder.objects.create(
            office_scope="medical",
            name="Medical Queue",
        )
        Document.objects.create(
            office_scope="nursing",
            title="Nursing Draft Document",
            folder=nursing_folder,
            status="draft",
        )
        Document.objects.create(
            office_scope="medical",
            title="Medical Draft Document",
            folder=medical_folder,
            status="draft",
        )

        EnquiryThread.objects.create(
            subject="Nursing Follow Up",
            office="nursing",
            created_by=self.registrar,
            status="open",
        )
        EnquiryThread.objects.create(
            subject="Medical Follow Up",
            office="medical",
            created_by=self.applicant,
            status="open",
        )

        self.import_batch = DataImportBatch.objects.create(
            source_file_name="duplicate_scope_test.xlsx",
            source_kind="nursing_full_registration_2026",
            status="completed",
        )
        self.medical_import_batch = DataImportBatch.objects.create(
            source_file_name="medical_finance_scope_test.xlsx",
            source_kind="medical_board_workbook",
            status="completed",
        )
        self.nursing_duplicate_record = PracticingLicenseRecord.objects.create(
            batch=self.import_batch,
            record_type="full",
            target_model="midwife",
            source_sheet_name="April 2026",
            source_row=10,
            record_year=2026,
            full_name="Anna Duplicate",
            registration_no="MID-100",
            practitioner_number="LIC-100",
        )
        self.medical_duplicate_record = PracticingLicenseRecord.objects.create(
            batch=self.import_batch,
            record_type="practicing_license",
            target_model="communityhealthworker",
            source_sheet_name="Medical CHW",
            source_row=20,
            record_year=2026,
            full_name="Brian Duplicate",
            registration_no="CHW-100",
            practitioner_number="ML-100",
        )
        self.nursing_duplicate_review = DuplicateReviewQueue.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=self.nursing_duplicate_record.id,
            suspected_duplicate={
                "audit_type": "same_name_same_registration_no_same_year_type",
                "target_model": "midwife",
                "record_type": "full",
                "record_year": 2026,
                "full_name": "Anna Duplicate",
                "identifier_field": "registration_no",
                "identifier_value": "MID-100",
                "member_ids": [self.nursing_duplicate_record.id],
                "member_count": 1,
            },
            similarity_score=1.0,
        )

        PracticingLicenseRecord.objects.create(
            batch=self.import_batch,
            record_type="payment",
            target_model="other",
            source_sheet_name="Nursing Payments",
            source_row=30,
            record_year=2026,
            full_name="Nursing Finance Row",
            payment_date="2026-04-20",
            amount="300.00",
            reference_number="NC-PAY-1",
            payment_method="Imported ATP Payment",
        )
        PracticingLicenseRecord.objects.create(
            batch=self.medical_import_batch,
            record_type="payment",
            target_model="communityhealthworker",
            source_sheet_name="Medical Payments",
            source_row=40,
            record_year=2026,
            full_name="Medical Finance Row",
            payment_date="2026-04-25",
            amount="425.00",
            reference_number="MB-PAY-1",
            payment_method="Imported Medical Payment",
        )
        self.medical_duplicate_review = DuplicateReviewQueue.objects.create(
            content_type=ContentType.objects.get_for_model(PracticingLicenseRecord),
            object_id=self.medical_duplicate_record.id,
            suspected_duplicate={
                "audit_type": "same_name_same_practitioner_no_same_year_type",
                "target_model": "communityhealthworker",
                "record_type": "practicing_license",
                "record_year": 2026,
                "full_name": "Brian Duplicate",
                "identifier_field": "practitioner_number",
                "identifier_value": "ML-100",
                "member_ids": [self.medical_duplicate_record.id],
                "member_count": 1,
            },
            similarity_score=1.0,
        )

    def test_staff_communications_is_scoped_for_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("staff_communications"))

        self.assertEqual(response.status_code, 200)
        summary = response.context["staff_summary"]
        self.assertEqual(summary["pending_application_count"], 1)
        self.assertEqual(summary["document_review_count"], 1)
        self.assertEqual(summary["open_thread_count"], 1)

    def test_profile_shows_staff_queue_panel_for_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inbox, Chat & Review Queue")
        self.assertContains(response, "Open Communications Hub")
        self.assertContains(response, "Statutory Context and Mandate of the PNG Nursing Council")
        self.assertContains(response, "AI Registrar Assistant")
        self.assertContains(response, "Monthly Excel Report")
        self.assertContains(response, "Yearly PDF Report")
        self.assertContains(response, "Minister Brief")

    def test_profile_hides_nursing_regulatory_alignment_for_medical_registrar(self):
        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Statutory Context and Mandate of the PNG Nursing Council")

    def test_medical_registrar_profile_counts_medical_board_missing_reviews(self):
        chw = CommunityHealthWorker.objects.create(
            first_name="Medical",
            last_name="CHW",
            registration_no="CHW-MISSING-1",
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(CommunityHealthWorker),
            object_id=chw.pk,
            full_name="Medical CHW",
            registration_no="CHW-MISSING-1",
            professional_type="Community Health Worker",
            missing_fields=["Email address", "Phone number"],
            missing_count=2,
        )
        MissingDataReview.objects.create(
            content_type=ContentType.objects.get_for_model(NursingProfessional),
            object_id=self.nursing_professional.pk,
            full_name="Nursing Applicant",
            registration_no="NC-1001",
            professional_type="Nursing Professional",
            missing_fields=["Email address"],
            missing_count=1,
        )
        self.client.force_login(self.medical_registrar)

        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["staff_ai_context"]["missing_review_count"], 1)
        self.assertContains(response, "Missing Data Reviews")

    def test_profile_shows_nursing_regulatory_alignment_for_admin(self):
        self.admin_user.is_superuser = True
        self.admin_user.is_staff = True
        self.admin_user.save(update_fields=["is_superuser", "is_staff"])
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Statutory Context and Mandate of the PNG Nursing Council")
        self.assertContains(response, "AI Registrar Assistant")

    def test_profile_hides_staff_ai_controls_for_applicant(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "AI Registrar Assistant")

    def test_staff_communications_redirects_non_staff_user(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("staff_communications"))

        self.assertEqual(response.status_code, 302)

    def test_staff_ai_assistant_is_available_to_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("staff_ai_assistant"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Applicant Screening Queue")
        self.assertContains(response, "Staff AI Chat")
        self.assertContains(response, "Duplicate Review Workflow")

    def test_staff_ai_assistant_redirects_non_staff_user(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("staff_ai_assistant"))

        self.assertEqual(response.status_code, 302)

    def test_helpdesk_redirects_staff_user_to_staff_ai_assistant(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("helpdesk"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("staff_ai_assistant"))

    def test_helpdesk_stays_available_for_applicant(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("helpdesk"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Helpdesk")

    def test_applicant_can_view_unassigned_enquiry_thread(self):
        thread = EnquiryThread.objects.create(
            subject="Applicant Unassigned Enquiry",
            office="nursing",
            created_by=self.applicant,
        )
        self.client.force_login(self.applicant)

        response = self.client.get(reverse("enquiry_thread", args=[thread.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Applicant Unassigned Enquiry")
        self.assertContains(response, "Unassigned")

    def test_mailbox_folders_are_available_to_applicant(self):
        self.client.force_login(self.applicant)

        response = self.client.get(reverse("enquiry_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inbox")
        self.assertContains(response, "Sent Items")
        self.assertContains(response, "Archived")
        self.assertContains(response, "Deleted Items")
        self.assertContains(response, "Conversation History")
        self.assertContains(response, "Notes")

    def test_applicant_navbar_shows_notifications_dropdown(self):
        Notification.objects.create(
            user=self.applicant,
            subject="Profile information required",
            message="Please complete missing registration details.",
        )
        self.client.force_login(self.applicant)

        response = self.client.get(reverse("enquiry_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notifications")
        self.assertContains(response, "Profile information required")
        self.assertContains(response, "View Notification History")
        self.assertContains(response, "data-notification-badge")
        self.assertContains(response, "Open Messages")

    def test_notification_dropdown_mark_read_endpoint_clears_unread_count(self):
        notification = Notification.objects.create(
            user=self.applicant,
            subject="Missing profile fields",
            message="Please update your contact details.",
        )
        self.client.force_login(self.applicant)

        response = self.client.post(
            reverse("notification_mark_read"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "updated": 1, "count": 0})
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

        response = self.client.get(reverse("enquiry_inbox"))
        self.assertNotContains(response, 'class="badge badge-warning navbar-badge" data-notification-badge')
        self.assertContains(response, "Missing profile fields")

    def test_notification_history_marks_notifications_read_for_staff_users(self):
        for user in [self.registrar, self.admin_user]:
            with self.subTest(username=user.username):
                notification = Notification.objects.create(
                    user=user,
                    subject=f"Staff notice for {user.username}",
                    message="Review the current queue.",
                )
                self.client.force_login(user)

                response = self.client.get(reverse("notification_history"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Notification History")
                self.assertContains(response, notification.subject)
                self.assertContains(response, "Current Staff Notices")
                notification.refresh_from_db()
                self.assertIsNotNone(notification.read_at)

    def test_registrar_can_search_individual_recipients_on_message_form(self):
        self.client.force_login(self.registrar)

        response = self.client.get(f"{reverse('enquiry_create')}?recipient_search=Nursing")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create a Message or Enquiry")
        self.assertContains(response, "Nursing Applicant")
        self.assertContains(response, "Platform mailbox and direct email")

    def test_registrar_can_send_platform_message_to_linked_individual_record(self):
        recipient = get_user_model().objects.create_user(
            username="linked.nurse",
            password="testpass123",
            role="nurse",
            email=self.nursing_professional.email,
        )
        content_type = ContentType.objects.get_for_model(self.nursing_professional)
        recipient_reference = f"record:{content_type.pk}:{self.nursing_professional.pk}"
        self.client.force_login(self.registrar)

        response = self.client.post(reverse("enquiry_create"), {
            "recipient": recipient_reference,
            "delivery_channel": "mailbox",
            "subject": "Missing profile information",
            "body": "Please provide your missing profile fields.",
        })

        self.assertEqual(response.status_code, 302)
        thread = EnquiryThread.objects.get(subject="Missing profile information")
        self.assertEqual(thread.recipient_user, recipient)
        self.assertEqual(thread.delivery_channel, "mailbox")
        self.assertEqual(thread.recipient_name, "Nursing Applicant")
        self.assertTrue(EnquiryMessage.objects.filter(thread=thread, sender=self.registrar).exists())
        self.assertTrue(Notification.objects.filter(user=recipient, subject="Missing profile information").exists())

        self.client.force_login(recipient)
        inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertContains(inbox_response, 'class="badge badge-warning navbar-badge" data-notification-badge')
        self.assertContains(inbox_response, "Mailbox messages waiting")
        self.assertContains(inbox_response, "Unread")

        thread_response = self.client.get(reverse("enquiry_thread", args=[thread.pk]))
        self.assertEqual(thread_response.status_code, 200)
        self.assertContains(thread_response, "Please provide your missing profile fields.")
        recipient_state = EnquiryMailboxState.objects.get(user=recipient, thread=thread)
        self.assertIsNotNone(recipient_state.read_at)

        inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertNotContains(inbox_response, 'class="badge badge-warning navbar-badge" data-notification-badge')
        self.assertNotContains(inbox_response, "Mailbox messages waiting")
        self.assertContains(inbox_response, "Read")

        self.client.force_login(self.registrar)
        sent_response = self.client.get(f"{reverse('enquiry_inbox')}?folder=sent")
        self.assertContains(sent_response, "Missing profile information")
        self.assertContains(sent_response, "Opened")

        self.client.force_login(recipient)
        reply_response = self.client.post(reverse("enquiry_thread", args=[thread.pk]), {
            "body": "I have updated the missing fields.",
        })
        self.assertEqual(reply_response.status_code, 302)

        self.client.force_login(self.registrar)
        registrar_inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertContains(registrar_inbox_response, 'class="badge badge-warning navbar-badge" data-notification-badge')
        self.assertContains(registrar_inbox_response, "Unread")

        registrar_thread_response = self.client.get(reverse("enquiry_thread", args=[thread.pk]))
        self.assertEqual(registrar_thread_response.status_code, 200)
        registrar_state = EnquiryMailboxState.objects.get(user=self.registrar, thread=thread)
        self.assertIsNotNone(registrar_state.read_at)

        self.client.force_login(recipient)
        sent_response = self.client.get(f"{reverse('enquiry_inbox')}?folder=sent")
        self.assertContains(sent_response, "Missing profile information")
        self.assertContains(sent_response, "Opened")

    def test_registrar_can_attach_receipt_or_certificate_to_mailbox_message(self):
        recipient = get_user_model().objects.create_user(
            username="linked.attachment.nurse",
            password="testpass123",
            role="nurse",
            email=self.nursing_professional.email,
        )
        content_type = ContentType.objects.get_for_model(self.nursing_professional)
        recipient_reference = f"record:{content_type.pk}:{self.nursing_professional.pk}"
        upload = SimpleUploadedFile(
            "receipt_certificate.pdf",
            b"%PDF-1.4 test receipt and certificate",
            content_type="application/pdf",
        )

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.registrar)
            response = self.client.post(reverse("enquiry_create"), {
                "recipient": recipient_reference,
                "delivery_channel": "mailbox",
                "subject": "Issued receipt and certificate",
                "body": "Please find your receipt and certificate attached.",
                "attachments": upload,
            })

            self.assertEqual(response.status_code, 302)
            thread = EnquiryThread.objects.get(subject="Issued receipt and certificate")
            message = EnquiryMessage.objects.get(thread=thread, sender=self.registrar)
            attachment = EnquiryMessageAttachment.objects.get(message=message)
            self.assertEqual(attachment.original_filename, "receipt_certificate.pdf")
            self.assertEqual(attachment.content_type, "application/pdf")

            self.client.force_login(recipient)
            thread_response = self.client.get(reverse("enquiry_thread", args=[thread.pk]))

            self.assertContains(thread_response, "receipt_certificate.pdf")
            self.assertContains(thread_response, "Please find your receipt and certificate attached.")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_direct_email_message_includes_uploaded_attachment(self):
        content_type = ContentType.objects.get_for_model(self.nursing_professional)
        recipient_reference = f"record:{content_type.pk}:{self.nursing_professional.pk}"
        upload = SimpleUploadedFile(
            "full_license.pdf",
            b"%PDF-1.4 issued full licence",
            content_type="application/pdf",
        )

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.registrar)
            response = self.client.post(reverse("enquiry_create"), {
                "recipient": recipient_reference,
                "delivery_channel": "email",
                "subject": "Issued full licence",
                "body": "Your full licence is attached.",
                "attachments": upload,
            })

            self.assertEqual(response.status_code, 302)
            thread = EnquiryThread.objects.get(subject="Issued full licence")
            self.assertTrue(EnquiryMessageAttachment.objects.filter(message__thread=thread).exists())
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(mail.outbox[0].attachments[0][0], "full_license.pdf")

    def test_office_enquiry_read_by_registrar_clears_bell_and_marks_sender_opened(self):
        self.client.force_login(self.applicant)

        response = self.client.post(reverse("enquiry_create"), {
            "recipient": "office:nursing",
            "office": "nursing",
            "subject": "Registrar read receipt request",
            "body": "Please review this nursing enquiry.",
        })

        self.assertEqual(response.status_code, 302)
        thread = EnquiryThread.objects.get(subject="Registrar read receipt request")
        self.assertTrue(Notification.objects.filter(
            user=self.registrar,
            subject="New mailbox message: Registrar read receipt request",
        ).exists())

        self.client.force_login(self.registrar)
        inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertContains(inbox_response, 'class="badge badge-warning navbar-badge" data-notification-badge')
        self.assertContains(inbox_response, "Inbox messages waiting")
        self.assertContains(inbox_response, "Unread")

        thread_response = self.client.get(reverse("enquiry_thread", args=[thread.pk]))
        self.assertEqual(thread_response.status_code, 200)
        registrar_state = EnquiryMailboxState.objects.get(user=self.registrar, thread=thread)
        self.assertIsNotNone(registrar_state.read_at)

        inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertNotContains(inbox_response, 'class="badge badge-warning navbar-badge" data-notification-badge')
        self.assertNotContains(inbox_response, "Inbox messages waiting")

        self.client.force_login(self.applicant)
        sender_inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertContains(sender_inbox_response, "Registrar read receipt request")
        self.assertContains(sender_inbox_response, "Opened")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_registrar_can_send_direct_email_to_individual_record(self):
        content_type = ContentType.objects.get_for_model(self.nursing_professional)
        recipient_reference = f"record:{content_type.pk}:{self.nursing_professional.pk}"
        self.client.force_login(self.registrar)

        response = self.client.post(reverse("enquiry_create"), {
            "recipient": recipient_reference,
            "delivery_channel": "email",
            "subject": "Direct email follow up",
            "body": "Please email the missing documents.",
        })

        self.assertEqual(response.status_code, 302)
        thread = EnquiryThread.objects.get(subject="Direct email follow up")
        self.assertIsNone(thread.recipient_user)
        self.assertEqual(thread.recipient_email, self.nursing_professional.email)
        self.assertEqual(thread.delivery_channel, "email")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.nursing_professional.email])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_application_status_email_skips_unlinked_application_without_recipient(self):
        content_type = ContentType.objects.get_for_model(NursingProfessional)
        application = Application.objects.create(
            content_type=content_type,
            object_id=999999,
            form_code="NC1",
            status="rejected",
        )

        sent = send_application_status_email(application)

        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_application_status_email_uses_payload_email_when_record_missing(self):
        application = Application.objects.create(
            form_code="NC1",
            status="rejected",
            payload={"email_address": "applicant@example.test"},
        )

        sent = send_application_status_email(application)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["applicant@example.test"])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_registrar_can_reject_application_without_linked_professional(self):
        content_type = ContentType.objects.get_for_model(NursingProfessional)
        application = Application.objects.create(
            content_type=content_type,
            object_id=999999,
            form_code="NC1",
            status="pending",
        )
        self.client.force_login(self.registrar)

        response = self.client.post(reverse("reject_application", args=[application.pk]), {"reason": ""})

        self.assertRedirects(response, reverse("application_detail", args=[application.pk]), fetch_redirect_response=False)
        application.refresh_from_db()
        self.assertEqual(application.status, "rejected")
        self.assertEqual(len(mail.outbox), 0)

    def test_applicant_can_archive_restore_and_delete_mailbox_thread(self):
        thread = EnquiryThread.objects.create(
            subject="Mailbox Folder Test",
            office="nursing",
            created_by=self.applicant,
        )
        self.client.force_login(self.applicant)

        archive_response = self.client.post(
            reverse("enquiry_mailbox_action", args=[thread.pk]),
            {"action": "archive", "next": reverse("enquiry_inbox")},
        )

        self.assertEqual(archive_response.status_code, 302)
        state = EnquiryMailboxState.objects.get(user=self.applicant, thread=thread)
        self.assertEqual(state.folder, "archived")
        inbox_response = self.client.get(reverse("enquiry_inbox"))
        self.assertNotContains(inbox_response, "Mailbox Folder Test")
        archived_response = self.client.get(f"{reverse('enquiry_inbox')}?folder=archived")
        self.assertContains(archived_response, "Mailbox Folder Test")

        restore_response = self.client.post(
            reverse("enquiry_mailbox_action", args=[thread.pk]),
            {"action": "restore", "next": reverse("enquiry_inbox")},
        )
        self.assertEqual(restore_response.status_code, 302)
        state.refresh_from_db()
        self.assertEqual(state.folder, "active")

        delete_response = self.client.post(
            reverse("enquiry_mailbox_action", args=[thread.pk]),
            {"action": "delete", "next": reverse("enquiry_inbox")},
        )
        self.assertEqual(delete_response.status_code, 302)
        state.refresh_from_db()
        self.assertEqual(state.folder, "deleted")
        deleted_response = self.client.get(f"{reverse('enquiry_inbox')}?folder=deleted")
        self.assertContains(deleted_response, "Mailbox Folder Test")

    def test_private_notes_show_thread_in_notes_folder(self):
        thread = EnquiryThread.objects.create(
            subject="Mailbox Notes Test",
            office="nursing",
            created_by=self.applicant,
        )
        self.client.force_login(self.applicant)

        response = self.client.post(
            reverse("enquiry_thread", args=[thread.pk]),
            {"thread_action": "note", "notes": "Follow up with registrar next week."},
        )

        self.assertEqual(response.status_code, 302)
        state = EnquiryMailboxState.objects.get(user=self.applicant, thread=thread)
        self.assertEqual(state.notes, "Follow up with registrar next week.")
        notes_response = self.client.get(f"{reverse('enquiry_inbox')}?folder=notes")
        self.assertContains(notes_response, "Mailbox Notes Test")

    def test_import_page_redirects_non_staff_user(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("import_data"))

        self.assertEqual(response.status_code, 302)

    def test_nursing_regulatory_alignment_page_is_available_to_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("nursing_regulatory_alignment"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Document-To-Database Comparison Summary")

    def test_nursing_regulatory_alignment_page_redirects_medical_registrar(self):
        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("nursing_regulatory_alignment"))

        self.assertEqual(response.status_code, 302)

    def test_nursing_regulatory_alignment_page_is_available_to_system_admin(self):
        self.admin_user.is_superuser = True
        self.admin_user.is_staff = True
        self.admin_user.save(update_fields=["is_superuser", "is_staff"])
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("nursing_regulatory_alignment"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Document-To-Database Comparison Summary")

    def test_duplicate_review_workflow_is_scoped_for_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("duplicate_review_workflow"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anna Duplicate")
        self.assertContains(response, 'data-duplicate-review-datatable="1"')
        self.assertContains(response, "Search duplicate queue:")
        self.assertContains(response, "Show _MENU_ duplicate reviews")
        self.assertContains(response, "pagingType: 'full_numbers'")
        self.assertNotContains(response, 'colspan="6"')
        self.assertNotContains(response, "Brian Duplicate")

    def test_duplicate_review_workflow_is_scoped_for_medical_registrar(self):
        self.client.force_login(self.medical_registrar)
        response = self.client.get(reverse("duplicate_review_workflow"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brian Duplicate")
        self.assertNotContains(response, "Anna Duplicate")

    def test_duplicate_review_update_marks_case_reviewed(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("duplicate_review_workflow"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("duplicate_review_update", args=[self.nursing_duplicate_review.id]),
            {"action": "reviewed", "next": reverse("duplicate_review_workflow")},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 302)
        self.nursing_duplicate_review.refresh_from_db()
        self.assertEqual(self.nursing_duplicate_review.status, "reviewed")
        self.assertEqual(self.nursing_duplicate_review.reviewed_by, self.registrar)

    def test_financial_forecast_is_scoped_for_nursing_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("financial_forecast_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nursing Council")
        self.assertContains(response, "NC-REC-100")
        self.assertNotContains(response, "MB-REC-100")
        self.assertNotContains(response, "MB-PAY-1")

    def test_financial_forecast_export_excel_is_available_to_registrar(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("export_financial_forecast_excel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_helpdesk_api_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("helpdesk_api"),
            data='{"question":"How do I renew?"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_helpdesk_api_accepts_valid_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.get(reverse("helpdesk"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("helpdesk_api"),
            data='{"question":"How do I renew?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response.json())

    def test_staff_ai_chat_accepts_valid_csrf_token_for_registrar(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("staff_ai_assistant"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("staff_ai_chat"),
            data='{"question":"How many pending applications do I need to review?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("title", payload)
        self.assertIn("answer", payload)

    def test_staff_ai_chat_returns_live_midwife_total(self):
        self.client.force_login(self.registrar)
        response = self.client.post(
            reverse("staff_ai_chat"),
            data='{"question":"what is the total for Midwives?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.get(reverse("staff_ai_assistant")).cookies["csrftoken"].value,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Midwives", payload["title"])
        self.assertIn("current total", payload["answer"].lower())

    def test_staff_ai_chat_returns_latest_source_answer(self):
        self.client.force_login(self.registrar)
        response = self.client.post(
            reverse("staff_ai_chat"),
            data='{"question":"Where did the latest data come from?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.client.get(reverse("staff_ai_assistant")).cookies["csrftoken"].value,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Latest Source Import", payload["title"])

    def test_staff_ai_chat_stream_returns_sse_answer(self):
        self.client.force_login(self.registrar)
        csrf_token = self.client.get(reverse("staff_ai_assistant")).cookies["csrftoken"].value

        response = self.client.post(
            reverse("staff_ai_chat_stream"),
            data='{"question":"Where did the latest data come from?"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("event: status", body)
        self.assertIn("event: answer", body)
        self.assertIn("Latest Source Import", body)

    def test_staff_ai_chat_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        response = csrf_client.post(
            reverse("staff_ai_chat"),
            data='{"question":"How many pending applications?"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_requires_csrf_token(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "ok"
        run_mock.return_value.stderr = ""

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"generate_snapshot"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        run_mock.assert_not_called()

    def test_profile_post_without_csrf_redirects_back_cleanly(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)

        response = csrf_client.post(
            reverse("user_profile"),
            {"first_name": "Updated"},
            HTTP_REFERER=reverse("user_profile"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("user_profile"))

    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_accepts_valid_csrf_token_for_registrar(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "snapshot complete"
        run_mock.return_value.stderr = ""

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("user_profile"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"generate_snapshot"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["returncode"], 0)
        run_mock.assert_called_once()

    @patch("apps.dashboard.views.subprocess.Popen")
    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_runs_audit_in_background(self, run_mock, popen_mock):
        popen_mock.return_value.pid = 4321

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.registrar)
        csrf_client.get(reverse("user_profile"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"audit_missing_data"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["background"])
        self.assertEqual(payload["pid"], 4321)
        run_mock.assert_not_called()
        popen_mock.assert_called_once()

    @patch("apps.dashboard.views.subprocess.run")
    def test_execute_management_command_rejects_non_staff_even_with_csrf(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = "ok"
        run_mock.return_value.stderr = ""

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.applicant)
        csrf_client.get(reverse("user_profile"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("execute_management_command"),
            data='{"command":"generate_snapshot"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 403)
        run_mock.assert_not_called()
