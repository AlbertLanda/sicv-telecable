"""
Pruebas del endpoint «Órdenes disponibles» de la API del técnico.

El endpoint publica el pool de OT sin dueño que un técnico puede tomar. Su
definición (bloqueo B1, cerrado el 02/09) vive en
`apps/work_orders/api/queries.py` y tiene cuatro condiciones: `PENDING`, sin
técnico asignado, `attention_type = FIELD` y tipo `INSTALLATION`.

Estas pruebas cubren las cuatro por separado —cada una con su propio caso
negativo— más el filtro blando de sede, los permisos de canal, la forma de la
respuesta y el costo en consultas.

Se apoyan en `WorkOrderTestCase`, que ya construye sede, zona, cliente,
dirección, suscripción, catálogos y los usuarios `technician`,
`other_technician`, `atc_user` y `supervisor`.
"""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organization.models import Branch
from apps.services.models import Subscription
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.models import OrderType, WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


class AvailableWorkOrdersAPITestCase(WorkOrderTestCase):
    """Base de las pruebas: cliente de API, sede alterna y helpers."""

    def setUp(self):
        super().setUp()

        self.url = reverse("work_orders_api:available")
        self.api = APIClient()

        # Segunda sede, para probar que el filtro de sede organiza pero no
        # restringe. No se agrega a `base.py` porque solo la necesitan estas
        # pruebas.
        self.other_branch = Branch.objects.create(
            code="SED02",
            name="Sede Norte",
        )

    def authenticate(self, user):
        """Autentica el cliente de API con el token del usuario indicado."""
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return token

    def order_numbers(self, response):
        return [row["order_number"] for row in response.data]

    def listed(self, **params):
        """Números de orden que devuelve el endpoint."""
        return self.order_numbers(self.api.get(self.url, params))


class AvailableWorkOrdersDefinitionTests(AvailableWorkOrdersAPITestCase):
    """Las cuatro condiciones de «disponible», una por una."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.technician)

    def test_pending_unassigned_field_installation_is_available(self):
        """El caso canónico: una instalación recién creada aparece.

        Es el escenario del hito: la OT que genera el alta comercial nace
        PENDING, sin técnico y de campo, así que debe estar disponible sin
        ningún paso intermedio ni sincronización manual.
        """
        order = self.create_order()

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.order_numbers(response), [order.order_number])

    def test_assigned_order_is_not_available(self):
        """Una OT que ya tiene responsable sale del pool."""
        assigned = self.create_assigned_order()

        self.assertNotIn(assigned.order_number, self.listed())

    def test_derived_and_reprogrammed_orders_are_not_available(self):
        """Solo PENDING. Los demás estados asignables quedan fuera.

        El dominio admite asignar desde `DERIVED` y `REPROGRAMMED`
        (`ASSIGNABLE_STATUSES`), pero en ambos ya hubo una decisión operativa
        previa —derivar a otra área, pactar fecha con el cliente— que una toma
        desde la app desharía. Decisión de negocio, no limitación técnica.
        """
        for state in (WorkOrder.Status.DERIVED, WorkOrder.Status.REPROGRAMMED):
            with self.subTest(estado=state):
                order = self.create_order(status=state)

                self.assertNotIn(order.order_number, self.listed())

    def test_system_attention_order_is_not_available(self):
        """Una OT de Sistema/NOC no se publica en la app del técnico.

        Regla permanente: NOC atiende por sistema y el técnico atiende en
        campo. Si una `SYSTEM` se colara, un técnico podría tomarla, pasaría a
        ASSIGNED con él como responsable y quedaría bloqueada para quien debe
        resolverla en remoto.
        """
        system_order = self.create_order(
            attention_type=WorkOrder.AttentionType.SYSTEM,
        )

        self.assertNotIn(system_order.order_number, self.listed())

    def test_other_order_types_are_not_available(self):
        """Recorte de alcance del MVP: solo instalaciones.

        Cortes, reconexiones y traslados se siguen despachando desde la
        bandeja web. Publicarlos aquí convertiría la app en una segunda vía
        de despacho para procesos que nadie pidió mover.
        """
        cut = self.create_order(order_type=self.cut_type)

        self.assertNotIn(cut.order_number, self.listed())

    def test_demo_installation_type_is_not_available(self):
        """El tipo de datos de prueba no entra en el pool real.

        La comparación por código es exacta, así que `DEMO-INSTALLATION` queda
        fuera sin necesitar una exclusión aparte. La prueba lo fija para que
        un futuro `startswith` o `icontains` no lo cuele.
        """
        demo_type = OrderType.objects.create(
            code="DEMO-INSTALLATION",
            name="Instalación (demo)",
        )

        demo_order = self.create_order(order_type=demo_type)

        self.assertNotIn(demo_order.order_number, self.listed())

    def test_order_of_a_cancelled_subscription_is_not_available(self):
        """Mitigación B10: no se publica trabajo de un servicio que ya no existe.

        Las otras cuatro condiciones miran solo la orden, y `WorkOrder` guarda
        su propio estado: una OT nacida sobre una suscripción válida sigue en
        `PENDING` aunque la suscripción se cancele después. El camino no es
        teórico —un corte definitivo cancela la suscripción y no toca sus otras
        órdenes— y sin esta condición el técnico podía tomar y viajar a
        instalar un servicio comercialmente cancelado.

        La lista de estados se importa del dominio, así que esta prueba
        también fija que las dos puntas usen el mismo criterio.
        """
        order = self.create_order()

        self.assertIn(order.order_number, self.listed())

        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        self.assertNotIn(order.order_number, self.listed())

    def test_other_subscription_statuses_stay_available(self):
        """La mitigación es estrecha: solo cancelada sale del pool.

        Una instalación vive precisamente en PRESALE, y una reinstalación
        puede ocurrir sobre una suscripción suspendida. Excluir de más dejaría
        al técnico sin trabajo legítimo, que es peor que el problema que se
        quiere evitar.
        """
        order = self.create_order()

        for state in (
            Subscription.Status.PRESALE,
            Subscription.Status.ACTIVE,
            Subscription.Status.SUSPENDED,
        ):
            with self.subTest(suscripcion=state):
                self.subscription.status = state
                self.subscription.save(update_fields=["status"])

                self.assertIn(order.order_number, self.listed())

    def test_everything_listed_satisfies_the_claim_condition(self):
        """Invariante del canal: lo listado es exactamente lo tomable.

        El listado y la toma del viernes consumen la misma función. Esta
        prueba fija esa coincidencia: si alguien ensancha el listado sin tocar
        la toma, la app mostraría órdenes que al pulsarlas devuelven 409.
        """
        self.create_order()
        self.create_assigned_order()
        self.create_order(order_type=self.cut_type)
        self.create_order(attention_type=WorkOrder.AttentionType.SYSTEM)

        listed = self.listed()

        claimable = set(
            available_work_orders().values_list("order_number", flat=True)
        )

        self.assertTrue(listed)
        self.assertTrue(set(listed).issubset(claimable))


class AvailableWorkOrdersBranchScopeTests(AvailableWorkOrdersAPITestCase):
    """Sede: criterio de organización y filtro, nunca restricción dura."""

    def test_other_branch_order_is_hidden_by_default(self):
        """Por defecto el técnico ve la bandeja de su sede."""
        own = self.create_order()
        foreign = self.create_order(branch=self.other_branch, zone=None)

        self.authenticate(self.technician)

        listed = self.listed()

        self.assertIn(own.order_number, listed)
        self.assertNotIn(foreign.order_number, listed)

    def test_scope_all_shows_every_branch(self):
        """`?scope=all` amplía: la sede no impide una asignación legítima.

        Es el criterio de aceptación del plan —sede como filtro y no como
        restricción rígida— traducido a comportamiento verificable.
        """
        own = self.create_order()
        foreign = self.create_order(branch=self.other_branch, zone=None)

        self.authenticate(self.technician)

        listed = self.listed(scope="all")

        self.assertIn(own.order_number, listed)
        self.assertIn(foreign.order_number, listed)

    def test_technician_without_branch_sees_every_available_order(self):
        """Sin sede registrada la bandeja no se queda vacía.

        Filtrar por `branch_id=None` devolvería siempre lista vacía, que es
        peor que no filtrar: dejaría al técnico sin trabajo por un dato
        administrativo faltante.
        """
        own_branch_order = self.create_order()
        other_branch_order = self.create_order(
            branch=self.other_branch,
            zone=None,
        )

        homeless = User.objects.create_user(
            username="tecnico_sin_sede",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=None,
        )

        self.authenticate(homeless)

        listed = self.listed()

        self.assertIn(own_branch_order.order_number, listed)
        self.assertIn(other_branch_order.order_number, listed)

    def test_scope_is_explicit_and_cannot_point_at_another_branch(self):
        """No existe un parámetro de sede: solo ampliar o no ampliar.

        El técnico puede ensanchar su universo, nunca apuntarlo a una sede
        concreta, así que no hay nada que manipular para espiar la carga de
        una sede ajena.
        """
        self.create_order()
        foreign = self.create_order(branch=self.other_branch, zone=None)

        self.authenticate(self.technician)

        # Un parámetro de sede inventado se ignora: no es parte del contrato.
        listed = self.listed(branch=self.other_branch.pk)

        self.assertNotIn(foreign.order_number, listed)

    def test_unknown_scope_is_rejected(self):
        """Un `scope` desconocido responde 400, no cae al defecto en silencio.

        Ignorarlo devolvería un universo distinto del pedido sin decírselo al
        cliente, y esa diferencia es invisible hasta que falta una orden.
        """
        self.authenticate(self.technician)

        response = self.api.get(self.url, {"scope": "todas"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Mismo formato que el resto de los errores del canal: `detail` es una
        # cadena, no una lista, para que el cliente no distinga formatos según
        # el código de estado.
        self.assertIsInstance(response.data["detail"], str)


class AvailableWorkOrdersContentTests(AvailableWorkOrdersAPITestCase):
    """Qué lleva cada fila y en qué orden llegan."""

    def test_row_exposes_the_agreed_fields(self):
        """La fila trae lo de la lista más lo que hace falta para decidir.

        La comparación es contra el conjunto exacto: si alguien agrega un
        campo sin decidirlo, la prueba falla en vez de dejarlo pasar.
        """
        self.create_order()

        self.authenticate(self.technician)

        row = self.api.get(self.url).data[0]

        self.assertEqual(
            set(row.keys()),
            {
                # Heredados de la fila del listado.
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
                # Propios de la bandeja de disponibles: ubicar para decidir.
                "branch",
                "zone",
                "district",
            },
        )

        self.assertEqual(row["status"], WorkOrder.Status.PENDING)
        self.assertEqual(row["status_display"], "Pendiente")
        self.assertEqual(row["order_type"], "Instalación")
        self.assertEqual(row["branch"], "Sede Central")
        self.assertEqual(row["zone"], "Zona Norte")
        self.assertEqual(row["district"], "Chachapoyas")

    def test_row_does_not_expose_the_exact_address(self):
        """El domicilio no viaja hasta que la orden tiene dueño.

        `available/` es visible para todos los técnicos del canal. El distrito
        ubica lo suficiente para decidir; la calle, la referencia y las
        coordenadas aparecen en el detalle, que solo responde sobre órdenes
        propias.
        """
        self.create_order()

        self.authenticate(self.technician)

        row = self.api.get(self.url).data[0]

        for field in ("address", "reference", "latitude", "longitude", "gps_link"):
            with self.subTest(campo=field):
                self.assertNotIn(field, row)

    def test_order_without_zone_is_serialized_as_null(self):
        """La zona es opcional en el modelo: sin ella la fila responde igual."""
        self.create_order(zone=None)

        self.authenticate(self.technician)

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data[0]["zone"])

    def test_scheduled_orders_come_first_and_the_rest_are_fifo(self):
        """Primero lo comprometido con el cliente, después lo más antiguo.

        Es el orden inverso al de la bandeja de despacho web, que mira lo
        recién ingresado: aquí lo viejo es lo que más urge repartir.
        """
        now = timezone.now()

        later = self.create_order(scheduled_at=now + timedelta(hours=5))
        sooner = self.create_order(scheduled_at=now + timedelta(hours=1))
        oldest_unscheduled = self.create_order()
        newest_unscheduled = self.create_order()

        self.authenticate(self.technician)

        self.assertEqual(
            self.listed(),
            [
                sooner.order_number,
                later.order_number,
                oldest_unscheduled.order_number,
                newest_unscheduled.order_number,
            ],
        )

    def test_empty_pool_returns_an_empty_list(self):
        """Sin órdenes disponibles -> 200 con lista vacía, no 404."""
        self.create_assigned_order()

        self.authenticate(self.technician)

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])


class AvailableWorkOrdersPermissionTests(AvailableWorkOrdersAPITestCase):
    """Quién puede usar el endpoint."""

    def test_request_without_token_is_rejected(self):
        """Sin token -> 401."""
        self.create_order()

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_non_technician_is_rejected(self):
        """Usuario autenticado sin rol técnico -> 403 por el permiso de canal.

        La bandeja de disponibles no filtra por `request.user` —son órdenes de
        nadie—, así que el permiso de canal es lo único que separa al técnico
        de cualquier otro usuario con token.
        """
        self.create_order()

        self.authenticate(self.atc_user)

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivated_technician_with_live_token_is_rejected(self):
        """Un token vigente no sobrevive a la desactivación de su dueño."""
        self.create_order()

        self.authenticate(self.technician)
        self.assertEqual(self.api.get(self.url).status_code, status.HTTP_200_OK)

        self.technician.is_active = False
        self.technician.save(update_fields=["is_active"])

        response = self.api.get(self.url)

        # Sin usuario activo la autenticación por token ya no resuelve: DRF
        # responde 401 antes de llegar al permiso de rol.
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_technician_moved_to_another_role_loses_access(self):
        """Un cambio de rol posterior al login revoca el acceso."""
        self.create_order()

        self.authenticate(self.technician)
        self.assertEqual(self.api.get(self.url).status_code, status.HTTP_200_OK)

        self.technician.role = User.Role.ATC
        self.technician.save(update_fields=["role"])

        response = self.api.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AvailableWorkOrdersReadOnlyTests(AvailableWorkOrdersAPITestCase):
    """La bandeja no abre ninguna puerta de escritura."""

    def test_write_methods_are_not_allowed(self):
        """Tomar una orden se pide sobre `claim/`, no editando la bandeja."""
        self.create_order()

        self.authenticate(self.technician)

        for method in ("post", "patch", "put", "delete"):
            with self.subTest(method=method):
                response = getattr(self.api, method)(self.url)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )


class AvailableWorkOrdersQueryCountTests(AvailableWorkOrdersAPITestCase):
    """El listado no crece en consultas con el número de órdenes."""

    def test_query_count_does_not_grow_with_the_number_of_orders(self):
        """Varias OT -> mismo número de consultas que con una sola.

        Se compara contra la línea base medida con una orden en lugar de
        fijar un número absoluto: lo que importa es que el costo no dependa
        del tamaño del listado. Si alguien quita un `select_related`, la
        segunda medición se dispara y la prueba falla.
        """
        self.authenticate(self.technician)

        self.create_order()

        with CaptureQueriesContext(connection) as baseline:
            self.api.get(self.url)

        for _ in range(6):
            self.create_order()

        with self.assertNumQueries(len(baseline.captured_queries)):
            response = self.api.get(self.url)

        self.assertEqual(len(response.data), 7)
