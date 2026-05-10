from django.db import migrations


def sync_staff_roles(apps, schema_editor):
    User = apps.get_model('accounts', 'User')

    User.objects.filter(role='registrar').update(
        role_approved=True,
        is_staff=True,
        is_active=True,
    )
    User.objects.filter(role='reviewer').update(
        is_staff=True,
        is_active=True,
    )
    User.objects.filter(role='admin', role_approved=True).update(
        is_staff=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_user_approved_at_user_approved_by_user_role_approved'),
    ]

    operations = [
        migrations.RunPython(sync_staff_roles, migrations.RunPython.noop),
    ]
