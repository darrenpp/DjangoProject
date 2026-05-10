from rest_framework import serializers
from .models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'role', 'applicant_type', 'phone', 'department',
            'employee_details', 'license_number', 'registration_number',
            'profile_image', 'passport_photo', 'id_document_image',
        ]
        read_only_fields = ['id']
