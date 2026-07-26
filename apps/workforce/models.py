from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


# ====================== LOOKUP MODELS ======================

class Cadre(models.Model):
    CATEGORY_CHOICES = [
        ('nursing', 'Nursing'),
        ('midwifery', 'Midwifery'),
        ('medical', 'Medical'),
        ('chw', 'CHW'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='nursing')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Location(models.Model):
    province = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    ward = models.CharField(max_length=100, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['province', 'district']),
        ]

    def __str__(self):
        return f"{self.district}, {self.province}"


class Facility(models.Model):
    OWNERSHIP_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('faith_based', 'Faith-Based'),
        ('ngo', 'NGO'),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, null=True)
    type = models.CharField(max_length=100)
    ownership = models.CharField(max_length=50, choices=OWNERSHIP_CHOICES)
    level = models.CharField(max_length=50, default='district')
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.name


class FacilityAccreditation(models.Model):
    """Medical Board accreditation status for a registered health facility.

    This is deliberately separate from an application/checklist.  A submitted
    facility form is evidence in a workflow; this record represents the
    regulator's current, reviewable accreditation decision.
    """

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('under_review', 'Under review'),
        ('accredited', 'Accredited'),
        ('conditional', 'Conditionally accredited'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired'),
        ('not_accredited', 'Not accredited'),
    ]
    ACCREDITATION_TYPE_CHOICES = [
        ('hospital', 'Hospital'),
        ('clinic', 'Clinic'),
        ('private_practice', 'Private practice'),
        ('specialist_centre', 'Specialist centre'),
        ('diagnostic_facility', 'Diagnostic facility'),
        ('training_college', 'Training college'),
        ('other', 'Other'),
    ]

    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='medical_accreditations')
    accreditation_type = models.CharField(max_length=40, choices=ACCREDITATION_TYPE_CHOICES, default='other')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='under_review', db_index=True)
    reference_number = models.CharField(max_length=100, blank=True, db_index=True)
    compliance_score = models.PositiveSmallIntegerField(null=True, blank=True)
    last_inspection_date = models.DateField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True, db_index=True)
    conditions_summary = models.TextField(blank=True)
    evidence_summary = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_facility_accreditations',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['facility__name', '-updated_at']
        indexes = [
            models.Index(fields=['status', 'valid_until']),
            models.Index(fields=['accreditation_type', 'status']),
        ]

    def __str__(self):
        return f"{self.facility} - {self.get_status_display()}"


class TrainingInstitution(models.Model):
    name = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=100, blank=True)
    ownership = models.CharField(max_length=120, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    registration_status = models.CharField(max_length=80, blank=True)
    regulatory_body_name = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=100, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class DocumentType(models.Model):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class RegulatoryBody(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Regulatory bodies"

    def __str__(self):
        return self.name


class ApplicationPathway(models.Model):
    regulatory_body = models.ForeignKey(RegulatoryBody, on_delete=models.CASCADE, related_name="application_pathways")
    pathway_code = models.CharField(max_length=60)
    pathway_name = models.CharField(max_length=255)
    applicant_type = models.CharField(max_length=60, blank=True)
    primary_form_code = models.CharField(max_length=20)
    checklist_code = models.CharField(max_length=60, blank=True)
    competency_framework_code = models.CharField(max_length=60, blank=True)
    fee_rule_code = models.CharField(max_length=60, blank=True)
    requires_payment = models.BooleanField(default=False)
    requires_employer = models.BooleanField(default=False)
    requires_institution = models.BooleanField(default=False)
    requires_supervisor = models.BooleanField(default=False)
    requires_registrar_approval = models.BooleanField(default=True)
    creates_licence_type = models.CharField(max_length=80, blank=True)
    public_visible = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["regulatory_body", "sort_order", "pathway_code"]
        unique_together = ("regulatory_body", "pathway_code")
        indexes = [
            models.Index(fields=["pathway_code"]),
            models.Index(fields=["active", "public_visible"]),
        ]

    def __str__(self):
        return f"{self.pathway_code} - {self.pathway_name}"


class DynamicFormDefinition(models.Model):
    regulatory_body = models.ForeignKey(RegulatoryBody, on_delete=models.CASCADE, related_name="form_definitions")
    pathway = models.ForeignKey(
        ApplicationPathway,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="form_definitions",
    )
    form_code = models.CharField(max_length=20)
    form_name = models.CharField(max_length=255)
    version = models.CharField(max_length=30, default="2026.1")
    sections = models.JSONField(default=list, blank=True)
    fields = models.JSONField(default=list, blank=True)
    validation_rules = models.JSONField(default=list, blank=True)
    visibility_rules = models.JSONField(default=list, blank=True)
    required_documents = models.JSONField(default=list, blank=True)
    mapped_model_fields = models.JSONField(default=dict, blank=True)
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["regulatory_body", "form_code", "-version"]
        unique_together = ("regulatory_body", "form_code", "version")
        indexes = [
            models.Index(fields=["form_code", "active"]),
        ]

    def __str__(self):
        return f"{self.form_code} - {self.form_name}"


class DocumentRequirement(models.Model):
    pathway = models.ForeignKey(ApplicationPathway, on_delete=models.CASCADE, related_name="document_requirements")
    form_definition = models.ForeignKey(
        DynamicFormDefinition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_requirements",
    )
    document_type = models.ForeignKey(DocumentType, on_delete=models.SET_NULL, null=True, blank=True)
    document_type_code = models.CharField(max_length=80)
    label = models.CharField(max_length=255)
    required = models.BooleanField(default=True)
    required_for_applicant_type = models.CharField(max_length=60, blank=True)
    accepts_multiple = models.BooleanField(default=False)
    requires_certification = models.BooleanField(default=False)
    requires_translation = models.BooleanField(default=False)
    requires_expiry_date = models.BooleanField(default=False)
    requires_issue_date = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["pathway", "sort_order", "label"]
        unique_together = ("pathway", "document_type_code")
        indexes = [
            models.Index(fields=["document_type_code", "active"]),
        ]

    def __str__(self):
        return f"{self.pathway.pathway_code} - {self.label}"


# ====================== BASE PROFESSIONAL ======================

class BaseHealthProfessional(models.Model):
    APPLICANT_TYPE_CHOICES = [
        ('national', 'National'),
        ('overseas', 'Overseas'),
    ]
    TITLE_CHOICES = [
        ('Miss', 'Miss'),
        ('Ms', 'Ms'),
        ('Mrs', 'Mrs'),
        ('Mr', 'Mr'),
        ('Sr', 'Sr'),
        ('Dr', 'Dr'),
        ('Prof', 'Prof'),
    ]
    MARITAL_STATUS_CHOICES = [
        ('married', 'Married'),
        ('single', 'Single'),
        ('divorced', 'Divorced'),
        ('widow_widower', 'Widow/Widower'),
        ('other', 'Other'),
    ]

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['registration_number']),
            models.Index(fields=['registration_no']),
        ]

    title = models.CharField(max_length=20, choices=TITLE_CHOICES, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    applicant_type = models.CharField(max_length=20, choices=APPLICANT_TYPE_CHOICES, default='national')
    registration_no = models.CharField(max_length=50, unique=True, blank=True, null=True, db_column='Registration_No')
    gender = models.CharField(max_length=10, choices=[('Male', 'Male'), ('Female', 'Female')], blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    marital_status = models.CharField(max_length=30, choices=MARITAL_STATUS_CHOICES, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    primary_phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True)
    full_address = models.TextField(blank=True)
    province = models.CharField(max_length=100, blank=True)
    registration_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    passport_photo = models.ImageField(upload_to='profiles/passports/', blank=True, null=True)
    id_document_image = models.ImageField(upload_to='profiles/ids/', blank=True, null=True)
    cadre = models.ForeignKey(Cadre, on_delete=models.PROTECT, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def national_id(self):
        return self.registration_no

    @national_id.setter
    def national_id(self, value):
        self.registration_no = value


# ====================== SPECIFIC PROFESSIONALS ======================

class NursingProfessional(BaseHealthProfessional):
    qualification_level = models.CharField(max_length=100, blank=True)
    license_expiry_date = models.DateField(null=True, blank=True)
    date_issued = models.DateField(null=True, blank=True)


class Midwife(BaseHealthProfessional):
    qualification_level = models.CharField(max_length=100, blank=True)
    license_expiry_date = models.DateField(null=True, blank=True)
    date_issued = models.DateField(null=True, blank=True)


class MedicalDoctor(BaseHealthProfessional):
    specialty = models.CharField(max_length=150, blank=True)
    license_expiry_date = models.DateField(null=True, blank=True)
    date_issued = models.DateField(null=True, blank=True)


class CommunityHealthWorker(BaseHealthProfessional):
    community_id = models.CharField(max_length=50, blank=True)
    training_level = models.CharField(max_length=100, blank=True)


class NurseAide(BaseHealthProfessional):
    training_level = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=150, blank=True)


class HealthStudent(BaseHealthProfessional):
    program = models.CharField(max_length=150)
    institution = models.ForeignKey(TrainingInstitution, on_delete=models.SET_NULL, null=True, blank=True)
    expected_graduation_date = models.DateField(null=True, blank=True)
    is_graduate = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Graduand"
        verbose_name_plural = "Graduands"


# ====================== GENERIC BASE (CRITICAL FIX) ======================

class GenericProfessionalRelation(models.Model):
    """
    Centralized base to enforce indexing and consistency for GenericFK models.
    """
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)

    professional = GenericForeignKey('content_type', 'object_id')

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]


# ====================== RELATED MODELS ======================

class Qualification(GenericProfessionalRelation):
    qualification_name = models.CharField(max_length=200)
    institution = models.ForeignKey(TrainingInstitution, on_delete=models.SET_NULL, null=True, blank=True)
    institution_name = models.CharField(max_length=255, blank=True)
    program_completed = models.CharField(max_length=255, blank=True)
    date_started = models.DateField(null=True, blank=True)
    date_completed = models.DateField(null=True, blank=True)
    completion_year = models.IntegerField(null=True, blank=True)
    qualification_type = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    certificate_attached = models.BooleanField(default=False)
    transcript_attached = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.qualification_name} - {self.professional or 'Unknown'}"


class ProfessionalDocument(GenericProfessionalRelation):
    document_type = models.ForeignKey(DocumentType, on_delete=models.SET_NULL, null=True)
    document_label = models.CharField(max_length=150, blank=True)
    file = models.FileField(upload_to='documents/')
    is_attached = models.BooleanField(default=True)
    verification_signature = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document_type} - {self.professional or 'Unknown'}"


class PostingHistory(GenericProfessionalRelation):
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True)
    position_title = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.professional or 'Unknown'} at {self.facility}"


class CPDRecord(GenericProfessionalRelation):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='workforce_cpd_records')
    training_type = models.CharField(max_length=150)
    provider = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    hours_credits = models.FloatField(default=0)

    def __str__(self):
        return f"{self.professional or 'Unknown'} - {self.training_type}"


class CredentialVerification(GenericProfessionalRelation):
    """Board-verifiable credential evidence for a professional profile."""

    STATUS_CHOICES = [
        ('pending', 'Pending verification'),
        ('institution_check', 'Institution check'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    CREDENTIAL_TYPE_CHOICES = [
        ('qualification', 'Qualification'),
        ('specialist_certificate', 'Specialist certificate'),
        ('fellowship', 'Fellowship'),
        ('registration', 'Registration evidence'),
        ('cpd', 'CPD evidence'),
        ('other', 'Other evidence'),
    ]

    credential_type = models.CharField(max_length=40, choices=CREDENTIAL_TYPE_CHOICES, default='qualification')
    credential_title = models.CharField(max_length=255)
    issuing_institution = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=100, blank=True)
    reference_number = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True)
    evidence_summary = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_credentials',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'credential_title']
        indexes = [
            models.Index(fields=['content_type', 'object_id', 'status']),
            models.Index(fields=['credential_type', 'status']),
        ]

    def __str__(self):
        return f"{self.credential_title} - {self.get_status_display()}"


class ClinicalPrivilege(GenericProfessionalRelation):
    """A Medical Board-approved scope of clinical practice.

    Clinical privileges are explicit decisions, never inferred from a doctor's
    specialty or from an uploaded document.
    """

    STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('conditional', 'Approved with conditions'),
        ('suspended', 'Suspended'),
        ('revoked', 'Revoked'),
        ('expired', 'Expired'),
    ]

    privilege_name = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='requested', db_index=True)
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True, blank=True, related_name='clinical_privileges')
    effective_from = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    decision_reference = models.CharField(max_length=120, blank=True)
    conditions_summary = models.TextField(blank=True)
    evidence_summary = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_clinical_privileges',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['privilege_name', '-updated_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id', 'status']),
            models.Index(fields=['status', 'expiry_date']),
        ]

    def __str__(self):
        return f"{self.privilege_name} - {self.get_status_display()}"


class ProfessionalProfileUpdateRequest(GenericProfessionalRelation):
    """A professional-submitted change awaiting regulatory review.

    User input is stored as a proposal first.  It is only promoted into an
    official registry, employment, credential, CPD, or clinical-privilege
    record by an authorised office decision.
    """

    OFFICE_SCOPE_CHOICES = [
        ('nursing', 'Nursing Council'),
        ('medical', 'Medical Board'),
    ]
    UPDATE_TYPE_CHOICES = [
        ('contact', 'Contact details'),
        ('workplace', 'Current workplace'),
        ('qualification', 'Qualification or specialist credential'),
        ('cpd', 'CPD activity'),
        ('clinical_privilege', 'Clinical privilege'),
    ]
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('under_review', 'Under review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]

    office_scope = models.CharField(max_length=20, choices=OFFICE_SCOPE_CHOICES, db_index=True)
    update_type = models.CharField(max_length=40, choices=UPDATE_TYPE_CHOICES, db_index=True)
    proposed_changes = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    evidence = models.FileField(upload_to='profile_update_requests/%Y/%m/', blank=True, null=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='professional_profile_update_requests',
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='submitted', db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_professional_profile_update_requests',
    )
    reviewer_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['office_scope', 'status', 'submitted_at']),
            models.Index(fields=['content_type', 'object_id', 'status']),
        ]

    def __str__(self):
        return f"{self.get_update_type_display()} - {self.get_status_display()}"


class Application(GenericProfessionalRelation):
    FORM_CHOICES = [
        ('MD1', 'MD1 - Medical Registration'),
        ('MD2', 'MD2 - Medical Renewal'),
        ('CHW1', 'CHW1 - CHW Registration'),
        ('CHWP', 'CHWP - CHW Provisional Licence'),
        ('CHWF', 'CHWF - CHW Full Licence'),
        ('MBSP', 'MBSP - Medical Board Specialist Application'),
        ('MBRN', 'MBRN - Medical Board Renewal Registration'),
        ('MBAC', 'MBAC - Medical Board Facility Accreditation Checklist'),
        ('MBPF', 'MBPF - Medical Board Private Health Facility Checklist'),
        ('MBTC', 'MBTC - Medical Board Training College Facility Form'),
        ('G1', 'G1 - Graduate Nurses Checklist'),
        ('G2', 'G2 - List of New Graduate Nurses'),
        ('G3', 'G3 - Graduate Vitae'),
        ('G4', 'G4 - Statement of Competency (Nurses)'),
        ('G5', 'G5 - Statement of Competency (Midwives)'),
        ('G6', 'G6 - Graduate Midwives Checklist'),
        ('G7', 'G7 - List of Graduate Midwives'),
        ('NC1', 'NC1 - Application for Provisional Licence'),
        ('NC2', 'NC2 - Application for Full Licence'),
        ('NC3', 'NC3 - Renewal of Licence'),
        ('NC4', 'NC4 - Checklist for Provisional Licence'),
        ('NC5', 'NC5 - Full Registration & Licence'),
        ('NC6', 'NC6 - Competency for Full Licence Nursing'),
        ('NC7', 'NC7 - Competency for Full Licence Midwifery'),
        ('NC8', 'NC8 - Application for Temporary Licence'),
        ('NC9', 'NC9 - Temporary Licence to Practise Criteria for Overseas Nurses Checklist'),
        ('NC10', 'NC10 - Competency for Full Licence Child Nursing'),
        ('NC11', 'NC11 - Double Major Full Registration Checklist'),
        ('GD', 'GD'),
        ('PG', 'PG'),
    ]
    PATHWAY_CHOICES = [
        ('local_nursing_graduate', 'Local Nursing Graduate (PNG)'),
        ('local_midwifery_graduate', 'Local Midwifery Graduate (PNG)'),
        ('overseas_nurse', 'Overseas Nurse'),
        ('overseas_midwife', 'Overseas Midwife'),
        ('medical_board', 'Medical Board Practitioner'),
        ('medical_facility', 'Medical Board Facility'),
        ('medical_training', 'Medical Board Training Facility'),
        ('special_case', 'Special Case'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    form_code = models.CharField(max_length=20, choices=FORM_CHOICES)
    pathway = models.CharField(max_length=40, choices=PATHWAY_CHOICES, default='other')
    form_title = models.CharField(max_length=255, blank=True)
    profession_track = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    submitted_date = models.DateField(auto_now_add=True)
    approved_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    reviewer_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.form_code} - {self.professional or 'Unknown'}"


class ApplicationFormResponse(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="form_responses")
    form_code = models.CharField(max_length=20)
    form_version = models.CharField(max_length=30, default="2026.1")
    response_json = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_form_responses",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locked_form_responses",
    )

    class Meta:
        ordering = ["-submitted_at"]
        unique_together = ("application", "form_code", "form_version")

    def __str__(self):
        return f"{self.form_code} response for application {self.application_id}"


class ApplicationChecklistItem(models.Model):
    STATUS_CHOICES = [
        ("not_uploaded", "Not Uploaded"),
        ("uploaded", "Uploaded"),
        ("verification_pending", "Verification Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("waived", "Waived"),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="checklist_items")
    document_requirement = models.ForeignKey(DocumentRequirement, on_delete=models.PROTECT, related_name="checklist_items")
    document = models.ForeignKey(
        ProfessionalDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checklist_items",
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="not_uploaded")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["application", "document_requirement__sort_order"]
        unique_together = ("application", "document_requirement")
        indexes = [
            models.Index(fields=["application", "status"]),
        ]

    def __str__(self):
        return f"{self.application_id} - {self.document_requirement.label}"


class FeeSchedule(models.Model):
    regulatory_body = models.ForeignKey(RegulatoryBody, on_delete=models.CASCADE, related_name="fee_schedules")
    pathway = models.ForeignKey(ApplicationPathway, on_delete=models.SET_NULL, null=True, blank=True, related_name="fee_schedules")
    fee_rule_code = models.CharField(max_length=60)
    label = models.CharField(max_length=255)
    applicant_type = models.CharField(max_length=60, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="PGK")
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["regulatory_body", "fee_rule_code", "applicant_type"]
        unique_together = ("regulatory_body", "fee_rule_code", "applicant_type", "effective_from")

    def __str__(self):
        return f"{self.fee_rule_code} - {self.amount} {self.currency}"


class PolicyDocument(models.Model):
    regulatory_body = models.ForeignKey(RegulatoryBody, on_delete=models.CASCADE, related_name="policy_documents")
    code = models.CharField(max_length=80)
    title = models.CharField(max_length=255)
    document_url = models.TextField(blank=True)
    version = models.CharField(max_length=30, default="2026.1")
    effective_from = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["regulatory_body", "code", "-version"]
        unique_together = ("regulatory_body", "code", "version")

    def __str__(self):
        return f"{self.code} - {self.title}"


class DeclarationTemplate(models.Model):
    regulatory_body = models.ForeignKey(RegulatoryBody, on_delete=models.CASCADE, related_name="declaration_templates")
    code = models.CharField(max_length=80)
    title = models.CharField(max_length=255)
    declaration_text = models.TextField()
    required_for_pathway = models.ForeignKey(
        ApplicationPathway,
        on_delete=models.CASCADE,
        related_name="declaration_templates",
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["regulatory_body", "code"]
        unique_together = ("regulatory_body", "code", "required_for_pathway")

    def __str__(self):
        return f"{self.code} - {self.title}"


class ApplicantDeclaration(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="declarations")
    declaration_template = models.ForeignKey(DeclarationTemplate, on_delete=models.PROTECT, related_name="accepted_declarations")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        unique_together = ("application", "declaration_template")

    def __str__(self):
        return f"{self.declaration_template.code} accepted for {self.application_id}"


class ApplicationStatusHistory(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=40, blank=True)
    new_status = models.CharField(max_length=40)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    supporting_document = models.ForeignKey(ProfessionalDocument, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["application", "new_status"]),
        ]

    def __str__(self):
        return f"{self.application_id}: {self.old_status} -> {self.new_status}"


class EmployerVerificationRequest(GenericProfessionalRelation):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("rejected", "Rejected"),
        ("closed", "Closed"),
    ]

    application = models.ForeignKey(
        Application,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employer_verification_requests",
    )
    employer_name = models.CharField(max_length=255)
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True, blank=True)
    facility_name = models.CharField(max_length=255, blank=True)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employer_verification_requests",
    )
    request_type = models.CharField(max_length=80, default="registration_status")
    safe_result_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "employer_name"]),
        ]

    def __str__(self):
        return f"{self.employer_name} - {self.status}"


class SupervisorAssignment(GenericProfessionalRelation):
    STATUS_CHOICES = [
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="supervisor_assignments")
    employer_name = models.CharField(max_length=255, blank=True)
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True, blank=True)
    supervisor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supervisor_assignments",
    )
    supervisor_name = models.CharField(max_length=255)
    supervisor_registration_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="assigned")
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(fields=["status", "supervisor_registration_number"]),
        ]

    def __str__(self):
        return f"{self.supervisor_name} - {self.application_id}"


class DeceasedNotification(GenericProfessionalRelation):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    reported_by_facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True, blank=True)
    facility_name = models.CharField(max_length=255, blank=True)
    ward = models.CharField(max_length=255, blank=True)
    registration_number = models.CharField(max_length=100, blank=True, db_index=True)
    practitioner_number = models.CharField(max_length=100, blank=True, db_index=True)
    name_at_report = models.CharField(max_length=255)
    gender = models.CharField(max_length=20, blank=True)
    workforce_category = models.CharField(max_length=100, blank=True)
    date_of_death = models.DateField()
    date_removed_from_hcprs = models.DateField(null=True, blank=True)
    supporting_document = models.ForeignKey(ProfessionalDocument, on_delete=models.SET_NULL, null=True, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deceased_notifications_reported",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deceased_notifications_verified",
    )
    registrar_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deceased_notifications_approved",
    )
    verification_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["verification_status", "workforce_category"]),
            models.Index(fields=["registration_number", "verification_status"]),
        ]

    def __str__(self):
        return f"{self.name_at_report} - {self.verification_status}"


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    entity_type = models.CharField(max_length=120)
    entity_id = models.CharField(max_length=80, blank=True)
    old_values_json = models.JSONField(default=dict, blank=True)
    new_values_json = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "entity_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.action} - {self.entity_type}:{self.entity_id}"


# ====================== SNAPSHOT ======================

class WorkforceSnapshot(models.Model):
    year = models.PositiveIntegerField(unique=True)
    total_active_workers = models.PositiveIntegerField(default=0)
    total_nurses = models.PositiveIntegerField(default=0)
    total_doctors = models.PositiveIntegerField(default=0)
    total_midwives = models.PositiveIntegerField(default=0)
    total_chw = models.PositiveIntegerField(default=0)
    new_registrations = models.PositiveIntegerField(default=0)
    renewals = models.PositiveIntegerField(default=0)
    retirements = models.PositiveIntegerField(default=0)
    new_graduates_joined = models.PositiveIntegerField(default=0)
    nearing_retirement = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Snapshot {self.year}"


class ProfessionalPhoto(GenericProfessionalRelation):
    image = models.ImageField(upload_to='photos/professionals/', null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_primary = models.BooleanField(default=True)

    def __str__(self):
        return f"Photo for {self.professional}"

    class Meta:
        verbose_name = "Professional Photo"
        verbose_name_plural = "Professional Photos"


class EmploymentRecord(GenericProfessionalRelation):
    EMPLOYMENT_STATUS_CHOICES = [
        ('employed', 'Employed'),
        ('inactive', 'Inactive'),
        ('retired', 'Retired'),
        ('deceased', 'Deceased'),
        ('overseas', 'Overseas'),
        ('unknown', 'Unknown'),
        ('full_time', 'Full Time'),
        ('part_time', 'Part Time'),
        ('studying', 'Studying'),
        ('unemployed', 'Unemployed'),
        ('other', 'Other'),
    ]
    AREA_OF_EMPLOYMENT_CHOICES = [
        ('public', 'Public'),
        ('church', 'Church'),
        ('ngo', 'NGO'),
        ('overseas', 'Overseas'),
        ('unknown', 'Unknown'),
        ('government', 'Government'),
        ('private', 'Private'),
        ('other', 'Other'),
    ]
    EMPLOYMENT_SECTOR_CHOICES = [
        ('public', 'Public'),
        ('church', 'Church'),
        ('private', 'Private'),
        ('ngo', 'NGO'),
        ('overseas', 'Overseas'),
        ('unknown', 'Unknown'),
    ]
    REVIEW_STATUS_CHOICES = [
        ('staged', 'Staged'),
        ('accepted', 'Accepted'),
        ('promoted', 'Promoted'),
        ('rejected', 'Rejected'),
    ]

    employer_name = models.CharField(max_length=255, blank=True)
    employer_address = models.TextField(blank=True)
    position_held = models.CharField(max_length=255, blank=True)
    duration_of_employment = models.CharField(max_length=100, blank=True)
    employment_status = models.CharField(max_length=30, choices=EMPLOYMENT_STATUS_CHOICES, blank=True)
    area_of_employment = models.CharField(max_length=30, choices=AREA_OF_EMPLOYMENT_CHOICES, blank=True)
    employment_sector = models.CharField(max_length=30, choices=EMPLOYMENT_SECTOR_CHOICES, blank=True)
    occupation = models.CharField(max_length=255, blank=True)
    function_type = models.CharField(max_length=255, blank=True)
    place_of_work = models.CharField(max_length=255, blank=True)
    facility = models.ForeignKey(Facility, on_delete=models.SET_NULL, null=True, blank=True)
    facility_name_raw = models.CharField(max_length=255, blank=True)
    province = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    position_title = models.CharField(max_length=255, blank=True)
    workforce_function = models.CharField(max_length=255, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    source_type = models.CharField(max_length=80, blank=True)
    source_submission = models.CharField(max_length=100, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    source_sheet = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    review_status = models.CharField(max_length=30, choices=REVIEW_STATUS_CHOICES, blank=True)
    business_address = models.TextField(blank=True)
    business_number = models.CharField(max_length=50, blank=True)
    reasons_for_unemployment = models.TextField(blank=True)
    employer_reference_attached = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employer_name or 'Employment'} - {self.professional or 'Unknown'}"


class DataImportBatch(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    source_file_name = models.CharField(max_length=255)
    source_file_path = models.TextField(blank=True)
    source_kind = models.CharField(max_length=50, blank=True, default='workbook')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_sheets = models.PositiveIntegerField(default=0)
    processed_sheets = models.PositiveIntegerField(default=0)
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='workforce_import_batches',
    )

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.source_file_name} ({self.status})"


class ImportedWorkbookSheet(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
    ]

    batch = models.ForeignKey(DataImportBatch, on_delete=models.CASCADE, related_name='sheets')
    sheet_name = models.CharField(max_length=255)
    sheet_type = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    raw_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['id']
        unique_together = ('batch', 'sheet_name')

    def __str__(self):
        return f"{self.sheet_name} - {self.batch_id}"


class PracticingLicenseRecord(models.Model):
    RECORD_TYPE_CHOICES = [
        ('provisional', 'Provisional Registration'),
        ('full', 'Full-Licence Applicant'),
        ('full_approved', 'Full-Licence Approved'),
        ('temporary', 'Temporary Certificate'),
        ('practicing_license', 'Practicing License'),
        ('payment', 'Payment'),
        ('workforce_listing', 'Workforce Listing'),
        ('summary', 'Summary'),
    ]
    TARGET_MODEL_CHOICES = [
        ('nursingprofessional', 'Nursing Professional'),
        ('midwife', 'Midwife'),
        ('medicaldoctor', 'Medical Doctor'),
        ('communityhealthworker', 'Community Health Worker'),
        ('nurseaide', 'Nurse Aide'),
        ('healthstudent', 'Health Student'),
        ('other', 'Other'),
    ]

    batch = models.ForeignKey(DataImportBatch, on_delete=models.CASCADE, related_name='records')
    sheet = models.ForeignKey(
        ImportedWorkbookSheet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='records',
    )
    record_type = models.CharField(max_length=40, choices=RECORD_TYPE_CHOICES)
    target_model = models.CharField(max_length=40, choices=TARGET_MODEL_CHOICES, default='other')
    source_sheet_name = models.CharField(max_length=255)
    source_row = models.PositiveIntegerField(default=0)
    record_year = models.PositiveIntegerField(null=True, blank=True)
    full_name = models.CharField(max_length=255)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    registration_no = models.CharField(max_length=100, blank=True, db_index=True)
    practitioner_number = models.CharField(max_length=100, blank=True, db_index=True)
    applicant_type = models.CharField(max_length=20, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    qualification_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=150, blank=True, db_index=True)
    institution_name = models.CharField(max_length=255, blank=True)
    workplace_address = models.TextField(blank=True)
    province = models.CharField(max_length=120, blank=True, db_index=True)
    issued_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    renewal_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    overseas_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    penalty_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    reference_number = models.CharField(max_length=120, blank=True)
    payment_method = models.CharField(max_length=120, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-record_year', 'source_sheet_name', 'source_row']
        unique_together = ('batch', 'source_sheet_name', 'source_row', 'record_type')
        indexes = [
            models.Index(fields=['record_year', 'record_type']),
            models.Index(fields=['source_sheet_name', 'record_type']),
            models.Index(fields=['registration_no', 'record_year']),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.record_type} - {self.record_year or 'n/a'}"


class IssuedLicenceDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('authority_to_practice', 'Authority to Practice'),
        ('full_licence', 'Full Licence'),
        ('provisional_licence', 'Provisional Licence'),
        ('temporary_licence', 'Temporary Licence'),
    ]
    DELIVERY_CHOICES = [
        ('mailbox', 'Platform mailbox'),
        ('email', 'Direct email'),
        ('both', 'Mailbox and email'),
    ]
    STATUS_CHOICES = [
        ('generated', 'Generated'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='issued_documents')
    practicing_record = models.ForeignKey(
        PracticingLicenseRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_documents',
    )
    document_type = models.CharField(max_length=40, choices=DOCUMENT_TYPE_CHOICES)
    document_number = models.CharField(max_length=100, unique=True)
    file = models.FileField(upload_to='issued_licence_documents/%Y/%m/')
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_licence_documents',
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_licence_documents',
    )
    recipient_name = models.CharField(max_length=255, blank=True)
    recipient_email = models.EmailField(blank=True)
    delivery_channel = models.CharField(max_length=20, choices=DELIVERY_CHOICES, default='both')
    mailbox_thread = models.ForeignKey(
        'notifications.EnquiryThread',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_licence_documents',
    )
    email_sent = models.BooleanField(default=False)
    mailbox_sent = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generated')
    notes = models.TextField(blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-issued_at']
        indexes = [
            models.Index(fields=['document_type', 'issued_at']),
            models.Index(fields=['status', 'delivery_channel']),
        ]

    def __str__(self):
        return f"{self.get_document_type_display()} {self.document_number}"


class MissingDataReview(models.Model):
    STATUS_CHOICES = [
        ('under_review', 'Under Review'),
        ('notified', 'Notified'),
        ('resolved', 'Resolved'),
    ]
    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    record = GenericForeignKey('content_type', 'object_id')
    full_name = models.CharField(max_length=255, blank=True)
    registration_no = models.CharField(max_length=100, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    professional_type = models.CharField(max_length=80, blank=True, db_index=True)
    missing_fields = models.JSONField(default=list, blank=True)
    missing_count = models.PositiveIntegerField(default=0)
    source_label = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='under_review', db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium', db_index=True)
    notification_sent = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    notified_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-missing_count', 'professional_type', 'full_name']
        unique_together = ('content_type', 'object_id')
        indexes = [
            models.Index(fields=['status', 'professional_type']),
            models.Index(fields=['registration_no', 'status']),
        ]

    def __str__(self):
        return f"{self.full_name or self.registration_no or self.object_id} - {self.get_status_display()}"
