from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.contracts.models import Contract
from apps.customers.models import Customer, CustomerAddress
from apps.payments.models import Charge
from apps.services.models import Subscription
from apps.work_orders.installation_withdrawal import (
    withdraw_pending_installation,
)
from apps.work_orders.models import InstallationWithdrawal, WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


class InstallationWithdrawalTests(WorkOrderTestCase):
    def _unsigned_contract(self, subscription=None, suffix="1"):
        subscription = subscription or self.subscription
        return Contract.objects.create(
            contract_number=f"CONT-WITHDRAW-{suffix}",
            customer=subscription.customer,
            subscription=subscription,
            service_type=subscription.service_type,
            plan=subscription.plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=date(2026, 9, 25),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

    def test_new_customer_withdrawal_removes_entire_provisional_registration(self):
        order = self.create_order(reason=self.installation_reason)
        contract = self._unsigned_contract()
        customer_id = self.customer.pk
        subscription_id = self.subscription.pk
        address_id = self.address.pk
        service_code = self.subscription.service_code
        customer_code = self.customer.code

        result = withdraw_pending_installation(
            order=order,
            user=self.atc_user,
            reason="El abonado desistió antes de la instalación.",
        )

        self.assertFalse(Customer.objects.filter(pk=customer_id).exists())
        self.assertFalse(
            Subscription.objects.filter(pk=subscription_id).exists()
        )
        self.assertFalse(
            CustomerAddress.objects.filter(pk=address_id).exists()
        )
        self.assertFalse(WorkOrder.objects.filter(pk=order.pk).exists())
        self.assertFalse(Contract.objects.filter(pk=contract.pk).exists())

        withdrawal = InstallationWithdrawal.objects.get(
            order_number=order.order_number
        )
        self.assertTrue(withdrawal.customer_deleted)
        self.assertEqual(withdrawal.released_customer_code, customer_code)
        self.assertEqual(withdrawal.released_service_code, service_code)
        self.assertTrue(result["customer_deleted"])

    def test_existing_customer_withdrawal_removes_only_second_service(self):
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status", "updated_at"])

        second_address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Alta provisional 200",
            district="Chachapoyas",
            is_primary=False,
        )
        second = Subscription.objects.create(
            customer=self.customer,
            address=second_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=2,
        )
        order = self.create_order(
            subscription=second,
            reason=self.installation_reason,
        )
        self._unsigned_contract(second, suffix="2")

        withdraw_pending_installation(
            order=order,
            user=self.atc_user,
            reason="El abonado desistió del segundo servicio.",
        )

        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())
        self.assertTrue(
            Subscription.objects.filter(pk=self.subscription.pk).exists()
        )
        self.assertFalse(Subscription.objects.filter(pk=second.pk).exists())
        self.assertFalse(
            CustomerAddress.objects.filter(pk=second_address.pk).exists()
        )
        self.assertEqual(
            Subscription.next_service_number(
                self.customer,
                self.service_type,
            ),
            2,
        )

        withdrawal = InstallationWithdrawal.objects.get(
            released_service_code=second.service_code
        )
        self.assertFalse(withdrawal.customer_deleted)
        self.assertEqual(withdrawal.released_customer_code, "")

    def test_signed_contract_blocks_physical_withdrawal(self):
        order = self.create_order(reason=self.installation_reason)
        self.ensure_signed_installation_contract(order)

        with self.assertRaises(ValidationError) as context:
            withdraw_pending_installation(
                order=order,
                user=self.atc_user,
                reason="El abonado pidió retirar el alta.",
            )

        self.assertIn("firmado", " ".join(context.exception.messages).lower())
        self.assertTrue(
            Subscription.objects.filter(pk=self.subscription.pk).exists()
        )
        self.assertTrue(WorkOrder.objects.filter(pk=order.pk).exists())
        self.assertFalse(InstallationWithdrawal.objects.exists())

    def test_emitted_charge_blocks_physical_withdrawal(self):
        order = self.create_order(reason=self.installation_reason)
        Charge.objects.create(
            customer=self.customer,
            subscription=self.subscription,
            concept=Charge.Concept.INSTALLATION,
            description="Instalación",
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 25),
        )

        with self.assertRaises(ValidationError) as context:
            withdraw_pending_installation(
                order=order,
                user=self.atc_user,
                reason="El abonado pidió retirar el alta.",
            )

        self.assertIn(
            "cargos/deuda",
            " ".join(context.exception.messages).lower(),
        )
        self.assertTrue(
            Subscription.objects.filter(pk=self.subscription.pk).exists()
        )
        self.assertTrue(WorkOrder.objects.filter(pk=order.pk).exists())

    def test_atc_can_open_withdrawal_confirmation_page(self):
        order = self.create_order(reason=self.installation_reason)
        self.client.login(username="atc1", password="test1234")

        response = self.client.get(
            reverse(
                "work_orders:installation_withdrawal",
                kwargs={"pk": order.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Desistimiento de instalación")
        self.assertContains(response, self.subscription.service_code)
        self.assertContains(response, "Confirmar desistimiento")
