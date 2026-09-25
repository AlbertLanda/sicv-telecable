from decimal import Decimal

from django.urls import reverse

from apps.organization.models import Branch, Zone
from apps.payments.models import Charge, ChargeConcept, ProposedCharge
from apps.services.models import Subscription
from apps.work_orders.models import TransferDetail, WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


class TransferCreateWebTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        ChargeConcept.objects.update_or_create(
            code="traslado",
            defaults={
                "name": "TRASLADO",
                "family": Charge.Concept.OTHER,
                "is_active": True,
            },
        )

        self.url = reverse(
            "work_orders:transfer_create",
            kwargs={"customer_pk": self.customer.pk},
        )
        self.client.login(username="atc1", password="test1234")

    def test_page_exposes_internal_and_external_transfer_flow(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nuevo traslado")
        self.assertContains(response, "Interno: S/ 20")
        self.assertContains(response, "Externo: S/ 30")

    def test_page_exposes_supply_lookup_for_external_transfer(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'id="btn-consultar-suministro-traslado"',
        )
        self.assertContains(
            response,
            'id="btn-usar-suministro-traslado"',
        )
        self.assertContains(response, "Ubicación encontrada")
        self.assertContains(response, reverse("customers:lookup_supply"))

    def test_external_transfer_requires_supply_location_to_be_applied(self):
        branch = Branch.objects.create(code="SED02", name="Sede Destino")
        zone = Zone.objects.create(branch=branch, name="Zona Destino")

        response = self.client.post(
            self.url,
            {
                "subscription": self.subscription.pk,
                "subtype": self.external_subtype.pk,
                "destination_branch": branch.pk,
                "destination_zone": zone.pk,
                "requested_address_text": "Av. escrita manualmente 500",
                "requested_supply_code": "",
                "estimated_extra_amount": "0.00",
                "customer_agreed_amount": "",
                "charge_mode": TransferDetail.ChargeMode.UPFRONT_BASE,
                "collection_mode": TransferDetail.CollectionMode.IMMEDIATE,
                "scheduled_at": "",
                "priority": WorkOrder.Priority.NORMAL,
                "detail": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "requested_supply_code",
            response.context["form"].errors,
        )
        self.assertFalse(
            WorkOrder.objects.filter(order_type=self.transfer_type).exists()
        )

    def test_internal_transfer_can_be_registered_from_web(self):
        response = self.client.post(
            self.url,
            {
                "subscription": self.subscription.pk,
                "subtype": self.internal_subtype.pk,
                "previous_location": "Sala",
                "new_location": "Dormitorio",
                "estimated_extra_amount": "0.00",
                "customer_agreed_amount": "",
                "charge_mode": TransferDetail.ChargeMode.UPFRONT_BASE,
                "collection_mode": TransferDetail.CollectionMode.IMMEDIATE,
                "scheduled_at": "",
                "priority": WorkOrder.Priority.NORMAL,
                "detail": "Mover equipo dentro de la vivienda.",
            },
        )

        self.assertEqual(response.status_code, 302)

        order = WorkOrder.objects.get(order_type=self.transfer_type)
        self.assertEqual(order.subtype, self.internal_subtype)
        self.assertEqual(
            order.transfer_detail.base_fee_snapshot,
            Decimal("20.00"),
        )
        self.assertTrue(
            ProposedCharge.objects.filter(work_order=order).exists()
        )

    def test_external_transfer_can_target_another_branch(self):
        branch = Branch.objects.create(code="SED02", name="Sede Destino")
        zone = Zone.objects.create(branch=branch, name="Zona Destino")

        response = self.client.post(
            self.url,
            {
                "subscription": self.subscription.pk,
                "subtype": self.external_subtype.pk,
                "destination_branch": branch.pk,
                "destination_zone": zone.pk,
                "requested_address_text": "Av. Nueva 500",
                "requested_reference": "Frente al parque",
                "requested_supply_code": "12345678",
                "requested_latitude": "-11.5000000",
                "requested_longitude": "-75.9000000",
                "estimated_extra_amount": "15.00",
                "customer_agreed_amount": "45.00",
                "charge_mode": TransferDetail.ChargeMode.UPFRONT_FULL,
                "collection_mode": TransferDetail.CollectionMode.IMMEDIATE,
                "scheduled_at": "2026-09-26T09:00",
                "priority": WorkOrder.Priority.NORMAL,
                "detail": "Traslado solicitado a otra sede.",
            },
        )

        self.assertEqual(response.status_code, 302)

        order = WorkOrder.objects.get(order_type=self.transfer_type)
        self.assertEqual(order.branch, branch)
        self.assertEqual(order.zone, zone)
        self.assertEqual(
            order.transfer_detail.customer_agreed_amount,
            Decimal("45.00"),
        )

    def test_full_upfront_requires_amount_informed_to_customer(self):
        branch = Branch.objects.create(code="SED02", name="Sede Destino")
        zone = Zone.objects.create(branch=branch, name="Zona Destino")

        response = self.client.post(
            self.url,
            {
                "subscription": self.subscription.pk,
                "subtype": self.external_subtype.pk,
                "destination_branch": branch.pk,
                "destination_zone": zone.pk,
                "requested_address_text": "Av. Nueva 500",
                "estimated_extra_amount": "15.00",
                "customer_agreed_amount": "",
                "charge_mode": TransferDetail.ChargeMode.UPFRONT_FULL,
                "collection_mode": TransferDetail.CollectionMode.IMMEDIATE,
                "scheduled_at": "",
                "priority": WorkOrder.Priority.NORMAL,
                "detail": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "customer_agreed_amount",
            response.context["form"].errors,
        )
        self.assertFalse(
            WorkOrder.objects.filter(order_type=self.transfer_type).exists()
        )

    def test_customer_orders_menu_exposes_transfer_entry(self):
        response = self.client.get(
            reverse("customers:orders", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Traslado")
        self.assertContains(response, self.url)

