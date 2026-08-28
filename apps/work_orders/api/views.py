"""
Vistas de API de órdenes de trabajo del canal técnico.

Hoy solo lectura: «Mis órdenes» (lista) y la ficha de una orden (detalle). Las
acciones de transición llegan los días 4 a 6, delegando siempre en los
servicios de dominio que ya usa la web.
"""

from django.db.models import F
from django.http import Http404
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from apps.accounts.api.permissions import IsActiveTechnician
from apps.work_orders.api.serializers import (
    WorkOrderDetailSerializer,
    WorkOrderListSerializer,
)
from apps.work_orders.models import WorkOrder


class TechnicianWorkOrdersMixin:
    """Base común de los endpoints de OT del técnico: quién entra y qué ve.

    Existe para que **el filtro por técnico viva en un solo sitio**. Es la
    única línea que impide que un técnico vea las órdenes de otro, y estaba
    copiada en la lista; duplicarla en el detalle significaría que un cambio
    futuro en el criterio —filtrar también por sede, excluir órdenes
    liquidadas— podría aplicarse en un endpoint y olvidarse en el otro, que es
    exactamente la clase de desalineación que abre un hueco de visibilidad.

    El `select_related` también es compartido porque el serializador de
    detalle **extiende** al de la lista: todo lo que pinta la fila lo pinta
    también la ficha, así que las mismas relaciones hacen falta en ambos. Cada
    vista añade encima lo suyo (la lista su orden, el detalle sus relaciones
    extra) sin volver a declarar la base.
    """

    # `IsAuthenticated` es el permiso global; se repite explícito porque
    # declarar `permission_classes` reemplaza el valor por defecto y omitirlo
    # dejaría los endpoints apoyados solo en el permiso de rol.
    permission_classes = [IsAuthenticated, IsActiveTechnician]

    def get_queryset(self):
        return (
            WorkOrder.objects
            # El filtro es del servidor, no del cliente: sale de
            # `request.user` y ninguna vista lee un parámetro de la petición
            # para decidir de quién son las órdenes. No hay parámetro que
            # manipular.
            .filter(assigned_technician=self.request.user)
            # Mismo criterio que la bandeja de despacho web: todo lo que el
            # serializador pinta se trae en la misma consulta. Sin esto,
            # listar N órdenes dispara una consulta por cliente, servicio,
            # plan, tipo y subtipo de cada fila.
            .select_related(
                "subscription",
                "subscription__customer",
                "subscription__service_type",
                "subscription__plan",
                "order_type",
                "subtype",
            )
        )


class MyWorkOrderListView(TechnicianWorkOrdersMixin, ListAPIView):
    """GET /api/technicians/work-orders/ — OT asignadas al técnico autenticado.

    Decisiones deliberadas:

    - **El filtro es del servidor, no del cliente**, y hoy vive en
      `TechnicianWorkOrdersMixin`, compartido con el detalle.
    - **Sin filtro por sede ni zona.** La sede del técnico es referencia
      operativa, no restricción de elegibilidad (decidido en el bloque de
      asignación), así que se lista todo lo asignado. El filtro por sede/zona
      es alcance del bloque 2 (App del técnico), y queda documentado como
      pendiente, no como olvido.
    - **Solo lectura.** No hay acciones de transición: los días 4 a 6 las
      montan sobre los servicios de dominio.
    """

    serializer_class = WorkOrderListSerializer

    def get_queryset(self):
        return (
            super().get_queryset()
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


class MyWorkOrderDetailView(TechnicianWorkOrdersMixin, RetrieveAPIView):
    """GET /api/technicians/work-orders/<id>/ — ficha de una OT propia.

    **El 404 uniforme no se programa: se hereda del queryset.**
    `RetrieveAPIView` resuelve el objeto con `get_object_or_404` sobre el
    queryset que devuelve el mixin, que ya está filtrado por técnico. Por eso
    «no existe» y «es de otro técnico» recorren exactamente el mismo camino de
    código y producen la misma respuesta: para esta vista la orden ajena
    sencillamente no está en el universo consultado.

    Deliberadamente **no** hay `has_object_permission` ni ninguna comprobación
    posterior sobre el objeto ya resuelto. Un chequeo así devolvería 403, que
    confirmaría al que pregunta que la orden existe y es de otro — justo lo que
    el principio de no enumerar del día 1 evita. La seguridad vive en el
    queryset, no en un permiso que llega tarde.

    Lo único que se ajusta a mano es el **texto** del 404 (ver `get_object`),
    no cuándo se emite.

    Solo lectura: `RetrieveAPIView` no expone POST, PATCH ni DELETE, así que
    ninguna acción de transición queda alcanzable desde este endpoint.
    """

    serializer_class = WorkOrderDetailSerializer

    def get_queryset(self):
        # Encadenar `select_related` acumula sobre el del mixin: estas son las
        # relaciones que solo la ficha necesita, y no se le cobran al listado.
        return super().get_queryset().select_related(
            "subscription__address",
            "branch",
            "zone",
        )

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            # Se sustituye el mensaje de Django («No WorkOrder matches the
            # given query.»), que va en inglés y nombra el modelo interno, por
            # el 404 estándar de DRF, que el proyecto ya sirve en español.
            #
            # No cambia la lógica: sigue siendo un único `raise` para los dos
            # casos —orden inexistente y orden ajena—, así que las respuestas
            # continúan siendo indistinguibles. Lo que se corrige es qué
            # cuenta el mensaje al cliente, no cuándo se emite.
            raise NotFound()
