from django.apps import AppConfig


class WorkOrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.work_orders'

    def ready(self):
        # El catálogo de NAP vive en un módulo separado para no convertir
        # models.py en un archivo aún más grande. Importarlo aquí registra el
        # modelo dentro de la app work_orders sin ejecutar consultas a BD.
        from . import nap_catalog  # noqa: F401
