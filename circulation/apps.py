from django.apps import AppConfig


class CirculationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "circulation"
    verbose_name = "Circulation & Loans"

    def ready(self):
        # Connect model signals for audit logs
        try:
            import circulation.signals  # noqa: F401
        except ImportError:
            pass
