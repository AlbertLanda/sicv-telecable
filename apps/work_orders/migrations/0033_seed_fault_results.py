"""Resultados de atención para las averías de internet y cable.

Los tipos de avería los siembra ``cargar_catalogo_ordenes``, pero sin
resultados: el técnico no tenía con qué finalizar la atención. Esta migración
los agrega en las bases que ya tienen esos tipos; en una base nueva los carga
el mismo comando.

Se siembra sin pisar lo que ya exista: si alguien corrigió un nombre desde el
admin, volver a correr las migraciones no lo devuelve al de la tabla.
"""

from django.db import migrations


FAULT_ORDER_TYPE_CODES = ("INTERNET_FAULT", "CABLE_FAULT")
FAULT_RESULTS = (
    ("SUCCESSFUL", "AVERÍA SOLUCIONADA", True),
    ("NOT_COMPLETED", "AVERÍA NO SOLUCIONADA", False),
)


def sembrar_resultados(apps, schema_editor):
    OrderType = apps.get_model("work_orders", "OrderType")
    OrderResult = apps.get_model("work_orders", "OrderResult")

    for order_type in OrderType.objects.filter(code__in=FAULT_ORDER_TYPE_CODES):
        for code, name, is_success in FAULT_RESULTS:
            OrderResult.objects.get_or_create(
                order_type=order_type,
                code=code,
                defaults={
                    "name": name,
                    "is_success": is_success,
                    "is_active": True,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("work_orders", "0032_fault_responsibility"),
    ]

    operations = [
        # Sin reverso: los resultados pueden estar ya en órdenes atendidas.
        migrations.RunPython(
            sembrar_resultados,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
