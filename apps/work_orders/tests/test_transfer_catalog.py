from io import StringIO

from django.core.management import call_command

from apps.services.models import ServiceType
from apps.work_orders.forms import WorkOrderCreateForm
from apps.work_orders.models import OrderReason, OrderResult, OrderSubtype, OrderType
from apps.work_orders.tests.base import WorkOrderTestCase


class TransferCatalogTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()

        ServiceType.objects.create(
            code="CABLE",
            name="Cable",
            supports_tv_annexes=True,
        )
        ServiceType.objects.create(
            code="DUO",
            name="Duo",
            supports_tv_annexes=True,
        )

        requirement = OrderType.objects.create(
            code="REQUIREMENT",
            name="REQUERIMIENTO",
        )
        self.legacy_reason = OrderReason.objects.create(
            order_type=requirement,
            code="TRANSFER",
            name="TRASLADO",
            classification=OrderReason.Classification.TECHNICAL,
            is_active=True,
        )

    def run_catalog(self):
        call_command(
            "cargar_catalogo_ordenes",
            stdout=StringIO(),
        )

    def test_transfer_is_first_class_order_with_internal_and_external_subtypes(self):
        self.run_catalog()

        transfer = OrderType.objects.get(code="TRANSFER")

        self.assertTrue(transfer.is_active)
        self.assertEqual(
            set(
                OrderSubtype.objects.filter(
                    order_type=transfer,
                    is_active=True,
                ).values_list("code", flat=True)
            ),
            {"INTERNAL", "EXTERNAL"},
        )
        self.assertTrue(
            OrderResult.objects.filter(
                order_type=transfer,
                code="SUCCESSFUL",
                is_success=True,
                is_active=True,
            ).exists()
        )

    def test_legacy_requirement_transfer_reason_is_retired(self):
        self.run_catalog()

        self.legacy_reason.refresh_from_db()
        self.assertFalse(self.legacy_reason.is_active)

    def test_generic_order_form_does_not_offer_incomplete_transfer(self):
        form = WorkOrderCreateForm(customer=self.customer)

        self.assertNotIn(
            "TRANSFER",
            set(form.fields["order_type"].queryset.values_list("code", flat=True)),
        )
        self.assertNotIn(
            self.legacy_reason.pk,
            set(form.fields["reason"].queryset.values_list("pk", flat=True)),
        )

    def test_catalog_is_idempotent_for_transfer_subtypes(self):
        self.run_catalog()
        self.run_catalog()

        transfer = OrderType.objects.get(code="TRANSFER")
        self.assertEqual(
            OrderSubtype.objects.filter(order_type=transfer).count(),
            2,
        )
