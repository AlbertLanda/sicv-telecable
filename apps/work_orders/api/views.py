"""
Vistas de API de órdenes de trabajo del canal técnico.

Tres endpoints de **solo lectura**: órdenes disponibles, mis órdenes y el
detalle de una orden propia. Ninguna acción de escritura vive aquí todavía:
la toma de la orden llega el viernes y delegará en los servicios de dominio
que ya usa la web, igual que hacen las vistas web hoy.

Ninguna vista de este módulo decide reglas de negocio. Qué es una orden
disponible lo define `api/queries.py`; de quién es una orden lo decide el
queryset a partir de `request.user`.
"""

from django.db.models import F
from django.http import Http404
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from apps.accounts.api.permissions import IsActiveTechnician
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.api.serializers import (
    AvailableWorkOrderSerializer,
    WorkOrderDetailSerializer,
    WorkOrderListSerializer,
)
from apps.work_orders.models import WorkOrder


class TechnicianChannelMixin:
    """Quién entra al canal y qué relaciones se precargan.

    **No decide qué órdenes se ven.** Esa separación es el punto de este
    mixin: «mis órdenes» y «disponibles» son universos opuestos —lo que ya
    tiene dueño frente a lo que no lo tiene— y meter el filtro por técnico en
    la base obligaría a que la bandeja de disponibles lo deshiciera. Un filtro
    de visibilidad que se aplica en un sitio y se revierte en otro es
    exactamente la clase de código donde se cuela un hueco.

    Lo que sí es común se declara una vez:

    - El permiso de canal. `IsAuthenticated` se repite explícito porque
      declarar `permission_classes` reemplaza el valor por defecto de los
      ajustes, y omitirlo dejaría los endpoints apoyados solo en el permiso
      de rol.
    - Las relaciones que cualquier fila pinta. Sin esto, listar N órdenes
      dispara una consulta por cliente, servicio, plan, tipo y subtipo de
      cada fila. Cada vista añade encima las suyas sin volver a declarar
      la base.
    """

    permission_classes = [IsAuthenticated, IsActiveTechnician]

    LIST_RELATIONS = (
        "subscription",
        "subscription__customer",
        "subscription__service_type",
        "subscription__plan",
        "order_type",
        "subtype",
    )

    def base_queryset(self):
        return WorkOrder.objects.select_related(*self.LIST_RELATIONS)


class AvailableWorkOrderListView(TechnicianChannelMixin, ListAPIView):
    """GET /api/technicians/work-orders/available/ — OT que se pueden tomar.

    Publica exactamente lo que el claim del viernes va a aceptar, porque
    ambos consumen `available_work_orders()`. Esa coincidencia no es un
    detalle de implementación: si el listado fuera más ancho que la toma, la
    app mostraría órdenes que al pulsarlas devuelven 409.

    **Sede: organización y filtro, no restricción dura.** El plan lo exige
    explícitamente. Por defecto se acota a la sede del técnico, que es lo que
    resuelve el 99 % de los casos, y `?scope=all` amplía a todas las sedes
    para las asignaciones legítimas fuera de sede. Lo que no existe es un
    parámetro de sede: el técnico puede *ampliar* su universo, nunca
    apuntarlo a otra sede concreta, así que no hay nada que manipular para
    espiar la carga de una sede ajena.

    A diferencia de «mis órdenes», este listado **no** filtra por
    `request.user`: por definición son órdenes de nadie. Lo que las protege es
    el permiso de canal —solo un técnico activo entra— y el propio filtro de
    disponibilidad, que deja fuera todo lo que ya tiene dueño.
    """

    serializer_class = AvailableWorkOrderSerializer

    # Universos que el técnico puede pedir. `branch` es el defecto; `all`
    # amplía. No hay un tercer valor que signifique «otra sede».
    SCOPE_BRANCH = "branch"
    SCOPE_ALL = "all"
    VALID_SCOPES = (SCOPE_BRANCH, SCOPE_ALL)

    def get_scope(self):
        """Universo pedido por el cliente, validado contra la lista blanca.

        Un valor desconocido responde 400 en lugar de caer en silencio al
        defecto. Ignorarlo devolvería un universo distinto del que el cliente
        pidió sin decírselo: la app creería estar viendo todas las sedes
        mientras mira solo una, y esa diferencia es invisible hasta que falta
        una orden.
        """
        scope = self.request.query_params.get("scope", self.SCOPE_BRANCH)

        if scope not in self.VALID_SCOPES:
            # `ParseError` y no `ValidationError` para que el cuerpo sea
            # `{"detail": "<mensaje>"}`, el mismo formato que el resto de los
            # errores del canal. `ValidationError` envolvería el mensaje en
            # una lista y obligaría al cliente a distinguir formatos según el
            # código de estado.
            raise ParseError(
                f"El valor de «scope» debe ser "
                f"{' o '.join(self.VALID_SCOPES)}."
            )

        return scope

    def get_queryset(self):
        # Se valida la entrada antes de construir nada: si el `scope` no es
        # válido la petición no llega a describir ninguna consulta.
        scope = self.get_scope()

        queryset = available_work_orders(
            self.base_queryset().select_related(
                "branch",
                "zone",
                "subscription__address",
            )
        )

        user = self.request.user

        # Un técnico sin sede registrada no se queda sin bandeja: filtrar por
        # `branch_id=None` devolvería siempre lista vacía, que es peor que no
        # filtrar. Ve todo lo disponible hasta que se le asigne una sede.
        if scope == self.SCOPE_BRANCH and user.branch_id:
            queryset = queryset.filter(branch_id=user.branch_id)

        # Cola de trabajo: primero lo que tiene fecha comprometida con el
        # cliente, después lo más antiguo sin programar. Es el orden inverso
        # al de la bandeja de despacho web (`-created_at`), que mira lo recién
        # ingresado; aquí lo viejo es lo que más urge repartir. El desempate
        # por `pk` mantiene el orden estable entre peticiones.
        return queryset.order_by(
            F("scheduled_at").asc(nulls_last=True),
            "created_at",
            "pk",
        )


class MyWorkOrdersMixin(TechnicianChannelMixin):
    """Restringe el universo a las órdenes del técnico autenticado.

    **El filtro por técnico vive aquí y solo aquí.** Es la única línea que
    impide que un técnico vea las órdenes de otro; duplicarla en cada vista
    significaría que un cambio futuro en el criterio podría aplicarse en un
    endpoint y olvidarse en el otro.

    El técnico sale de `request.user`. Ninguna vista lee un parámetro de la
    petición para decidir de quién son las órdenes, así que no hay parámetro
    que manipular.
    """

    def get_queryset(self):
        return self.base_queryset().filter(
            assigned_technician=self.request.user
        )


class MyWorkOrderListView(MyWorkOrdersMixin, ListAPIView):
    """GET /api/technicians/work-orders/ — OT asignadas al técnico autenticado.

    Decisiones deliberadas:

    - **Sin filtro por sede ni zona.** Al contrario que en «disponibles»,
      aquí la sede no organiza nada: son las órdenes que el técnico ya tiene.
      Ocultarle una porque quedó fuera de su sede sería precisamente la
      restricción dura que el plan prohíbe.
    - **Solo lectura.** El listado no expone acciones: tomar, iniciar y
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


class TechnicianWorkOrderObjectMixin(MyWorkOrdersMixin):
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

    **Una orden disponible todavía no es visible aquí**, y es intencional: el
    flujo aprobado pone «ver detalle» después de «tomar orden». Lo que el
    técnico necesita para decidir si la toma viaja en la fila de `available/`.

    Solo lectura: `RetrieveAPIView` no expone POST, PATCH ni DELETE, así que
    ninguna acción de transición queda alcanzable desde este endpoint.
    """

    serializer_class = WorkOrderDetailSerializer
