import re

from django.apps import apps


def next_available_branch_code(prefix):
    """Devuelve el primer correlativo realmente libre para una sede.

    Un código sigue ocupado si pertenece a un Customer, a una suscripción
    vigente/histórica o al historial de un traslado real. Las altas
    provisionales eliminadas por desistimiento desaparecen de esas fuentes y
    por eso su correlativo vuelve a quedar disponible.
    """
    pattern = re.compile(
        rf"^{re.escape(prefix)}(?P<number>\d{{7}})(?:-|$)"
    )
    used = set()

    Customer = apps.get_model("customers", "Customer")
    Subscription = apps.get_model("services", "Subscription")
    TransferDetail = apps.get_model("work_orders", "TransferDetail")

    sources = [
        Customer.objects.filter(
            code__startswith=prefix,
        ).values_list("code", flat=True),
        Subscription.objects.filter(
            service_code__startswith=prefix,
        ).values_list("service_code", flat=True),
        TransferDetail.objects.filter(
            previous_service_code__startswith=prefix,
        ).values_list("previous_service_code", flat=True),
        TransferDetail.objects.filter(
            resulting_service_code__startswith=prefix,
        ).values_list("resulting_service_code", flat=True),
    ]

    for source in sources:
        for code in source.iterator():
            match = pattern.match(code or "")
            if match:
                used.add(int(match.group("number")))

    candidate = 1
    while candidate in used:
        candidate += 1

    return f"{prefix}{candidate:07d}"
