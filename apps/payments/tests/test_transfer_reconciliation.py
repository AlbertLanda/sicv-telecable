from decimal import Decimal

from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.payments.models import Charge, ChargeConcept
from apps.services.models import Subscription
from apps.work_orders.models import TransferDetail
from apps.work_orders.services import (
    attend_order,
    create_transfer_work_order,
    liquidate_order,
    start_order_attention,
    submit_liquidation,
    validate_liquidation,
)
from apps.work_orders.tests.base import WorkOrderTestCase


class TransferReconciliationWebTests(WorkOrderTestCase):
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

        self.order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
        )
        self.order.assign_technician(
            self.technician,
            assigned_by=self.technician,
        )
        start_order_attention(self.order, user=self.technician)
        attend_order(
            self.order,
            result=self.transfer_success,
            user=self.technician,
        )
        self.liquidation = liquidate_order(
            self.order,
            user=self.technician,
            resolution_detail="Traslado interno ejecutado.",
            items=[
                {
                    "movement_type": "USED",
                    "material_name": "Cable drop",
                    "quantity": Decimal("10.00"),
                    "unit_of_measure": "METER",
                    "is_billable": True,
                    "unit_price": Decimal("0.80"),
                },
            ],
        )
        submit_liquidation(self.liquidation, user=self.technician)

        self.resolver = self.supervisor
        self._grant("work_orders", "validate_liquidation")
        self._grant("work_orders", "resolve_transfer_reconciliation")
        self._grant("payments", "view_charge")
        validate_liquidation(
            self.liquidation,
            validator=self.resolver,
        )
        self.client.force_login(self.resolver)

    def _grant(self, app_label, codename):
        permission = Permission.objects.get(
            content_type__app_label=app_label,
            codename=codename,
        )
        self.resolver.user_permissions.add(permission)
        if hasattr(self.resolver, "_perm_cache"):
            del self.resolver._perm_cache

    def test_debt_board_surfaces_pending_transfer_reconciliation(self):
        response = self.client.get(
            reverse("payments:debt", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Regularización de traslado")
        self.assertContains(response, "Diferencia S/ 8.00")
        self.assertContains(response, self.order.order_number)

    def test_reconciliation_page_shows_commercial_and_real_amounts(self):
        transfer = TransferDetail.objects.get(work_order=self.order)

        response = self.client.get(
            reverse(
                "payments:transfer_reconciliation_resolve",
                kwargs={
                    "pk": self.customer.pk,
                    "transfer_pk": transfer.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Costo técnico real")
        self.assertContains(response, "S/ 28.00")
        self.assertContains(response, "Monto acordado")
        self.assertContains(response, "S/ 20.00")
        self.assertContains(response, "Diferencia")

    def test_authorized_user_can_absorb_difference_with_audit_only(self):
        transfer = TransferDetail.objects.get(work_order=self.order)

        response = self.client.post(
            reverse(
                "payments:transfer_reconciliation_resolve",
                kwargs={
                    "pk": self.customer.pk,
                    "transfer_pk": transfer.pk,
                },
            ),
            {
                "action": TransferDetail.ReconciliationAction.ABSORB,
                "note": "Cortesía comercial autorizada por supervisión.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        transfer.refresh_from_db()
        self.assertEqual(
            transfer.reconciliation_status,
            TransferDetail.ReconciliationStatus.RESOLVED,
        )
        self.assertEqual(
            transfer.reconciliation_action,
            TransferDetail.ReconciliationAction.ABSORB,
        )
        self.assertEqual(transfer.reconciled_by, self.resolver)
        self.assertIsNotNone(transfer.reconciled_at)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())
        self.assertNotContains(response, "Regularización de traslado")
