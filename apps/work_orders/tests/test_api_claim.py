"""
Pruebas del endpoint «Tomar orden» (claim) de la API del técnico.

Es la única acción de escritura del canal: el técnico se adjudica una OT del
pool sin dueño y la orden pasa PENDING → ASSIGNED con él como responsable.

Lo que estas pruebas fijan, en orden de importancia:

1. **Que nadie pueda quedarse con una orden ajena.** `assign_technician()`
   admite reasignar una orden ya ASSIGNED —es una potestad legítima del
   despacho web—, así que lo único que impide que un técnico se apropie de la
   orden de otro por la API es que el universo de la toma sea
   `available_work_orders()`. Hay una prueba dedicada a ese robo.
2. **Que lo listado sea exactamente lo tomable.** Las dos puntas del canal
   consumen la misma definición; aquí se verifica de ida (lo disponible se
   toma) y de vuelta (lo tomado desaparece de la bandeja).
3. **Que la respuesta a lo no tomable sea siempre la misma**, sin distinguir
   entre una orden inexistente y una que ya tiene dueño.
4. **Que el bloqueo de fila se pida de verdad**, y limitado a la OT.
5. **Que el cliente no decida nada**: ni el técnico, ni el estado, ni la hora.

Se apoyan en `WorkOrderTestCase`, que ya construye sede, zona, cliente,
dirección, suscripción, catálogos y los usuarios `technician`,
`other_technician`, `atc_user` y `supervisor`.
"""

from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organization.models import Branch
from apps.services.models import Subscription
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.models import OrderType, WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


class ClaimWorkOrderAPITestCase(WorkOrderTestCase):
    """Base de las pruebas: cliente de API y helpers de ruta."""

    def setUp(self):
        super().setUp()

        self.api = APIClient()

    def authenticate(self, user):
        """Autentica el cliente de API con el token del usuario indicado."""
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return token

    def claim_url(self, order_or_pk):
        pk = getattr(order_or_pk, "pk", order_or_pk)

        return reverse("work_orders_api:claim", args=[pk])

    def claim(self, order_or_pk, **payload):
        return self.api.post(self.claim_url(order_or_pk), payload)

    def unknown_pk(self):
        """Un id que con seguridad no corresponde a ninguna orden."""
        last = WorkOrder.objects.order_by("-pk").first()

        return (last.pk if last else 0) + 1000


class ClaimSuccessTests(ClaimWorkOrderAPITestCase):
    """El camino feliz y lo que deja registrado."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def test_technician_claims_an_available_order(self):
        """El caso canónico del hito: la OT del alta comercial se toma.

        Nace PENDING, sin técnico y de campo, y una sola petición la deja
        asignada al técnico que la pidió, sin paso intermedio ni intervención
        de despacho.
        """
        order = self.create_order()

        response = self.claim(order)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(order.assigned_technician, self.technician)

    def test_claim_opens_a_single_assignment_traced_to_the_technician(self):
        """La traza queda en `WorkOrderAssignment`, no solo en la OT.

        En una toma, quien adjudica y quien recibe son el mismo usuario: es lo
        que distingue en el historial una orden tomada desde la app de una
        despachada por un supervisor. `assigned_by` se registra en lugar de
        dejarse nulo, que se leería como un dato faltante.
        """
        order = self.create_order()

        self.claim(order)

        assignments = order.assignments.all()

        self.assertEqual(assignments.count(), 1)

        assignment = assignments.first()

        self.assertEqual(assignment.technician, self.technician)
        self.assertEqual(assignment.assigned_by, self.technician)
        self.assertIsNone(assignment.unassigned_at)

    def test_claim_records_the_transition_in_the_history(self):
        """El estado se mueve por el mecanismo oficial, con historial.

        La vista no escribe `status`: lo hace `change_status()` dentro de
        `assign_technician()`. Que exista el registro PENDING → ASSIGNED es la
        prueba de que la transición pasó por el dominio y no por un `update`.
        """
        order = self.create_order()

        self.claim(order)

        entry = order.status_history.first()

        self.assertEqual(entry.previous_status, WorkOrder.Status.PENDING)
        self.assertEqual(entry.new_status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(entry.changed_by, self.technician)

    def test_remarks_travel_to_the_assignment_and_the_history(self):
        """La observación es lo único que el técnico aporta, y se conserva."""
        order = self.create_order()

        self.claim(order, remarks="Voy en camino, llego en 20 minutos.")

        self.assertEqual(
            order.assignments.first().remarks,
            "Voy en camino, llego en 20 minutos.",
        )
        self.assertEqual(
            order.status_history.first().remarks,
            "Voy en camino, llego en 20 minutos.",
        )

    def test_claim_without_body_is_valid(self):
        """`remarks` es opcional: tomar la orden no exige escribir nada."""
        order = self.create_order()

        response = self.api.post(self.claim_url(order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(order.assignments.first().remarks, "")

    def test_response_is_the_full_ficha_with_the_address(self):
        """La respuesta trae ya la ficha del detalle, no la fila de la bandeja.

        El técnico que acaba de tomar la orden necesita la dirección y las
        coordenadas —que `available/` deliberadamente no publica— para
        empezar a moverse. Devolverlas aquí le ahorra una segunda petición, y
        además demuestra que ya tiene derecho a verlas: la orden es suya.
        """
        order = self.create_order()

        response = self.claim(order)

        self.assertEqual(
            set(response.data.keys()),
            {
                "id",
                "order_number",
                "customer",
                "service_type",
                "plan",
                "order_type",
                "subtype",
                "status",
                "status_display",
                "priority",
                "priority_display",
                "scheduled_at",
                "created_at",
                "address",
                "detail",
                "branch",
                "zone",
                "reason",
                "started_at",
                "attended_at",
                "can_start_attention",
                "technical_data",
            },
        )

        # Recién tomada: nada ejecutado todavía, y la siguiente acción
        # disponible es iniciar la atención. La app lo lee del dominio en vez
        # de deducirlo del estado.
        self.assertIsNone(response.data["started_at"])
        self.assertIsNone(response.data["technical_data"])
        self.assertTrue(response.data["can_start_attention"])

        # El estado que viaja es el de después de la toma, no el de antes: la
        # ficha se relee de la base tras la transición.
        self.assertEqual(response.data["status"], WorkOrder.Status.ASSIGNED)
        self.assertEqual(response.data["status_display"], "Asignada")

        self.assertEqual(
            response.data["address"]["address"],
            "Av. Los Álamos 123",
        )


class ClaimChannelInvariantTests(ClaimWorkOrderAPITestCase):
    """Coherencia entre la bandeja, la toma y «mis órdenes»."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def test_everything_available_can_actually_be_claimed(self):
        """De ida: lo que la bandeja publica, la toma lo acepta.

        Es el invariante del canal visto desde el cliente. Si el listado fuera
        más ancho que la toma, el técnico vería órdenes que al pulsarlas
        rebotan con 409 sin explicación posible.
        """
        self.create_order()
        self.create_order(scheduled_at=None, priority=WorkOrder.Priority.HIGH)

        listed = self.api.get(reverse("work_orders_api:available")).data

        self.assertTrue(listed)

        for row in listed:
            with self.subTest(orden=row["order_number"]):
                response = self.claim(row["id"])

                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_claimed_order_leaves_the_available_pool(self):
        """De vuelta: lo tomado desaparece de la bandeja compartida.

        Sin esto dos técnicos verían la misma orden después de que uno la
        tomara, y el segundo perdería el viaje.
        """
        order = self.create_order()

        available_url = reverse("work_orders_api:available")

        self.assertIn(
            order.order_number,
            [row["order_number"] for row in self.api.get(available_url).data],
        )

        self.claim(order)

        self.assertEqual(self.api.get(available_url).data, [])

    def test_claimed_order_becomes_visible_in_my_orders_and_detail(self):
        """Tomar es lo que abre el detalle: antes 404, después 200.

        El flujo aprobado pone *ver detalle* después de *tomar orden*, y el
        detalle solo responde sobre órdenes propias. Esta prueba recorre el
        cambio de universo completo en una sola secuencia.
        """
        order = self.create_order()

        detail_url = reverse("work_orders_api:my_order_detail", args=[order.pk])

        self.assertEqual(
            self.api.get(detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.claim(order)

        self.assertEqual(
            self.api.get(detail_url).status_code,
            status.HTTP_200_OK,
        )

        self.assertIn(
            order.order_number,
            [
                row["order_number"]
                for row in self.api.get(reverse("work_orders_api:my_orders")).data
            ],
        )


class ClaimUnavailableOrderTests(ClaimWorkOrderAPITestCase):
    """Lo que no se puede tomar, y que todo responde igual."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def assertUnavailable(self, response):
        """Respuesta única de «no tomable»: 409 con `detail` de texto."""
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIsInstance(response.data["detail"], str)

    def test_order_already_taken_by_another_technician_is_not_stolen(self):
        """**Ningún técnico puede apropiarse de la orden de otro.**

        Es la prueba central de seguridad del endpoint. `assign_technician()`
        acepta reasignar una orden en ASSIGNED —es una potestad legítima del
        despacho web, que decide a quién le toca— así que si la toma resolviera
        la orden por `pk` sin más, un técnico podría arrebatarle el trabajo a
        otro con una sola petición. Lo único que lo impide es que el universo
        de la toma sea `available_work_orders()`, donde una orden con dueño no
        está.

        Se comprueba también que la orden **no cambió**: no basta con recibir
        409 si por el camino se abrió una asignación nueva.
        """
        order = self.create_assigned_order()

        self.authenticate(self.other_technician)

        self.assertUnavailable(self.claim(order))

        order.refresh_from_db()

        self.assertEqual(order.assigned_technician, self.technician)
        self.assertEqual(order.status, WorkOrder.Status.ASSIGNED)
        self.assertEqual(order.assignments.count(), 1)

    def test_second_claim_of_the_same_order_is_rejected(self):
        """Tomar dos veces la misma orden no reasigna ni duplica la traza.

        Incluye el caso del propio dueño: un segundo POST del mismo técnico
        —doble toque en la app, o un reintento por red intermitente— recibe
        409 y no abre una segunda asignación.

        Que ese reintento del dueño responda 409 en lugar de devolver la ficha
        está registrado como bloqueo B9: si negocio quiere que la toma sea
        idempotente para el mismo técnico, es la app quien hoy debe recuperarse
        recargando «mis órdenes». Ver docs/api_technician_claim.md §7.
        """
        order = self.create_order()

        self.assertEqual(self.claim(order).status_code, status.HTTP_200_OK)

        self.assertUnavailable(self.claim(order))

        order.refresh_from_db()

        self.assertEqual(order.assigned_technician, self.technician)
        self.assertEqual(order.assignments.count(), 1)
        self.assertEqual(order.status_history.count(), 1)

    def test_unknown_order_is_indistinguishable_from_an_unavailable_one(self):
        """No enumerar: «no existe» y «ya tiene dueño» responden idéntico.

        Se comparan código **y** cuerpo. Si difirieran, un técnico podría
        descubrir qué ids de orden existen probándolos uno por uno, que es
        justo lo que el 404 uniforme del detalle evita en la lectura.
        """
        foreign = self.create_assigned_order()

        unknown_response = self.claim(self.unknown_pk())
        foreign_response = self.claim(foreign)

        self.assertUnavailable(unknown_response)
        self.assertUnavailable(foreign_response)

        self.assertEqual(
            unknown_response.status_code,
            foreign_response.status_code,
        )
        self.assertEqual(unknown_response.data, foreign_response.data)

    def test_system_attention_order_cannot_be_claimed(self):
        """Una OT de Sistema/NOC no la toma un técnico de campo.

        Regla permanente. Si se pudiera tomar, pasaría a ASSIGNED con un
        técnico de campo como responsable y quedaría bloqueada para quien debe
        resolverla en remoto. La condición no se reescribe aquí: viene del
        mismo filtro que oculta la orden en la bandeja.
        """
        order = self.create_order(
            attention_type=WorkOrder.AttentionType.SYSTEM,
        )

        self.assertUnavailable(self.claim(order))

        order.refresh_from_db()

        self.assertIsNone(order.assigned_technician)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)

    def test_other_order_types_cannot_be_claimed(self):
        """Recorte de alcance del MVP: solo instalaciones.

        Cortes, reconexiones y traslados se siguen despachando desde la web.
        Poder tomarlos por la API convertiría la app en una segunda vía de
        despacho para procesos que nadie pidió mover.
        """
        for order_type in (
            self.cut_type,
            self.reconnection_type,
            self.transfer_type,
        ):
            with self.subTest(tipo=order_type.code):
                order = self.create_order(order_type=order_type)

                self.assertUnavailable(self.claim(order))

    def test_demo_installation_type_cannot_be_claimed(self):
        """El tipo de datos de prueba tampoco entra por la toma.

        La comparación por código es exacta. La prueba lo fija para que un
        futuro `startswith` o `icontains` en la definición no lo cuele.
        """
        demo_type = OrderType.objects.create(
            code="DEMO-INSTALLATION",
            name="Instalación (demo)",
        )

        self.assertUnavailable(self.claim(self.create_order(order_type=demo_type)))

    def test_order_of_a_cancelled_subscription_cannot_be_claimed(self):
        """Mitigación B10: la toma la hereda sin escribir una línea.

        Al vivir la condición en `available_work_orders()`, la orden deja de
        ser tomable en el mismo momento en que deja de publicarse. Es
        exactamente el beneficio de que el listado y la toma compartan
        definición: la protección llega a las dos puntas o a ninguna.

        Evita el caso operativo concreto: un técnico viajando a instalar un
        servicio que comercialmente ya se canceló.
        """
        order = self.create_order()

        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        self.assertUnavailable(self.claim(order))

        order.refresh_from_db()

        self.assertIsNone(order.assigned_technician)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)

    def test_non_pending_states_cannot_be_claimed(self):
        """Solo PENDING, incluidos los estados asignables del dominio.

        `DERIVED` y `REPROGRAMMED` son asignables para el dominio, pero en
        ambos ya hubo una decisión operativa previa —derivar a otra área,
        pactar fecha con el cliente— que una toma desde la app desharía sin
        que nadie se entere. Los terminales quedan fuera por definición.
        """
        for state in (
            WorkOrder.Status.DERIVED,
            WorkOrder.Status.REPROGRAMMED,
            WorkOrder.Status.CANCELLED,
            WorkOrder.Status.NOT_FEASIBLE,
        ):
            with self.subTest(estado=state):
                order = self.create_order(status=state)

                self.assertUnavailable(self.claim(order))

                order.refresh_from_db()

                self.assertEqual(order.status, state)
                self.assertIsNone(order.assigned_technician)


class ClaimConcurrencyTests(ClaimWorkOrderAPITestCase):
    """El hueco de concurrencia del día 1 y cómo se cierra."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def test_the_claim_locks_only_the_work_order_row(self):
        """La toma pide bloqueo de fila, y solo sobre la OT.

        Prueba de caja blanca a propósito. El escenario que importa —dos tomas
        simultáneas de la misma orden— no es reproducible en SQLite, donde la
        cláusula `FOR UPDATE` se ignora y las escrituras se serializan a nivel
        de base de datos; en PostgreSQL, el motor de producción, el bloqueo es
        real. Como el comportamiento no se puede observar en el entorno de
        pruebas, se verifica que la consulta lo **pida**, que es lo que un
        refactor podría perder en silencio.

        `of=("self",)` no es un detalle de estilo: el filtro por
        `order_type__code` obliga a un JOIN con el catálogo, y un `FOR UPDATE`
        sin `of` bloquearía también esa fila. Como todas las instalaciones
        comparten el mismo `OrderType`, cada toma quedaría esperando a la
        anterior en el sistema completo en vez de solo en su propia orden.
        """
        order = self.create_order()

        with patch(
            "apps.work_orders.api.views.available_work_orders",
            wraps=available_work_orders,
        ) as spy:
            response = self.claim(order)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        locked_queryset = spy.call_args.args[0]

        self.assertTrue(locked_queryset.query.select_for_update)
        self.assertEqual(locked_queryset.query.select_for_update_of, ("self",))

    def test_the_loser_of_the_race_gets_the_unavailable_response(self):
        """Resultado observable de la carrera: uno gana, el otro recibe 409.

        Es el escenario secuencial equivalente al que el bloqueo garantiza en
        paralelo: cuando el segundo técnico llega, la orden ya tiene dueño y no
        cumple el filtro. Lo que se fija es que **nunca queden dos técnicos
        convencidos de ser el responsable**.
        """
        order = self.create_order()

        self.assertEqual(self.claim(order).status_code, status.HTTP_200_OK)

        self.authenticate(self.other_technician)
        loser = self.claim(order)

        self.assertEqual(loser.status_code, status.HTTP_409_CONFLICT)

        order.refresh_from_db()

        self.assertEqual(order.assigned_technician, self.technician)

        # Una sola asignación vigente: el perdedor no dejó rastro.
        self.assertEqual(
            order.assignments.filter(unassigned_at__isnull=True).count(),
            1,
        )

    def test_a_rejected_claim_leaves_nothing_behind(self):
        """Una toma rechazada no escribe nada: ni traza, ni historial.

        La resolución y la adjudicación viven en la misma transacción, así que
        no hay estado intermedio observable.
        """
        order = self.create_order(attention_type=WorkOrder.AttentionType.SYSTEM)

        self.claim(order)

        self.assertEqual(order.assignments.count(), 0)
        self.assertEqual(order.status_history.count(), 0)


class ClaimBranchScopeTests(ClaimWorkOrderAPITestCase):
    """Sede: organiza y filtra la bandeja, nunca bloquea la toma."""

    def test_order_from_another_branch_can_be_claimed(self):
        """Criterio de aceptación del plan (4.1) en la acción de escritura.

        La bandeja oculta por defecto las órdenes de otra sede y `?scope=all`
        las muestra; la toma **no filtra por sede en absoluto**. Si lo hiciera,
        una asignación legítima fuera de sede quedaría bloqueada: el técnico
        vería la orden con `scope=all` y no podría tomarla, que es exactamente
        la restricción dura que el plan prohíbe.
        """
        other_branch = Branch.objects.create(code="SED02", name="Sede Norte")

        foreign = self.create_order(branch=other_branch, zone=None)

        self.authenticate(self.technician)

        response = self.claim(foreign)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        foreign.refresh_from_db()

        self.assertEqual(foreign.assigned_technician, self.technician)

    def test_technician_without_branch_can_claim(self):
        """Sin sede registrada el técnico sigue pudiendo trabajar.

        Un dato administrativo faltante no debe dejarlo sin poder tomar
        órdenes, igual que no lo deja sin bandeja.
        """
        order = self.create_order()

        homeless = User.objects.create_user(
            username="tecnico_sin_sede",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=None,
        )

        self.authenticate(homeless)

        self.assertEqual(self.claim(order).status_code, status.HTTP_200_OK)


class ClaimPermissionTests(ClaimWorkOrderAPITestCase):
    """Quién puede tomar, y en qué orden se evalúa.

    Cada prueba comprueba además que la orden **sigue disponible** después del
    rechazo: un 401 o un 403 que ya hubiera tocado la orden sería peor que un
    200 mal dado.
    """

    def setUp(self):
        super().setUp()

        self.order = self.create_order()

    def assertOrderUntouched(self):
        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(self.order.assigned_technician)

    def test_request_without_token_is_rejected(self):
        """Sin token -> 401."""
        response = self.claim(self.order)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertOrderUntouched()

    def test_authenticated_non_technician_is_rejected(self):
        """Con token pero sin rol técnico -> 403 por el permiso de canal.

        Un usuario de ATC o un supervisor no toma órdenes: despacha desde la
        web, donde la acción tiene su propio permiso funcional.
        """
        for user in (self.atc_user, self.supervisor):
            with self.subTest(rol=user.role):
                self.authenticate(user)

                response = self.claim(self.order)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                )
                self.assertOrderUntouched()

    def test_technician_moved_to_another_role_loses_the_claim(self):
        """El permiso de canal se reevalúa en cada petición.

        El token del canal técnico no caduca, así que un cambio de rol
        posterior al login tiene que cortar el acceso en la siguiente
        petición, no cuando el token expire.
        """
        self.authenticate(self.technician)

        self.technician.role = User.Role.ATC
        self.technician.save(update_fields=["role"])

        response = self.claim(self.order)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertOrderUntouched()

    def test_permission_is_evaluated_before_the_object(self):
        """Quien no puede tomar recibe 403 para cualquier id.

        Si el objeto se resolviera primero, un no-técnico recibiría 409 en un
        id existente y 403 en el resto —o al revés—, y esa diferencia le diría
        qué órdenes existen. Evaluar el permiso antes cierra el sondeo.
        """
        self.authenticate(self.atc_user)

        response = self.claim(self.unknown_pk())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_functional_permission_gates_the_claim(self):
        """Cableado del bloqueo B3: cuando haya permiso funcional, manda.

        Hoy `CLAIM_PERMISSION` es `None` y la autorización de la toma es el
        permiso de canal (ver `api/permissions.py`). Esta prueba fija que
        cerrar B3 sea cambiar **una línea**: se simula el permiso decidido y se
        comprueba que un técnico sin él recibe 403 —antes de resolver la
        orden— y que con él concedido la toma vuelve a funcionar.

        Se usa `assign_workorder` solo porque existe hoy en el catálogo de
        permisos; la prueba no propone que sea ese el elegido.
        """
        from django.contrib.auth.models import Permission

        self.authenticate(self.technician)

        with patch(
            "apps.work_orders.api.permissions.CLAIM_PERMISSION",
            "work_orders.assign_workorder",
        ):
            self.assertEqual(
                self.claim(self.order).status_code,
                status.HTTP_403_FORBIDDEN,
            )
            self.assertOrderUntouched()

            self.technician.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="work_orders",
                    codename="assign_workorder",
                )
            )
            # El caché de permisos del usuario se resuelve una vez por
            # instancia: hay que releerla para que la concesión se note.
            self.technician = User.objects.get(pk=self.technician.pk)
            self.authenticate(self.technician)

            self.assertEqual(
                self.claim(self.order).status_code,
                status.HTTP_200_OK,
            )


class ClaimContractTests(ClaimWorkOrderAPITestCase):
    """Forma del endpoint: métodos admitidos y qué se ignora del cuerpo."""

    def setUp(self):
        super().setUp()

        self.order = self.create_order()
        self.authenticate(self.technician)

    def test_only_post_is_allowed(self):
        """Tomar es una acción, no un recurso que se lea o se edite.

        `GET`, `PUT`, `PATCH` y `DELETE` responden 405. En particular `GET` no
        debe tomar la orden: una acción de escritura alcanzable por una
        navegación accidental es una orden asignada sin que nadie la pidiera.
        """
        url = self.claim_url(self.order)

        for method in ("get", "put", "patch", "delete"):
            with self.subTest(metodo=method):
                response = getattr(self.api, method)(url)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )

        self.order.refresh_from_db()

        self.assertEqual(self.order.status, WorkOrder.Status.PENDING)

    def test_the_client_cannot_decide_the_technician_or_the_status(self):
        """Lo que llega en el cuerpo no participa en ninguna decisión.

        El serializador de entrada declara `remarks` y nada más, así que un
        POST que incluya `assigned_technician` o `status` no los cuela: DRF los
        descarta al validar y el dominio nunca los ve. El responsable sale de
        `request.user` y el estado destino lo decide la matriz de transiciones.
        """
        response = self.claim(
            self.order,
            assigned_technician=self.other_technician.pk,
            status=WorkOrder.Status.LIQUIDATED,
            order_number="OT-2026-999999",
            remarks="Tomada por mí.",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.order.refresh_from_db()

        self.assertEqual(self.order.assigned_technician, self.technician)
        self.assertEqual(self.order.status, WorkOrder.Status.ASSIGNED)
        self.assertNotEqual(self.order.order_number, "OT-2026-999999")
