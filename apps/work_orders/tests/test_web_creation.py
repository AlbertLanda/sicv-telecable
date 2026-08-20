"""
Pruebas del flujo web controlado de creación de órdenes de trabajo.

Cubren WorkOrderCreateForm + WorkOrderCreateView: autenticación, ámbito del
cliente, catálogos, y las garantías que la capa web no puede relajar
(correlativo y autoría emitidos en servidor, estado inicial PENDING,
suscripción intacta y ausencia de registros parciales).

Lo que aquí se verifica es que la vista NO abre puertas que el servicio ya
cerró. Las reglas de dominio en sí están probadas en test_creation.py.
"""

from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.work_orders.models import (
    OrderSubtype,
    OrderType,
    WorkOrder,
    WorkOrderSequence,
)
from apps.work_orders.services import format_order_number
from apps.work_orders.tests.base import WorkOrderTestCase


class WorkOrderWebCreationTestCase(WorkOrderTestCase):
    """Escenario común del flujo web: URL, sesión iniciada y POST válido."""

    def setUp(self):
        super().setUp()

        self.url = reverse(
            "work_orders:create",
            kwargs={"customer_pk": self.customer.pk},
        )

        self.client.login(username="atc1", password="test1234")

    def valid_payload(self, **overrides):
        """POST mínimo y correcto para registrar una OT de instalación."""
        payload = {
            "subscription": self.subscription.pk,
            "order_type": self.installation_type.pk,
            "subtype": "",
            "reason": self.installation_reason.pk,
            "branch": self.branch.pk,
            "zone": self.zone.pk,
            "attention_type": WorkOrder.AttentionType.FIELD,
            "priority": WorkOrder.Priority.NORMAL,
            "scheduled_at": "",
            "detail": "Instalación de cliente nuevo.",
        }

        payload.update(overrides)

        return payload

    def create_other_customer_subscription(self):
        """Suscripción perteneciente a un cliente distinto al de la ruta."""
        other_customer = Customer.objects.create(
            code="CLI999",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10203040",
            first_name="Ana",
            paternal_surname="Torres",
            maternal_surname="Vega",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Jr. Libertad 900",
            district="Chachapoyas",
            is_primary=True,
        )

        return Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
        )


class WorkOrderCreateViewAccessTests(WorkOrderWebCreationTestCase):
    """Prueba 2: la creación web exige usuario autenticado."""

    def test_authenticated_user_sees_the_form(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("form", response.context)

    def test_anonymous_user_cannot_open_the_form(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_anonymous_user_cannot_create_an_order(self):
        self.client.logout()

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_unknown_customer_returns_not_found(self):
        url = reverse(
            "work_orders:create",
            kwargs={"customer_pk": self.customer.pk + 999},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)


class WorkOrderCreateViewSuccessTests(WorkOrderWebCreationTestCase):
    """Pruebas 1, 7, 8, 9 y 10: la orden nace correcta y con autoría real."""

    def test_valid_request_creates_exactly_one_order(self):
        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(WorkOrder.objects.count(), 1)

        order = WorkOrder.objects.get()

        self.assertEqual(order.subscription, self.subscription)
        self.assertEqual(order.order_type, self.installation_type)
        self.assertEqual(order.reason, self.installation_reason)
        self.assertEqual(order.branch, self.branch)
        self.assertEqual(order.zone, self.zone)
        self.assertEqual(order.detail, "Instalación de cliente nuevo.")

        self.assertRedirects(
            response,
            reverse("customers:detail", kwargs={"pk": self.customer.pk}),
        )

    def test_order_number_comes_from_the_backend_sequence(self):
        self.client.post(self.url, self.valid_payload())

        order = WorkOrder.objects.get()

        expected = format_order_number(timezone.localdate().year, 1)

        self.assertEqual(order.order_number, expected)

    def test_browser_cannot_impose_the_order_number(self):
        """Prueba 7: order_number enviado por POST se descarta."""
        self.client.post(
            self.url,
            self.valid_payload(order_number="OT-9999-000999"),
        )

        order = WorkOrder.objects.get()

        expected = format_order_number(timezone.localdate().year, 1)

        self.assertEqual(order.order_number, expected)
        self.assertNotEqual(order.order_number, "OT-9999-000999")

    def test_created_by_is_the_authenticated_user(self):
        """Prueba 8: la autoría sale de request.user, no del POST."""
        self.client.post(
            self.url,
            self.valid_payload(created_by=self.technician.pk),
        )

        order = WorkOrder.objects.get()

        self.assertEqual(order.created_by, self.atc_user)
        self.assertNotEqual(order.created_by, self.technician)

    def test_status_and_technician_are_not_manipulable(self):
        """Prueba 9: la orden nace en PENDING y sin técnico asignado."""
        self.client.post(
            self.url,
            self.valid_payload(
                status=WorkOrder.Status.ATTENDED,
                assigned_technician=self.technician.pk,
            ),
        )

        order = WorkOrder.objects.get()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertIsNone(order.assigned_technician)

    def test_installation_order_keeps_the_subscription_in_presale(self):
        """Prueba 10: crear la OT no activa el servicio."""
        self.client.post(self.url, self.valid_payload())

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.PRESALE,
        )

        self.assertIsNone(self.subscription.installation_date)

    def test_optional_fields_may_be_omitted(self):
        response = self.client.post(
            self.url,
            self.valid_payload(reason="", zone="", detail=""),
        )

        self.assertEqual(response.status_code, 302)

        order = WorkOrder.objects.get()

        self.assertIsNone(order.reason)
        # Sin zona explícita el servicio toma la de la dirección del servicio.
        self.assertEqual(order.zone, self.zone)


class WorkOrderCreateViewScopeTests(WorkOrderWebCreationTestCase):
    """Pruebas 3 y 6: el ámbito del cliente y de la sede no se puede forzar."""

    def test_rejects_a_subscription_from_another_customer(self):
        foreign_subscription = self.create_other_customer_subscription()

        response = self.client.post(
            self.url,
            self.valid_payload(subscription=foreign_subscription.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("subscription", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_form_only_offers_subscriptions_of_the_displayed_customer(self):
        foreign_subscription = self.create_other_customer_subscription()

        response = self.client.get(self.url)

        offered = response.context["form"].fields["subscription"].queryset

        self.assertIn(self.subscription, offered)
        self.assertNotIn(foreign_subscription, offered)

    def test_rejects_a_zone_from_another_branch(self):
        other_branch = Branch.objects.create(code="SED02", name="Sede Sur")

        other_zone = Zone.objects.create(
            branch=other_branch,
            name="Zona Sur",
        )

        response = self.client.post(
            self.url,
            self.valid_payload(zone=other_zone.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("zone", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_a_branch_that_is_not_the_customer_branch(self):
        other_branch = Branch.objects.create(code="SED03", name="Sede Este")

        response = self.client.post(
            self.url,
            self.valid_payload(branch=other_branch.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("branch", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)


class WorkOrderCreateViewCatalogTests(WorkOrderWebCreationTestCase):
    """Pruebas 4 y 5: catálogos inactivos e incompatibles."""

    def test_rejects_an_inactive_order_type(self):
        inactive_type = OrderType.objects.create(
            code="MAINTENANCE",
            name="Mantenimiento",
            is_active=False,
        )

        response = self.client.post(
            self.url,
            self.valid_payload(order_type=inactive_type.pk, reason=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("order_type", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_an_inactive_subtype(self):
        inactive_subtype = OrderSubtype.objects.create(
            order_type=self.installation_type,
            code="AERIAL",
            name="Instalación aérea",
            is_active=False,
        )

        response = self.client.post(
            self.url,
            self.valid_payload(subtype=inactive_subtype.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("subtype", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_an_inactive_reason(self):
        self.installation_reason.is_active = False
        self.installation_reason.save(update_fields=["is_active"])

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 200)
        self.assertIn("reason", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_inactive_catalogs_are_not_offered(self):
        self.cut_type.is_active = False
        self.cut_type.save(update_fields=["is_active"])

        response = self.client.get(self.url)

        offered = response.context["form"].fields["order_type"].queryset

        self.assertIn(self.installation_type, offered)
        self.assertNotIn(self.cut_type, offered)

    def test_rejects_a_subtype_from_another_order_type(self):
        """Prueba 5: el subtipo de Corte no vale para una Instalación."""
        response = self.client.post(
            self.url,
            self.valid_payload(subtype=self.temporary_subtype.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("subtype", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_rejects_a_reason_from_another_order_type(self):
        response = self.client.post(
            self.url,
            self.valid_payload(reason=self.cut_reason.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("reason", response.context["form"].errors)
        self.assertEqual(WorkOrder.objects.count(), 0)


class WorkOrderCreateViewAtomicityTests(WorkOrderWebCreationTestCase):
    """Prueba 11: un rechazo del servicio no deja rastro."""

    def test_service_rejection_returns_to_the_form_without_partial_records(self):
        """
        La suscripción cancelada pasa el filtro del formulario pero el
        servicio la rechaza: es el caso que demuestra quién decide.
        """
        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        response = self.client.post(self.url, self.valid_payload())

        self.assertEqual(response.status_code, 200)

        errors = response.context["form"].non_field_errors()

        self.assertTrue(errors)
        self.assertIn("cancelada", " ".join(errors))

        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_failed_creation_does_not_consume_a_correlative(self):
        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save(update_fields=["status"])

        self.client.post(self.url, self.valid_payload())

        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertFalse(WorkOrderSequence.objects.exists())

        # Tras el fallo, una creación válida sigue tomando el primer número.
        self.subscription.status = Subscription.Status.PRESALE
        self.subscription.save(update_fields=["status"])

        self.client.post(self.url, self.valid_payload())

        order = WorkOrder.objects.get()

        self.assertEqual(
            order.order_number,
            format_order_number(timezone.localdate().year, 1),
        )
