#!/usr/bin/env python
"""Database integrity and record count verification."""

import os
from pathlib import Path
import sys

import django

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoh_workforce_registry.settings")
django.setup()

from django.db import connection

from apps.accounts.models import User
from apps.competency.models import CompetencyAssessment
from apps.workforce.models import (
    Application,
    Cadre,
    CommunityHealthWorker,
    CPDRecord,
    DocumentType,
    Facility,
    HealthStudent,
    MedicalDoctor,
    Midwife,
    NursingProfessional,
    PostingHistory,
    ProfessionalDocument,
    Qualification,
    TrainingInstitution,
)


MODELS_TO_CHECK = {
    "User": User,
    "Cadre": Cadre,
    "Facility": Facility,
    "TrainingInstitution": TrainingInstitution,
    "DocumentType": DocumentType,
    "NursingProfessional": NursingProfessional,
    "MedicalDoctor": MedicalDoctor,
    "Midwife": Midwife,
    "CommunityHealthWorker": CommunityHealthWorker,
    "HealthStudent": HealthStudent,
    "Application": Application,
    "Qualification": Qualification,
    "ProfessionalDocument": ProfessionalDocument,
    "PostingHistory": PostingHistory,
    "CPDRecord": CPDRecord,
    "CompetencyAssessment": CompetencyAssessment,
}


def main():
    print("=== DATABASE INTEGRITY CHECK ===\n")
    print("MODEL RECORD COUNTS:")

    total_records = 0
    for name, model in MODELS_TO_CHECK.items():
        try:
            count = model.objects.count()
            total_records += count
            print(f"OK {name:30} {count:6} records")
        except Exception as exc:
            print(f"ERR {name:30} {exc}")

    print(f"\nTotal records across all checked models: {total_records}")
    print("\n=== DATABASE TABLES ===")
    print(f"Total tables in database: {len(connection.introspection.table_names())}")
    print("\nDATABASE INTEGRITY CHECK COMPLETE")


if __name__ == "__main__":
    main()
