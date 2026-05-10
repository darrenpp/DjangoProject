from rest_framework import serializers


class StaffSerializer(serializers.Serializer):
    id = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    registration_no = serializers.CharField()
    email = serializers.EmailField()
    primary_phone = serializers.CharField()
    cadre = serializers.CharField()
    cadre_category = serializers.CharField()
    is_active = serializers.BooleanField()
    photo = serializers.CharField(allow_null=True)
    document_count = serializers.IntegerField()
    location = serializers.CharField(allow_null=True)
    professional_type = serializers.CharField()
    applicant_type = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
