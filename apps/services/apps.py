from django.apps import AppConfig


class ServicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.services"

    def ready(self):
        # Registra efectos de dominio que reaccionan a la liquidación de una
        # OT de anexos. La importación vive aquí para ejecutarse solo cuando
        # el registro de apps de Django ya está listo.
        from . import signals  # noqa: F401
