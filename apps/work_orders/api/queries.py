"""
Definición de «orden disponible» para el canal del técnico.

Este módulo existe para que la regla viva en **un solo sitio**. La consumen
el listado ``available/`` y la toma ``claim/``: lo que el técnico ve es
exactamente lo que el backend le permite tomar.

El canal nació con instalaciones como alcance MVP. Desde la incorporación de
la derivación NOC -> campo, también publica las averías físicas de Internet y
Cable. Todos esos tipos comparten las mismas reglas: PENDING, sin técnico y
atención FIELD.
"""

from apps.work_orders.field_order_types import (
    TECHNICIAN_AVAILABLE_ORDER_TYPE_CODES,
)
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import SUBSCRIPTION_BLOCKED_STATUSES


def available_work_orders(queryset=None):
    """Órdenes que un técnico puede ver y tomar desde la app.

    Condiciones de negocio:

    1. ``status = PENDING`` — todavía no tiene ejecución. Listar y reclamar
       consumen esta misma función para que nunca aparezca un botón condenado
       a devolver 409.

    2. ``assigned_technician IS NULL`` — la orden pertenece al pool común y
       aún no tiene responsable.

    3. ``attention_type = FIELD`` — regla permanente: el canal técnico solo
       recibe trabajo físico. Las incidencias NOC siguen siendo SYSTEM y no se
       mezclan con este pool.

    4. El tipo de orden está en ``TECHNICIAN_AVAILABLE_ORDER_TYPE_CODES``:
       actualmente INSTALACIÓN, AVERÍA INTERNET y AVERÍA CABLE. Una avería
       generada por NOC entra por el mismo canal que una instalación: nadie la
       asigna manualmente; un técnico la toma.

    5. La suscripción no está en un estado que bloquee trabajo nuevo. Es la
       misma lista que utiliza el dominio al crear una OT.

    El parámetro ``queryset`` permite aplicar la regla sobre una consulta ya
    preparada (por ejemplo con ``select_related`` o ``select_for_update``).
    """
    base = WorkOrder.objects.all() if queryset is None else queryset

    return base.filter(
        status=WorkOrder.Status.PENDING,
        assigned_technician__isnull=True,
        attention_type=WorkOrder.AttentionType.FIELD,
        order_type__code__in=TECHNICIAN_AVAILABLE_ORDER_TYPE_CODES,
    ).exclude(
        subscription__status__in=SUBSCRIPTION_BLOCKED_STATUSES,
    )
