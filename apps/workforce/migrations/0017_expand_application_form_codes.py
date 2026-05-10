from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workforce', '0016_alter_application_form_code'),
    ]

    operations = [
        migrations.AlterField(
            model_name='application',
            name='form_code',
            field=models.CharField(
                choices=[
                    ('MD1', 'MD1 - Medical Registration'),
                    ('MD2', 'MD2 - Medical Renewal'),
                    ('CHW1', 'CHW1 - CHW Registration'),
                    ('NC1', 'NC1 - Provisional'),
                    ('NC2', 'NC2 - Full'),
                    ('NC3', 'NC3 - Renewal'),
                    ('G1', 'G1 - Graduand'),
                    ('G4', 'G4 - Provisional Licence'),
                    ('G5', 'G5 - Full Licence'),
                    ('GD', 'GD'),
                    ('PG', 'PG'),
                ],
                max_length=20,
            ),
        ),
    ]
