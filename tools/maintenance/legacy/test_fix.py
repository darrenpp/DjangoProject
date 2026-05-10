#!/usr/bin/env python
"""
Ad hoc verification script for the historical national_id fix.

This file is intentionally import-safe because Django's test discovery will
import any module that matches ``test*.py``. Run it directly if you want the
manual checks.
"""

import os
from pathlib import Path
import sys

import django

BASE_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoh_workforce_registry.settings")


def main():
    django.setup()

    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    from apps.accounts.models import User
    from apps.dashboard.views import student_dashboard
    from apps.workforce.models import HealthStudent

    print("Test 1: Check User model has national_id field")
    try:
        user = User.objects.first()
        has_attr = hasattr(user, "national_id")
        print(f"  [OK] User has national_id attribute: {has_attr}")
    except Exception as exc:
        print(f"  [ERR] {exc}")

    print("\nTest 2: Check tolly user")
    try:
        tolly = User.objects.get(username="tolly")
        print(f"  Username: {tolly.username}")
        print(f"  First Name: {tolly.first_name}")
        print(f"  Last Name: {tolly.last_name}")
        print(f"  National ID: {tolly.national_id}")
        print(f"  Role: {tolly.role}")
        if tolly.national_id:
            print("  [OK] tolly user has national_id set")
        else:
            print("  [ERR] tolly user does NOT have national_id set")
    except Exception as exc:
        print(f"  [ERR] {exc}")

    print("\nTest 3: Check if HealthStudent exists for tolly's national_id")
    try:
        tolly = User.objects.get(username="tolly")
        if tolly.national_id:
            student = HealthStudent.objects.filter(national_id=tolly.national_id).first()
            if student:
                print(f"  [OK] Found HealthStudent: {student.first_name} {student.last_name}")
            else:
                print(f"  [ERR] No HealthStudent found with national_id: {tolly.national_id}")
        else:
            print("  [ERR] tolly user has no national_id")
    except Exception as exc:
        print(f"  [ERR] {exc}")

    print("\nTest 4: Test student_dashboard view")
    try:
        tolly = User.objects.get(username="tolly")
        factory = RequestFactory()
        request = factory.get("/dashboard/student/")
        request.user = tolly

        middleware = SessionMiddleware(lambda x: None)
        middleware.process_request(request)
        request.session.save()

        response = student_dashboard(request)
        print("  [OK] student_dashboard view executed successfully")
        print(f"  Response status: {response.status_code if hasattr(response, 'status_code') else 'N/A'}")
    except AttributeError as exc:
        print(f"  [ERR] AttributeError: {exc}")
    except Exception as exc:
        print(f"  [ERR] {exc}")

    print("\n" + "=" * 50)
    print("All manual checks completed.")


if __name__ == "__main__":
    main()
