"""
Vistas de API de órdenes de trabajo del canal técnico.

Hoy solo lectura: «Mis órdenes». El detalle llega el día 3 y las acciones de
transición los días 4 a 6, delegando siempre en los servicios de dominio que
ya usa la web.
"""

from django.db.models import F
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.accounts.api.permissions import IsActiveTechnician
from apps.work_orders.api.serializers import WorkOrderListSerializer
from apps.work_orders.models import WorkOrder


class MyWorkOrderListView(ListAPIView):
    """GET /api/technicians/work-orders/ — OT asignadas al técnico autenticado.

    Decisiones deliberadas:

    - **El filtro es del servidor, no del cliente.** El queryset filtra por
      `request.user` y la vista no lee ningún parámetro de la petición: no
      existe parámetro que manipular para ver las órdenes de otro técnico.
    - **Sin filtro por sede ni zona.** La sede del técnico es referencia
      operativa, no restricción de elegibilidad (decidido en el bloque de
      asignación), así que se lista todo lo asignado. El filtro por sede/zona
      es alcance del bloque 2 (App del técnico), y queda documentado como
      pendiente, no como olvido.
    - **Solo lectura.** No hay acciones de transición: los días 4 a 6 las
      montan sobre los servicios de dominio.
    """

    serializer_class = WorkOrderListSerializer

    # `IsAuthenticated` es el permiso global; se repite explícito porque
    # declarar `permission_classes` reemplaza el valor por defecto y omitirlo
    # dejaría el endpoint apoyado solo en el permiso de rol.
    permission_classes = [IsAuthenticated, IsActiveTechnician]

    def get_queryset(self):
        return (
            WorkOrder.objects
            .filter(assigned_technician=self.request.user)
            # Mismo criterio que la bandeja de despacho web: todo lo que el
            # serializador pinta por fila se trae en la misma consulta. Sin
            # esto, listar N órdenes dispara una consulta por cliente,
            # servicio, plan, tipo y subtipo de cada fila.
            .select_related(
                "subscription",
                "subscription__customer",
                "subscription__service_type",
                "subscription__plan",
                "order_type",
                "subtype",
            )
            # Orden decidido para el técnico en campo: lo más próximo primero.
            # `Meta.ordering` del modelo (`-created_at`) sirve a la bandeja de
            # despacho, que mira lo recién ingresado; el técnico mira su
            # jornada. Las órdenes sin fecha programada van al final en lugar
            # de encabezar la lista. No se ordena por `priority` porque es un
            # CharField con choices: alfabéticamente daría HIGH, LOW, NORMAL,
            # URGENT, un orden sin sentido operativo; hacerlo bien exigiría
            # anotar un peso, y se deja documentado como opción futura.
            # El desempate por `pk` mantiene el orden estable si se pagina.
            .order_by(
                F("scheduled_at").asc(nulls_last=True),
                "-created_at",
                "pk",
            )
        )
