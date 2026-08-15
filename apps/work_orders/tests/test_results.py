"""
Pruebas 19 a 24: efectos de los resultados operativos sobre la suscripción.

Estas pruebas consumen apply_order_result() y attend_order() de
apps/work_orders/services.py. Las reglas de negocio no se replican aquí:
solo se verifican sus efectos.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.services.models import Subscription
from apps.work_orders.models import CutDetail, TransferDetail, WorkOrder
from apps.work_orders.services import apply_order_result, attend_order
from apps.work_orders.tests.base import WorkOrderTestCase


class OrderResultTests(WorkOrderTestCase):

    def test_successful_installation_activates_subscription(self):
        """19. Instalación exitosa activa la suscripción."""
        order = self.create_order_in_progress(
            order_type=self.installation_type,
        )

        attend_order(order, result=self.installation_success, user=self.technician)

        self.subscription.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(
            self.subscription.installation_date,
            timezone.localdate(),
        )
        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)

    def test_successful_temporary_cut_suspends_subscription(self):
        """20. Corte temporal exitoso suspende la suscripción."""
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        order = self.create_order_in_progress(
            order_type=self.cut_type,
            subtype=self.temporary_subtype,
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
            subtype=self.definitive_subtype,
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

    def test_successful_external_transfer_changes_address(self):
        """24. Traslado externo exitoso cambia la dirección."""
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

        self.assertEqual(self.subscription.address, self.other_address)

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
