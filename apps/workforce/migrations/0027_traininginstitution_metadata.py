from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workforce", "0026_alter_application_form_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="traininginstitution",
            name="country",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="traininginstitution",
            name="location_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="traininginstitution",
            name="ownership",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="traininginstitution",
            name="registration_status",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="traininginstitution",
            name="regulatory_body_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="traininginstitution",
            name="source_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="traininginstitution",
            name="source_reference",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
