from datetime import date
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.competency.models import CompetencyAssessment
from apps.complaints.models import RegulatoryDecisionRecord
from apps.dashboard.models import Receipt
from apps.workforce.models import (
    Application,
    ApplicationChecklistItem,
    ApplicationPathway,
    ApplicationFormResponse,
    ApplicationStatusHistory,
    ApplicantDeclaration,
    AuditLog,
    DataImportBatch,
    DeceasedNotification,
    DeclarationTemplate,
    DocumentRequirement,
    DocumentType,
    DynamicFormDefinition,
    EmployerVerificationRequest,
    EmploymentRecord,
    FeeSchedule,
    HealthStudent,
    Midwife,
    NurseAide,
    NursingProfessional,
    PolicyDocument,
    PracticingLicenseRecord,
    RegulatoryBody,
    SupervisorAssignment,
)
from apps.workforce.services.data_quality import quality_approved_import_records


NURSING_COUNCIL_CODE = "PNG_NURSING_COUNCIL"

FORM_DEFINITIONS = [
    ("NC1", "Application for Provisional Licence to Practice", "PNG_NURSE_GRAD_PROV"),
    ("NC2", "Application for Full Licence to Practice", "PNG_FULL_REG"),
    ("NC3", "Application for Renewal of Licence to Practice", "PNG_RENEWAL"),
    ("NC4", "Overseas Provisional Licence Checklist", "OVERSEAS_PROV"),
    ("NC5", "Overseas Full Registration Application", "OVERSEAS_FULL"),
    ("NC6", "Competency for Full Licence Nursing", "PNG_PROV_TO_FULL"),
    ("NC7", "Competency for Full Licence Midwifery", "PNG_MIDWIFE_GRAD_FULL"),
    ("NC8", "Application for Temporary Licence to Practice", "OVERSEAS_TEMP"),
    ("NC9", "Temporary Licence to Practise Criteria for Overseas Nurses Checklist (Revised 2023)", "OVERSEAS_TEMP"),
    ("NC10", "Competency for Full Licence Child Nursing", "CHILD_HEALTH_SPEC"),
    ("NC11", "Double Major Full Registration Checklist", "DOUBLE_MAJOR"),
    ("G1", "Graduate Nurses Checklist", "PNG_NURSE_GRAD_PROV"),
    ("G2", "List of New Graduate Nurses for Provisional Licence", "PNG_NURSE_GRAD_PROV"),
    ("G3", "Graduate Vitae", "PNG_NURSE_GRAD_PROV"),
    ("G4", "Statement of Competency for Graduate Nurses", "PNG_NURSE_GRAD_PROV"),
    ("G5", "Statement of Competency for Graduate Midwives", "PNG_MIDWIFE_GRAD_FULL"),
    ("G6", "Graduate Midwives Checklist", "PNG_MIDWIFE_GRAD_FULL"),
    ("G7", "List of Graduate Midwives for Licence to Practice", "PNG_MIDWIFE_GRAD_FULL"),
]

NURSING_FORM_CODES = {form_code for form_code, _form_name, _pathway in FORM_DEFINITIONS}

PATHWAY_DEFINITIONS = [
    {
        "pathway_code": "PNG_NURSE_GRAD_PROV",
        "pathway_name": "PNG Graduate Nurse Provisional Licence",
        "applicant_type": "national_graduate",
        "primary_form_code": "NC1",
        "checklist_code": "G1",
        "competency_framework_code": "G4",
        "fee_rule_code": "NATIONAL_PROVISIONAL",
        "requires_payment": True,
        "requires_institution": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "provisional",
        "sort_order": 10,
    },
    {
        "pathway_code": "PNG_MIDWIFE_GRAD_FULL",
        "pathway_name": "PNG Graduate Midwife Full Registration",
        "applicant_type": "national_midwifery_graduate",
        "primary_form_code": "NC2",
        "checklist_code": "G6/G7",
        "competency_framework_code": "G5",
        "fee_rule_code": "NATIONAL_FULL",
        "requires_payment": True,
        "requires_institution": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "full_registration",
        "sort_order": 20,
    },
    {
        "pathway_code": "PNG_FULL_REG",
        "pathway_name": "PNG Full Registration",
        "applicant_type": "national",
        "primary_form_code": "NC2",
        "checklist_code": "registration_checklist",
        "competency_framework_code": "NC6/NC7",
        "fee_rule_code": "NATIONAL_FULL",
        "requires_payment": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "full_registration",
        "sort_order": 30,
    },
    {
        "pathway_code": "PNG_RENEWAL",
        "pathway_name": "PNG Licence Renewal",
        "applicant_type": "national",
        "primary_form_code": "NC3",
        "checklist_code": "renewal_checklist",
        "competency_framework_code": "",
        "fee_rule_code": "NATIONAL_RENEWAL_NURSE",
        "requires_payment": True,
        "requires_employer": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "renewal",
        "sort_order": 40,
    },
    {
        "pathway_code": "PNG_PROV_TO_FULL",
        "pathway_name": "Provisional to Full",
        "applicant_type": "national",
        "primary_form_code": "NC2",
        "checklist_code": "provisional_to_full_checklist",
        "competency_framework_code": "NC6/NC7",
        "fee_rule_code": "NATIONAL_FULL",
        "requires_payment": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "full_registration",
        "sort_order": 50,
    },
    {
        "pathway_code": "OVERSEAS_PROV",
        "pathway_name": "Overseas Provisional",
        "applicant_type": "overseas",
        "primary_form_code": "NC1",
        "checklist_code": "NC4",
        "competency_framework_code": "NC6/NC7",
        "fee_rule_code": "OVERSEAS_PROVISIONAL_FULL",
        "requires_payment": True,
        "requires_employer": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "provisional",
        "sort_order": 60,
    },
    {
        "pathway_code": "OVERSEAS_FULL",
        "pathway_name": "Overseas Full",
        "applicant_type": "overseas",
        "primary_form_code": "NC5",
        "checklist_code": "overseas_full_checklist",
        "competency_framework_code": "NC6/NC7",
        "fee_rule_code": "OVERSEAS_PROVISIONAL_FULL",
        "requires_payment": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "full_registration",
        "sort_order": 70,
    },
    {
        "pathway_code": "OVERSEAS_TEMP",
        "pathway_name": "Temporary Overseas Licence",
        "applicant_type": "overseas",
        "primary_form_code": "NC8",
        "checklist_code": "NC9",
        "competency_framework_code": "",
        "fee_rule_code": "OVERSEAS_TEMPORARY",
        "requires_payment": True,
        "requires_employer": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "temporary",
        "sort_order": 80,
    },
    {
        "pathway_code": "CHILD_HEALTH_SPEC",
        "pathway_name": "Child Health Specialist",
        "applicant_type": "existing_practitioner",
        "primary_form_code": "NC2",
        "checklist_code": "specialist_checklist",
        "competency_framework_code": "NC10",
        "fee_rule_code": "NATIONAL_FULL",
        "requires_payment": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "specialist_recognition",
        "sort_order": 90,
    },
    {
        "pathway_code": "DOUBLE_MAJOR",
        "pathway_name": "Double Major Registration",
        "applicant_type": "existing_practitioner",
        "primary_form_code": "NC2",
        "checklist_code": "NC11",
        "competency_framework_code": "NC6/NC7/NC10",
        "fee_rule_code": "NATIONAL_FULL",
        "requires_payment": True,
        "requires_supervisor": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "double_major",
        "sort_order": 100,
    },
    {
        "pathway_code": "DECEASED_NOTICE",
        "pathway_name": "Deceased Notification",
        "applicant_type": "facility",
        "primary_form_code": "deceased_form",
        "checklist_code": "deceased_checklist",
        "competency_framework_code": "",
        "fee_rule_code": "",
        "requires_payment": False,
        "requires_employer": True,
        "requires_registrar_approval": True,
        "creates_licence_type": "deceased_status_update",
        "public_visible": False,
        "sort_order": 110,
    },
    {
        "pathway_code": "EMPLOYER_VERIFY",
        "pathway_name": "Employer Verification",
        "applicant_type": "employer",
        "primary_form_code": "verification_request",
        "checklist_code": "employer_checklist",
        "competency_framework_code": "",
        "fee_rule_code": "",
        "requires_payment": False,
        "requires_employer": True,
        "requires_registrar_approval": False,
        "creates_licence_type": "",
        "public_visible": False,
        "sort_order": 120,
    },
]

DOCUMENT_REQUIREMENTS = {
    "PNG_NURSE_GRAD_PROV": [
        ("academic_award", "Academic award", True),
        ("character_reference", "Character reference", True),
        ("treasury_receipt", "Treasury receipt", True),
        ("graduate_vitae", "Graduate vitae", True),
        ("competency_statement", "G4 competency statement", True),
    ],
    "PNG_MIDWIFE_GRAD_FULL": [
        ("academic_award", "Academic award", True),
        ("character_reference", "Character reference", True),
        ("treasury_receipt", "Treasury receipt", True),
        ("graduate_vitae", "Graduate vitae", True),
        ("competency_statement", "G5 competency statement", True),
    ],
    "PNG_FULL_REG": [
        ("academic_award", "Academic award", True),
        ("treasury_receipt", "Treasury receipt", True),
        ("competency_statement", "NC6 or NC7 competency", True),
        ("supervisor_recommendation", "Supervisor recommendation", True),
    ],
    "PNG_RENEWAL": [
        ("treasury_receipt", "Treasury receipt", True),
        ("employer_support_letter", "Employment or workplace confirmation", True),
        ("declaration", "Code of ethics and conduct declaration", True),
    ],
    "PNG_PROV_TO_FULL": [
        ("provisional_licence", "Existing provisional licence", True),
        ("treasury_receipt", "Treasury receipt", True),
        ("competency_statement", "NC6 or NC7 competency", True),
        ("supervisor_recommendation", "Supervisor recommendation", True),
    ],
    "OVERSEAS_PROV": [
        ("passport", "Passport", True),
        ("home_registration", "Current licence or registration from home country", True),
        ("good_standing", "Certificate of good standing", True),
        ("academic_transcript", "Academic transcript", True),
        ("cv", "CV", True),
        ("professional_reference", "Professional references", True),
        ("police_clearance", "Police clearance", True),
        ("medical_report", "Medical report", True),
        ("work_contract", "Work contract", True),
        ("english_language_evidence", "English-language evidence", True),
        ("treasury_receipt", "Treasury receipt", True),
    ],
    "OVERSEAS_FULL": [
        ("provisional_licence", "Existing overseas provisional licence", True),
        ("competency_statement", "NC6 or NC7 competency", True),
        ("supervisor_recommendation", "Supervisor recommendation", True),
        ("treasury_receipt", "Treasury receipt", True),
    ],
    "OVERSEAS_TEMP": [
        ("work_contract", "PNG contract or employment letter", True),
        ("temporary_licence_application", "Form NC8 - applicant form for nursing temporary licence", True),
        ("home_registration", "Current registration licence issued by regulatory authority", True),
        ("academic_award", "Institution awards - academic and professional awards", True),
        ("cv", "Curriculum vitae", True),
        ("professional_reference", "Two professional references", True),
        ("passport", "Copy of passport bio-page verified by recognised authority", True),
        ("police_clearance", "Current police clearance report from country of origin", True),
        ("medical_report", "Full medical report signed and certified by examining doctor", True),
        ("name_change_evidence", "Evidence of name change if applicable", False),
        ("english_language_evidence", "Evidence of knowledge of English; IELTS report score 4 or more", True),
        ("treasury_receipt", "Original receipt payment K50.00 or approved waiver fee for applicants 2-9 months", True),
    ],
    "CHILD_HEALTH_SPEC": [
        ("academic_award", "Specialist qualification evidence", True),
        ("academic_transcript", "Transcript", True),
        ("competency_statement", "NC10 competency", True),
        ("supervisor_recommendation", "Supervisor recommendation", True),
        ("treasury_receipt", "Treasury receipt", True),
    ],
    "DOUBLE_MAJOR": [
        ("dual_qualification_evidence", "Dual qualification evidence", True),
        ("academic_transcript", "Transcript", True),
        ("competency_statement", "Competency evidence for both majors", True),
        ("supervisor_recommendation", "Supervisor recommendation", True),
        ("treasury_receipt", "Treasury receipt", True),
    ],
    "DECEASED_NOTICE": [
        ("deceased_notification_evidence", "Deceased notification evidence", True),
    ],
    "EMPLOYER_VERIFY": [
        ("employer_support_letter", "Employer verification request", True),
    ],
}

FEE_RULES = [
    ("NATIONAL_PROVISIONAL", "National - Provisional new graduates", "national", "PNG_NURSE_GRAD_PROV", "30.00"),
    ("NATIONAL_FULL", "National - Full registration", "national", "PNG_FULL_REG", "50.00"),
    ("NATIONAL_RENEWAL_NURSE", "National - Renewal for nurses", "national", "PNG_RENEWAL", "70.00"),
    ("NATIONAL_RENEWAL_NURSEAIDE", "National - Renewal for nurse aides", "national", "PNG_RENEWAL", "15.00"),
    ("OVERSEAS_TEMPORARY", "Overseas - Temporary 5 weeks to 9 months", "overseas", "OVERSEAS_TEMP", "50.00"),
    ("OVERSEAS_PROVISIONAL_FULL", "Overseas - Provisional and full registration", "overseas", "OVERSEAS_PROV", "500.00"),
    ("OVERSEAS_RENEWAL", "Overseas - Renewal", "overseas", "PNG_RENEWAL", "250.00"),
    ("DUPLICATE_CERTIFICATE", "Duplicate lost certificate or licence", "", "PNG_RENEWAL", "30.00"),
    ("GOOD_STANDING_LETTER", "Good standing letter", "", "EMPLOYER_VERIFY", "40.00"),
    ("LATE_REGISTRATION", "Late registration fee", "", "PNG_RENEWAL", "100.00"),
]


def ensure_nursing_council_configuration():
    body, _ = RegulatoryBody.objects.update_or_create(
        code=NURSING_COUNCIL_CODE,
        defaults={
            "name": "PNG Nursing Council",
            "description": "Structured configuration for Nursing Council registration, renewal, overseas, competency, employer, and deceased workflows.",
            "is_active": True,
        },
    )

    pathway_map = {}
    for config in PATHWAY_DEFINITIONS:
        config = config.copy()
        code = config.pop("pathway_code")
        pathway, _ = ApplicationPathway.objects.update_or_create(
            regulatory_body=body,
            pathway_code=code,
            defaults=config,
        )
        pathway_map[code] = pathway

    form_map = {}
    form_pathway_lookup = dict(PATHWAY_DEFINITIONS_BY_FORM())
    for form_code, form_name, default_pathway_code in FORM_DEFINITIONS:
        pathway = pathway_map.get(default_pathway_code)
        sections = _default_sections_for_form(form_code)
        form_definition, _ = DynamicFormDefinition.objects.update_or_create(
            regulatory_body=body,
            form_code=form_code,
            version="2026.1",
            defaults={
                "form_name": form_name,
                "pathway": pathway,
                "sections": sections,
                "fields": _default_fields_for_form(form_code),
                "validation_rules": _default_validation_for_form(form_code, form_pathway_lookup.get(form_code, default_pathway_code)),
                "visibility_rules": [],
                "required_documents": [],
                "mapped_model_fields": _mapped_fields_for_form(form_code),
                "active": True,
                "active_from": date(2026, 1, 1),
            },
        )
        form_map[form_code] = form_definition

    document_type_map = {}
    for requirements in DOCUMENT_REQUIREMENTS.values():
        for code, label, _required in requirements:
            document_type, _ = DocumentType.objects.get_or_create(
                name=label,
                defaults={"description": f"Nursing Council document requirement: {label}", "is_required": True},
            )
            document_type_map[code] = document_type

    for pathway_code, requirements in DOCUMENT_REQUIREMENTS.items():
        pathway = pathway_map[pathway_code]
        form_definition = form_map.get(pathway.primary_form_code)
        for index, (doc_code, label, required) in enumerate(requirements, start=1):
            DocumentRequirement.objects.update_or_create(
                pathway=pathway,
                document_type_code=doc_code,
                defaults={
                    "form_definition": form_definition,
                    "document_type": document_type_map.get(doc_code),
                    "label": label,
                    "required": required,
                    "accepts_multiple": doc_code in {"professional_reference", "academic_transcript"},
                    "requires_certification": pathway.applicant_type == "overseas" or doc_code in {"academic_award", "academic_transcript"},
                    "requires_translation": pathway.applicant_type == "overseas",
                    "requires_expiry_date": doc_code in {"passport", "police_clearance", "medical_report", "home_registration"},
                    "requires_issue_date": doc_code in {"passport", "police_clearance", "medical_report", "good_standing"},
                    "sort_order": index,
                    "active": True,
                },
            )

    for fee_code, label, applicant_type, pathway_code, amount in FEE_RULES:
        FeeSchedule.objects.update_or_create(
            regulatory_body=body,
            fee_rule_code=fee_code,
            applicant_type=applicant_type,
            effective_from=date(2026, 1, 1),
            defaults={
                "pathway": pathway_map.get(pathway_code),
                "label": label,
                "amount": Decimal(amount),
                "currency": "PGK",
                "active": True,
            },
        )

    ethics, _ = PolicyDocument.objects.update_or_create(
        regulatory_body=body,
        code="CODE_OF_ETHICS",
        version="2026.1",
        defaults={
            "title": "PNG Nursing Council Code of Ethics",
            "document_url": "https://www.health.gov.pg/subindex.php?health_ministry=7",
            "effective_from": date(2026, 1, 1),
            "active": True,
        },
    )
    conduct, _ = PolicyDocument.objects.update_or_create(
        regulatory_body=body,
        code="CODE_OF_PROFESSIONAL_CONDUCT",
        version="2026.1",
        defaults={
            "title": "PNG Nursing Council Code of Professional Conduct",
            "document_url": "https://www.health.gov.pg/subindex.php?health_ministry=7",
            "effective_from": date(2026, 1, 1),
            "active": True,
        },
    )

    for pathway in pathway_map.values():
        if not pathway.public_visible and pathway.pathway_code != "EMPLOYER_VERIFY":
            continue
        DeclarationTemplate.objects.update_or_create(
            regulatory_body=body,
            code=f"{pathway.pathway_code}_ETHICS_DECLARATION",
            required_for_pathway=pathway,
            defaults={
                "title": "Ethics and professional conduct declaration",
                "declaration_text": (
                    f"I confirm that this application follows the {ethics.title} and "
                    f"{conduct.title}, and that the information submitted is true and complete."
                ),
                "active": True,
            },
        )

    return {
        "regulatory_body": body,
        "pathways": len(pathway_map),
        "forms": len(form_map),
        "document_requirements": DocumentRequirement.objects.filter(pathway__regulatory_body=body).count(),
        "fees": FeeSchedule.objects.filter(regulatory_body=body).count(),
        "declarations": DeclarationTemplate.objects.filter(regulatory_body=body).count(),
    }


def PATHWAY_DEFINITIONS_BY_FORM():
    for config in PATHWAY_DEFINITIONS:
        yield config["primary_form_code"], config["pathway_code"]


def _default_sections_for_form(form_code):
    base = ["Applicant Identity", "Education and Qualification", "Documents", "Declaration"]
    if form_code == "NC3":
        return base[:1] + ["Licence Renewal", "Employment Update", "Payment"] + base[-1:]
    if form_code == "NC9":
        return ["Applicant Details", "Temporary Registration Criteria", "Office Use", "Declaration"]
    if form_code in {"NC1", "NC5", "NC8"}:
        return base[:1] + ["Registration Details", "Overseas Details", "Payment"] + base[-1:]
    if form_code in {"G4", "G5", "NC6", "NC7", "NC10"}:
        return ["Applicant Identity", "Supervisor Assessment", "Competency Domains", "Verification"]
    if form_code in {"G2", "G7"}:
        return ["Institution Batch", "Graduate List", "Validation", "Submission"]
    return base


def _default_fields_for_form(form_code):
    fields = ["first_name", "surname", "date_of_birth", "gender"]
    if form_code == "NC3":
        fields += ["registration_number", "practitioner_number", "employment_status", "employer_name", "facility_name", "province", "position_title", "receipt_number"]
    elif form_code == "NC9":
        fields += [
            "organisation_name",
            "place_of_work",
            "postal_address",
            "png_contract_or_employment_letter",
            "nc8_application_form",
            "home_registration_license",
            "academic_awards",
            "curriculum_vitae",
            "professional_references",
            "passport_bio_page",
            "police_clearance_report",
            "medical_report",
            "name_change_evidence",
            "english_language_evidence",
            "temporary_licence_receipt",
        ]
    elif form_code in {"NC1", "NC2", "NC5", "NC8"}:
        fields += ["registration_number", "practitioner_number", "qualification", "institution", "receipt_number"]
    elif form_code in {"G2", "G7"}:
        fields += ["institution", "graduation_year", "graduate_list"]
    elif form_code in {"G4", "G5", "NC6", "NC7", "NC10"}:
        fields += ["supervisor_name", "supervisor_registration_number", "competency_domains", "overall_result"]
    return fields


def _default_validation_for_form(form_code, pathway_code):
    rules = ["identity_required", "documents_required", "declaration_required"]
    if form_code == "NC3":
        rules += ["employment_required", "payment_required", "duplicate_licence_period_blocked"]
    if pathway_code and pathway_code.startswith("OVERSEAS"):
        rules += ["passport_required", "home_registration_required", "certification_required"]
    if form_code in {"G4", "G5", "NC6", "NC7", "NC10"}:
        rules += ["competency_must_be_competent", "supervisor_required"]
    return rules


def _mapped_fields_for_form(form_code):
    mapping = {
        "first_name": "professional.first_name",
        "surname": "professional.last_name",
        "date_of_birth": "professional.date_of_birth",
        "gender": "professional.gender",
        "registration_number": "professional.registration_no",
        "practitioner_number": "professional.registration_number",
        "qualification": "qualification.qualification_name",
        "institution": "qualification.institution_name",
        "employment_status": "employment_record.employment_status",
        "employer_name": "employment_record.employer_name",
        "receipt_number": "receipt.official_receipt_no",
    }
    if form_code in {"G4", "G5", "NC6", "NC7", "NC10"}:
        mapping.update({
            "supervisor_name": "competency_assessment.supervisor_name",
            "competency_domains": "competency_assessment.competency_domains",
            "overall_result": "competency_assessment.is_passed",
        })
    return mapping


def get_nursing_pathways(public_only=True):
    queryset = ApplicationPathway.objects.filter(
        regulatory_body__code=NURSING_COUNCIL_CODE,
        active=True,
    ).select_related("regulatory_body")
    if public_only:
        queryset = queryset.filter(public_visible=True)
    return queryset.order_by("sort_order", "pathway_code")


def generate_application_checklist(application):
    pathway = NursingCouncilValidationService(application)._resolve_pathway(application)
    if not pathway:
        return []

    checklist_items = []
    requirements = DocumentRequirement.objects.filter(pathway=pathway, active=True).order_by("sort_order", "label")
    for requirement in requirements:
        item, _created = ApplicationChecklistItem.objects.get_or_create(
            application=application,
            document_requirement=requirement,
            defaults={"status": "not_uploaded"},
        )
        checklist_items.append(item)
    return checklist_items


def is_nursing_council_application(application):
    return (application.form_code or "").upper() in NURSING_FORM_CODES


def infer_nursing_pathway_code(application):
    payload = application.payload or {}
    if payload.get("pathway_code"):
        return payload["pathway_code"]

    form_code = (application.form_code or "").upper()
    professional = application.professional
    applicant_type = (payload.get("applicant_type") or getattr(professional, "applicant_type", "") or "").lower()

    if form_code in {"G1", "G2", "G3", "G4"}:
        return "PNG_NURSE_GRAD_PROV"
    if form_code in {"G5", "G6", "G7"}:
        return "PNG_MIDWIFE_GRAD_FULL"
    if form_code == "NC1":
        return "OVERSEAS_PROV" if applicant_type == "overseas" else "PNG_NURSE_GRAD_PROV"
    if form_code == "NC2":
        if isinstance(professional, Midwife):
            return "PNG_MIDWIFE_GRAD_FULL"
        return "PNG_FULL_REG"
    if form_code == "NC3":
        return "PNG_RENEWAL"
    if form_code == "NC4":
        return "OVERSEAS_PROV"
    if form_code == "NC5":
        return "OVERSEAS_FULL"
    if form_code in {"NC6", "NC7"}:
        return "PNG_PROV_TO_FULL"
    if form_code in {"NC8", "NC9"}:
        return "OVERSEAS_TEMP"
    if form_code == "NC10":
        return "CHILD_HEALTH_SPEC"
    if form_code == "NC11":
        return "DOUBLE_MAJOR"
    return ""


def prepare_nursing_application_submission(application, *, actor=None, request=None):
    if not is_nursing_council_application(application):
        return application

    ensure_nursing_council_configuration()
    payload = dict(application.payload or {})
    payload.setdefault("pathway_code", infer_nursing_pathway_code(application))
    payload.setdefault("workflow_prepared_at", timezone.now().isoformat())
    application.payload = payload
    application.save(update_fields=["payload"])

    form_response, created = ApplicationFormResponse.objects.get_or_create(
        application=application,
        form_code=application.form_code,
        form_version="2026.1",
        defaults={
            "response_json": _json_safe(payload),
            "submitted_by": actor,
        },
    )
    if not created:
        form_response.response_json = _json_safe(payload)
        form_response.save(update_fields=["response_json"])
    checklist_items = generate_application_checklist(application)
    _accept_required_declarations_from_payload(application, actor=actor, request=request)
    record_application_status(application, "", application.status, actor=actor, reason="Application submitted")
    audit_action(
        "APPLICATION_SUBMITTED",
        application,
        actor=actor,
        request=request,
        new_values={"form_code": application.form_code, "pathway_code": payload.get("pathway_code"), "checklist_items": len(checklist_items)},
    )
    return application


def record_application_status(application, old_status, new_status, *, actor=None, reason="", comment="", supporting_document=None):
    if old_status == new_status and ApplicationStatusHistory.objects.filter(
        application=application,
        old_status=old_status or "",
        new_status=new_status or "",
        reason=reason or "",
    ).exists():
        return None
    return ApplicationStatusHistory.objects.create(
        application=application,
        old_status=old_status or "",
        new_status=new_status or "",
        changed_by=actor,
        reason=reason or "",
        comment=comment or "",
        supporting_document=supporting_document,
    )


def audit_action(action, entity, *, actor=None, request=None, old_values=None, new_values=None):
    ip_address, user_agent = _request_meta(request)
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type=entity.__class__.__name__,
        entity_id=str(getattr(entity, "pk", "")),
        old_values_json=_json_safe(old_values or {}),
        new_values_json=_json_safe(new_values or {}),
        ip_address=ip_address,
        user_agent=user_agent,
    )


def verify_application_payment(application, *, actor=None, request=None):
    updated = Receipt.objects.filter(application=application).exclude(status="completed").update(status="completed")
    if updated:
        audit_action("PAYMENT_VERIFIED", application, actor=actor, request=request, new_values={"receipts_verified": updated})
    return updated


def review_checklist_item(item, *, status, actor=None, request=None, rejection_reason=""):
    old_status = item.status
    item.status = status
    item.verified_by = actor
    item.verified_at = timezone.now()
    item.rejection_reason = rejection_reason or ""
    item.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason"])
    audit_action(
        "DOCUMENT_VERIFIED",
        item.application,
        actor=actor,
        request=request,
        old_values={"checklist_item": item.pk, "status": old_status},
        new_values={"checklist_item": item.pk, "status": item.status},
    )
    return item


@transaction.atomic
def approve_nursing_application(application, *, actor=None, request=None, enforce_validation=True):
    if not is_nursing_council_application(application):
        return _approve_basic_application(application, actor=actor, request=request)

    prepare_nursing_application_submission(application, actor=actor, request=request)
    validation = NursingCouncilValidationService(application).validate_for_status("approved")
    if enforce_validation and not validation["can_proceed"]:
        return {"approved": False, "errors": validation["errors"], "warnings": validation.get("warnings", [])}

    old_status = application.status
    today = date.today()
    application.status = "approved"
    application.approved_date = today
    application.reviewed_by = actor
    application.expiry_date = _calculated_expiry(application, today)
    application.save(update_fields=["status", "approved_date", "reviewed_by", "expiry_date"])

    _apply_licence_lifecycle(application, actor=actor, request=request)
    record_application_status(application, old_status, application.status, actor=actor, reason="Registrar approved")
    audit_action("REGISTRAR_APPROVED", application, actor=actor, request=request, old_values={"status": old_status}, new_values={"status": application.status})
    return {"approved": True, "errors": [], "warnings": validation.get("warnings", [])}


@transaction.atomic
def reject_nursing_application(application, *, actor=None, request=None, reason=""):
    old_status = application.status
    application.status = "rejected"
    application.reviewed_by = actor
    application.reviewer_notes = reason or application.reviewer_notes
    application.save(update_fields=["status", "reviewed_by", "reviewer_notes"])
    record_application_status(application, old_status, application.status, actor=actor, reason="Registrar rejected", comment=reason)
    audit_action("REGISTRAR_REJECTED", application, actor=actor, request=request, old_values={"status": old_status}, new_values={"status": application.status, "reason": reason})
    return application


NURSING_PUBLIC_IMPORT_TARGET_CATEGORIES = {
    "nursingprofessional": "Registered Nurse",
    "midwife": "Midwife",
    "nurseaide": "Nurse Aide",
    "healthstudent": "Graduand",
}
NURSING_PUBLIC_IMPORT_RECORD_TYPES = {
    "provisional",
    "full",
    "full_approved",
    "temporary",
    "practicing_license",
    "workforce_listing",
}


def _apply_public_token_search(queryset, query, fields):
    tokens = [token.strip() for token in str(query or "").split() if token.strip()]
    for token in tokens:
        token_filter = Q()
        for field in fields:
            token_filter |= Q(**{f"{field}__icontains": token})
        queryset = queryset.filter(token_filter)
    return queryset


def _nursing_import_record_status(record):
    if record.record_type == "practicing_license":
        current_year = date.today().year
        if record.record_year and record.record_year < current_year:
            return "Expired"
        return "Active"
    if record.record_type in {"full", "full_approved", "workforce_listing"}:
        return "Registered"
    if record.record_type == "provisional":
        return "Provisional"
    if record.record_type == "temporary":
        return "Temporary"
    return record.get_record_type_display()


def _nursing_import_category(record):
    category = NURSING_PUBLIC_IMPORT_TARGET_CATEGORIES.get(record.target_model, "")
    if category:
        return category
    text = (record.category or record.qualification_name or "").lower()
    if "midwife" in text or "midwifery" in text:
        return "Midwife"
    if "aide" in text:
        return "Nurse Aide"
    return "Registered Nurse"


def _safe_public_import_record(record):
    status = _nursing_import_record_status(record)
    return {
        "full_name": record.full_name,
        "registration_number": record.registration_no or "",
        "practitioner_number": record.practitioner_number or "",
        "professional_category": _nursing_import_category(record),
        "licence_status": status,
        "licence_expiry_date": "",
        "eligible_to_practice": status in {"Active", "Registered", "Provisional", "Temporary"},
        "conditions_summary": "Check with Nursing Council for current public conditions",
        "source": f"Nursing Council import {record.record_year or ''}".strip(),
    }


def _nursing_public_row_identity(row):
    return (
        (row.get("registration_number") or "").strip().upper(),
        (row.get("practitioner_number") or "").strip().upper(),
        (row.get("full_name") or "").strip().upper(),
        (row.get("professional_category") or "").strip().upper(),
    )


def search_public_nursing_register(*, query="", registration_number="", practitioner_number="", professional_category="", licence_status=""):
    rows = []
    model_category = [
        (NursingProfessional, "Registered Nurse"),
        (Midwife, "Midwife"),
        (NurseAide, "Nurse Aide"),
    ]
    for model, category in model_category:
        queryset = model.objects.all()
        if query:
            queryset = _apply_public_token_search(
                queryset,
                query,
                ["first_name", "middle_name", "last_name", "registration_no", "registration_number"],
            )
        if registration_number:
            queryset = queryset.filter(registration_no__icontains=registration_number)
        if practitioner_number:
            queryset = queryset.filter(registration_number__icontains=practitioner_number)
        if professional_category and professional_category.lower() not in category.lower():
            continue
        for obj in queryset.order_by("last_name", "first_name")[:100]:
            safe = _safe_public_professional(obj, category)
            if licence_status and safe["licence_status"].lower() != licence_status.lower():
                continue
            rows.append(safe)

    imported_records = quality_approved_import_records(
        PracticingLicenseRecord.objects.select_related("batch").filter(
            target_model__in=NURSING_PUBLIC_IMPORT_TARGET_CATEGORIES.keys(),
            record_type__in=NURSING_PUBLIC_IMPORT_RECORD_TYPES,
        ).exclude(batch__source_kind="medical_board_workbook")
    )
    if query:
        imported_records = _apply_public_token_search(
            imported_records,
            query,
            ["full_name", "first_name", "last_name", "registration_no", "practitioner_number", "category", "qualification_name"],
        )
    if registration_number:
        imported_records = imported_records.filter(registration_no__icontains=registration_number)
    if practitioner_number:
        imported_records = imported_records.filter(practitioner_number__icontains=practitioner_number)

    for record in imported_records.order_by("-record_year", "-issued_date", "full_name")[:200]:
        safe = _safe_public_import_record(record)
        if professional_category and professional_category.lower() not in safe["professional_category"].lower():
            continue
        if licence_status and safe["licence_status"].lower() != licence_status.lower():
            continue
        rows.append(safe)

    deduped = []
    seen = set()
    for row in rows:
        identity = _nursing_public_row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped[:100]


def create_employer_verification_request(*, actor, registration_number="", practitioner_number="", employer_name="", facility_name="", comments="", request=None):
    professional = _find_nursing_professional(registration_number=registration_number, practitioner_number=practitioner_number)
    verification = EmployerVerificationRequest.objects.create(
        content_type=ContentType.objects.get_for_model(professional) if professional else None,
        object_id=professional.pk if professional else None,
        employer_name=employer_name or "Employer",
        facility_name=facility_name or "",
        requester=actor,
        request_type="registration_status",
        safe_result_json=_safe_public_professional(professional, _category_for_professional(professional)) if professional else {},
        status="verified" if professional else "pending",
        comments=comments,
    )
    audit_action("EMPLOYER_VERIFICATION_REQUESTED", verification, actor=actor, request=request, new_values=verification.safe_result_json)
    return verification


def create_supervisor_assignment(*, application, supervisor_name, actor=None, supervisor_registration_number="", employer_name="", request=None):
    professional = application.professional
    assignment = SupervisorAssignment.objects.create(
        application=application,
        content_type=ContentType.objects.get_for_model(professional) if professional else None,
        object_id=professional.pk if professional else None,
        employer_name=employer_name or "",
        supervisor_name=supervisor_name,
        supervisor_registration_number=supervisor_registration_number or "",
        supervisor_user=actor,
        status="assigned",
    )
    audit_action("SUPERVISOR_ASSIGNED", assignment, actor=actor, request=request, new_values={"application_id": application.pk})
    return assignment


def complete_supervisor_competency(*, assignment, actor=None, result="competent", comments="", request=None):
    professional = assignment.professional
    if not professional:
        raise ValueError("Supervisor assignment is not linked to a practitioner.")
    assessment = CompetencyAssessment.objects.create(
        content_type=ContentType.objects.get_for_model(professional),
        object_id=professional.pk,
        assessment_name=f"Supervisor competency for application {assignment.application_id}",
        assessment_type="supervisor_assignment",
        form_code=assignment.application.form_code,
        profession_track=assignment.application.profession_track,
        competency_domains=[{"result": result, "comment": comments}],
        supervisor_name=assignment.supervisor_name,
        supervisor_assessment=comments,
        assessment_date=date.today(),
        is_passed=result == "competent",
    )
    assignment.status = "completed"
    assignment.completed_at = timezone.now()
    assignment.notes = comments
    assignment.save(update_fields=["status", "completed_at", "notes"])
    audit_action("COMPETENCY_SUBMITTED", assessment, actor=actor, request=request, new_values={"assignment_id": assignment.pk, "result": result})
    return assessment


@transaction.atomic
def create_deceased_notification(*, actor, name_at_report, date_of_death, registration_number="", practitioner_number="", workforce_category="", facility_name="", comments="", request=None):
    professional = _find_nursing_professional(registration_number=registration_number, practitioner_number=practitioner_number, full_name=name_at_report)
    notification = DeceasedNotification.objects.create(
        content_type=ContentType.objects.get_for_model(professional) if professional else None,
        object_id=professional.pk if professional else None,
        registration_number=(registration_number or getattr(professional, "registration_no", "") if professional else registration_number) or "",
        practitioner_number=(practitioner_number or getattr(professional, "registration_number", "") if professional else practitioner_number) or "",
        name_at_report=name_at_report,
        gender=getattr(professional, "gender", "") if professional else "",
        workforce_category=workforce_category or _category_for_professional(professional),
        date_of_death=date_of_death,
        facility_name=facility_name or "",
        reported_by=actor,
        comments=comments,
    )
    audit_action("PRACTITIONER_DECEASED_NOTICE_CREATED", notification, actor=actor, request=request)
    return notification


@transaction.atomic
def approve_deceased_notification(notification, *, actor=None, request=None):
    old_status = notification.verification_status
    professional = notification.professional
    notification.verification_status = "approved"
    notification.verified_by = actor
    notification.registrar_approved_by = actor
    notification.date_removed_from_hcprs = notification.date_removed_from_hcprs or date.today()
    notification.save(update_fields=["verification_status", "verified_by", "registrar_approved_by", "date_removed_from_hcprs"])
    if professional:
        professional.is_active = False
        if hasattr(professional, "license_expiry_date"):
            professional.license_expiry_date = notification.date_of_death
            professional.save(update_fields=["is_active", "license_expiry_date", "updated_at"])
        else:
            professional.save(update_fields=["is_active", "updated_at"])
        from apps.accounts.professional_linking import mark_users_deceased_for_professional

        mark_users_deceased_for_professional(professional)
    audit_action(
        "PRACTITIONER_MARKED_DECEASED",
        notification,
        actor=actor,
        request=request,
        old_values={"status": old_status},
        new_values={"status": notification.verification_status, "professional_id": getattr(professional, "pk", None)},
    )
    return notification


def build_nursing_workflow_rows():
    rows = []
    for pathway in get_nursing_pathways(public_only=False):
        rows.append({
            "pathway": pathway.pathway_name,
            "code": pathway.pathway_code,
            "who": pathway.get_applicant_type_display() if hasattr(pathway, "get_applicant_type_display") else pathway.applicant_type.replace("_", " ").title(),
            "summary": _pathway_summary(pathway),
            "primary_form_code": pathway.primary_form_code,
            "checklist_code": pathway.checklist_code,
            "competency_framework_code": pathway.competency_framework_code or "Not required",
            "requires_payment": pathway.requires_payment,
            "requires_employer": pathway.requires_employer,
            "requires_institution": pathway.requires_institution,
            "requires_supervisor": pathway.requires_supervisor,
        })
    return rows


def build_public_form_guide():
    guide = {}
    for pathway in get_nursing_pathways(public_only=True).prefetch_related("form_definitions"):
        pathway_label = f"{pathway.pathway_name} ({pathway.pathway_code})"
        guide[pathway_label] = [
            (form.form_code, form.form_name)
            for form in pathway.form_definitions.filter(active=True).order_by("form_code")
        ]
        if not guide[pathway_label]:
            guide[pathway_label] = [(pathway.primary_form_code, pathway.pathway_name)]
    nc9 = DynamicFormDefinition.objects.filter(
        regulatory_body__code=NURSING_COUNCIL_CODE,
        form_code="NC9",
        active=True,
    ).first()
    guide["Special application forms"] = [
        (
            "NC9",
            nc9.form_name if nc9 else "Temporary Licence to Practise Criteria for Overseas Nurses Checklist (Revised 2023)",
        ),
    ]
    return guide


def _request_meta(request):
    if not request:
        return None, ""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR")
    return ip_address or None, request.META.get("HTTP_USER_AGENT", "")


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _accept_required_declarations_from_payload(application, *, actor=None, request=None):
    payload = application.payload or {}
    accepted = payload.get("declaration_acceptance") or payload.get("ethics_declaration_accepted") or payload.get("confirm_declaration")
    if not accepted:
        return 0
    pathway = NursingCouncilValidationService(application)._resolve_pathway(application)
    if not pathway:
        return 0
    count = 0
    for declaration in DeclarationTemplate.objects.filter(required_for_pathway=pathway, active=True):
        _obj, created = ApplicantDeclaration.objects.get_or_create(
            application=application,
            declaration_template=declaration,
            defaults={
                "accepted_by": actor,
                "ip_address": _request_meta(request)[0],
                "user_agent": _request_meta(request)[1],
            },
        )
        count += int(created)
    return count


def _approve_basic_application(application, *, actor=None, request=None):
    old_status = application.status
    today = date.today()
    application.status = "approved"
    application.approved_date = today
    application.reviewed_by = actor
    application.expiry_date = application.expiry_date or _calculated_expiry(application, today)
    application.save(update_fields=["status", "approved_date", "reviewed_by", "expiry_date"])
    record_application_status(application, old_status, application.status, actor=actor, reason="Registrar approved")
    audit_action("REGISTRAR_APPROVED", application, actor=actor, request=request, old_values={"status": old_status}, new_values={"status": application.status})
    return {"approved": True, "errors": [], "warnings": []}


def _calculated_expiry(application, approved_date):
    pathway = NursingCouncilValidationService(application)._resolve_pathway(application) if is_nursing_council_application(application) else None
    licence_type = getattr(pathway, "creates_licence_type", "") if pathway else ""
    if licence_type == "provisional" or application.form_code == "NC1":
        return approved_date + timedelta(days=180)
    if licence_type == "temporary" or application.form_code == "NC8":
        payload = application.payload or {}
        return _coerce_date(payload.get("end_date") or payload.get("expiry_date")) or approved_date + timedelta(days=90)
    return date(approved_date.year, 12, 31) if application.form_code == "NC3" else approved_date + timedelta(days=365)


def _apply_licence_lifecycle(application, *, actor=None, request=None):
    pathway = NursingCouncilValidationService(application)._resolve_pathway(application)
    if not pathway:
        return None

    professional = application.professional
    if professional and pathway.creates_licence_type != "deceased_status_update":
        if hasattr(professional, "date_issued"):
            professional.date_issued = application.approved_date
        if hasattr(professional, "license_expiry_date"):
            professional.license_expiry_date = application.expiry_date
        professional.is_active = True
        professional.save()

    if pathway.creates_licence_type in {"provisional", "full_registration", "renewal", "temporary", "specialist_recognition", "double_major"}:
        record = _record_licence_event(application, pathway)
        audit_action("LICENCE_CREATED" if pathway.creates_licence_type != "renewal" else "LICENCE_RENEWED", application, actor=actor, request=request, new_values={"record_id": record.pk if record else None, "licence_type": pathway.creates_licence_type})
        return record
    return None


def _record_licence_event(application, pathway):
    professional = application.professional
    if not professional:
        return None
    record_type = {
        "provisional": "provisional",
        "full_registration": "full_approved",
        "renewal": "practicing_license",
        "temporary": "temporary",
        "specialist_recognition": "full_approved",
        "double_major": "full_approved",
    }.get(pathway.creates_licence_type, "full_approved")
    batch = _get_live_workflow_batch()
    full_name = f"{getattr(professional, 'first_name', '')} {getattr(professional, 'last_name', '')}".strip()
    payload = application.payload or {}
    amount = None
    receipt = Receipt.objects.filter(application=application).order_by("-transaction_date").first()
    if receipt:
        amount = receipt.amount
    return PracticingLicenseRecord.objects.create(
        batch=batch,
        source_sheet_name="Live workflow approvals",
        source_row=application.pk,
        record_type=record_type,
        target_model=professional._meta.model_name,
        record_year=(application.approved_date or date.today()).year,
        full_name=full_name or str(professional),
        first_name=getattr(professional, "first_name", ""),
        last_name=getattr(professional, "last_name", ""),
        gender=getattr(professional, "gender", "") or "",
        date_of_birth=getattr(professional, "date_of_birth", None),
        registration_no=getattr(professional, "registration_no", "") or "",
        practitioner_number=getattr(professional, "registration_number", "") or payload.get("practitioner_number", "") or "",
        applicant_type=getattr(professional, "applicant_type", "") or "",
        nationality=getattr(professional, "nationality", "") or "",
        qualification_name=getattr(professional, "qualification_level", "") or payload.get("program_completed", "") or "",
        category=_category_for_professional(professional),
        institution_name=payload.get("institution_attended", "") or payload.get("institute_name", "") or "",
        workplace_address=payload.get("place_of_work", "") or payload.get("employer_name", "") or "",
        province=getattr(professional, "province", "") or payload.get("province", "") or "",
        issued_date=application.approved_date,
        payment_date=receipt.receipt_date.date() if receipt and receipt.receipt_date else None,
        amount=amount,
        reference_number=receipt.official_receipt_no or receipt.receipt_number if receipt else "",
        payment_method=receipt.payment_method if receipt else "",
        raw_payload=_json_safe({"application_id": application.pk, "pathway_code": pathway.pathway_code, **payload}),
    )


def _get_live_workflow_batch():
    batch = DataImportBatch.objects.filter(
        source_file_name="Live Nursing Council workflow approvals",
        source_kind="nursing_live_workflow",
    ).order_by("-started_at").first()
    defaults = {
        "source_file_path": "live-workflow",
        "status": "completed",
        "total_sheets": 1,
        "processed_sheets": 1,
        "completed_at": timezone.now(),
    }
    if batch:
        for key, value in defaults.items():
            setattr(batch, key, value)
        batch.save(update_fields=list(defaults))
        return batch
    return DataImportBatch.objects.create(
        source_file_name="Live Nursing Council workflow approvals",
        source_kind="nursing_live_workflow",
        **defaults,
    )


def _coerce_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _category_for_professional(professional):
    if isinstance(professional, Midwife):
        return "Midwife"
    if isinstance(professional, NurseAide):
        return "Nurse Aide"
    if isinstance(professional, HealthStudent):
        return "Graduand"
    if isinstance(professional, NursingProfessional):
        return "Registered Nurse"
    return ""


def _licence_status(professional):
    if not professional:
        return "Not Found"
    if not getattr(professional, "is_active", False):
        return "Inactive"
    expiry = getattr(professional, "license_expiry_date", None)
    if expiry and expiry < date.today():
        return "Expired"
    if expiry:
        return "Active"
    return "Registered"


def _public_condition_count(professional):
    content_type = ContentType.objects.get_for_model(professional)
    registration_number = str(getattr(professional, "registration_no", "") or "").strip()
    query = Q(subject_content_type=content_type, subject_object_id=professional.pk)
    if registration_number:
        query |= Q(subject_identifier__iexact=registration_number)
    return RegulatoryDecisionRecord.objects.filter(
        query,
        office_scope="nursing",
        status="final",
    ).exclude(conditions="").filter(
        Q(expiry_date__isnull=True) | Q(expiry_date__gte=date.today())
    ).count()


def _safe_public_professional(professional, category=""):
    if not professional:
        return {}
    expiry = getattr(professional, "license_expiry_date", None)
    conditions_count = _public_condition_count(professional)
    return {
        "full_name": f"{professional.first_name} {professional.last_name}".strip(),
        "registration_number": professional.registration_no or "",
        "practitioner_number": professional.registration_number or "",
        "professional_category": category or _category_for_professional(professional),
        "licence_status": _licence_status(professional),
        "licence_expiry_date": expiry.isoformat() if expiry else "",
        "eligible_to_practice": _licence_status(professional) in {"Active", "Registered"},
        "conditions_summary": "Active conditions recorded" if conditions_count else "No active public conditions recorded",
    }


def _find_nursing_professional(*, registration_number="", practitioner_number="", full_name=""):
    for model in (NursingProfessional, Midwife, NurseAide, HealthStudent):
        queryset = model.objects.all()
        filters = Q()
        if registration_number:
            filters |= Q(registration_no__iexact=registration_number)
        if practitioner_number:
            filters |= Q(registration_number__iexact=practitioner_number)
        if full_name:
            tokens = full_name.split()
            for token in tokens:
                filters |= Q(first_name__icontains=token) | Q(last_name__icontains=token)
        if filters:
            obj = queryset.filter(filters).first()
            if obj:
                return obj
    return None


def _pathway_summary(pathway):
    flags = []
    if pathway.requires_payment:
        flags.append("payment")
    if pathway.requires_institution:
        flags.append("institution")
    if pathway.requires_employer:
        flags.append("employer")
    if pathway.requires_supervisor:
        flags.append("supervisor")
    required = ", ".join(flags) if flags else "standard identity and document"
    return f"Uses {pathway.primary_form_code}; requires {required} checks before registrar decision."


class NursingCouncilValidationService:
    BLOCKED_STATUSES = {"registrar_review", "approved", "licence_issued"}

    def __init__(self, application):
        self.application = application
        self.pathway = self._resolve_pathway(application)

    def validate_for_status(self, target_status):
        errors = []
        warnings = []
        if not self.pathway:
            return {
                "can_proceed": False,
                "errors": ["No Nursing Council pathway configuration is linked to this application."],
                "warnings": [],
            }

        errors.extend(self._identity_errors())
        if target_status in self.BLOCKED_STATUSES:
            errors.extend(self._checklist_errors())
            errors.extend(self._payment_errors())
            errors.extend(self._competency_errors())
            errors.extend(self._declaration_errors())
        if self.application.form_code == "NC3":
            errors.extend(self._renewal_employment_errors())

        return {
            "can_proceed": not errors,
            "errors": errors,
            "warnings": warnings,
            "pathway_code": self.pathway.pathway_code,
        }

    def _resolve_pathway(self, application):
        pathway_code = (application.payload or {}).get("pathway_code")
        if pathway_code:
            pathway = ApplicationPathway.objects.filter(
                regulatory_body__code=NURSING_COUNCIL_CODE,
                pathway_code=pathway_code,
                active=True,
            ).first()
            if pathway:
                return pathway
        return ApplicationPathway.objects.filter(
            regulatory_body__code=NURSING_COUNCIL_CODE,
            primary_form_code=application.form_code,
            active=True,
        ).order_by("sort_order").first()

    def _identity_errors(self):
        professional = self.application.professional
        if not professional:
            return ["Application is not linked to a practitioner profile."]
        errors = []
        for field, label in [("first_name", "first name"), ("last_name", "surname"), ("date_of_birth", "date of birth"), ("gender", "gender")]:
            if not getattr(professional, field, None):
                errors.append(f"Missing {label}.")
        return errors

    def _checklist_errors(self):
        missing = ApplicationChecklistItem.objects.filter(
            application=self.application,
            document_requirement__required=True,
        ).exclude(status__in=["accepted", "waived"])
        if missing.exists():
            labels = ", ".join(missing.values_list("document_requirement__label", flat=True)[:5])
            return [f"Required checklist items are not accepted or waived: {labels}."]
        required_count = DocumentRequirement.objects.filter(pathway=self.pathway, required=True, active=True).count()
        existing_count = ApplicationChecklistItem.objects.filter(application=self.application).count()
        if required_count and existing_count == 0:
            return ["Required checklist has not been generated for this application."]
        return []

    def _payment_errors(self):
        if not self.pathway.requires_payment:
            return []
        has_verified_receipt = Receipt.objects.filter(application=self.application, status="completed").exists()
        has_waiver = ApplicationChecklistItem.objects.filter(
            application=self.application,
            document_requirement__document_type_code="treasury_receipt",
            status="waived",
        ).exists()
        if not has_verified_receipt and not has_waiver:
            return ["Payment must be verified or officially waived before registrar review."]
        return []

    def _competency_errors(self):
        if not self.pathway.competency_framework_code:
            return []
        professional = self.application.professional
        if not professional:
            return []
        ct = ContentType.objects.get_for_model(professional)
        passed = CompetencyAssessment.objects.filter(
            content_type=ct,
            object_id=professional.pk,
            is_passed=True,
        ).exists()
        if not passed:
            return ["Required competency assessment is not completed as competent."]
        return []

    def _declaration_errors(self):
        required_templates = DeclarationTemplate.objects.filter(required_for_pathway=self.pathway, active=True)
        accepted = ApplicantDeclaration.objects.filter(application=self.application).values_list("declaration_template_id", flat=True)
        missing = required_templates.exclude(id__in=accepted)
        if missing.exists():
            return ["Required ethics and professional conduct declaration has not been accepted."]
        return []

    def _renewal_employment_errors(self):
        payload = self.application.payload or {}
        employment_status = payload.get("employment_status")
        if not employment_status:
            return ["Renewal applications must capture employment status."]
        if employment_status in {"full_time", "part_time", "employed_full_time", "employed_part_time"}:
            missing = [
                label
                for key, label in [
                    ("employer_name", "employer name"),
                    ("facility_name", "facility or workplace name"),
                    ("province", "province"),
                    ("position_title", "position title"),
                    ("area_of_employment", "employment sector"),
                    ("start_date", "employment start date"),
                ]
                if not payload.get(key)
            ]
            return [f"Renewal employment details are incomplete: {', '.join(missing)}."] if missing else []
        if employment_status == "unemployed" and not payload.get("reasons_for_unemployment"):
            return ["Unemployed renewal applicants must provide unemployment reason."]
        return []
