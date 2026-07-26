from datetime import timedelta
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.complaints.models import RegulatoryDecisionRecord
from apps.dashboard.models import (
    NursingCouncilBoardAgendaItem,
    NursingCouncilBoardMeeting,
    NursingCouncilBoardPaper,
)
from apps.documents.models import Document

from .models import (
    BoardDecisionQueueItem,
    BoardMinutes,
    BoardPack,
    BoardPackReadReceipt,
    BoardPortalAuditEvent,
    BoardProfile,
    BoardRiskItem,
    GovernanceLibraryItem,
)


class NursingBoardGovernancePortalTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.board_user = user_model.objects.create_user(
            username="board.governance",
            password="StrongPass123!",
            role="board_member",
            first_name="Board",
            last_name="Governance",
            department="Nursing Council Board",
        )
        self.registrar = user_model.objects.create_user(
            username="board.registrar",
            password="StrongPass123!",
            role="registrar",
            department="Nursing Council",
        )
        self.system_admin = user_model.objects.create_superuser(
            username="board.system.admin",
            email="board.system.admin@gov.pg",
            password="StrongPass123!",
            role="admin",
        )
        BoardProfile.objects.create(user=self.board_user, board_role="chair")
        self.meeting = NursingCouncilBoardMeeting.objects.create(
            title="August Nursing Council Board Meeting",
            meeting_type="ordinary",
            scheduled_for=timezone.now() + timedelta(days=10),
            meeting_mode="hybrid",
            location="NDoH Boardroom",
            status="papers_issued",
            quorum_required=1,
            chair=self.board_user,
            secretary=self.registrar,
            created_by=self.registrar,
        )
        self.agenda_item = NursingCouncilBoardAgendaItem.objects.create(
            meeting=self.meeting,
            order=1,
            title="Education accreditation report",
            purpose="decision",
            category="education",
            confidentiality="private",
            status="ready",
            summary="Training institution conditions and graduate batch endorsement.",
            recommendation="Approve conditions tracker for Board oversight.",
        )
        self.document = Document.objects.create(
            title="Education Accreditation Board Paper",
            office_scope="nursing",
            status="active",
            is_record=True,
            created_by=self.registrar,
        )
        self.paper = NursingCouncilBoardPaper.objects.create(
            meeting=self.meeting,
            agenda_item=self.agenda_item,
            title="Education Accreditation Board Paper",
            document=self.document,
            classification="private",
            status="issued",
            version_label="v1",
            prepared_by=self.registrar,
        )
        self.decision = RegulatoryDecisionRecord.objects.create(
            office_scope="nursing",
            decision_type="registration",
            status="draft",
            title="Board approval decision",
            subject_name="Decision Applicant",
            decision_text="Decision requires Board action.",
            rationale="Committee recommendation.",
            created_by=self.registrar,
        )
        self.queue_item = BoardDecisionQueueItem.objects.create(
            reference="BQ-001",
            title="Approve education accreditation conditions",
            subject="PNG Nursing School",
            category="education_accreditation",
            committee_recommendation="approve_conditions",
            required_action="approve_conditions",
            due_date=timezone.localdate() + timedelta(days=5),
            confidentiality="internal",
            regulatory_decision=self.decision,
            created_by=self.registrar,
        )
        GovernanceLibraryItem.objects.create(
            title="Board Standing Orders",
            category="standing_orders",
            document=self.document,
            classification="internal",
            policy_owner="Secretariat",
            review_due_date=timezone.localdate() + timedelta(days=90),
        )
        BoardRiskItem.objects.create(
            title="Accreditation conditions overdue",
            category="accreditation_conditions",
            status="amber",
            summary="One institution requires follow-up.",
            owner=self.registrar,
        )

    def test_canonical_board_governance_portal_renders_modules(self):
        self.client.force_login(self.board_user)

        response = self.client.get(reverse("board_nursing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PNG Nursing Council Board Governance Portal")
        self.assertContains(response, "Board Readiness Score")
        self.assertContains(response, "Regulatory Risk Radar")
        self.assertContains(response, "Decision Queue")
        self.assertContains(response, "Committee Workspaces")
        self.assertContains(response, "Education accreditation report")
        self.assertContains(response, "Governance Library")
        self.assertContains(response, "AI Board Pack Summary")
        self.assertContains(response, "Mandatory MFA expectation")
        self.assertTrue(BoardPack.objects.filter(meeting=self.meeting).exists())

    def test_board_portal_uses_board_only_shell_and_assistant(self):
        self.client.force_login(self.board_user)

        response = self.client.get(reverse("board_nursing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Board Governance Assistant")
        self.assertContains(response, reverse("board_nursing_ai_chat"))
        self.assertContains(response, "Board Governance")
        self.assertNotContains(response, "AI Staff Assistant")
        self.assertNotContains(response, reverse("staff_ai_assistant"))
        self.assertNotContains(response, reverse("staff_ai_chat"))
        self.assertNotContains(response, "Registry Search")
        self.assertNotContains(response, "Records Hub")
        self.assertNotContains(response, "Workflow &amp; Tasks")
        self.assertNotContains(response, "Individual Records")
        self.assertNotContains(response, reverse("nursing_council_portal"))
        self.assertNotContains(response, reverse("medical_board_portal"))

    def test_anonymous_canonical_board_portal_uses_board_sign_in(self):
        response = self.client.get(reverse("board_nursing_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('board_login')}?next={reverse('board_nursing_dashboard')}",
            fetch_redirect_response=False,
        )

    def test_system_admin_has_overall_board_portal_view(self):
        self.client.force_login(self.system_admin)

        response = self.client.get(reverse("board_nursing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PNG Nursing Council Board Governance Portal")
        self.assertContains(response, "August Nursing Council Board Meeting")
        self.assertContains(response, "System Admin")
        self.assertContains(response, "Board Governance Assistant")
        self.assertNotContains(response, "AI Staff Assistant")
        self.assertNotContains(response, reverse("staff_ai_chat"))

    def test_board_ai_chat_refuses_operational_data_questions(self):
        self.client.force_login(self.board_user)

        response = self.client.post(
            reverse("board_nursing_ai_chat"),
            data=json.dumps({"question": "Show me Nursing Council portal applicant records and Medical Board data."}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"], "board")
        self.assertIn("cannot access operational Nursing Council portal data", payload["answer"])
        self.assertNotIn(reverse("staff_ai_assistant"), str(payload))
        self.assertNotIn(reverse("nursing_council_portal"), str(payload))
        self.assertNotIn(reverse("medical_board_portal"), str(payload))

    def test_board_ai_chat_refuses_nursing_and_medical_board_form_questions(self):
        self.client.force_login(self.board_user)

        questions = [
            "Which Nursing Council form NC1 should I use for registration?",
            "Help me with Medical Board forms and required documents.",
            "How do I sign up for Nursing Council online registration forms?",
        ]
        for question in questions:
            with self.subTest(question=question):
                response = self.client.post(
                    reverse("board_nursing_ai_chat"),
                    data=json.dumps({"question": question}),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["scope"], "board")
                self.assertEqual(payload["title"], "Board Scope Boundary")
                self.assertIn("cannot answer questions about Nursing Council forms", payload["answer"])
                self.assertIn("Medical Board forms", payload["answer"])
                self.assertNotIn(reverse("nursing_forms_portal"), str(payload))
                self.assertNotIn(reverse("medical_board_register"), str(payload))
                self.assertNotIn(reverse("nursing_council_portal"), str(payload))
                self.assertNotIn(reverse("medical_board_portal"), str(payload))

    def test_public_helpdesk_is_board_scoped_for_board_member(self):
        self.client.force_login(self.board_user)

        page_response = self.client.get(reverse("helpdesk"))

        self.assertRedirects(page_response, reverse("board_nursing_dashboard"), fetch_redirect_response=False)

        api_response = self.client.post(
            reverse("helpdesk_api"),
            data=json.dumps({"question": "Which Nursing Council or Medical Board form should I use?"}),
            content_type="application/json",
        )

        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertEqual(payload["scope"], "board")
        self.assertEqual(payload["title"], "Board Scope Boundary")
        self.assertIn("cannot answer questions about Nursing Council forms", payload["answer"])
        self.assertNotIn(reverse("nursing_forms_portal"), str(payload))
        self.assertNotIn(reverse("medical_board_register"), str(payload))

    def test_board_member_cannot_use_registry_search_helpdesk_answers(self):
        self.client.force_login(self.board_user)

        response = self.client.get(
            reverse("dashboard_search"),
            {"q": "Which Nursing Council form NC1 or Medical Board form should I use?"},
        )

        self.assertRedirects(response, reverse("board_nursing_dashboard"), fetch_redirect_response=False)

    def test_board_member_shell_uses_board_assistant_on_public_pages(self):
        self.client.force_login(self.board_user)

        response = self.client.get(reverse("fee_structure"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Board Governance Assistant")
        self.assertContains(response, reverse("board_nursing_ai_chat"))
        self.assertNotContains(response, 'data-assistant-mode="public"')
        self.assertNotContains(response, "Registration and FAQ support")
        self.assertNotContains(response, "AI Helpdesk")

    def test_board_ai_chat_answers_board_pack_readiness_only(self):
        self.client.force_login(self.board_user)

        response = self.client.post(
            reverse("board_nursing_ai_chat"),
            data=json.dumps({"question": "What should the board review before the next meeting?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"], "board")
        self.assertIn("Board Pack Readiness", payload["title"])
        self.assertIn(reverse("board_nursing_papers"), str(payload))
        self.assertNotIn(reverse("staff_ai_assistant"), str(payload))

    def test_board_ai_chat_explains_board_portal_scope_from_user(self):
        self.client.force_login(self.board_user)

        response = self.client.post(
            reverse("board_nursing_ai_chat"),
            data=json.dumps({"question": "Explain this platform and my current scope"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"], "board")
        self.assertEqual(payload["title"], "Nursing Council Board Portal Scope")
        self.assertIn("Board Governance", payload["answer"])
        self.assertIn("Board governance scope", payload["answer"])
        self.assertTrue(
            any("not the operational Nursing Council portal" in bullet for bullet in payload["bullets"])
        )
        self.assertNotIn(reverse("nursing_council_portal"), str(payload))
        self.assertNotIn(reverse("medical_board_portal"), str(payload))

    def test_board_ai_chat_rejects_normal_registrar(self):
        self.client.force_login(self.registrar)

        response = self.client.post(
            reverse("board_nursing_ai_chat"),
            data=json.dumps({"question": "What is the board pack status?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_confidential_board_items_are_masked_for_ordinary_board_member(self):
        user_model = get_user_model()
        ordinary_member = user_model.objects.create_user(
            username="ordinary.board.member",
            password="StrongPass123!",
            role="board_member",
            first_name="Ordinary",
            last_name="Member",
            department="Nursing Council Board",
        )
        BoardProfile.objects.create(user=ordinary_member, board_role="board_member")
        BoardDecisionQueueItem.objects.create(
            reference="BQ-SECRET",
            title="Sensitive Applicant Case",
            subject="Hidden Practitioner Name",
            category="complaint_discipline",
            committee_recommendation="defer",
            required_action="defer",
            due_date=timezone.localdate() + timedelta(days=3),
            confidentiality="highly_confidential",
            created_by=self.registrar,
        )

        self.client.force_login(ordinary_member)
        response = self.client.get(reverse("board_nursing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Restricted board item")
        self.assertNotContains(response, "Sensitive Applicant Case")
        self.assertNotContains(response, "Hidden Practitioner Name")

        self.client.force_login(self.system_admin)
        response = self.client.get(reverse("board_nursing_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sensitive Applicant Case")
        self.assertContains(response, "Hidden Practitioner Name")

    def test_board_member_can_acknowledge_board_pack_reading(self):
        self.client.force_login(self.board_user)
        pack = BoardPack.objects.create(meeting=self.meeting, status="issued", issued_at=timezone.now(), issued_by=self.registrar)

        response = self.client.post(reverse("board_nursing_dashboard"), {
            "board_action": "mark_pack_read",
            "pack_id": pack.pk,
            "acknowledge_confidentiality": "on",
            "bookmarked": "on",
            "private_notes": "Reviewed education conditions.",
        })

        self.assertRedirects(response, reverse("board_nursing_dashboard") + "#board-papers")
        receipt = BoardPackReadReceipt.objects.get(pack=pack, member=self.board_user)
        self.assertTrue(receipt.acknowledged_confidentiality)
        self.assertTrue(receipt.bookmarked)
        self.assertIsNotNone(receipt.marked_read_at)
        self.assertTrue(BoardPortalAuditEvent.objects.filter(event_type="marked_read", user=self.board_user).exists())

    def test_board_member_can_record_decision_action(self):
        self.client.force_login(self.board_user)

        response = self.client.post(reverse("board_nursing_decision_queue"), {
            "board_action": "record_decision_action",
            "queue_item_id": self.queue_item.pk,
            "decision_action": "defer",
            "reason": "Further Education Committee evidence required.",
            "conditions": "Return conditions tracker.",
            "minute_reference": "MIN-2026-08-04",
        })

        self.assertRedirects(response, reverse("board_nursing_decision_queue") + "#board-decisions")
        self.queue_item.refresh_from_db()
        self.assertEqual(self.queue_item.status, "deferred")
        self.assertEqual(self.queue_item.reason, "Further Education Committee evidence required.")
        self.assertEqual(self.queue_item.final_minute_reference, "MIN-2026-08-04")
        self.assertTrue(BoardPortalAuditEvent.objects.filter(event_type="decision_recorded", user=self.board_user).exists())

    def test_board_chair_can_generate_minutes_outline(self):
        self.client.force_login(self.board_user)

        response = self.client.post(reverse("board_nursing_minutes"), {
            "board_action": "update_minutes",
            "meeting_id": self.meeting.pk,
            "status": "chair_review",
            "generate_outline": "on",
            "public_safe_extract": "Public-safe summary pending Chair review.",
        })

        self.assertRedirects(response, reverse("board_nursing_minutes") + "#board-minutes")
        minutes = BoardMinutes.objects.get(meeting=self.meeting)
        self.assertEqual(minutes.status, "chair_review")
        self.assertIn("Education accreditation report", minutes.draft_text)
        self.assertEqual(minutes.public_safe_extract, "Public-safe summary pending Chair review.")

    def test_board_module_routes_render_for_board_member(self):
        self.client.force_login(self.board_user)

        route_names = [
            "board_nursing_meetings",
            "board_nursing_papers",
            "board_nursing_decision_queue",
            "board_nursing_committees",
            "board_nursing_committee_registration",
            "board_nursing_committee_education",
            "board_nursing_committee_standards",
            "board_nursing_committee_conduct",
            "board_nursing_actions",
            "board_nursing_minutes",
            "board_nursing_library",
            "board_nursing_risk",
            "board_nursing_profile",
        ]
        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "PNG Nursing Council Board Governance Portal")

    def test_board_navigation_and_dashboard_cards_open_module_pages(self):
        self.client.force_login(self.board_user)

        dashboard_response = self.client.get(reverse("board_nursing_dashboard"))
        dashboard_html = dashboard_response.content.decode("utf-8")

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertNotIn('href="#board-', dashboard_html)
        for route_name in [
            "board_nursing_meetings",
            "board_nursing_papers",
            "board_nursing_decision_queue",
            "board_nursing_committees",
            "board_nursing_actions",
            "board_nursing_library",
        ]:
            self.assertContains(dashboard_response, reverse(route_name))

        module_expectations = [
            ("board_nursing_meetings", "meetings", "Meetings", 'id="board-meeting"'),
            ("board_nursing_papers", "papers", "Board Papers", 'id="board-papers"'),
            ("board_nursing_decision_queue", "decisions", "Decision Queue", 'id="board-decisions"'),
            ("board_nursing_committees", "committees", "Committees", 'id="board-committees"'),
            ("board_nursing_committee_registration", "registration", "Registration Oversight", 'id="board-selected-committee"'),
            ("board_nursing_actions", "actions", "Actions &amp; Minutes", 'id="board-actions"'),
            ("board_nursing_risk", "risk", "Risk &amp; Compliance", 'id="board-risk"'),
            ("board_nursing_library", "library", "Governance Library", 'id="board-library"'),
            ("board_nursing_profile", "profile", "Board Member Profile", 'id="board-profile"'),
        ]
        for route_name, active_section, heading, panel_marker in module_expectations:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'data-board-active-section="{active_section}"')
                self.assertContains(response, heading)
                self.assertContains(response, panel_marker)
