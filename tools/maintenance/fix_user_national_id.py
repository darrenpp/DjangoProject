#!/usr/bin/env python
"""
Script to fix missing national_id for existing users
"""
import os
from pathlib import Path
import sys

import django

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'NDOH_regulatory_bodies.settings')
django.setup()

from apps.accounts.models import User
from apps.workforce.models import HealthStudent

# Find all users without a national_id
users_without_id = User.objects.filter(national_id__isnull=True) | User.objects.filter(national_id='')

print(f"Found {users_without_id.count()} users without national_id")

for user in users_without_id:
    # Try to find a corresponding student
    student = HealthStudent.objects.filter(
        first_name=user.first_name,
        last_name=user.last_name
    ).first()

    if student:
        user.national_id = student.national_id
        user.save()
        print(f"Updated user '{user.username}' with national_id from HealthStudent: {student.national_id}")
    else:
        # If no student found, use license_number or create a placeholder
        if user.license_number:
            user.national_id = user.license_number
            user.save()
            print(f"Updated user '{user.username}' with license_number as national_id: {user.license_number}")
        else:
            print(f"User '{user.username}' has no corresponding HealthStudent or license_number")

print("Done!")

