from apps.accounts.models import User
from apps.common.models import DeceasedRecord, DuplicateReviewQueue
from apps.competency.models import CompetencyAssessment
from apps.dashboard.models import Report, Receipt
from apps.notifications.models import Notification
from apps.ocr.models import OCRDocument
from apps.workforce.models import (
    Application,
    Cadre,
    CommunityHealthWorker,
    CPDRecord,
    DocumentType,
    Facility,
    HealthStudent,
    Location,
    MedicalDoctor,
    Midwife,
    NurseAide,
    NursingProfessional,
    ProfessionalDocument,
    ProfessionalPhoto,
    TrainingInstitution,
    WorkforceSnapshot,
    PracticingLicenseRecord,
)


MODEL_REGISTRY = {
    "user": User,
    "cadre": Cadre,
    "location": Location,
    "facility": Facility,
    "traininginstitution": TrainingInstitution,
    "documenttype": DocumentType,
    "medicaldoctor": MedicalDoctor,
    "medicalspecialist": MedicalDoctor,
    "nursingprofessional": NursingProfessional,
    "midwife": Midwife,
    "communityhealthworker": CommunityHealthWorker,
    "nurseaide": NurseAide,
    "healthstudent": HealthStudent,
    "graduand": HealthStudent,
    "application": Application,
    "receipt": Receipt,
    "workforcesnapshot": WorkforceSnapshot,
    "practicinglicenserecord": PracticingLicenseRecord,
    "cpdrecord": CPDRecord,
    "professionaldocument": ProfessionalDocument,
    "professionalphoto": ProfessionalPhoto,
    "competencyassessment": CompetencyAssessment,
    "duplicatereviewqueue": DuplicateReviewQueue,
    "deceasedrecord": DeceasedRecord,
    "notification": Notification,
    "ocrdocument": OCRDocument,
    "report": Report,
}
