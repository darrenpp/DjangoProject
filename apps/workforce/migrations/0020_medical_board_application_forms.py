from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workforce', '0019_dataimportbatch_importedworkbooksheet_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='application',
            name='form_code',
            field=models.CharField(choices=[
                ('MD1', 'MD1 - Medical Registration'),
                ('MD2', 'MD2 - Medical Renewal'),
                ('CHW1', 'CHW1 - CHW Registration'),
                ('MBSP', 'MBSP - Medical Board Specialist Application'),
                ('MBRN', 'MBRN - Medical Board Renewal Registration'),
                ('MBAC', 'MBAC - Medical Board Facility Accreditation Checklist'),
                ('MBPF', 'MBPF - Medical Board Private Health Facility Checklist'),
                ('MBTC', 'MBTC - Medical Board Training College Facility Form'),
                ('G1', 'G1 - Graduate Nurses Checklist'),
                ('G2', 'G2 - List of New Graduate Nurses'),
                ('G3', 'G3 - Graduate Vitae'),
                ('G4', 'G4 - Statement of Competency (Nurses)'),
                ('G5', 'G5 - Statement of Competency (Midwives)'),
                ('G6', 'G6 - Graduate Midwives Checklist'),
                ('G7', 'G7 - List of Graduate Midwives'),
                ('NC1', 'NC1 - Application for Provisional Licence'),
                ('NC2', 'NC2 - Application for Full Licence'),
                ('NC3', 'NC3 - Renewal of Licence'),
                ('NC4', 'NC4 - Checklist for Provisional Licence'),
                ('NC5', 'NC5 - Full Registration & Licence'),
                ('NC6', 'NC6 - Competency for Full Licence Nursing'),
                ('NC7', 'NC7 - Competency for Full Licence Midwifery'),
                ('NC8', 'NC8 - Application for Temporary Licence'),
                ('NC9', 'NC9 - Checklist for Temporary Licence'),
                ('NC10', 'NC10 - Competency for Full Licence Child Nursing'),
                ('NC11', 'NC11 - Double Major Full Registration Checklist'),
                ('GD', 'GD'),
                ('PG', 'PG'),
            ], max_length=20),
        ),
        migrations.AlterField(
            model_name='application',
            name='pathway',
            field=models.CharField(choices=[
                ('local_nursing_graduate', 'Local Nursing Graduate (PNG)'),
                ('local_midwifery_graduate', 'Local Midwifery Graduate (PNG)'),
                ('overseas_nurse', 'Overseas Nurse'),
                ('overseas_midwife', 'Overseas Midwife'),
                ('medical_board', 'Medical Board Practitioner'),
                ('medical_facility', 'Medical Board Facility'),
                ('medical_training', 'Medical Board Training Facility'),
                ('special_case', 'Special Case'),
                ('other', 'Other'),
            ], default='other', max_length=40),
        ),
    ]
