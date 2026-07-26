from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.dashboard'

    def ready(self):
        # Register knowledge-source invalidation after Django has loaded models.
        from . import signals  # noqa: F401
