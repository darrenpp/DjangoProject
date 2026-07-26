from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'applicant_type', 'phone', 'department',
            'middle_name', 'cadre_name',
            'secondary_email', 'postal_address', 'employee_details',
            'license_number', 'registration_number', 'national_id',
            'professional_record_status', 'professional_linked_at', 'professional_link_review_note',
            'job_title', 'workplace_name', 'workplace_location', 'practice_country',
            'practice_province', 'practice_district', 'work_status',
            'professional_bio', 'qualification_summary', 'specialty_area',
            'professional_memberships', 'primary_contact_method', 'profile_visibility',
            'show_email_on_profile', 'show_phone_on_profile', 'allow_profile_contact',
            'profile_image', 'passport_photo', 'id_document_image',
        ]
        read_only_fields = ['id']
