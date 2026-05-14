import re
from datetime import date, datetime, time
from decimal import Decimal

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from apps.competency.models import CompetencyAssessment
from apps.dashboard.models import Receipt

from .models import (
    Application,
    ApplicationFormResponse,
    CommunityHealthWorker,
    EmploymentRecord,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    ProfessionalDocument,
    ProfessionalPhoto,
    Qualification,
    TrainingInstitution,
)
from .services.institution_classification import classify_training_institution


TITLE_CHOICES = [
    ("Miss", "Miss"),
    ("Ms", "Ms"),
    ("Mrs", "Mrs"),
    ("Mr", "Mr"),
    ("Sr", "Sr"),
    ("Dr", "Dr"),
    ("Prof", "Prof"),
]

GENDER_CHOICES = [("Female", "Female"), ("Male", "Male")]

MARITAL_STATUS_CHOICES = [
    ("married", "Married"),
    ("single", "Single"),
    ("divorced", "Divorced"),
    ("widow_widower", "Widow/Widower"),
    ("other", "Other"),
]

NURSING_CATEGORY_CHOICES = [
    ("registered_nurse", "Registered Nurse"),
    ("midwife", "Midwife"),
    ("maternal_child_health", "Maternal Child Health"),
    ("paediatric_nurse", "Paediatric Nurse"),
    ("mental_health_nurse", "Mental Health Nurse"),
    ("enrolled_nurse", "Enrolled Nurse"),
    ("nurse_aide", "Nurse Aide"),
]

EMPLOYMENT_STATUS_CHOICES = EmploymentRecord.EMPLOYMENT_STATUS_CHOICES
AREA_OF_EMPLOYMENT_CHOICES = EmploymentRecord.AREA_OF_EMPLOYMENT_CHOICES

NURSING_COMPETENCY_CHOICES = [
    ("clinical", "Clinical Competence"),
    ("ethical", "Ethical and Professional Practice"),
    ("communication", "Communication and Teamwork"),
    ("patient_care", "Patient Care"),
    ("medication_administration", "Medication Administration"),
    ("documentation", "Documentation"),
]

MIDWIFERY_COMPETENCY_CHOICES = [
    ("antenatal_care", "Antenatal Care"),
    ("delivery_care", "Delivery Care"),
    ("postnatal_care", "Postnatal Care"),
    ("newborn_care", "Newborn Care"),
    ("emergency_obstetrics", "Emergency Obstetric Response"),
    ("ethical", "Ethical and Professional Practice"),
]

CHILD_NURSING_COMPETENCY_CHOICES = [
    ("paediatrics", "Paediatrics"),
    ("neonatal_care", "Neonatal Care"),
    ("child_assessment", "Child Assessment"),
    ("family_education", "Family Education"),
    ("emergency_response", "Emergency Response"),
    ("ethical", "Ethical and Professional Practice"),
]

DOUBLE_MAJOR_COMPETENCY_CHOICES = [
    ("nursing_major", "Nursing Major"),
    ("midwifery_major", "Midwifery Major"),
    ("maternal_child_health", "Maternal Child Health"),
    ("paediatrics", "Paediatrics"),
]

YES_NO_NA_CHOICES = [
    ("", "---------"),
    ("yes", "Yes"),
    ("no", "No"),
    ("na", "N/A"),
]

YES_NO_CHOICES = [
    ("", "---------"),
    ("yes", "Yes"),
    ("no", "No"),
]

QUALITY_PLACEHOLDER_VALUES = {
    "",
    "-",
    "--",
    "N/A",
    "NA",
    "NONE",
    "NULL",
    "UNKNOWN",
    "TBA",
    "TBD",
    "TEST",
    "DUMMY",
    "SAMPLE",
    "NOT AVAILABLE",
    "NOT APPLICABLE",
}
STRICT_REQUIRED_FIELD_NAMES = {
    "full_name",
    "first_name",
    "last_name",
    "applicant_type",
    "gender",
    "date_of_birth",
    "nationality",
    "contact_number",
    "primary_phone",
    "phone",
    "email",
    "email_address",
    "full_address",
    "province",
    "registration_no",
    "registration_number",
    "licence_number",
    "provisional_licence_number",
    "practitioner_no",
    "practitioner_number",
    "community_id",
    "training_level",
    "institution_attended",
    "institute_name",
    "program_completed",
    "date_of_completion",
    "employment_status",
    "applicant_signature",
    "declaration_acceptance",
}
FACILITY_REQUIRED_FIELD_NAMES = {
    "facility_name",
    "facility_owner",
    "ownership",
    "facility_level",
    "province",
    "district",
    "physical_address",
    "contact_person",
    "contact_number",
    "email_address",
    "services_offered",
    "staffing_summary",
    "equipment_and_supplies",
    "infection_control_measures",
    "emergency_readiness",
    "applicant_signature",
    "declaration",
    "applicant_full_name",
    "applicant_address",
    "operation_type",
    "premises_description",
    "declared_at",
    "oath_witness",
}
EMPLOYED_STATUSES_REQUIRING_DETAILS = {"full_time", "part_time", "other"}
EMPLOYMENT_DETAIL_FIELDS = ("employer_name", "name_of_employer", "place_of_work")
NAME_VALIDATION_FIELDS = {"full_name", "first_name", "last_name", "applicant_full_name", "contact_person"}
PUBLIC_PROFILE_REQUIRED_FIELDS = {
    "first_name",
    "last_name",
    "applicant_type",
    "registration_no",
    "gender",
    "primary_phone",
    "email",
    "passport_photo",
    "id_document_image",
}


def _clean_quality_text(value):
    return " ".join(str(value or "").strip().split())


def _is_quality_placeholder(value):
    return _clean_quality_text(value).upper() in QUALITY_PLACEHOLDER_VALUES


def _looks_like_invalid_name(value):
    text = _clean_quality_text(value)
    if not text:
        return False
    lower_text = text.lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", lower_text) if token}
    return (
        re.fullmatch(r"[\d\W_]+", text) is not None
        or bool(tokens & {"test", "dummy", "sample", "unknown"})
        or "listing starts here" in lower_text
        or lower_text in {"full name", "name of applicant", "total", "grand total"}
    )

MEDICAL_BOARD_PRACTITIONER_STREAM_CHOICES = [
    ("medical_practitioner", "Medical Practitioner"),
    ("dental_practitioner", "Dental Practitioner"),
]

MEDICAL_BOARD_SPECIALIST_CHOICES = [
    ("orthopaedics_surgery", "Specialist in Orthopaedics Surgery"),
    ("neurosurgery", "Specialist in Neurosurgery"),
    ("ophthalmology", "Specialist in Ophthalmology"),
    ("internal_medicine", "Specialist in Internal Medicine"),
    ("cardiology", "Specialist Cardiologist"),
    ("rural_general_practice", "Specialist in Rural General Practice"),
    ("psychology", "Specialist Psychologist"),
    ("human_resource_management_teaching", "Specialist in Human Resource Management & Teaching Education"),
    ("paediatric_child_health", "Specialist in Paediatric & Child Health"),
    ("sports_medicine_public_health", "Specialist in Sports Medicine & Public Health"),
    ("accident_emergency", "Specialist Accident & Emergency Program"),
    ("disease_control", "Specialist in Disease Control"),
    ("hiv_aids", "Specialist in HIV & AIDS"),
    ("psychiatry_mental_health", "Specialist Psychiatric (Mental Health)"),
    ("obstetrics_gynaecology", "Specialist Obstetrics & Gynaecology"),
    ("ent", "Specialist Ear, Nose & Throat (ENT)"),
    ("policy_planning_management", "Specialist Policy, Planning & Management"),
    ("rural_health_emergency", "Specialist in Rural Health Emergency"),
    ("hospital_administration_management", "Specialist Hospital Administration & Management"),
    ("dermatology", "Specialist Dermatologist"),
    ("public_health", "Specialist Public Health"),
    ("tropical_medicine", "Specialist Tropical Medicine"),
    ("radiology", "Specialist Radiologist"),
    ("oncology", "Specialist Oncologist"),
    ("pathology", "Specialist Pathologist"),
    ("microbiology", "Specialist Microbiologist"),
    ("general_surgery", "Specialist in General Surgery"),
    ("postgraduate_education_teaching", "Specialist in Education & Teaching of Postgraduate Studies"),
    ("public_health_aviation_emergency", "Specialist in Public Health & Aviation Emergency"),
    ("medical_physicist", "Medical Physicist"),
    ("other", "Other specialist category"),
]

MEDICAL_BOARD_APPLICATION_TYPE_CHOICES = [
    ("new_registration_certificate", "New registration for certificate to practice"),
    ("provisional_certificate", "Provisional certificate"),
    ("annual_renewal_certificate", "Annual renewal of certificate to practice"),
    ("restoration_certificate", "Restoration of certificate"),
    ("temporary_certificate", "Temporary certificate"),
    ("fees_waiver", "Fees waiver"),
    ("probational_certificate", "Probational certificate"),
]

MEDICAL_BOARD_PRACTITIONER_CATEGORY_CHOICES = [
    ("mbbs", "MBBS"),
    ("heo", "HEO"),
    ("anaesthetics_ato", "Anaesthetics/ATO"),
    ("mlt_mla_mt", "MLT/MLA (MT)"),
    ("radiographer_mit", "Radiographer (MIT)"),
    ("chw", "CHW"),
    ("occupational_health_safety_therapist", "Occupational Health & Safety Therapist"),
    ("dental_hygienist", "Dental Hygienist"),
    ("chiropractic_technologist", "Chiropractic Technologist"),
    ("dental_therapist", "Dental Therapist"),
    ("dental_technician_mechanician", "Dental Technician/Mechanician"),
    ("bds_dental_practitioner", "BDS (Dental Practitioner)"),
    ("specialist", "Specialist (MP/DP/AHW)"),
    ("eho", "EHO"),
    ("physiotherapist", "Physiotherapist"),
    ("nutritionist_dietitian", "Nutritionist/Dietitian"),
    ("speech_audiologist", "Speech Audiologist"),
    ("audiologist_hearing", "Audiologist or Hearing"),
    ("bio_scientist", "Bio-Scientist"),
    ("psychologist", "Psychologist"),
    ("optometrist_ophthalmic_clinician", "Optometrist/Ophthalmic Clinician (Eye Care)"),
    ("optician", "Opticians (Eye Glass)"),
    ("radiation_therapist", "Radiation Therapist"),
    ("audiologist_testing_hearing", "Audiologist (Testing and Hearing)"),
    ("paramedic", "Paramedic"),
    ("prosthetist_orthotist", "Prosthetist & Orthotist"),
    ("dental_nurse", "Dental Nurse"),
    ("social_worker", "Social Worker"),
    ("other", "Other"),
]

MEDICAL_BOARD_INITIAL_QUALIFICATION_CHOICES = [
    ("general_doctor", "General Doctor"),
    ("resident_health_extension_officer", "Resident Health Extension Officer"),
    ("anaesthetic_ato", "Anaesthetic/ATO"),
    ("resident_mlt_mla_mt", "Resident MLT/MLA/MT"),
    ("resident_radiographer_mit", "Resident Radiographer (MIT)"),
    ("community_health_worker", "Community Health Worker"),
    ("nutritionist_dietician", "Nutritionist/Dietician"),
    ("audiologist_testing_hearing", "Audiologist (Testing and Hearing)"),
    ("dental_therapist", "Dental Therapist"),
    ("resident_dental_practitioner", "Resident Dental Practitioner"),
    ("dental_technician", "Dental Technician"),
    ("resident_eho", "Resident EHO"),
    ("resident_physiotherapist", "Resident Physiotherapist"),
    ("dental_hygienist", "Dental Hygienist"),
    ("chiropractic_technologist", "Chiropractic Technologist"),
    ("optician_eye_glass", "Optician (Eye Glass)"),
    ("bio_scientist", "Bio-Scientist"),
    ("psychologist", "Psychologist"),
    ("optometrist_ophthalmic_clinician", "Optometrist/Ophthalmic Clinician (Eye Care)"),
    ("radiation_therapist", "Radiation Therapist"),
    ("speech_pathologist_audiologist", "Speech Pathologist & Audiologist"),
    ("prosthetist_orthotist", "Prosthetist & Orthotist"),
    ("other", "Other"),
]

MEDICAL_BOARD_WORKER_TYPE_CHOICES = [
    ("director", "Director"),
    ("professor", "Professor"),
    ("specialist_doctor", "Specialist Doctor"),
    ("specialist_dentist", "Specialist Dentist"),
    ("lecturer", "Lecturer"),
    ("provincial_administrator", "Provincial Administrator"),
    ("general_practitioner", "General Practitioner"),
    ("heo", "HEO"),
    ("other", "Other"),
]

MEDICAL_BOARD_APPLICATION_AREA_CHOICES = [
    ("government", "Government"),
    ("church", "Church"),
    ("private", "Private"),
    ("ngo", "NGOs"),
    ("unemployment", "Unemployment"),
    ("other", "Other"),
]

MEDICAL_BOARD_PLACE_OF_WORK_CHOICES = [
    ("department_health_statutory_body", "Department of Health/Statutory Body"),
    ("industrial_occupational_business", "Industrial/Occupational/Business Section"),
    ("agency_private_practice_clinic", "Agency/Private Practice/Private Clinic"),
    ("sub_health_centre", "Sub Health Centre"),
    ("university", "University"),
    ("hospital", "Hospital"),
    ("health_centre", "Health Centre"),
    ("urban_clinic", "Urban Clinic"),
    ("teaching_institute", "Teaching Institute"),
    ("not_employed", "Not Employed"),
    ("ngos", "NGOs"),
    ("aid_post", "Aid Post"),
    ("other", "Other"),
]

MEDICAL_BOARD_UNEMPLOYMENT_REASON_CHOICES = [
    ("position_not_available", "Position is not available"),
    ("marriage_child_family", "Marriage/Child Birth/Family Reason"),
    ("further_study", "To undertake further study"),
    ("employment_elsewhere", "Take employment elsewhere"),
    ("go_abroad", "To go abroad"),
    ("other", "Other"),
]

MEDICAL_BOARD_POSTGRAD_CHOICES = [
    ("obstetrics", "Obstetrics"),
    ("gynaecology", "Gynaecology"),
    ("dental_surgery", "Dental Surgery"),
    ("surgery_neurosurgery", "Surgery/Neurosurgery"),
    ("dermatology", "Dermatology"),
    ("cardiology", "Cardiology"),
    ("anaesthesiology", "Anaesthesiology"),
    ("psychiatry", "Psychiatry"),
    ("public_community_health", "Public/Community Health"),
    ("accident_emergency_medicine", "Accident & Emergency Medicine"),
    ("paediatric", "Paediatric"),
    ("pathology", "Pathology"),
    ("bio_science", "Bio-science"),
    ("ent", "ENT"),
    ("radiography", "Radiography"),
    ("ophthalmology", "Ophthalmology"),
    ("laboratory_technician", "Laboratory Technician"),
    ("laboratory_assistant", "Laboratory Assistant"),
    ("anaesthetic_technician", "Anaesthetic Technician"),
    ("physiotherapy", "Physiotherapy"),
    ("medical_imaging_technician", "Medical Imaging Technician"),
    ("health_extension_officer", "Health Extension Officer"),
    ("environmental_health_officer", "Environmental Health Officer"),
    ("oral_health", "Oral Health"),
    ("other", "Other"),
]

PRIVATE_HEALTH_CHECKLIST_CHOICES = [
    ("application_form", "1. Medical Board application form filled and Commissioner of Oaths signed"),
    ("clinic_name_signboard", "2. Proposed clinic/facility name and sign board details"),
    ("business_contacts", "3. Contact details, email, telephone and postal address"),
    ("location_address", "4. Facility location address, suburb, section, allotment, town/province"),
    ("clinic_services", "5. Type or nature of clinic services to establish/provide"),
    ("in_house_facilities", "6. In-house facilities and equipment list/floor plan"),
    ("medical_equipment_inventory", "7. Inventory of medical equipment, instruments and accessories"),
    ("qualified_staff", "8. Qualified trained health professionals, ATP/certificates and CVs"),
    ("ipa_irc_certificates", "9. IPA and IRC certificates attached"),
    ("company_profile", "10. Company profile, policies, guidelines, vision and goals"),
    ("pharmacy_dispensary", "11. Pharmacy or dispensary service requirements"),
    ("registration_fee", "12. Private health facility registration/application fee receipt"),
    ("other_documents", "13. Lease/ownership, building, fire, water and power certificates"),
    ("qualified_doctor_operation", "14. Diagnostic clinics operated by qualified doctors"),
    ("floor_plan", "15. Floor plan with service areas, toilets, x-ray, dental, admin and dispensary"),
]

ACCREDITATION_ACTIVITY_CHOICES = [
    ("general_information", "1. General information about the health training institution"),
    ("curriculum", "Part A. Curriculum"),
    ("teachers_residence", "2. Teachers residence"),
    ("classrooms", "3. Type of classroom"),
    ("audio_visual_aids", "4. Audio visual aids"),
    ("teacher_qualifications", "5. Teachers qualifications"),
    ("student_intake_ratio", "6. Ratio of student intake each year"),
    ("field_attachments", "7. Field attachments in hospitals, rural health centres and community health posts"),
    ("first_year_clo_meeting", "8. Meeting with first year students based on CLO"),
    ("second_year_clo_meeting", "9. Meeting with second year students based on CLO"),
    ("teachers_clinical_staff_meeting", "10. Meeting with teachers and clinical staff"),
    ("student_assessment", "11. Training institution student assessment per term or semester"),
    ("clinical_supervision", "12. Clinical staff and supervision from training institution"),
    ("final_assessment_committee", "13. Final assessment with pre-registration sub committee"),
    ("program_structure", "14. Structure of the training program or curriculum"),
    ("teaching_staff_performance", "15. Teaching staff performances"),
    ("head_of_training_institution", "16. Head of training institution"),
]

HSFC_REQUIREMENT_CHOICES = [
    ("formal_application", "1. Formal application filled"),
    ("fees_paid", "2. Fees paid"),
    ("company_profile", "3. Company profile"),
    ("irc_certificate", "4. IRC certificate"),
    ("ipa_certificate", "5. IPA certificate"),
    ("building_board", "6. Building Board certificate"),
    ("power_certificate", "7. Power certificate"),
    ("water_certificate", "8. Water/Eda Ranu certificate"),
    ("fire_certificate", "9. Fire certificate"),
    ("security_camera_guards", "10. Security camera/guards"),
    ("floor_plan", "11. Floor plan"),
    ("dental_chairs_certified", "12. Dental chairs commissioned and certified"),
]

HSFC_PURPOSE_CHOICES = [
    ("new_facility_license", "New facility for licence"),
    ("renewal_permanent_license", "Facility for renewal or permanent licence"),
]


def _payload_value(value):
    if hasattr(value, "name"):
        return value.name
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_payload_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _payload_value(item) for key, item in value.items()}
    return value


def _record_application_form_response(application):
    if not application.form_code:
        return
    ApplicationFormResponse.objects.update_or_create(
        application=application,
        form_code=application.form_code,
        form_version="2026.1",
        defaults={"response_json": _payload_value(application.payload or {})},
    )


def _add_checklist_status_fields(form, *, prefix, choices, required=False, include_comments=True):
    status_names = []
    comment_names = []
    for value, label in choices:
        status_name = f"{prefix}_{value}_status"
        form.fields[status_name] = forms.ChoiceField(
            choices=YES_NO_NA_CHOICES,
            required=required,
            label=label,
        )
        status_names.append(status_name)
        if include_comments:
            comment_name = f"{prefix}_{value}_comments"
            form.fields[comment_name] = forms.CharField(
                required=False,
                label=f"{label} - comments",
                widget=forms.Textarea(attrs={"rows": 2}),
            )
            comment_names.append(comment_name)
    return status_names, comment_names


def _split_name(full_name):
    tokens = (full_name or "").strip().split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return " ".join(tokens[:-1]), tokens[-1]


class SectionedFormMixin:
    form_sections = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_dynamic_fields()
        for name, field in self.fields.items():
            css_class = "form-control"
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.CheckboxSelectMultiple):
                css_class = "ndoh-checkbox-group"
            elif isinstance(field.widget, forms.ClearableFileInput):
                css_class = "form-control-file"
            elif isinstance(field.widget, forms.RadioSelect):
                css_class = "ndoh-radio-group"
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {css_class}".strip()
        form_code = getattr(self, "form_code", "")
        nursing_codes = {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}
        if "declaration_acceptance" in self.fields and not (form_code.startswith("NC") or form_code in nursing_codes):
            self.fields.pop("declaration_acceptance")
        self.apply_required_field_rules()
        form_sections = [(title, list(field_names)) for title, field_names in self.form_sections]
        placed_names = {name for _title, field_names in form_sections for name in field_names}
        if "applicant_type" in self.fields and "applicant_type" not in placed_names and form_sections:
            first_title, first_fields = form_sections[0]
            insert_at = first_fields.index("full_name") + 1 if "full_name" in first_fields else len(first_fields)
            first_fields.insert(insert_at, "applicant_type")
            form_sections[0] = (first_title, first_fields)
        self.section_layout = [
            {
                "title": title,
                "fields": [self[name] for name in field_names if name in self.fields],
            }
            for title, field_names in form_sections
        ]
        placed_fields = {name for _title, field_names in form_sections for name in field_names}
        remaining_fields = [
            self[name]
            for name in self.fields
            if name not in placed_fields and not self.fields[name].widget.is_hidden
        ]
        if remaining_fields:
            self.section_layout.append({
                "title": "Declarations and final confirmation",
                "fields": remaining_fields,
            })

    def add_dynamic_fields(self):
        return None

    def apply_required_field_rules(self):
        required_names = set(getattr(self, "quality_required_fields", STRICT_REQUIRED_FIELD_NAMES))
        if getattr(self, "pathway", "") in {"medical_facility", "medical_training"}:
            required_names.update(FACILITY_REQUIRED_FIELD_NAMES)
        for field_name in required_names:
            field = self.fields.get(field_name)
            if not field:
                continue
            field.required = True
            field.widget.attrs["aria-required"] = "true"
            if not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["required"] = "required"

    def clean(self):
        cleaned_data = super().clean()
        self._reject_placeholder_required_values(cleaned_data)
        self._validate_conditional_employment(cleaned_data)
        return cleaned_data

    def _reject_placeholder_required_values(self, cleaned_data):
        message = "Enter the correct information. Placeholders such as N/A, unknown, test, dummy, or sample are not accepted."
        for field_name, field in self.fields.items():
            if not field.required:
                continue
            value = cleaned_data.get(field_name)
            if isinstance(value, str) and _is_quality_placeholder(value):
                self.add_error(field_name, message)
            if field_name in NAME_VALIDATION_FIELDS and _looks_like_invalid_name(value):
                self.add_error(field_name, "Enter the applicant's real name.")

    def _validate_conditional_employment(self, cleaned_data):
        status = _clean_quality_text(cleaned_data.get("employment_status")).lower()
        if status not in EMPLOYED_STATUSES_REQUIRING_DETAILS:
            return
        for field_name in EMPLOYMENT_DETAIL_FIELDS:
            if field_name in self.fields and not cleaned_data.get(field_name):
                self.add_error(field_name, "Employer and workplace details are required for employed applicants.")


class CouncilApplicationForm(SectionedFormMixin, forms.Form):
    form_code = ""
    form_title = ""
    pathway = "other"
    profession_track = ""
    professional_model = None
    declaration_acceptance = forms.BooleanField(
        required=True,
        label="I confirm the information provided is true and I accept the Nursing Council Code of Ethics and Professional Conduct declarations.",
    )

    def save(self):
        with transaction.atomic():
            professional = self.save_professional()
            application = self.save_application(professional)
            self.save_related_records(professional, application)
            self.prepare_submission(application)
            return application

    def save_professional(self):
        model = self.get_professional_model()
        if model is None:
            return None

        full_name = self.cleaned_data.get("full_name") or " ".join(
            value for value in [
                self.cleaned_data.get("first_name", ""),
                self.cleaned_data.get("last_name", ""),
            ] if value
        ).strip()
        first_name = self.cleaned_data.get("first_name")
        last_name = self.cleaned_data.get("last_name")
        if not first_name and full_name:
            first_name, last_name = _split_name(full_name)

        registration_no = (
            self.cleaned_data.get("provisional_licence_number")
            or self.cleaned_data.get("registration_no")
            or self.cleaned_data.get("registration_number")
            or self.cleaned_data.get("licence_number")
            or None
        )
        email = self.cleaned_data.get("email_address") or self.cleaned_data.get("email") or ""

        professional = None
        if registration_no:
            professional = model.objects.filter(registration_no=registration_no).first()
        if professional is None and email:
            professional = model.objects.filter(email=email).first()
        if professional is None:
            professional = model()

        professional.first_name = first_name or professional.first_name or "Applicant"
        professional.last_name = last_name or professional.last_name or "Record"
        professional.middle_name = self.cleaned_data.get("middle_name", professional.middle_name)
        professional.title = self.cleaned_data.get("title", professional.title)
        professional.applicant_type = self.cleaned_data.get("applicant_type", professional.applicant_type or "national")
        professional.registration_no = registration_no or professional.registration_no
        professional.gender = self.cleaned_data.get("gender", professional.gender)
        professional.date_of_birth = self.cleaned_data.get("date_of_birth", professional.date_of_birth)
        professional.marital_status = self.cleaned_data.get("marital_status", professional.marital_status)
        professional.nationality = self.cleaned_data.get("nationality", professional.nationality)
        professional.primary_phone = self.cleaned_data.get("contact_number") or self.cleaned_data.get("phone") or professional.primary_phone
        professional.email = email or professional.email
        professional.full_address = self.cleaned_data.get("full_address", professional.full_address)
        professional.province = self.cleaned_data.get("province", professional.province)
        if self.cleaned_data.get("passport_photo"):
            professional.passport_photo = self.cleaned_data["passport_photo"]
        if self.cleaned_data.get("id_document_image"):
            professional.id_document_image = self.cleaned_data["id_document_image"]

        if isinstance(professional, HealthStudent):
            professional.program = self.cleaned_data.get("program_completed") or self.cleaned_data.get("program") or professional.program or "Nursing"
            professional.is_graduate = True
            institution = self._get_or_create_institution()
            if institution:
                professional.institution = institution
            professional.expected_graduation_date = self.cleaned_data.get("date_of_completion", professional.expected_graduation_date)

        if isinstance(professional, NursingProfessional):
            professional.qualification_level = self.cleaned_data.get("program_completed", professional.qualification_level)

        if isinstance(professional, Midwife):
            professional.qualification_level = self.cleaned_data.get("program_completed", professional.qualification_level)

        if isinstance(professional, MedicalDoctor):
            professional.specialty = self.cleaned_data.get("specialty", professional.specialty)
            professional.license_expiry_date = self.cleaned_data.get("license_expiry_date", professional.license_expiry_date)
            professional.date_issued = self.cleaned_data.get("date_issued", professional.date_issued)

        if isinstance(professional, CommunityHealthWorker):
            professional.community_id = self.cleaned_data.get("community_id", professional.community_id)
            professional.training_level = self.cleaned_data.get("training_level") or self.cleaned_data.get("program_completed", professional.training_level)

        professional.save()
        return professional

    def save_application(self, professional):
        application = Application(
            form_code=self.form_code,
            form_title=self.form_title,
            pathway=self.pathway,
            profession_track=self.profession_track,
            status="pending",
            reviewer_notes="Submitted via public portal",
            payload=self.build_payload(),
        )
        if professional is not None:
            application.content_type = ContentType.objects.get_for_model(professional)
            application.object_id = professional.pk
        application.save()
        return application

    def prepare_submission(self, application):
        if self.pathway in {"medical_board", "medical_facility", "medical_training"}:
            _record_application_form_response(application)
            return
        from .services.nursing_council_workflows import prepare_nursing_application_submission
        prepare_nursing_application_submission(application)

    def save_related_records(self, professional, application):
        if professional is None:
            return
        self._save_qualification(professional)
        self._save_employment(professional)
        self._save_competency(professional)
        self._save_documents(professional)
        self._save_payment(application)

    def build_payload(self):
        payload = {}
        for key, value in self.cleaned_data.items():
            payload[key] = _payload_value(value)
        return payload

    def get_professional_model(self):
        return self.professional_model

    def _get_or_create_institution(self):
        institute_name = self.cleaned_data.get("institution_attended") or self.cleaned_data.get("institute_name")
        if not institute_name:
            return None
        institution_type = classify_training_institution(institute_name)
        institution, created = TrainingInstitution.objects.get_or_create(
            name=institute_name,
            defaults={"type": institution_type},
        )
        if not created and institution.type != institution_type:
            institution.type = institution_type
            institution.save(update_fields=["type"])
        return institution

    def _save_qualification(self, professional):
        if not any(self.cleaned_data.get(name) for name in [
            "institution_attended", "institute_name", "program_completed",
            "date_of_completion", "dates_of_study", "date_started", "date_completed"
        ]):
            return

        institution = self._get_or_create_institution()
        qualification, _ = Qualification.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            qualification_name=self.cleaned_data.get("program_completed") or self.form_title,
        )
        qualification.institution = institution
        qualification.institution_name = (
            self.cleaned_data.get("institution_attended")
            or self.cleaned_data.get("institute_name")
            or qualification.institution_name
        )
        qualification.program_completed = self.cleaned_data.get("program_completed", qualification.program_completed)
        qualification.date_started = self.cleaned_data.get("date_started", qualification.date_started)
        qualification.date_completed = self.cleaned_data.get("date_of_completion") or self.cleaned_data.get("date_completed") or qualification.date_completed
        if qualification.date_completed:
            qualification.completion_year = qualification.date_completed.year
        qualification.qualification_type = self.cleaned_data.get("qualification_type", qualification.qualification_type)
        qualification.country = self.cleaned_data.get("country", qualification.country)
        qualification.certificate_attached = bool(self.cleaned_data.get("qualification_certificates"))
        qualification.transcript_attached = bool(self.cleaned_data.get("transcript"))
        qualification.save()

    def _save_employment(self, professional):
        employer_name = self.cleaned_data.get("employer_name") or self.cleaned_data.get("name_of_employer")
        if not employer_name and not self.cleaned_data.get("employment_status"):
            return
        EmploymentRecord.objects.create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            employer_name=employer_name or "",
            employer_address=self.cleaned_data.get("employer_address") or self.cleaned_data.get("business_address") or "",
            position_held=self.cleaned_data.get("position_held") or "",
            duration_of_employment=self.cleaned_data.get("duration_of_employment") or "",
            employment_status=self.cleaned_data.get("employment_status") or "",
            area_of_employment=self.cleaned_data.get("area_of_employment") or "",
            occupation=self.cleaned_data.get("occupation") or "",
            function_type=self.cleaned_data.get("function_type") or "",
            place_of_work=self.cleaned_data.get("place_of_work") or "",
            business_address=self.cleaned_data.get("business_address") or "",
            business_number=self.cleaned_data.get("business_number") or "",
            reasons_for_unemployment=self.cleaned_data.get("reasons_for_unemployment") or "",
            employer_reference_attached=bool(self.cleaned_data.get("employer_reference")),
        )

    def _save_competency(self, professional):
        domains = self.cleaned_data.get("competency_domains")
        if not domains and not self.cleaned_data.get("supervisor_assessment"):
            return
        CompetencyAssessment.objects.create(
            content_type=ContentType.objects.get_for_model(professional),
            object_id=professional.pk,
            assessment_name=self.form_title,
            assessment_type="council_form",
            form_code=self.form_code,
            profession_track=self.profession_track,
            competency_domains=domains or [],
            supervisor_name=self.cleaned_data.get("supervisor_name") or self.cleaned_data.get("supervisor_details") or "",
            supervisor_assessment=self.cleaned_data.get("supervisor_assessment") or "",
            supervisor_signature=self.cleaned_data.get("supervisor_signature") or "",
            verification_signature=self.cleaned_data.get("verification_signature") or "",
            assessment_date=self.cleaned_data.get("assessment_date") or self.cleaned_data.get("date") or self.cleaned_data.get("date_of_graduation"),
            score=0,
            is_passed=True,
        )

    def _save_documents(self, professional):
        for field_name, label in [
            ("passport_copy", "Passport Copy"),
            ("qualification_certificates", "Qualification Certificates"),
            ("transcript", "Transcript"),
            ("employer_reference", "Employer Reference"),
            ("competency_evidence", "Competency Evidence"),
            ("continuing_practice_evidence", "Continuing Practice Evidence"),
            ("verification_stamp", "Verification Stamp"),
            ("certificate_transcript_attached", "Certificate or Transcript Attached"),
            ("institute_certification", "Institute Certification"),
            ("dual_qualification_evidence", "Dual Qualification Evidence"),
            ("dual_major_competency_evidence", "Competency Evidence for Both Majors"),
        ]:
            uploaded = self.cleaned_data.get(field_name)
            if not uploaded:
                continue
            ProfessionalDocument.objects.create(
                content_type=ContentType.objects.get_for_model(professional),
                object_id=professional.pk,
                document_type=None,
                document_label=label,
                file=uploaded,
                is_attached=True,
                verification_signature=self.cleaned_data.get("verification_signature") or "",
            )

    def _save_payment(self, application):
        amount = self.cleaned_data.get("amount")
        if amount in (None, ""):
            return
        Receipt.objects.create(
            receipt_number="",
            official_receipt_no=self.cleaned_data.get("official_receipt_number") or None,
            amount=amount,
            description=f"{self.form_code} payment for application {application.pk}",
            status="pending",
            payment_method="office",
            application=application,
            officer_receiving=self.cleaned_data.get("officer_receiving") or "",
            provincial_treasury_office=self.cleaned_data.get("provincial_treasury_office_payment_made") or "",
            atp_number=self.cleaned_data.get("atp_number") or "",
            payment_stamp=self.cleaned_data.get("stamp") or "",
            practitioner_number=self.cleaned_data.get("practitioner_number") or "",
        )


class ApplicantMediaRequiredMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in PUBLIC_PROFILE_REQUIRED_FIELDS:
            field = self.fields.get(field_name)
            if not field:
                continue
            field.required = True
            field.widget.attrs["aria-required"] = "true"
            field.widget.attrs["required"] = "required"

    def clean(self):
        cleaned_data = super().clean()
        if "passport_photo" in self.fields and not cleaned_data.get("passport_photo"):
            self.add_error("passport_photo", "Passport photo is required for applicants.")
        if "id_document_image" in self.fields and not cleaned_data.get("id_document_image"):
            self.add_error("id_document_image", "Valid ID is required for applicants.")
        message = "Enter the correct information. Placeholders such as N/A, unknown, test, dummy, or sample are not accepted."
        for field_name in PUBLIC_PROFILE_REQUIRED_FIELDS:
            if field_name not in self.fields:
                continue
            value = cleaned_data.get(field_name)
            if isinstance(value, str) and _is_quality_placeholder(value):
                self.add_error(field_name, message)
            if field_name in NAME_VALIDATION_FIELDS and _looks_like_invalid_name(value):
                self.add_error(field_name, "Enter the applicant's real name.")
        return cleaned_data


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [
            "form_code",
            "pathway",
            "form_title",
            "profession_track",
            "status",
            "approved_date",
            "expiry_date",
            "reviewer_notes",
        ]
        widgets = {
            "approved_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
            "reviewer_notes": forms.Textarea(attrs={"rows": 4}),
        }


class NursingPublicRegistrationForm(ApplicantMediaRequiredMixin, forms.ModelForm):
    class Meta:
        model = NursingProfessional
        fields = [
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "applicant_type",
            "registration_no",
            "gender",
            "nationality",
            "primary_phone",
            "email",
            "date_of_birth",
            "full_address",
            "province",
            "passport_photo",
            "id_document_image",
            "qualification_level",
        ]


class NursingFullLicenseForm(NursingPublicRegistrationForm):
    pass


class NursingRenewalForm(NursingPublicRegistrationForm):
    pass


class ChwPublicRegistrationForm(ApplicantMediaRequiredMixin, forms.ModelForm):
    class Meta:
        model = CommunityHealthWorker
        fields = [
            "first_name",
            "last_name",
            "applicant_type",
            "registration_no",
            "gender",
            "primary_phone",
            "email",
            "passport_photo",
            "id_document_image",
            "community_id",
            "training_level",
        ]


class MedicalDoctorPublicRegistrationForm(ApplicantMediaRequiredMixin, forms.ModelForm):
    class Meta:
        model = MedicalDoctor
        fields = [
            "first_name",
            "last_name",
            "applicant_type",
            "registration_no",
            "gender",
            "primary_phone",
            "email",
            "passport_photo",
            "id_document_image",
            "specialty",
            "license_expiry_date",
            "date_issued",
        ]


class HealthStudentPublicRegistrationForm(ApplicantMediaRequiredMixin, forms.ModelForm):
    class Meta:
        model = HealthStudent
        fields = [
            "first_name",
            "last_name",
            "applicant_type",
            "registration_no",
            "gender",
            "primary_phone",
            "email",
            "passport_photo",
            "id_document_image",
            "program",
            "institution",
            "expected_graduation_date",
            "is_graduate",
        ]


class NurseAidePublicRegistrationForm(ApplicantMediaRequiredMixin, forms.ModelForm):
    class Meta:
        model = NurseAide
        fields = [
            "first_name",
            "last_name",
            "applicant_type",
            "registration_no",
            "gender",
            "primary_phone",
            "email",
            "passport_photo",
            "id_document_image",
            "training_level",
            "employer",
        ]


class ImportForm(forms.Form):
    file = forms.FileField(
        label="Upload Excel or CSV File",
        help_text="Supported formats: .xlsx, .xls, .csv",
    )


class QualificationForm(forms.ModelForm):
    class Meta:
        model = Qualification
        fields = [
            "qualification_name",
            "institution",
            "institution_name",
            "program_completed",
            "date_started",
            "date_completed",
            "completion_year",
            "qualification_type",
            "country",
            "certificate_attached",
            "transcript_attached",
        ]


class ProfessionalPhotoForm(forms.ModelForm):
    class Meta:
        model = ProfessionalPhoto
        fields = ["image", "is_primary"]


class ProfessionalDocumentForm(forms.ModelForm):
    class Meta:
        model = ProfessionalDocument
        fields = ["document_type", "document_label", "file", "verification_signature"]


class BaseProfileFieldsForm(CouncilApplicationForm):
    title = forms.ChoiceField(choices=TITLE_CHOICES, required=False)
    full_name = forms.CharField(max_length=255)
    applicant_type = forms.ChoiceField(choices=[("national", "National"), ("overseas", "Overseas")])
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    gender = forms.ChoiceField(choices=GENDER_CHOICES, required=False)
    nationality = forms.CharField(max_length=100, required=False)
    contact_number = forms.CharField(max_length=50, required=False)
    email_address = forms.EmailField(required=False)
    passport_photo = forms.ImageField(required=False)
    id_document_image = forms.ImageField(required=False)
    full_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    province = forms.CharField(max_length=100, required=False)
    applicant_signature = forms.CharField(max_length=255, required=False)
    assessment_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    verification_signature = forms.CharField(max_length=255, required=False)


class QualificationFieldsForm(BaseProfileFieldsForm):
    institution_attended = forms.CharField(max_length=255, required=False)
    institute_name = forms.CharField(max_length=255, required=False)
    program_completed = forms.CharField(max_length=255, required=False)
    program_length = forms.CharField(max_length=100, required=False)
    date_of_completion = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    certificate_transcript_attached = forms.FileField(required=False)
    qualification_certificates = forms.FileField(required=False)
    transcript = forms.FileField(required=False)
    date_started = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_completed = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    country = forms.CharField(max_length=100, required=False)


class EmploymentFieldsForm(QualificationFieldsForm):
    licence_number = forms.CharField(max_length=100, required=False)
    employer_name = forms.CharField(max_length=255, required=False)
    employer_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    position_held = forms.CharField(max_length=255, required=False)
    duration_of_employment = forms.CharField(max_length=100, required=False)
    employment_status = forms.ChoiceField(choices=[("", "---------")] + EMPLOYMENT_STATUS_CHOICES, required=False)
    area_of_employment = forms.ChoiceField(choices=[("", "---------")] + AREA_OF_EMPLOYMENT_CHOICES, required=False)
    occupation = forms.CharField(max_length=255, required=False)
    function_type = forms.CharField(max_length=255, required=False)
    place_of_work = forms.CharField(max_length=255, required=False)
    business_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    business_number = forms.CharField(max_length=50, required=False)
    reasons_for_unemployment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    employer_reference = forms.FileField(required=False)
    continuing_practice_evidence = forms.FileField(required=False)


class CompetencyFieldsForm(EmploymentFieldsForm):
    competency_domains = forms.MultipleChoiceField(
        choices=NURSING_COMPETENCY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    supervisor_name = forms.CharField(max_length=255, required=False)
    supervisor_assessment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    supervisor_signature = forms.CharField(max_length=255, required=False)
    verification_signature = forms.CharField(max_length=255, required=False)
    verification_stamp = forms.FileField(required=False)
    competency_evidence = forms.FileField(required=False)
    assessment_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    applicant_signature = forms.CharField(max_length=255, required=False)


class GraduateNursesChecklistForm(QualificationFieldsForm):
    form_code = "G1"
    form_title = "Graduate Nurses Checklist"
    pathway = "local_nursing_graduate"
    profession_track = "nursing"
    professional_model = HealthStudent
    form_sections = [
        ("Section A: Institute Details", ["institute_name", "program_completed", "date_of_completion"]),
        ("Section B: Graduate Details", ["full_name", "verification_stamp"]),
    ]

    verification_stamp = forms.FileField(required=True)


class GraduateNurseBatchListForm(CouncilApplicationForm):
    form_code = "G2"
    form_title = "List of New Graduate Nurses for Provisional Licence"
    pathway = "local_nursing_graduate"
    profession_track = "nursing"
    form_sections = [
        ("Section A: Institute Certification", ["institute_name", "date_of_graduation"]),
        ("Section B: Graduate Batch List", ["graduate_batch_list", "institute_certification"]),
    ]

    institute_name = forms.CharField(max_length=255)
    date_of_graduation = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    graduate_batch_list = forms.CharField(label="Graduate Names (Batch List)", widget=forms.Textarea(attrs={"rows": 6}))
    institute_certification = forms.FileField()


class GraduateVitaeForm(CompetencyFieldsForm):
    form_code = "G3"
    form_title = "Graduate Vitae"
    pathway = "local_nursing_graduate"
    profession_track = "nursing_midwifery"
    professional_model = HealthStudent
    form_sections = [
        ("Part A: Personal Details", ["full_name", "date_of_birth", "contact_number", "email_address"]),
        ("Part B: Education History", ["institution_attended", "program_completed", "program_length", "date_started", "date_completed"]),
        ("Part C: Clinical Placements", ["clinical_placements", "supervisor_name"]),
        ("Part D: Skills Log Summary", ["skills_log_summary", "verification_signature"]),
    ]

    clinical_placements = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    skills_log_summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))


class NurseCompetencyStatementForm(CompetencyFieldsForm):
    form_code = "G4"
    form_title = "Statement of Competency (Nurses)"
    pathway = "local_nursing_graduate"
    profession_track = "nursing"
    professional_model = NursingProfessional
    form_sections = [
        ("Section A: Graduate Information", ["full_name", "program_completed"]),
        ("Section B: Competency Domains", ["competency_domains", "supervisor_assessment"]),
        ("Section C: Verification", ["supervisor_signature", "assessment_date"]),
    ]

    competency_domains = forms.MultipleChoiceField(
        choices=NURSING_COMPETENCY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )


class MidwifeCompetencyStatementForm(CompetencyFieldsForm):
    form_code = "G5"
    form_title = "Statement of Competency (Midwives)"
    pathway = "local_midwifery_graduate"
    profession_track = "midwifery"
    professional_model = Midwife
    form_sections = [
        ("Section A: Graduate Information", ["full_name", "program_completed"]),
        ("Section B: Competency Domains", ["competency_domains", "supervisor_assessment"]),
        ("Section C: Verification", ["supervisor_signature", "assessment_date"]),
    ]

    competency_domains = forms.MultipleChoiceField(
        choices=MIDWIFERY_COMPETENCY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )


class GraduateMidwivesChecklistForm(QualificationFieldsForm):
    form_code = "G6"
    form_title = "Graduate Midwives Checklist"
    pathway = "local_midwifery_graduate"
    profession_track = "midwifery"
    professional_model = HealthStudent
    form_sections = [
        ("Section A: Institute Details", ["institute_name", "program_completed", "date_of_completion"]),
        ("Section B: Graduate Details", ["full_name", "verification_stamp"]),
    ]

    verification_stamp = forms.FileField(required=True)


class GraduateMidwifeBatchListForm(CouncilApplicationForm):
    form_code = "G7"
    form_title = "List of Graduate Midwives for Licence to Practise"
    pathway = "local_midwifery_graduate"
    profession_track = "midwifery"
    form_sections = [
        ("Section A: Institute Certification", ["institute_name", "date_of_graduation"]),
        ("Section B: Graduate Batch List", ["graduate_batch_list", "institute_certification"]),
    ]

    institute_name = forms.CharField(max_length=255)
    date_of_graduation = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    graduate_batch_list = forms.CharField(label="Graduate Names (Batch List)", widget=forms.Textarea(attrs={"rows": 6}))
    institute_certification = forms.FileField()


class NC1ProvisionalLicenceForm(QualificationFieldsForm):
    form_code = "NC1"
    form_title = "Application for Provisional Licence"
    pathway = "local_nursing_graduate"
    profession_track = "nursing_midwifery"
    professional_model = NursingProfessional
    form_sections = [
        ("Part A: Personal Details", ["full_name", "date_of_birth", "gender", "nationality", "contact_number", "email_address"]),
        ("Part B: Qualification Details", ["institution_attended", "program_completed", "date_of_completion", "certificate_transcript_attached"]),
        ("Part C: Supporting Documents Checklist", ["passport_copy", "qualification_certificates", "transcript", "employer_reference", "competency_evidence"]),
        ("Part D: Declaration & Signature", ["applicant_signature", "assessment_date", "verification_stamp"]),
    ]

    passport_copy = forms.FileField(required=True)
    qualification_certificates = forms.FileField(required=True)
    transcript = forms.FileField(required=True)
    employer_reference = forms.FileField(required=False)
    competency_evidence = forms.FileField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        program = (cleaned_data.get("program_completed") or "").lower()
        if "midwif" in program:
            self.pathway = "local_midwifery_graduate" if cleaned_data.get("applicant_type", "national") == "national" else "overseas_midwife"
            self.profession_track = "midwifery"
            self.professional_model = Midwife
        else:
            self.pathway = "local_nursing_graduate" if cleaned_data.get("applicant_type", "national") == "national" else "overseas_nurse"
            self.profession_track = "nursing"
            self.professional_model = NursingProfessional
        return cleaned_data


class NC2FullLicenceForm(CompetencyFieldsForm):
    form_code = "NC2"
    form_title = "Application for Full Licence"
    pathway = "local_nursing_graduate"
    profession_track = "nursing_midwifery"
    professional_model = NursingProfessional
    form_sections = [
        ("Part A: Applicant Details", ["full_name", "provisional_licence_number", "contact_number", "email_address"]),
        ("Part B: Competency Evidence", ["supervisor_assessment", "competency_domains", "supervisor_signature", "assessment_date"]),
        ("Part C: Employer Details", ["employer_name", "employer_address", "position_held", "duration_of_employment"]),
        ("Part D: Declaration", ["applicant_signature", "assessment_date"]),
    ]

    provisional_licence_number = forms.CharField(max_length=100)


class NC3RenewalLicenceForm(EmploymentFieldsForm):
    form_code = "NC3"
    form_title = "Application for Renewal of Licence to Practise"
    pathway = "other"
    profession_track = "nursing_midwifery"
    professional_model = NursingProfessional
    form_sections = [
        ("Part A: Personal Details", ["title", "full_name", "licence_number", "date_of_birth", "marital_status", "nationality", "gender", "contact_number", "email_address"]),
        ("Part B: Application Details", ["nursing_categories"]),
        ("Part C: Employment Details", ["employment_status", "area_of_employment", "name_of_employer", "occupation", "function_type", "place_of_work", "business_address", "business_number", "reasons_for_unemployment", "continuing_practice_evidence"]),
        ("Part D: Post-Graduate Qualifications", ["qualification_type_1", "program_title_1", "pg_date_started_1", "pg_date_completed_1", "pg_institution_1", "country_1"]),
        ("Part E: Payment Details (Office Use Only)", ["official_receipt_number", "amount", "assessment_date", "officer_receiving", "provincial_treasury_office_payment_made", "atp_number", "stamp", "practitioner_number"]),
        ("Final Section", ["full_address", "province", "applicant_signature", "assessment_date"]),
    ]

    marital_status = forms.ChoiceField(choices=MARITAL_STATUS_CHOICES)
    nursing_categories = forms.MultipleChoiceField(choices=NURSING_CATEGORY_CHOICES, widget=forms.CheckboxSelectMultiple)
    name_of_employer = forms.CharField(max_length=255, required=False)
    qualification_type_1 = forms.CharField(max_length=100, required=False)
    program_title_1 = forms.CharField(max_length=255, required=False)
    pg_date_started_1 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    pg_date_completed_1 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    pg_institution_1 = forms.CharField(max_length=255, required=False)
    country_1 = forms.CharField(max_length=100, required=False)
    official_receipt_number = forms.CharField(max_length=100, required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    officer_receiving = forms.CharField(max_length=255, required=False)
    provincial_treasury_office_payment_made = forms.CharField(max_length=255, required=False)
    atp_number = forms.CharField(max_length=100, required=False)
    stamp = forms.CharField(max_length=255, required=False)
    practitioner_number = forms.CharField(max_length=100, required=False)

    def _save_payment(self, application):
        amount = self.cleaned_data.get("amount")
        if amount in (None, ""):
            return
        Receipt.objects.create(
            receipt_number="",
            official_receipt_no=self.cleaned_data.get("official_receipt_number") or None,
            amount=amount,
            description=f"NC3 Renewal payment for application {application.pk}",
            status="pending",
            payment_method="office",
            application=application,
            officer_receiving=self.cleaned_data.get("officer_receiving") or "",
            provincial_treasury_office=self.cleaned_data.get("provincial_treasury_office_payment_made") or "",
            atp_number=self.cleaned_data.get("atp_number") or "",
            payment_stamp=self.cleaned_data.get("stamp") or "",
            practitioner_number=self.cleaned_data.get("practitioner_number") or "",
        )


class NC4ProvisionalChecklistForm(QualificationFieldsForm):
    form_code = "NC4"
    form_title = "Checklist for Provisional Licence"
    pathway = "overseas_nurse"
    profession_track = "overseas"
    professional_model = NursingProfessional
    form_sections = [
        ("Required Attachments", ["passport_copy", "qualification_certificates", "transcript", "employer_reference", "competency_evidence", "verification_signature"]),
    ]

    passport_copy = forms.FileField(required=True)
    qualification_certificates = forms.FileField(required=True)
    transcript = forms.FileField(required=True)
    employer_reference = forms.FileField(required=True)
    competency_evidence = forms.FileField(required=True)
    verification_signature = forms.CharField(max_length=255)


class NC5OverseasFullRegistrationForm(CompetencyFieldsForm):
    form_code = "NC5"
    form_title = "Application for Full Registration & Licence"
    pathway = "overseas_nurse"
    profession_track = "overseas"
    professional_model = NursingProfessional
    form_sections = [
        ("Part A: Applicant Details", ["full_name", "nationality", "contact_number", "email_address"]),
        ("Part B: Qualification Details", ["institution_attended", "program_completed", "date_of_completion"]),
        ("Part C: Competency Evidence", ["supervisor_assessment", "competency_domains", "competency_evidence"]),
        ("Part D: Employer Details", ["employer_name", "employer_address", "position_held"]),
        ("Part E: Declaration", ["applicant_signature", "assessment_date"]),
    ]

    qualification_certificates = forms.FileField(required=True)
    competency_evidence = forms.FileField(required=True)

    def clean(self):
        cleaned_data = super().clean()
        program = (cleaned_data.get("program_completed") or "").lower()
        if "midwif" in program:
            self.pathway = "overseas_midwife"
            self.profession_track = "midwifery"
            self.professional_model = Midwife
            self.fields["competency_domains"].choices = MIDWIFERY_COMPETENCY_CHOICES
        else:
            self.pathway = "overseas_nurse"
            self.profession_track = "nursing"
            self.professional_model = NursingProfessional
        return cleaned_data


class NC6NursingCompetencyForm(CompetencyFieldsForm):
    form_code = "NC6"
    form_title = "Competency for Full Licence Nursing"
    pathway = "local_nursing_graduate"
    profession_track = "nursing"
    professional_model = NursingProfessional
    form_sections = [
        ("Required Fields", ["full_name", "competency_domains", "supervisor_assessment", "supervisor_signature", "assessment_date"]),
    ]

    competency_domains = forms.MultipleChoiceField(choices=NURSING_COMPETENCY_CHOICES, widget=forms.CheckboxSelectMultiple)


class NC7MidwiferyCompetencyForm(CompetencyFieldsForm):
    form_code = "NC7"
    form_title = "Competency for Full Licence Midwifery"
    pathway = "local_midwifery_graduate"
    profession_track = "midwifery"
    professional_model = Midwife
    form_sections = [
        ("Required Fields", ["full_name", "competency_domains", "supervisor_assessment", "supervisor_signature", "assessment_date"]),
    ]

    competency_domains = forms.MultipleChoiceField(choices=MIDWIFERY_COMPETENCY_CHOICES, widget=forms.CheckboxSelectMultiple)


class NC8TemporaryLicenceForm(EmploymentFieldsForm):
    form_code = "NC8"
    form_title = "Application for Temporary Licence"
    pathway = "overseas_nurse"
    profession_track = "temporary"
    professional_model = NursingProfessional
    form_sections = [
        ("Applicant Details", ["full_name", "nationality", "contact_number", "email_address"]),
        ("Qualification Details", ["institution_attended", "program_completed", "date_of_completion"]),
        ("Employer Details", ["employer_name", "employer_address", "position_held"]),
        ("Duration Requested", ["duration_requested"]),
        ("Signature & Date", ["applicant_signature", "assessment_date"]),
    ]

    duration_requested = forms.CharField(max_length=100)


class NC9TemporaryChecklistForm(QualificationFieldsForm):
    form_code = "NC9"
    form_title = "Checklist for Temporary Licence"
    pathway = "overseas_nurse"
    profession_track = "temporary"
    professional_model = NursingProfessional
    form_sections = [
        ("Required Attachments", ["passport_copy", "qualification_certificates", "employer_reference", "competency_evidence"]),
    ]

    passport_copy = forms.FileField(required=True)
    qualification_certificates = forms.FileField(required=True)
    employer_reference = forms.FileField(required=True)
    competency_evidence = forms.FileField(required=True)


class NC10ChildNursingCompetencyForm(CompetencyFieldsForm):
    form_code = "NC10"
    form_title = "Competency for Full Licence Child Nursing"
    pathway = "overseas_nurse"
    profession_track = "child_nursing"
    professional_model = NursingProfessional
    form_sections = [
        ("Required Fields", ["full_name", "competency_domains", "supervisor_assessment", "supervisor_signature", "assessment_date"]),
    ]

    competency_domains = forms.MultipleChoiceField(choices=CHILD_NURSING_COMPETENCY_CHOICES, widget=forms.CheckboxSelectMultiple)


class NC11DoubleMajorChecklistForm(CompetencyFieldsForm):
    form_code = "NC11"
    form_title = "Double Major Full Registration Checklist"
    pathway = "special_case"
    profession_track = "double_major"
    professional_model = NursingProfessional
    form_sections = [
        ("Required Fields", ["full_name", "dual_qualification_evidence", "competency_domains", "dual_major_competency_evidence", "employer_name", "applicant_signature", "assessment_date"]),
    ]

    dual_qualification_evidence = forms.FileField(required=True)
    competency_domains = forms.MultipleChoiceField(choices=DOUBLE_MAJOR_COMPETENCY_CHOICES, widget=forms.CheckboxSelectMultiple)
    dual_major_competency_evidence = forms.FileField(required=True)


class MedicalBoardSpecialistApplicationForm(EmploymentFieldsForm):
    form_code = "MBSP"
    form_title = "Medical Board Application for Specialist Registration"
    pathway = "medical_board"
    profession_track = "medical_specialist"
    professional_model = MedicalDoctor
    form_sections = [
        ("Applicant statement", ["full_name", "full_address", "practitioner_stream"]),
        ("Specialist category", ["specialty", "other_specialty", "qualifications_summary", "qualification_certificates"]),
        ("Declaration before Commissioner of Oaths", ["assessment_date", "applicant_signature", "commissioner_of_oaths"]),
    ]

    registration_no = forms.CharField(max_length=100, required=False, label="Medical registration number")
    practitioner_stream = forms.ChoiceField(
        choices=MEDICAL_BOARD_PRACTITIONER_STREAM_CHOICES,
        widget=forms.RadioSelect,
        label="Practitioner stream",
    )
    specialty = forms.ChoiceField(
        choices=[("", "---------")] + MEDICAL_BOARD_SPECIALIST_CHOICES,
        label="Specialist category applied for",
    )
    other_specialty = forms.CharField(max_length=150, required=False, label="Other specialist category")
    qualifications_summary = forms.CharField(
        required=False,
        label="My qualifications are",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    commissioner_of_oaths = forms.CharField(max_length=255, required=False, label="Commissioner of Oaths")
    qualification_certificates = forms.FileField(required=False)


class MedicalBoardRenewalRegistrationForm(EmploymentFieldsForm):
    form_code = "MBRN"
    form_title = "Medical Board Renewal Registration Application"
    pathway = "medical_board"
    profession_track = "medical_renewal"
    form_sections = [
        ("Registration numbers", ["registration_no", "practitioner_no", "licence_number"]),
        ("Part A: Personal Details", ["title", "last_name", "first_name", "full_name", "date_of_birth", "marital_status", "nationality", "gender", "province", "village", "full_address", "contact_number", "business_number", "email_address"]),
        ("Part B: Application Details", ["application_types", "practitioner_categories", "other_practitioner_category"]),
        ("Part C: Initial Training and Registration Details", ["health_care_practitioner_qualification", "other_initial_qualification", "institution_attended", "country", "date_started", "date_completed", "date_sighted", "program_completed", "initial_registration_date"]),
        ("Part D: Employment Details", ["worker_type", "other_worker_type", "function_type", "place_of_work", "employment_status", "area_of_employment", "reasons_for_unemployment", "reasons_for_unemployment_other", "employer_name", "email_no", "phone_no"]),
        ("Part E: Post-Graduate Qualification 1", ["postgrad_qualification_type_1", "postgrad_program_title_1", "postgrad_date_started_1", "postgrad_date_completed_1", "postgrad_institution_1", "postgrad_country_1"]),
        ("Part E: Post-Graduate Qualification 2", ["postgrad_qualification_type_2", "postgrad_program_title_2", "postgrad_date_started_2", "postgrad_date_completed_2", "postgrad_institution_2", "postgrad_country_2"]),
        ("Part E: Post-Graduate Qualification 3", ["postgrad_qualification_type_3", "postgrad_program_title_3", "postgrad_date_started_3", "postgrad_date_completed_3", "postgrad_institution_3", "postgrad_country_3"]),
        ("Signature and Medical Board office use", ["applicant_signature", "assessment_date", "official_receipt_number", "amount", "receipt_date"]),
    ]

    first_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=100, required=False)
    practitioner_no = forms.CharField(max_length=100, required=False, label="Practitioner number")
    village = forms.CharField(max_length=100, required=False, label="Name of village")
    business_number = forms.CharField(max_length=50, required=False, label="Business phone")
    application_types = forms.MultipleChoiceField(
        choices=MEDICAL_BOARD_APPLICATION_TYPE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Application for",
    )
    practitioner_categories = forms.MultipleChoiceField(
        choices=MEDICAL_BOARD_PRACTITIONER_CATEGORY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Register as",
    )
    other_practitioner_category = forms.CharField(max_length=150, required=False)
    health_care_practitioner_qualification = forms.ChoiceField(
        choices=[("", "---------")] + MEDICAL_BOARD_INITIAL_QUALIFICATION_CHOICES,
        required=False,
        label="Health care practitioner qualification",
    )
    other_initial_qualification = forms.CharField(max_length=150, required=False)
    initial_registration_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_sighted = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    worker_type = forms.ChoiceField(
        choices=[("", "---------")] + MEDICAL_BOARD_WORKER_TYPE_CHOICES,
        required=False,
        label="Health care worker type",
    )
    other_worker_type = forms.CharField(max_length=150, required=False)
    place_of_work = forms.ChoiceField(choices=[("", "---------")] + MEDICAL_BOARD_PLACE_OF_WORK_CHOICES, required=False)
    area_of_employment = forms.ChoiceField(choices=[("", "---------")] + MEDICAL_BOARD_APPLICATION_AREA_CHOICES, required=False)
    reasons_for_unemployment = forms.ChoiceField(choices=[("", "---------")] + MEDICAL_BOARD_UNEMPLOYMENT_REASON_CHOICES, required=False)
    reasons_for_unemployment_other = forms.CharField(max_length=255, required=False)
    email_no = forms.EmailField(required=False, label="Employer email")
    phone_no = forms.CharField(max_length=50, required=False, label="Employer phone")
    registration_no = forms.CharField(max_length=100, required=False)
    official_receipt_number = forms.CharField(max_length=100, required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    receipt_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    postgrad_qualification_type_1 = forms.ChoiceField(choices=[("", "---------")] + MEDICAL_BOARD_POSTGRAD_CHOICES, required=False)
    postgrad_program_title_1 = forms.CharField(max_length=255, required=False)
    postgrad_date_started_1 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    postgrad_date_completed_1 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    postgrad_institution_1 = forms.CharField(max_length=255, required=False)
    postgrad_country_1 = forms.CharField(max_length=100, required=False)
    postgrad_qualification_type_2 = forms.ChoiceField(choices=[("", "---------")] + MEDICAL_BOARD_POSTGRAD_CHOICES, required=False)
    postgrad_program_title_2 = forms.CharField(max_length=255, required=False)
    postgrad_date_started_2 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    postgrad_date_completed_2 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    postgrad_institution_2 = forms.CharField(max_length=255, required=False)
    postgrad_country_2 = forms.CharField(max_length=100, required=False)
    postgrad_qualification_type_3 = forms.ChoiceField(choices=[("", "---------")] + MEDICAL_BOARD_POSTGRAD_CHOICES, required=False)
    postgrad_program_title_3 = forms.CharField(max_length=255, required=False)
    postgrad_date_started_3 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    postgrad_date_completed_3 = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    postgrad_institution_3 = forms.CharField(max_length=255, required=False)
    postgrad_country_3 = forms.CharField(max_length=100, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].required = False
        self.fields["full_name"].widget.attrs.pop("required", None)
        self.fields["full_name"].widget.attrs["aria-required"] = "false"

    def get_professional_model(self):
        categories = self.cleaned_data.get("practitioner_categories") or []
        if "chw" in categories:
            self.profession_track = "community_health_worker"
            return CommunityHealthWorker
        self.profession_track = "medical_specialist" if "specialist" in categories else "medical_doctor"
        return MedicalDoctor


class MedicalBoardChwRegistrationForm(QualificationFieldsForm):
    form_code = "CHW1"
    form_title = "Medical Board Community Health Worker Registration"
    pathway = "medical_board"
    profession_track = "community_health_worker"
    professional_model = CommunityHealthWorker
    form_sections = [
        ("Part A: CHW Details", ["full_name", "registration_no", "community_id", "date_of_birth", "gender", "contact_number", "email_address"]),
        ("Part B: Training Details", ["training_level", "institution_attended", "program_completed", "date_of_completion", "qualification_certificates"]),
        ("Part C: Address and Declaration", ["full_address", "province", "applicant_signature", "assessment_date"]),
    ]

    registration_no = forms.CharField(max_length=100, required=False)
    community_id = forms.CharField(max_length=50, required=False, label="Practitioner / CHW ID")
    training_level = forms.CharField(max_length=100, required=False)
    qualification_certificates = forms.FileField(required=False)


class MedicalBoardFacilityApplicationForm(SectionedFormMixin, forms.Form):
    form_code = ""
    form_title = ""
    pathway = "medical_facility"
    profession_track = "medical_facility"
    facility_type = "Medical Facility"

    facility_name = forms.CharField(max_length=255)
    facility_owner = forms.CharField(max_length=255, required=False)
    ownership = forms.ChoiceField(choices=[("", "---------")] + Facility.OWNERSHIP_CHOICES, required=False)
    facility_level = forms.CharField(max_length=80, required=False)
    province = forms.CharField(max_length=100, required=False)
    district = forms.CharField(max_length=100, required=False)
    physical_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    contact_person = forms.CharField(max_length=255, required=False)
    contact_number = forms.CharField(max_length=50, required=False)
    email_address = forms.EmailField(required=False)
    services_offered = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    staffing_summary = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    equipment_and_supplies = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    infection_control_measures = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    emergency_readiness = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    supporting_documents = forms.FileField(required=False)
    inspection_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    inspector_name = forms.CharField(max_length=255, required=False)
    official_receipt_number = forms.CharField(max_length=100, required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    receipt_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    applicant_signature = forms.CharField(max_length=255, required=False)
    declaration = forms.BooleanField(required=True, label="I confirm the information provided is complete and ready for Medical Board review.")

    def save(self):
        with transaction.atomic():
            location = None
            if self.cleaned_data.get("province") or self.cleaned_data.get("district"):
                location, _ = Location.objects.get_or_create(
                    province=self.cleaned_data.get("province") or "Unknown",
                    district=self.cleaned_data.get("district") or "Unknown",
                    defaults={"ward": ""},
                )
            facility, _ = Facility.objects.update_or_create(
                name=self.cleaned_data["facility_name"],
                defaults={
                    "type": self.facility_type,
                    "ownership": self.cleaned_data.get("ownership") or "private",
                    "level": self.cleaned_data.get("facility_level") or "facility",
                    "location": location,
                },
            )
            application = Application.objects.create(
                content_type=ContentType.objects.get_for_model(facility),
                object_id=facility.pk,
                form_code=self.form_code,
                form_title=self.form_title,
                pathway=self.pathway,
                profession_track=self.profession_track,
                status="pending",
                reviewer_notes="Submitted via Medical Board public portal",
                payload=self.build_payload(),
            )
            self._save_payment(application)
            _record_application_form_response(application)
            return application

    def build_payload(self):
        payload = {}
        for key, value in self.cleaned_data.items():
            payload[key] = _payload_value(value)
        return payload

    def _save_payment(self, application):
        amount = self.cleaned_data.get("amount")
        if amount in (None, ""):
            return
        Receipt.objects.create(
            receipt_number="",
            official_receipt_no=self.cleaned_data.get("official_receipt_number") or None,
            amount=amount,
            description=f"{self.form_code} facility payment for application {application.pk}",
            status="pending",
            payment_method="office",
            application=application,
        )


class MedicalBoardAccreditationChecklistForm(MedicalBoardFacilityApplicationForm):
    form_code = "MBAC"
    form_title = "Medical Board Accreditation Checklist for Facilities"
    facility_type = "Accredited Medical Facility"
    dherst_registered = forms.ChoiceField(choices=YES_NO_CHOICES, required=False, label="Registered under DHERST")
    vision_mission_statement = forms.ChoiceField(choices=YES_NO_CHOICES, required=False, label="Clear vision and mission statement")
    total_students_current_year = forms.IntegerField(required=False, min_value=0)
    total_academic_staff_current_year = forms.IntegerField(required=False, min_value=0)
    accreditation_committee_comments = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    form_sections = [
        ("Training institution identity", ["facility_name", "facility_owner", "ownership", "facility_level", "province", "district", "physical_address"]),
        ("General information", ["dherst_registered", "vision_mission_statement", "total_students_current_year", "total_academic_staff_current_year", "services_offered", "staffing_summary"]),
        ("Accreditation comments and evidence", ["accreditation_committee_comments", "supporting_documents"]),
        ("Inspection and declaration", ["inspection_date", "inspector_name", "declaration"]),
    ]

    def add_dynamic_fields(self):
        status_names, comment_names = _add_checklist_status_fields(
            self,
            prefix="accreditation",
            choices=ACCREDITATION_ACTIVITY_CHOICES,
        )
        self.form_sections = list(self.form_sections) + [
            ("Accreditation requirements and guidelines", status_names),
            ("Accreditation review comments", comment_names),
        ]


class MedicalBoardPrivateHealthFacilityChecklistForm(MedicalBoardFacilityApplicationForm):
    form_code = "MBPF"
    form_title = "Medical Board Private Health Facilities Checklist"
    facility_type = "Private Health Facility"
    proposed_signboard_details = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    clinic_services_description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    floor_plan_details = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    qualified_staff_details = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    pharmacy_dispensary_details = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    land_or_building_documents = forms.FileField(required=False)
    form_sections = [
        ("Facility and Ownership", ["facility_name", "facility_owner", "ownership", "facility_level", "province", "district", "physical_address"]),
        ("Contact and Proposed Services", ["contact_person", "contact_number", "email_address", "proposed_signboard_details", "clinic_services_description", "services_offered"]),
        ("Facility, Equipment, Staff and Pharmacy Details", ["floor_plan_details", "equipment_and_supplies", "qualified_staff_details", "pharmacy_dispensary_details", "infection_control_measures", "emergency_readiness"]),
        ("Required Documents and Fee", ["supporting_documents", "land_or_building_documents", "official_receipt_number", "amount", "receipt_date"]),
        ("Declaration", ["inspection_date", "inspector_name", "declaration"]),
    ]

    def add_dynamic_fields(self):
        status_names, comment_names = _add_checklist_status_fields(
            self,
            prefix="private_health",
            choices=PRIVATE_HEALTH_CHECKLIST_CHOICES,
        )
        self.form_sections = list(self.form_sections) + [
            ("Private health facility establishment checklist", status_names),
            ("Private health facility checklist comments", comment_names),
        ]


class MedicalBoardTrainingCollegeFacilityForm(MedicalBoardFacilityApplicationForm):
    form_code = "MBTC"
    form_title = "Medical Board Training Colleges Facilities Form"
    pathway = "medical_training"
    profession_track = "medical_training_facility"
    facility_type = "Training College Facility"
    applicant_full_name = forms.CharField(max_length=255, required=False)
    applicant_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    operation_type = forms.CharField(max_length=255, required=False, label="Type of operation")
    premises_description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    declared_at = forms.CharField(max_length=255, required=False)
    oath_witness = forms.CharField(max_length=255, required=False, label="Commissioner of Oaths / Court Magistrate")
    business_profile = forms.FileField(required=False, label="Full business profile")
    application_requirements_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    date_application_submitted = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    inspectors = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    inspection_purpose = forms.MultipleChoiceField(choices=HSFC_PURPOSE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple)
    outside_sign_board = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    general_environment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    standalone_building = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    building_part_description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    patient_waiting_area = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    administration_office = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    patient_registration_area = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dental_chair_1_components = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dental_chair_1_equipment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dental_chair_1_xray = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dental_drugs_consumables = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dental_protective_equipment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dental_chair_2_condition = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    procedure_laboratory = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    patient_toilet_shower = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    staff_amenities = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    infection_control_practices = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    referral_pathways = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    dispensary_pharmacy_storage = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    furniture_chairs = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    furniture_tables = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    furniture_workstations = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    general_assessment_information = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    png_medical_board_recommendation = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    reasons_not_registered = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    registrar_name = forms.CharField(max_length=255, required=False)
    registrar_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    registrar_signature = forms.CharField(max_length=255, required=False)
    staff_roster = forms.CharField(
        required=False,
        label="Staff roster: name, specialty/registration, full or part time, expiry date, clinical or administration role",
        widget=forms.Textarea(attrs={"rows": 8}),
    )
    form_sections = [
        ("Permission to Conduct Facility or Training College", ["applicant_full_name", "applicant_address", "operation_type", "premises_description", "facility_name", "facility_owner", "ownership", "province", "district", "physical_address", "declared_at", "applicant_signature", "oath_witness", "business_profile"]),
        ("HSFC Inspection Identity and Requirements", ["contact_number", "email_address", "application_requirements_notes", "date_application_submitted", "inspection_date", "inspectors", "inspection_purpose"]),
        ("Outside Environment and Building Structure", ["outside_sign_board", "general_environment", "standalone_building", "building_part_description", "patient_waiting_area", "administration_office", "patient_registration_area"]),
        ("Dental Procedure Rooms and Infection Control", ["dental_chair_1_components", "dental_chair_1_equipment", "dental_chair_1_xray", "dental_drugs_consumables", "dental_protective_equipment", "dental_chair_2_condition", "procedure_laboratory", "patient_toilet_shower", "staff_amenities", "infection_control_practices", "referral_pathways"]),
        ("Other Services, Furniture and Staff", ["dispensary_pharmacy_storage", "furniture_chairs", "furniture_tables", "furniture_workstations", "staff_roster"]),
        ("Medical Board Review", ["general_assessment_information", "png_medical_board_recommendation", "reasons_not_registered", "registrar_name", "registrar_date", "registrar_signature", "supporting_documents", "declaration"]),
    ]

    def add_dynamic_fields(self):
        status_names, comment_names = _add_checklist_status_fields(
            self,
            prefix="hsfc_requirement",
            choices=HSFC_REQUIREMENT_CHOICES,
        )
        self.form_sections = list(self.form_sections) + [
            ("HSFC application requirements submitted", status_names),
            ("HSFC requirement comments", comment_names),
        ]
