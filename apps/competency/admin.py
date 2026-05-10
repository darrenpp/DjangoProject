from django.contrib import admin
from .models import CompetencyAssessment


@admin.register(CompetencyAssessment)
class CompetencyAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "assessment_name",
        "professional",
        "score",
        "assessment_date",
        "is_passed",
    )

    list_filter = (
        "is_passed",
        "assessment_date",
    )

    search_fields = (
        "assessment_name",
        "supervisor_name",
    )

    date_hierarchy = "assessment_date"