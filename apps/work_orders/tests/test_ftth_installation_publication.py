"""
Publicación de la OT de instalación: del alta comercial al canal técnico.

Estas pruebas recorren el circuito del hito del 07/09 en su forma mínima:

    Subscription válida
        -> create_work_order(order_type=INSTALLATION)
        -> WorkOrder PENDING con correlativo oficial
        -> GET /api/technicians/work-orders/available/ la devuelve

Son deliberadamente **de integración y no de unidad**. Los tests de
`test_creation.py` ya cubren el servicio por dentro y los de
`test_api_available_orders.py` cubren el endpoint por dentro; lo que aquí se
verifica es la **costura entre ambos**, que es justo lo que ningún test de un
solo módulo puede fallar y que es el criterio de aceptación §6 del plan:

- «Una Subscription válida genera una OT INSTALLATION con correlativo oficial
  y estado PENDING.»
- «La OT aparece en available inmediatamente después de su creación.»

La creación se hace **siempre** llamando a `create_work_order()`, nunca con
`WorkOrder.objects.create()` ni con el helper `create_order()` de `base.py`:
el objetivo es probar la vía oficial de dominio que el flujo comercial va a
consumir, no una imitación de ella.
"""

import re

from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.services.models import Subscription
from apps.work_orders.models import OrderType, WorkOrder
from apps.work_orders.services import (
    create_installation_work_order,
    create_work_order,
)
from apps.work_orders.tests.base import WorkOrderTestCase


class InstallationPublicationTestCase(WorkOrderTestCase):
    """Base: cliente de API y el alta de instalación por la vía oficial."""

    def setUp(self):
        super().setUp()

        self.available_url = reverse("work_orders_api:available")
        self.api = APIClient()

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return token

    def register_installation(self, **kwargs):
        """Registra la OT de instalación como debe hacerlo el flujo comercial.

        Los tres argumentos fijos son los que definen el caso: la suscripción
        del cliente, el tipo `INSTALLATION` del catálogo y el usuario ejecutor
        —que en producción sale de `request.user`, nunca de datos enviados por
        el navegador—.

        Nada más se envía: ni `order_number`, ni `status`, ni
        `assigned_technician`. El correlativo lo emite el dominio, el estado
        inicial lo fija el dominio y la asignación es un flujo aparte.
        """
        defaults = {
            "subscription": self.subscription,
            "order_type": self.installation_type,
            "created_by": self.atc_user,
        }

        defaults.update(kwargs)

        return create_work_order(**defaults)

    def available_rows(self, **params):
        return self.api.get(self.available_url, params).data


class InstallationOrderCreationTests(InstallationPublicationTestCase):
    """La OT que produce el alta comercial cumple lo que exige el hito."""

    def test_installation_is_created_pending_with_official_number(self):
        """Criterio §6.1: PENDING, correlativo oficial, tipo INSTALLATION."""
        order = self.register_installation()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.order_type.code, "INSTALLATION")

        # Formato oficial del correlativo: OT-2026-000001. Se comprueba la
        # forma y no un valor fijo para que la prueba no dependa del año ni
        # del número de órdenes creadas antes.
        self.assertRegex(order.order_number, r"^OT-\d{4}-\d{6}$")

    def test_installation_is_created_without_technician(self):
        """Nace sin responsable: la toma es una decisión posterior del técnico.

        Es lo que la hace elegible para `available/`. Si el alta comercial
        asignara un técnico, la OT saldría del pool sin que nadie la hubiera
        tomado.
        """
        order = self.register_installation()

        self.assertIsNone(order.assigned_technician)

    def test_installation_is_field_attention_by_default(self):
        """Sin indicar nada, la OT es de campo y por tanto publicable.

        `attention_type` decide si la orden pertenece al canal del técnico o
        al de NOC. El valor por defecto del modelo es `FIELD`, así que el
        flujo comercial no necesita enviarlo — pero si algún día lo envía,
        enviarlo mal saca la OT de la app (ver
        `InstallationPublicationTrapTests`).
        """
        order = self.register_installation()

        self.assertEqual(order.attention_type, WorkOrder.AttentionType.FIELD)

    def test_branch_comes_from_the_customer(self):
        """La sede de la OT es la del cliente, no la del operador que registra.

        Importa para la publicación: `available/` acota por defecto a la sede
        del técnico, así que la sede de la OT decide quién la ve sin ampliar
        el alcance.
        """
        order = self.register_installation()

        self.assertEqual(order.branch, self.customer.branch)

    def test_creating_the_order_does_not_touch_the_subscription(self):
        """Registrar la OT no adelanta el estado comercial.

        Una instalación sobre una suscripción en PRESALE la deja en PRESALE.
        La promoción a INSTALLATION ocurre después, cuando el técnico inicia
        la atención (`start_order_attention()`), no al crear la orden.
        """
        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)

        self.register_installation()

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)

    def test_consecutive_installations_get_different_numbers(self):
        """El correlativo no se reparte dos veces.

        Dos altas seguidas —el caso real de ATC registrando en cadena— deben
        producir números distintos. El servicio lo garantiza reservando el
        número dentro de la transacción, no leyendo la última orden creada.
        """
        first = self.register_installation()
        second = self.register_installation()

        self.assertNotEqual(first.order_number, second.order_number)

        numbers = [
            int(re.search(r"(\d{6})$", order.order_number).group(1))
            for order in (first, second)
        ]

        self.assertEqual(numbers[1], numbers[0] + 1)


class InstallationBecomesAvailableTests(InstallationPublicationTestCase):
    """Criterio §6.2: la OT aparece en `available/` recién creada."""

    def test_installation_appears_in_available_immediately(self):
        """Sin copia, sin job y sin sincronización manual.

        La misma petición que sigue al alta ya la devuelve. No hay ningún
        paso intermedio que alguien pueda olvidar ejecutar.
        """
        order = self.register_installation()

        self.authenticate(self.technician)

        rows = self.available_rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["order_number"], order.order_number)

    def test_the_published_order_is_the_same_row_not_a_copy(self):
        """La API publica la WorkOrder del dominio, no un duplicado.

        Requisito explícito del plan: «la aplicación no debe crear copias de
        la orden». Se comprueba por identidad —mismo id— y verificando que en
        la base hay exactamente una orden con ese número.
        """
        order = self.register_installation()

        self.authenticate(self.technician)

        row = self.available_rows()[0]

        self.assertEqual(row["id"], order.pk)
        self.assertEqual(
            WorkOrder.objects.filter(order_number=order.order_number).count(),
            1,
        )

    def test_available_row_carries_what_the_technician_needs_to_decide(self):
        """La fila publicada identifica cliente, plan y ubicación."""
        self.register_installation()

        self.authenticate(self.technician)

        row = self.available_rows()[0]

        self.assertEqual(row["status"], WorkOrder.Status.PENDING)
        self.assertEqual(row["order_type"], "Instalación")
        self.assertEqual(row["service_type"], "Internet")
        self.assertEqual(row["plan"], "Fibra 100 Mbps")
        self.assertEqual(row["customer"]["display_name"], "Juan Pérez Ramos")
        self.assertEqual(row["branch"], "Sede Central")
        self.assertEqual(row["district"], "Chachapoyas")

    def test_several_installations_are_all_published(self):
        """El circuito no depende de que haya una sola orden en el sistema."""
        registered = [self.register_installation() for _ in range(3)]

        self.authenticate(self.technician)

        published = {row["order_number"] for row in self.available_rows()}

        self.assertEqual(
            published,
            {order.order_number for order in registered},
        )

    def test_technician_of_another_branch_sees_it_only_when_widening(self):
        """La sede organiza la bandeja, pero no bloquea la atención.

        El técnico de otra sede no la ve en su vista por defecto y sí con
        `?scope=all`. Es el criterio del plan —sede como filtro y no como
        restricción rígida— aplicado al circuito completo.
        """
        from apps.accounts.models import User
        from apps.organization.models import Branch

        other_branch = Branch.objects.create(code="SED02", name="Sede Norte")

        outsider = User.objects.create_user(
            username="tecnico_otra_sede",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=other_branch,
        )

        order = self.register_installation()

        self.authenticate(outsider)

        by_default = {row["order_number"] for row in self.available_rows()}
        widened = {row["order_number"] for row in self.available_rows(scope="all")}

        self.assertNotIn(order.order_number, by_default)
        self.assertIn(order.order_number, widened)


class InstallationPublicationTrapTests(InstallationPublicationTestCase):
    """Las dos formas de crear una OT que **no** llega a la app.

    Ninguna es un fallo del código: son argumentos del alta comercial que, si
    llegan mal, producen una orden perfectamente válida e invisible para el
    técnico. Se prueban aquí para que el modo de fallo esté documentado y sea
    reproducible antes de la prueba integrada, no descubierto durante ella.
    """

    def test_system_attention_installation_never_reaches_the_app(self):
        """`attention_type=SYSTEM` publica en el canal equivocado.

        Si el formulario comercial deja elegir el tipo de atención y alguien
        marca «Sistema / NOC», la OT se crea, queda PENDING y no aparece
        jamás en la app del técnico. Recomendación para el flujo FTTH: no
        exponer el campo y dejar que aplique el valor por defecto.
        """
        order = self.register_installation(
            attention_type=WorkOrder.AttentionType.SYSTEM,
        )

        self.authenticate(self.technician)

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(self.available_rows(), [])

    def test_demo_installation_type_never_reaches_the_app(self):
        """Usar el tipo de datos de prueba produce una OT invisible.

        El catálogo tiene un `DEMO-INSTALLATION` además del `INSTALLATION`
        real. El flujo comercial debe resolver el tipo por código exacto, no
        por nombre ni por el primer resultado del catálogo.
        """
        demo_type = OrderType.objects.create(
            code="DEMO-INSTALLATION",
            name="Instalación (demo)",
        )

        order = self.register_installation(order_type=demo_type)

        self.authenticate(self.technician)

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(self.available_rows(), [])


class InstallationServiceTests(InstallationPublicationTestCase):
    """`create_installation_work_order()`: el punto de entrada del alta FTTH.

    Las trampas de `InstallationPublicationTrapTests` existen porque el
    llamador puede equivocarse de tipo de orden o de canal de atención. Este
    servicio las cierra **por firma**: no hay argumento que equivocar. Estas
    pruebas verifican que así sea, y que el servicio no invente nada por su
    cuenta más allá de eso.
    """

    def test_service_publishes_the_installation_end_to_end(self):
        """Una sola llamada deja la OT publicada en el canal técnico."""
        order = create_installation_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
        )

        self.authenticate(self.technician)

        rows = self.available_rows()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertRegex(order.order_number, r"^OT-\d{4}-\d{6}$")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], order.pk)

    def test_service_resolves_the_real_type_not_the_demo_one(self):
        """Trampa 2 cerrada: el tipo se resuelve por código exacto.

        Con ambos tipos en el catálogo, el servicio elige el real sin que el
        llamador tenga que saber que el otro existe.
        """
        OrderType.objects.create(
            code="DEMO-INSTALLATION",
            name="Instalación (demo)",
        )

        order = create_installation_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
        )

        self.assertEqual(order.order_type, self.installation_type)
        self.assertEqual(order.order_type.code, "INSTALLATION")

    def test_service_always_creates_field_attention(self):
        """Trampa 1 cerrada: la instalación es siempre trabajo de campo."""
        order = create_installation_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
        )

        self.assertEqual(order.attention_type, WorkOrder.AttentionType.FIELD)

    def test_attention_type_cannot_be_passed_at_all(self):
        """No es que se ignore: no hay parámetro que enviar.

        Cerrar la trampa por firma y no por validación significa que ni
        siquiera existe un valor que el llamador pueda pasar mal. Si alguien
        añadiera el argumento en el futuro, esta prueba lo detiene.
        """
        with self.assertRaises(TypeError):
            create_installation_work_order(
                subscription=self.subscription,
                created_by=self.atc_user,
                attention_type=WorkOrder.AttentionType.SYSTEM,
            )

        self.assertFalse(WorkOrder.objects.exists())

    def test_missing_catalog_type_is_reported_clearly(self):
        """Sin el código INSTALLATION en el catálogo, el error lo nombra.

        Es una falta de datos maestros, no un error del operador: el mensaje
        debe servirle a quien administra el catálogo.

        No se borra el tipo de orden: `OrderType` está referenciado con
        PROTECT desde motivos, causas y resultados, así que borrarlo es
        imposible por diseño. Se le cambia el código, que además reproduce el
        escenario realista —un catálogo mal configurado, no uno vacío— y deja
        el resto del catálogo en pie.
        """
        from django.core.exceptions import ValidationError

        self.installation_type.code = "INSTALACION"
        self.installation_type.save(update_fields=["code"])

        with self.assertRaises(ValidationError) as caught:
            create_installation_work_order(
                subscription=self.subscription,
                created_by=self.atc_user,
            )

        self.assertIn("INSTALLATION", " ".join(caught.exception.messages))
        self.assertFalse(WorkOrder.objects.exists())

    def test_service_delegates_domain_validations(self):
        """No reimplementa las reglas de creación: las hereda.

        Una suscripción cancelada la rechaza `create_work_order()`, y el
        servicio de instalación no tiene por qué saberlo. Si tuviera su propia
        copia de esa comprobación, las dos podrían desalinearse.
        """
        from django.core.exceptions import ValidationError

        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            create_installation_work_order(
                subscription=self.subscription,
                created_by=self.atc_user,
            )

        self.assertFalse(WorkOrder.objects.exists())

    def test_service_does_not_touch_the_subscription(self):
        """Registrar la instalación no adelanta el estado comercial."""
        create_installation_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)

    def test_optional_commercial_data_reaches_the_order(self):
        """Lo que el alta comercial sí decide se transmite tal cual."""
        order = create_installation_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason=self.installation_reason,
            priority=WorkOrder.Priority.HIGH,
            detail="Cliente nuevo FTTH. Coordinar acceso con portería.",
        )

        self.assertEqual(order.reason, self.installation_reason)
        self.assertEqual(order.priority, WorkOrder.Priority.HIGH)
        self.assertEqual(
            order.detail,
            "Cliente nuevo FTTH. Coordinar acceso con portería.",
        )


class InstallationCreationRejectionTests(InstallationPublicationTestCase):
    """Lo que el dominio rechaza antes de crear nada.

    Se prueba desde el circuito porque es lo que el flujo comercial verá: un
    `ValidationError` que la vista debe mostrar al operador, sin OT creada y
    sin correlativo consumido.
    """

    def test_cancelled_subscription_cannot_generate_an_installation(self):
        """No se registra trabajo sobre una suscripción cancelada."""
        from django.core.exceptions import ValidationError

        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.register_installation()

        self.assertFalse(WorkOrder.objects.exists())

    def test_inactive_user_cannot_register_an_installation(self):
        """El usuario que registra debe estar activo."""
        from django.core.exceptions import ValidationError

        self.atc_user.is_active = False
        self.atc_user.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.register_installation()

        self.assertFalse(WorkOrder.objects.exists())
