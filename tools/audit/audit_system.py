#!/usr/bin/env python
"""Comprehensive system audit for the NDOH regulatory platform."""

import os
from pathlib import Path
import sys

import django

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndoh_workforce_registry.settings")
django.setup()

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.db import connection
from django.urls import reverse


REQUIRED_MODELS = {
    "workforce": [
        "NursingProfessional",
        "MedicalDoctor",
        "Midwife",
        "CommunityHealthWorker",
        "HealthStudent",
        "Application",
        "Facility",
        "TrainingInstitution",
    ],
    "competency": ["CompetencyAssessment"],
    "accounts": ["User"],
    "notifications": ["Notification"],
    "ocr": ["OCRDocument"],
    "documents": ["Document", "DocumentVersion", "DocumentAuditEvent"],
}

REQUIRED_URLS = {
    "records_home": "/records/",
    "population_guide": "/records/population-guide/",
    "advanced_dashboard": "/dashboard/",
    "admin:index": "/admin/",
}

VIEWS_TO_CHECK = [
    ("apps.dashboard.views", ["AdvancedDashboardView"]),
    ("apps.common.record_views", ["RecordsHomeView"]),
    ("apps.accounts.views", ["public_register", "staff_register"]),
    ("apps.documents.views", ["repository_search"]),
]


def check_database_connectivity():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    print("OK database connection")
    return True


def check_models():
    model_names_by_app = {}
    for model in apps.get_models():
        app_name = model._meta.app_label
        model_names_by_app.setdefault(app_name, set()).add(model.__name__)

    missing = []
    for app_name, expected_models in REQUIRED_MODELS.items():
        available = model_names_by_app.get(app_name, set())
        for model_name in expected_models:
            if model_name not in available:
                missing.append(f"{app_name}.{model_name}")

    if missing:
        print("ERR missing models: " + ", ".join(missing))
        return False

    print(f"OK required models present ({sum(len(v) for v in REQUIRED_MODELS.values())} checked)")
    return True


def check_urls():
    ok = True
    for name, expected_path in REQUIRED_URLS.items():
        try:
            url = reverse(name)
        except Exception as exc:
            print(f"ERR url {name}: {exc}")
            ok = False
            continue
        if url != expected_path:
            print(f"WARN url {name}: resolved {url}, expected {expected_path}")
        else:
            print(f"OK url {name}: {url}")
    return ok


def check_views():
    ok = True
    for module_name, view_names in VIEWS_TO_CHECK:
        try:
            module = __import__(module_name, fromlist=view_names)
        except Exception as exc:
            print(f"ERR import {module_name}: {exc}")
            ok = False
            continue
        for view_name in view_names:
            if hasattr(module, view_name):
                print(f"OK view {module_name}.{view_name}")
            else:
                print(f"ERR view missing {module_name}.{view_name}")
                ok = False
    return ok


def check_admin():
    registered_count = len(admin.site._registry)
    print(f"OK admin registry contains {registered_count} models")
    return registered_count > 0


def check_settings():
    checks = {
        "ALLOWED_HOSTS configured": bool(settings.ALLOWED_HOSTS),
        "SECRET_KEY configured": bool(settings.SECRET_KEY),
        "DATABASES configured": "default" in settings.DATABASES,
        "INSTALLED_APPS configured": bool(settings.INSTALLED_APPS),
    }
    for label, passed in checks.items():
        print(f"{'OK' if passed else 'ERR'} {label}")
    return all(checks.values())


def check_security_posture():
    checks = {
        "SESSION_COOKIE_HTTPONLY": settings.SESSION_COOKIE_HTTPONLY,
        "SECURE_CONTENT_TYPE_NOSNIFF": settings.SECURE_CONTENT_TYPE_NOSNIFF,
        "X_FRAME_OPTIONS set": bool(settings.X_FRAME_OPTIONS),
        "CSRF middleware enabled": "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE,
    }
    for label, passed in checks.items():
        print(f"{'OK' if passed else 'ERR'} {label}")
    return all(checks.values())


def check_migrations():
    call_command("showmigrations", verbosity=0, no_color=True)
    print("OK migrations are inspectable")
    return True


def run_check(label, function):
    print(f"\n== {label} ==")
    try:
        return function()
    except Exception as exc:
        print(f"ERR {label}: {exc}")
        return False


def main():
    print("NDOH REGULATORY PLATFORM SYSTEM AUDIT")
    print("=" * 42)

    checks = {
        "Database": check_database_connectivity,
        "Models": check_models,
        "URLs": check_urls,
        "Views": check_views,
        "Admin": check_admin,
        "Settings": check_settings,
        "Security": check_security_posture,
        "Migrations": check_migrations,
    }

    results = {label: run_check(label, function) for label, function in checks.items()}

    print("\n== Summary ==")
    for label, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'} {label}")

    passed_count = sum(results.values())
    print(f"\nOverall: {passed_count}/{len(results)} checks passed")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
