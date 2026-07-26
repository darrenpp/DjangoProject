from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_alter_user_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='board_registration_token',
            field=models.CharField(blank=True, max_length=40, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='user',
            name='board_registration_token_created_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
