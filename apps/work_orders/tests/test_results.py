"""
Pruebas 19 a 24: efectos de los resultados operativos sobre la suscripción.

Estas pruebas consumen apply_order_result() y attend_order() de
apps/work_orders/services.py. Las reglas de negocio no se replican aquí:
solo se verifican sus efectos.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.services.models import Subscription
from apps.work_orders.models import CutDetail, OrderReason, TransferDetail, WorkOrder
from apps.work_orders.services import (
    apply_order_result,
    attend_order,
    start_order_attention,
)
from apps.work_orders.tests.base import WorkOrderTestCase


class OrderResultTests(WorkOrderTestCase):

    def delinquency_cut(self):
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])
        order = self.create_order_in_progress(order_type=self.cut_type, reason=self.cut_reason)
        CutDetail.objects.create(work_order=order, expected_return_date=timezone.localdate() + timedelta(days=30))
        attend_order(order, result=self.cut_success, user=self.technician)
        return order

    def test_delinquency_cut_generates_one_fixed_reconnection_charge(self):
        from apps.payments.models import Charge
        order = self.delinquency_cut()
        charge = Charge.objects.get(source_cut_order=order)
        self.assertEqual(charge.amount, Decimal("15.00"))
        self.assertEqual(charge.subscription, self.subscription)
        self.assertFalse(charge.auto_update)
        self.assertEqual(charge.early_discount, 0)
        apply_order_result(order)
        self.assertEqual(Charge.objects.filter(source_cut_order=order).count(), 1)

    def test_voluntary_cut_has_no_delinquency_fee(self):
        from apps.payments.models import Charge
        reason = OrderReason.objects.create(order_type=self.cut_type, code="VOLUNTARY", name="Voluntario")
        order = self.create_order_in_progress(order_type=self.cut_type, reason=reason)
        CutDetail.objects.create(work_order=order, expected_return_date=timezone.localdate() + timedelta(days=30))
        attend_order(order, result=self.cut_success, user=self.technician)
        self.assertFalse(Charge.objects.filter(source_cut_order=order).exists())

    def test_reconnection_requires_confirmed_payment_of_fee_and_service_debt(self):
        from apps.payments.models import Charge, Payment
        from apps.payments.services import create_manual_charge, register_payment
        cut = self.delinquency_cut()
        fee = Charge.objects.get(source_cut_order=cut)
        today = timezone.localdate()
        monthly = create_manual_charge(
            customer=self.customer, subscription=self.subscription, concept=Charge.Concept.MONTHLY,
            description="Mensualidad pendiente", amount=Decimal("89.00"),
            due_date=today, period=date(today.year, today.month, 1), auto_update=False,
        )
        order = self.create_order_in_progress(order_type=self.reconnection_type)
        with self.assertRaises(ValidationError):
            attend_order(order, result=self.reconnection_success, user=self.technician)
        order.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        pending, _ = register_payment(
            customer=self.customer, branch=self.branch, user=self.atc_user, amount=Decimal("15.00"),
            method=Payment.Method.CASH, allocations=[(fee, Decimal("15.00"))], settled=False,
        )
        register_payment(
            customer=self.customer, branch=self.branch, user=self.atc_user, amount=Decimal("89.00"),
            method=Payment.Method.CASH, allocations=[(monthly, Decimal("89.00"))], full_monthly_only=True,
        )
        with self.assertRaises(ValidationError):
            attend_order(order, result=self.reconnection_success, user=self.technician)
        order.refresh_from_db()
        pending.confirm(actor=self.atc_user)
        future = today + timedelta(days=40)
        create_manual_charge(
            customer=self.customer, subscription=self.subscription, concept=Charge.Concept.MONTHLY,
            description="Periodo futuro", amount=Decimal("89.00"), due_date=future,
            period=date(future.year, future.month, 1), auto_update=False,
        )
        attend_order(order, result=self.reconnection_success, user=self.technician)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)

    def test_successful_installation_activates_subscription(self):
        """19. Instalación exitosa activa la suscripción."""
        order = self.create_order_in_progress(
            order_type=self.installation_type,
        )
        contract = self.ensure_signed_installation_contract(order)

        attend_order(order, result=self.installation_success, user=self.technician)

        self.subscription.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(
            self.subscription.installation_date,
            timezone.localdate(),
        )
        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)

        contract.refresh_from_db()
        self.assertEqual(
            contract.last_activation_date,
            timezone.localdate(),
        )

    def test_successful_installation_without_signature_is_rejected(self):
        """Una instalación no activa servicio sin conformidad del abonado."""
        from datetime import date

        from apps.contracts.models import Contract

        order = self.create_assigned_order(
            order_type=self.installation_type,
        )
        start_order_attention(
            order,
            user=self.technician,
        )
        Contract.objects.create(
            contract_number="CONT-UNSIGNED",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=date(2026, 9, 23),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "firme su contrato",
        ):
            attend_order(
                order,
                result=self.installation_success,
                user=self.technician,
            )

        order.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(
            self.subscription.status,
            Subscription.Status.INSTALLATION,
        )

    def test_successful_temporary_cut_suspends_subscription(self):
        """20. Corte temporal exitoso suspende la suscripción."""
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        order = self.create_order_in_progress(
            order_type=self.cut_type,
            reason=self.cut_reason,
        )

        CutDetail.objects.create(
            work_order=order,
            expected_return_date=timezone.localdate() + timedelta(days=30),
        )

        attend_order(order, result=self.cut_success, user=self.technician)

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.SUSPENDED)
        self.assertEqual(self.subscription.cut_date, timezone.localdate())

    def test_successful_definitive_cut_cancels_subscription(self):
        """21. Corte definitivo exitoso cancela la suscripción."""
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        order = self.create_order_in_progress(
            order_type=self.cut_type,
            reason=self.definitive_cut_reason,
        )

        CutDetail.objects.create(
            work_order=order,
            cancellation_reason_detail="Migra a otro operador",
            competitor="Operador X",
        )

        attend_order(order, result=self.cut_success, user=self.technician)

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.CANCELLED)
        self.assertEqual(self.subscription.cut_date, timezone.localdate())

    def test_successful_reconnection_activates_subscription(self):
        """22. Reconexión exitosa activa la suscripción."""
        self.subscription.status = Subscription.Status.SUSPENDED
        self.subscription.save(update_fields=["status"])

        order = self.create_order_in_progress(
            order_type=self.reconnection_type,
        )

        attend_order(
            order,
            result=self.reconnection_success,
            user=self.technician,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(
            self.subscription.reconnection_date,
            timezone.localdate(),
        )

    def test_successful_internal_transfer_keeps_address(self):
        """23. Traslado interno exitoso no cambia dirección."""
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        order = self.create_order_in_progress(
            order_type=self.transfer_type,
            subtype=self.internal_subtype,
        )

        TransferDetail.objects.create(
            work_order=order,
            previous_location="Sala principal",
            new_location="Dormitorio 2",
        )

        attend_order(order, result=self.transfer_success, user=self.technician)

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.address, self.address)

    def test_successful_external_transfer_keeps_address_until_liquidation(self):
        """24. Atender un traslado externo aún no cambia el domicilio."""
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        order = self.create_order_in_progress(
            order_type=self.transfer_type,
            subtype=self.external_subtype,
        )

        TransferDetail.objects.create(
            work_order=order,
            previous_address=self.address,
            new_address=self.other_address,
        )

        attend_order(order, result=self.transfer_success, user=self.technician)

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.address, self.address)

    def test_apply_result_without_result_is_rejected(self):
        """Complemento: no se pueden aplicar efectos sin resultado."""
        order = self.create_order_in_progress()

        with self.assertRaises(ValidationError):
            apply_order_result(order)

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)

    def test_attend_order_with_foreign_result_is_rejected(self):
        """Complemento: el resultado debe ser del mismo tipo de orden."""
        order = self.create_order_in_progress(
            order_type=self.installation_type,
        )

        with self.assertRaises(ValidationError):
            attend_order(order, result=self.cut_success, user=self.technician)

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.IN_PROGRESS)
        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)

    def test_attended_order_with_not_feasible_result_does_not_activate(self):
        """
        Complemento (§10): una orden puede estar ATTENDED con un resultado
        no efectivo. La suscripción no debe activarse.
        """
        not_feasible_result = self.installation_type.results.create(
            code="NOT_FEASIBLE",
            name="No factible",
            is_success=False,
        )

        order = self.create_order_in_progress(
            order_type=self.installation_type,
        )

        attend_order(order, result=not_feasible_result, user=self.technician)

        self.subscription.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        self.assertEqual(self.subscription.status, Subscription.Status.PRESALE)
        self.assertIsNone(self.subscription.installation_date)

    def test_start_installation_changes_presale_to_installation(self):
        """
        Cuando inicia realmente una instalación,
        PREVENTA pasa a EN INSTALACIÓN.
        """
        order = self.create_assigned_order(
            order_type=self.installation_type,
        )

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.PRESALE,
        )

        start_order_attention(
            order,
            user=self.technician,
            remarks="Técnico inicia instalación",
        )

        self.subscription.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(
            order.status,
            WorkOrder.Status.IN_PROGRESS,
        )

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.INSTALLATION,
        )

    def test_attend_order_from_pending_is_rejected(self):
        """No se puede atender una orden que nunca inició atención."""
        order = self.create_order(
            order_type=self.installation_type,
        )

        with self.assertRaises(ValidationError):
            attend_order(
                order,
                result=self.installation_success,
                user=self.technician,
            )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            WorkOrder.Status.PENDING,
        )

    def test_attend_order_from_assigned_is_rejected(self):
        """Una orden asignada todavía no puede finalizarse."""
        order = self.create_assigned_order(
            order_type=self.installation_type,
        )

        with self.assertRaises(ValidationError):
            attend_order(
                order,
                result=self.installation_success,
                user=self.technician,
            )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            WorkOrder.Status.ASSIGNED,
        )

    def test_full_installation_flow_presale_to_active(self):
        """
        Flujo completo:
        PRESALE -> INSTALLATION -> ACTIVE.
        """
        order = self.create_assigned_order(
            order_type=self.installation_type,
        )

        start_order_attention(
            order,
            user=self.technician,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.INSTALLATION,
        )

        self.ensure_signed_installation_contract(order)

        attend_order(
            order,
            result=self.installation_success,
            user=self.technician,
        )

        self.subscription.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(
            order.status,
            WorkOrder.Status.ATTENDED,
        )

        self.assertEqual(
            self.subscription.status,
            Subscription.Status.ACTIVE,
        )

        self.assertIsNotNone(
            self.subscription.installation_date,
        )
