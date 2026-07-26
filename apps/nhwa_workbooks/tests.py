from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    NHWACellEntry,
    NHWACellTemplate,
    NHWAWebSheet,
    NHWAWebWorkbook,
    NHWAWorkbookAuditEvent,
)


class NHWAAlignmentCentreTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            username="nhwa.admin",
            password="StrongPass123!",
            role="admin",
        )
        self.admin_user.is_staff = True
        self.admin_user.is_superuser = True
        self.admin_user.save(update_fields=["is_staff", "is_superuser"])
        self.registrar = user_model.objects.create_user(
            username="nhwa.registrar",
            password="StrongPass123!",
            role="registrar",
            department="Nursing Council",
        )

    def _create_workbook(self, checklist_value="", status="active"):
        workbook = NHWAWebWorkbook.objects.create(
            office_scope="nursing",
            title="Nursing Council NHWA Web Workbook",
            slug="nursing-nhwa-test",
            source_title="PNG NHWA Data Collection Toolkit v2",
            source_version="May 2026",
            reporting_year=2026,
            status=status,
        )
        sheet = NHWAWebSheet.objects.create(
            workbook=workbook,
            source_sheet_name="DATA_QUALITY_CHECKLIST",
            title="Data Quality Checklist",
            sort_order=1,
            max_row=13,
            max_column=7,
            editable=True,
        )
        cell = NHWACellTemplate.objects.create(
            sheet=sheet,
            coordinate="D13",
            row_index=13,
            column_index=4,
            column_letter="D",
            initial_value="",
            is_editable=True,
        )
        NHWACellEntry.objects.create(template=cell, value=checklist_value)
        return workbook

    def test_alignment_centre_is_visible_to_system_admin_and_staff_read_only(self):
        self._create_workbook(checklist_value="Completed")

        self.client.force_login(self.admin_user)
        admin_response = self.client.get(reverse("nhwa_alignment_centre"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "System Admin NHWA Import and Alignment Centre")
        self.assertContains(admin_response, "Bootstrap NHWA Toolkit")
        self.assertContains(admin_response, "Registry / Analytics / Finance / Facilities")

        self.client.force_login(self.registrar)
        registrar_response = self.client.get(reverse("nhwa_alignment_centre"))
        self.assertEqual(registrar_response.status_code, 200)
        self.assertContains(registrar_response, "restricted to System Admin users")

    def test_signoff_lock_requires_completed_data_quality_checklist(self):
        workbook = self._create_workbook(checklist_value="")
        self.client.force_login(self.admin_user)

        blocked_response = self.client.post(reverse("nhwa_alignment_action"), {
            "action": "lock_signoff",
            "scope": "nursing",
        })

        self.assertEqual(blocked_response.status_code, 302)
        workbook.refresh_from_db()
        self.assertEqual(workbook.status, "active")

        entry = NHWACellEntry.objects.get(template__sheet__workbook=workbook)
        entry.value = "Completed"
        entry.save(update_fields=["value", "updated_at"])

        locked_response = self.client.post(reverse("nhwa_alignment_action"), {
            "action": "lock_signoff",
            "scope": "nursing",
        })

        self.assertEqual(locked_response.status_code, 302)
        workbook.refresh_from_db()
        self.assertEqual(workbook.status, "locked")
        self.assertTrue(NHWAWorkbookAuditEvent.objects.filter(workbook=workbook, action="LOCKED").exists())

    def test_submission_pack_requires_locked_workbook_and_exports_zip(self):
        workbook = self._create_workbook(checklist_value="Completed")
        self.client.force_login(self.admin_user)

        blocked_response = self.client.get(reverse("nhwa_submission_pack_export") + "?scope=nursing")
        self.assertEqual(blocked_response.status_code, 302)

        workbook.status = "locked"
        workbook.save(update_fields=["status", "updated_at"])

        export_response = self.client.get(reverse("nhwa_submission_pack_export") + "?scope=nursing")

        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response["Content-Type"], "application/zip")
        self.assertTrue(export_response.content.startswith(b"PK"))

    def test_workbook_detail_renders_controlled_reporting_interface(self):
        workbook = self._create_workbook(checklist_value="Completed")
        council_register = NHWAWebSheet.objects.create(
            workbook=workbook,
            source_sheet_name="T3_COUNCIL_REGISTER",
            title="T3 Council Register",
            sort_order=2,
            max_row=1,
            max_column=2,
            editable=True,
        )
        editable_cell = NHWACellTemplate.objects.create(
            sheet=council_register,
            coordinate="A1",
            row_index=1,
            column_index=1,
            column_letter="A",
            initial_value="Practitioner count",
            fill_rgb="FFF2CC",
            is_editable=True,
        )
        NHWACellEntry.objects.create(template=editable_cell, value="")
        NHWAWorkbookAuditEvent.objects.create(
            workbook=workbook,
            sheet=council_register,
            actor=self.admin_user,
            action="SHEET_SAVED",
            details={"changed_cells": 1},
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("nhwa_workbook_detail", args=[workbook.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NHWA controlled web workbook")
        self.assertContains(response, "Workbook Status")
        self.assertContains(response, "Sheet Outline")
        self.assertContains(response, "Validation Panel")
        self.assertContains(response, "Sign-off And Audit")
        self.assertContains(response, "Data Quality Checklist is complete")
        self.assertContains(response, "Lock For Sign-off")
        self.assertContains(response, "Go Row")
        self.assertContains(response, "Go Cell")
        self.assertContains(response, 'data-coordinate="A1"')
        self.assertContains(response, "Sheet saved")
