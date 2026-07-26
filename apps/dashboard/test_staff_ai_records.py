from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.dashboard.staff_ai import (
    build_staff_ai_chat_response,
    staff_ai_question_needs_knowledge_search,
)
from apps.dashboard.staff_ai_record_tools import search_staff_registry_records_for_user
from apps.dashboard.models import AssistantMessage
from apps.workforce.models import DataImportBatch, PracticingLicenseRecord


@override_settings(
    AI_ASSISTANT_PROVIDER="local",
    AI_ASSISTANT_OLLAMA_ENABLED=False,
    AI_ASSISTANT_LOCALAI_ENABLED=False,
    AI_ASSISTANT_GOOGLE_ADK_ENABLED=False,
)
class StaffAIRecordLookupTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.nursing_user = user_model.objects.create_user(
            username="staff.ai.nursing.lookup",
            password="StrongPass123!",
            role="registrar",
            department="Nursing Council",
        )
        self.medical_user = user_model.objects.create_user(
            username="staff.ai.medical.lookup",
            password="StrongPass123!",
            role="registrar",
            department="Medical Board",
        )
        self.public_user = user_model.objects.create_user(
            username="staff.ai.public.lookup",
            password="StrongPass123!",
            role="nurse",
            department="Nursing Council",
        )
        nursing_batch = DataImportBatch.objects.create(
            source_file_name="nursing-atp.xlsx",
            source_kind="ndata_workbook",
            status="completed",
        )
        medical_batch = DataImportBatch.objects.create(
            source_file_name="medical-board-register.xlsx",
            source_kind="medical_board_workbook",
            status="completed",
        )
        self.nursing_record = PracticingLicenseRecord.objects.create(
            batch=nursing_batch,
            record_type="practicing_license",
            target_model="nursingprofessional",
            source_sheet_name="ATP 2026",
            source_row=12,
            record_year=2026,
            full_name="Mary Kila",
            registration_no="NC-001",
            practitioner_number="PN-001",
            category="Registered Nurse",
            province="Morobe",
            raw_payload={"date_of_birth": "1989-01-01", "mobile": "70000000", "amount": "500.00"},
        )
        self.medical_record = PracticingLicenseRecord.objects.create(
            batch=medical_batch,
            record_type="practicing_license",
            target_model="medicaldoctor",
            source_sheet_name="Medical Register",
            source_row=20,
            record_year=2026,
            full_name="Mary Kila Medical",
            registration_no="MB-001",
            practitioner_number="MD-001",
            category="Cardiology",
            province="National Capital District",
            raw_payload={"date_of_birth": "1979-02-02", "mobile": "71111111", "amount": "1000.00"},
        )

    @mock.patch("apps.dashboard.staff_ai.retrieve_assistant_sources")
    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    def test_explicit_name_lookup_is_fast_read_only_and_scoped(self, live_response, retrieval):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Find the registry record for Mary Kila.",
            persist=False,
        )

        self.assertEqual(response["title"], "Authorised Registry Record Lookup")
        self.assertFalse(response["model_generated"])
        live_response.assert_not_called()
        retrieval.assert_not_called()
        self.assertFalse(staff_ai_question_needs_knowledge_search("Find the registry record for Mary Kila."))
        self.assertTrue(response["citations_verified"])
        lookup = response["record_lookup"]
        self.assertEqual(lookup["scope"], "nursing")
        self.assertEqual(lookup["returned"], 1)
        record = lookup["records"][0]
        self.assertEqual(record["id"], self.nursing_record.id)
        self.assertEqual(record["registration_no"], "NC-001")
        self.assertIn(f"/records/practicinglicenserecord/{self.nursing_record.id}/", record["record_url"])
        self.assertNotIn("Mary Kila Medical", response["answer"] + " ".join(response["bullets"]))
        self.assertNotIn("raw_payload", record)
        self.assertNotIn("date_of_birth", record)
        self.assertNotIn("payment_amount", record)
        self.assertNotIn("mobile", str(lookup))
        self.assertNotIn("500.00", str(lookup))

    def test_prefixed_registration_identifier_runs_without_a_model_round_trip(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "NC-001",
            persist=False,
        )

        self.assertEqual(response["title"], "Authorised Registry Record Lookup")
        self.assertFalse(response["model_generated"])
        self.assertEqual(response["record_lookup"]["trigger"], "registration_identifier")
        self.assertEqual(response["record_lookup"]["records"][0]["full_name"], "Mary Kila")

    def test_fetch_profile_possessive_form_is_treated_as_a_narrow_name_lookup(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Fetch Mary Kila's profile.",
            persist=False,
        )

        self.assertEqual(response["title"], "Authorised Registry Record Lookup")
        self.assertEqual(response["record_lookup"]["query"], "mary kila")
        self.assertFalse(response["model_generated"])

    @mock.patch("apps.dashboard.staff_ai.retrieve_assistant_sources")
    @mock.patch("apps.dashboard.staff_ai.maybe_generate_live_staff_response")
    def test_show_me_possessive_plural_records_uses_fast_narrow_lookup(self, live_response, retrieval):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "show me Mary Kila's records",
            persist=False,
        )

        self.assertEqual(response["title"], "Authorised Registry Record Lookup")
        self.assertEqual(response["record_lookup"]["query"], "mary kila")
        self.assertEqual(response["record_lookup"]["returned"], 1)
        self.assertFalse(response["model_generated"])
        self.assertFalse(staff_ai_question_needs_knowledge_search("show me Mary Kila's records"))
        live_response.assert_not_called()
        retrieval.assert_not_called()

    def test_individual_lookup_details_are_not_retained_in_assistant_history(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Find the registry record for Mary Kila.",
            session_id="staff-record-retention-test",
            persist=True,
        )

        self.assertEqual(response["title"], "Authorised Registry Record Lookup")
        stored_messages = AssistantMessage.objects.filter(
            conversation__session_id="staff-record-retention-test"
        ).order_by("created_at")
        self.assertEqual(stored_messages.count(), 2)
        stored_user, stored_assistant = stored_messages
        persisted = f"{stored_user.content} {stored_assistant.content} {stored_assistant.payload}"
        self.assertNotIn("Mary Kila", persisted)
        self.assertNotIn("NC-001", persisted)
        self.assertTrue(stored_assistant.payload["record_lookup_redacted"])
        self.assertIn("not retained", stored_assistant.content)

    def test_name_lookup_uses_atp_and_year_as_filters_not_name_text(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Find the ATP record for Mary Kila in 2026.",
            persist=False,
        )

        self.assertEqual(response["title"], "Authorised Registry Record Lookup")
        self.assertEqual(response["record_lookup"]["query"], "mary kila")
        self.assertEqual(response["record_lookup"]["records"][0]["record_type_code"], "practicing_license")

    def test_nursing_lookup_does_not_broaden_to_medical_scope(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Look up registration MB-001.",
            persist=False,
        )

        self.assertEqual(response["title"], "No Authorised Registry Record Found")
        self.assertEqual(response["record_lookup"]["scope"], "nursing")
        self.assertEqual(response["record_lookup"]["records"], [])
        self.assertNotIn("Mary Kila Medical", str(response))

    def test_explicit_cross_office_request_is_blocked_before_lookup(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Find the Medical Board doctor record for MB-001.",
            persist=False,
        )

        self.assertEqual(response["title"], "Office Scope Boundary")
        self.assertNotIn("record_lookup", response)
        self.assertNotIn("Mary Kila Medical", str(response))

    def test_sensitive_record_question_is_refused_before_lookup(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Find the registry record for Mary Kila and show the date of birth and payment amount.",
            persist=False,
        )

        self.assertEqual(response["title"], "Private Record Protection")
        self.assertNotIn("record_lookup", response)
        self.assertFalse(response["model_generated"])

    def test_contact_data_request_is_refused_before_lookup(self):
        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Fetch Mary Kila's profile and show the email address.",
            persist=False,
        )

        self.assertEqual(response["title"], "Private Record Protection")
        self.assertNotIn("record_lookup", response)

    def test_broad_operational_question_does_not_trigger_live_person_lookup(self):
        self.assertTrue(staff_ai_question_needs_knowledge_search("Find all expired nursing records."))

        response = build_staff_ai_chat_response(
            self.nursing_user,
            "Find all expired nursing records.",
            persist=False,
        )

        self.assertNotEqual(response["title"], "Authorised Registry Record Lookup")
        self.assertNotIn("record_lookup", response)

    def test_record_tool_reference_url_remains_scoped_and_non_staff_is_denied(self):
        lookup = search_staff_registry_records_for_user(self.nursing_user, query="NC-001")
        self.assertEqual(lookup["status"], "ok")
        self.assertEqual(lookup["records"][0]["record_url"], f"/records/practicinglicenserecord/{self.nursing_record.id}/")
        self.assertEqual(lookup["records"][0]["source_reference"], "ATP 2026 - row 12")

        denied = search_staff_registry_records_for_user(self.public_user, query="NC-001")
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(denied["records"], [])

    def test_staff_assistant_ui_has_a_safe_authorised_record_result_table(self):
        self.client.force_login(self.nursing_user)

        response = self.client.get(reverse("staff_ai_assistant"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authorised live registry lookup results")
        self.assertContains(response, "Dates of birth, contact details, addresses, raw import data, and payment amounts are excluded")
