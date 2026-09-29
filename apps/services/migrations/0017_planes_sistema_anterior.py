"""Planes del sistema anterior para la migración manual de abonados.

El catálogo vive en `apps.services.catalogo_sistema_anterior`, que también usa
`cargar_catalogo_comercial` para las bases nuevas. Aquí se aplica a las bases
que ya están en uso, que no vuelven a correr ese comando.
"""

from django.db import migrations


def sembrar(apps, schema_editor):
    from apps.services.catalogo_sistema_anterior import (
        sembrar_planes_sistema_anterior,
    )

    sembrar_planes_sistema_anterior(
        apps.get_model("services", "Plan"),
        apps.get_model("services", "ServiceType"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0016_backfill_subscription_seller"),
    ]

    operations = [
        # Sin reverso, como 0011: un plan sembrado aquí puede tener ya
        # suscripciones colgando -PROTECT- y borrarlo al desandar fallaría.
        migrations.RunPython(sembrar, migrations.RunPython.noop),
    ]
