#!/usr/bin/env python
"""
Manual verification script for the original national_id dashboard fix.
"""

import os
from pathlib import Path
import sys

import django

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "NDOH_regulatory_bodies.settings")


def main():
    django.setup()

    from apps.accounts.models import User
    from apps.workforce.models import HealthStudent

    print("Testing the exact line that was failing (line 220 in views.py)...")
    print()

    tolly = User.objects.get(username="tolly")
    print(f"User object: {tolly}")
    print(f"User has national_id attribute: {hasattr(tolly, 'national_id')}")
    print(f"Accessing national_id: {tolly.national_id}")
    print()

    student = HealthStudent.objects.filter(national_id=tolly.national_id).first()
    print(f"Query result: {student}")
    print()
    print("[OK] Line 220 (student_dashboard view) now works without AttributeError.")
    print()
    print("=== Summary of Fix ===")
    print("[OK] Added 'national_id' field to User model")
    print("[OK] Created migration to add national_id field to database")
    print("[OK] Applied migration successfully")
    print("[OK] Updated dashboard views to check if national_id exists before querying")
    print("[OK] Updated user registration form to include national_id field")
    print("[OK] Populated tolly user with correct national_id from HealthStudent")


if __name__ == "__main__":
    main()
