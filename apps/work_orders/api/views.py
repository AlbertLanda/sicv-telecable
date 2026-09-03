"""
Vistas de API de órdenes de trabajo del canal técnico.

Tres endpoints de lectura —órdenes disponibles, mis órdenes y el detalle de una
orden propia— y **una** acción de escritura: la toma de la orden (`claim/`).

Ninguna vista de este módulo decide reglas de negocio. Qué es una orden
disponible lo define `api/queries.py`; de quién es una orden lo decide el
queryset a partir de `request.user`; y la transición de la toma la ejecuta
`WorkOrder.assign_technician()`, el mismo método que usa la bandeja web. Lo
único que la vista de escritura añade sobre el dominio es el **bloqueo de
fila**, que es una responsabilidad del canal y no una regla nueva.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.http import Http404
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.api.permissions import IsActiveTechnician
from apps.work_orders.api.permissions import CanClaimWorkOrder
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.api.serializers import (
    AvailableWorkOrderSerializer,
    WorkOrderClaimSerializer,
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

    # Relaciones que solo hacen falta al operar sobre UNA orden y que no se le
    # cobran a los listados. Se declaran aquí, y no dentro del detalle, porque
    # hay dos consumidores: la ficha de `<id>/` y la respuesta de `claim/`,
    # que devuelve esa misma ficha. Escritas dos veces, un campo nuevo en el
    # detalle costaría una consulta extra en la toma sin que nadie lo note.
    OBJECT_RELATIONS = (
        "subscription__address",
        "branch",
        "zone",
        "reason",
        # Reverso uno-a-uno: trae el bloque técnico en la misma consulta. Sin
        # esto, cada ficha dispara una consulta extra solo para descubrir que
        # la orden todavía no tiene liquidación, que es el caso más frecuente.
        "liquidation",
    )

    def base_queryset(self):
        return WorkOrder.objects.select_related(*self.LIST_RELATIONS)

    def object_queryset(self):
        """Consulta para pintar **una** orden completa, sin filtrar por dueño.

        El filtro por técnico es responsabilidad de quien la use: el detalle
        lo aplica (`MyWorkOrdersMixin`), y la toma no puede aplicarlo porque
        opera justo sobre órdenes que todavía no tienen dueño.
        """
        return self.base_queryset().select_related(*self.OBJECT_RELATIONS)


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
        # Encadenar `select_related` acumula sobre el del mixin base. Las
        # relaciones se leen de `OBJECT_RELATIONS`, compartidas con la
        # respuesta de la toma, para no declararlas dos veces.
        return super().get_queryset().select_related(*self.OBJECT_RELATIONS)

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


class ClaimWorkOrderView(TechnicianChannelMixin, GenericAPIView):
    """POST /api/technicians/work-orders/<id>/claim/ — el técnico toma la OT.

    Única acción de escritura del canal. **No implementa ninguna transición**:
    llama a `WorkOrder.assign_technician()`, exactamente el mismo método que
    ejecuta la bandeja de despacho web (`views.py:214`), que mueve
    PENDING → ASSIGNED por `change_status()`, deja historial y abre el
    `WorkOrderAssignment`. Reimplementar la comprobación de estados aquí
    crearía una segunda matriz que podría desalinearse de la del dominio.

    La diferencia con el despacho web no está en el mecanismo sino en **quién
    decide**: allí un supervisor elige a quién le toca, aquí el técnico se
    adjudica trabajo sin dueño. Por eso `assigned_by` y `technician` son el
    mismo usuario, y así queda en la traza: una asignación donde ambos
    coinciden es, en el historial, una orden tomada desde la app.

    **No hereda de `TechnicianWorkOrderObjectMixin`** —corrección de lo que
    anticipaba `docs/api_technician_work_orders.md` §4—. Ese mixin filtra por
    `assigned_technician = request.user`, y una orden tomable no tiene técnico
    asignado: heredarlo daría un universo vacío y ninguna orden podría
    tomarse nunca. La toma resuelve su objeto contra
    `available_work_orders()`, que es el universo correcto y además el mismo
    que publica `available/`.

    **Cuatro capas, evaluadas en este orden y por separado:**

    1. `IsActiveTechnician` — ¿puedes operar en este canal?
    2. `CanClaimWorkOrder` — ¿puedes ejecutar *esta acción*? (bloqueo B3: hoy
       no exige un permiso Django adicional; ver `api/permissions.py`.)
    3. `available_work_orders()` bajo bloqueo de fila — ¿está tomable *ahora*?
    4. El dominio — ¿admite la transición?

    Las dos primeras se evalúan antes de resolver la orden, así que quien no
    puede tomar recibe `403` para cualquier id y no puede sondear cuáles
    existen.
    """

    # Se **suma** a la lista del canal en lugar de reescribirla: si mañana se
    # agrega un permiso de canal, la toma lo hereda sin que nadie tenga que
    # acordarse de repetirlo aquí.
    permission_classes = (
        TechnicianChannelMixin.permission_classes + [CanClaimWorkOrder]
    )

    serializer_class = WorkOrderClaimSerializer

    # Una sola respuesta para todo lo que no se puede tomar: inexistente, ya
    # tomada, de otro técnico, en otro estado o de otro tipo. Es deliberado
    # que sean indistinguibles —mismo código y mismo cuerpo—, por el mismo
    # principio de no enumeración que el 404 del detalle: si «no existe»
    # respondiera distinto de «ya la tomó otro», el técnico podría descubrir
    # qué ids existen probándolos.
    #
    # El código es 409 y no 404 porque la pregunta del cliente no es «¿existe
    # esta orden?» sino «¿puedo tomarla?», y la respuesta —para todos esos
    # casos— es que ya no está disponible. El mensaje dice exactamente eso y
    # no cuenta de más.
    UNAVAILABLE_DETAIL = "La orden ya no está disponible."

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = self.claim(remarks=serializer.validated_data["remarks"])

        except WorkOrder.DoesNotExist:
            return Response(
                {"detail": self.UNAVAILABLE_DETAIL},
                status=http_status.HTTP_409_CONFLICT,
            )

        except ValidationError as exc:
            # Red de seguridad, no camino esperado: las condiciones que
            # `assign_technician()` valida —técnico activo con rol técnico,
            # orden en un estado asignable— ya las garantizan el permiso de
            # canal y el filtro de disponibilidad. Se captura para que una
            # regla de dominio futura se manifieste como un 400 con su mensaje
            # en español y no como un 500. La transacción ya revirtió: no
            # queda ni asignación ni historial a medias.
            #
            # Los mensajes se unen en una cadena para que `detail` tenga el
            # mismo tipo que en el resto de los errores del canal y el cliente
            # no distinga entre texto y lista según el código.
            return Response(
                {"detail": " ".join(exc.messages)},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # La respuesta es la ficha completa, con el serializador del detalle:
        # el técnico que acaba de tomar la orden ya necesita la dirección y
        # las coordenadas —que la fila de `available/` no lleva—, y así no
        # hace una segunda petición para empezar a moverse. Se relee por
        # `object_queryset()` en lugar de serializar la instancia bloqueada:
        # esa se cargó sin `select_related` a propósito (ver `claim()`), y
        # pintarla dispararía una consulta por cada relación.
        claimed = self.object_queryset().get(pk=order.pk)

        return Response(WorkOrderDetailSerializer(claimed).data)

    @transaction.atomic
    def claim(self, *, remarks):
        """Resuelve la orden bajo bloqueo de fila y la adjudica al técnico.

        Cierra el hueco detectado en la auditoría del día 1 (§2.3):
        `assign_technician()` es atómico pero **no bloquea la fila** —valida
        `self.status` sobre la instancia ya cargada en memoria—, así que dos
        tomas simultáneas de la misma OT podrían leer ambas `PENDING` y pasar
        las dos, dejando a dos técnicos convencidos de ser el responsable. El
        bloqueo se resuelve aquí, en el canal, sin modificar el dominio.

        Todo el peso está en que **el filtro viaja dentro del
        `select_for_update()`**: el ganador toma el lock con la orden aún
        disponible; el perdedor espera, y cuando el lock se libera la orden ya
        no cumple el filtro —tiene dueño y está en ASSIGNED—, así que cae en
        `DoesNotExist` y recibe 409. Si la comprobación se hiciera antes o
        después del bloqueo en lugar de dentro, la carrera seguiría abierta.

        El universo es `available_work_orders()`, la **misma** función que
        publica `available/`. Esa coincidencia es la garantía de que lo
        listado es exactamente lo tomable: sin ella, un listado más ancho que
        la toma haría que la app muestre órdenes que al pulsarlas rebotan con
        409 sin explicación posible. Y trae de regalo dos cosas que no hay que
        programar aquí: una orden de otro técnico no es tomable (tiene dueño)
        y una `SYSTEM` de NOC tampoco (no es de campo).

        **`of=("self",)` es intencional.** El filtro por
        `order_type__code` obliga a un JOIN con el catálogo, y un
        `FOR UPDATE` sin `of` bloquearía también esa fila: como todas las
        instalaciones comparten el mismo `OrderType`, cada toma esperaría a la
        anterior en el sistema completo, no solo en su orden. Limitando el
        bloqueo a `self` se lockea la OT y nada más. En SQLite (desarrollo y
        CI) toda la cláusula se ignora y las escrituras se serializan a nivel
        de base de datos; en PostgreSQL (producción) el bloqueo es real.

        **No se filtra por sede.** El plan lo exige: la sede organiza y
        filtra, nunca restringe. `available/` la usa para ordenar la bandeja
        —con `?scope=all` para ampliar—, pero una asignación legítima fuera de
        sede no puede quedar bloqueada en la toma.
        """
        order = available_work_orders(
            # Sin `select_related`: la consulta que bloquea trae solo la fila
            # de la OT. Añadir relaciones aquí metería LEFT JOIN por las FK
            # opcionales (`zone`, `subtype`), y PostgreSQL rechaza un
            # `FOR UPDATE` sobre el lado nulable de un outer join. La ficha se
            # relee después, ya fuera de la carrera.
            WorkOrder.objects.select_for_update(of=("self",))
        ).get(pk=self.kwargs["pk"])

        order.assign_technician(
            # El técnico sale de `request.user`, jamás del cuerpo: no hay
            # parámetro que manipular para tomar una orden en nombre de otro.
            self.request.user,
            # Quien adjudica es el propio técnico. La traza lo refleja tal
            # cual en lugar de dejarlo vacío: una asignación con `assigned_by`
            # nulo se leería como un dato faltante, y aquí sí se sabe quién
            # decidió.
            assigned_by=self.request.user,
            remarks=remarks,
        )

        return order
