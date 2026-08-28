"""
Vistas de API de órdenes de trabajo del canal técnico.

Lectura —«Mis órdenes» y la ficha de una orden— e inicio de atención, que es la
primera acción de escritura del canal. Atender y liquidar llegan los días 5 y
6. Ninguna vista de este módulo decide reglas de negocio: las acciones delegan
en los servicios de dominio que ya usa la web.
"""

from django.core.exceptions import ValidationError
from django.db.models import F
from django.http import Http404
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.api.permissions import IsActiveTechnician
from apps.work_orders.api.permissions import CanStartWorkOrder
from apps.work_orders.api.serializers import (
    WorkOrderDetailSerializer,
    WorkOrderListSerializer,
    WorkOrderStartAttentionSerializer,
)
from apps.work_orders.models import WorkOrder
from apps.work_orders.services import start_order_attention


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
    - **Solo lectura.** El listado no expone acciones: iniciar, atender y
      liquidar se piden sobre una orden concreta, no sobre la bandeja.
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


class TechnicianWorkOrderObjectMixin(TechnicianWorkOrdersMixin):
    """Resuelve **una** OT propia por id: la ficha y las acciones sobre ella.

    Añade a la base las relaciones que solo hacen falta al operar sobre una
    orden concreta —y que no se le cobran al listado— y unifica el 404.

    Es el punto donde el «no enumerar» deja de ser una decisión por vista y
    pasa a ser una propiedad del canal: cualquier endpoint que herede de aquí
    responde igual ante una orden ajena y una inexistente, sin tener que
    acordarse de implementarlo.
    """

    def get_queryset(self):
        # Encadenar `select_related` acumula sobre el del mixin base.
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


class MyWorkOrderDetailView(TechnicianWorkOrderObjectMixin, RetrieveAPIView):
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

    Solo lectura: `RetrieveAPIView` no expone POST, PATCH ni DELETE, así que
    ninguna acción de transición queda alcanzable desde este endpoint.
    """

    serializer_class = WorkOrderDetailSerializer


class StartWorkOrderAttentionView(TechnicianWorkOrderObjectMixin, GenericAPIView):
    """POST /api/technicians/work-orders/<id>/start/ — inicia la atención.

    Primera acción de escritura del canal técnico. **No implementa ninguna
    regla de transición**: llama a `start_order_attention()`, exactamente la
    misma función que ejecuta la vista web, que a su vez usa
    `WorkOrder.start_attention()` y mantiene coherente la suscripción —una
    instalación en preventa pasa a instalación—. Llamar al modelo directamente
    dejaría ese segundo efecto fuera, y reimplementar la comprobación de
    estados crearía una segunda matriz que podría desalinearse de la del
    dominio.

    La vista tampoco pregunta si la orden es iniciable: lo intenta y deja que
    el dominio acepte o rechace, igual que la web. Una comprobación previa
    aquí sería una regla duplicada con fecha de caducidad.

    **Tres capas, evaluadas en este orden y por separado:**

    1. `IsActiveTechnician` — ¿puedes operar en este canal?
    2. `CanStartWorkOrder` — ¿puedes ejecutar *esta acción*? Un técnico puede
       ver su OT y aun así no tener `start_workorder`: son preguntas distintas
       y ninguna suple a la otra.
    3. El queryset filtrado — ¿es tuya esta orden? 404 uniforme si no.

    El permiso de acción se evalúa **antes** de resolver la orden, igual que en
    la web: si el orden fuera el inverso, un técnico sin el permiso recibiría
    404 en la OT ajena y 403 en la propia, y esa diferencia le diría cuáles
    existen. Con este orden recibe 403 para cualquier id y no aprende nada.
    """

    permission_classes = [
        IsAuthenticated,
        IsActiveTechnician,
        CanStartWorkOrder,
    ]

    serializer_class = WorkOrderStartAttentionSerializer

    def post(self, request, *args, **kwargs):
        order = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            start_order_attention(
                order,
                user=request.user,
                remarks=serializer.validated_data["remarks"],
            )

        except ValidationError as exc:
            # El dominio rechazó el inicio (estado no iniciable, orden sin
            # técnico). El servicio es atómico: no quedó ni `started_at` ni
            # historial a medias. Se relee la orden para no serializar un
            # objeto en memoria que no refleje la base de datos.
            order.refresh_from_db()

            # El mensaje del dominio se devuelve tal cual: ya está redactado
            # para el operador y no expone trazas internas. Se unen en una
            # cadena para que `detail` tenga el mismo tipo que en el resto de
            # los errores del canal (401, 403, 404) y el cliente no tenga que
            # distinguir entre texto y lista según el código.
            return Response(
                {"detail": " ".join(exc.messages)},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # La respuesta es la ficha ya actualizada, con el serializador del día
        # 3: el cliente que acaba de iniciar no necesita una segunda petición
        # para refrescar la pantalla, y no se inventa una forma de respuesta
        # distinta para la misma orden.
        return Response(WorkOrderDetailSerializer(order).data)
