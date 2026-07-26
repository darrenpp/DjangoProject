from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_existing_staff_approvals(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    staff_roles = ['admin', 'registrar', 'reviewer', 'mobile_collector']
    User.objects.filter(role__in=staff_roles, role_approved=True).update(system_admin_approved=True)
    User.objects.filter(role='admin', is_superuser=True).update(
        role_approved=True,
        system_admin_approved=True,
        is_staff=True,
    )


def clear_backfilled_staff_approvals(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.update(system_admin_approved=False)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0018_alter_securityauditevent_action_alter_user_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='system_admin_approved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='system_admin_approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='system_admin_approved_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='system_admin_approved_user_accounts',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_existing_staff_approvals, clear_backfilled_staff_approvals),
    ]
