from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.customers.models import CustomerAddress
from apps.organization.models import Branch, Zone
from apps.payments.models import Charge, ChargeConcept, ProposedCharge
from apps.payments.proposals import accept_proposed_charge, suggested_proposed_charge_amount
from apps.services.models import Subscription
from apps.work_orders.models import TransferDetail, WorkOrder, WorkOrderLiquidation
from apps.work_orders.services import (
    attend_order,
    confirm_external_transfer_destination,
    create_transfer_work_order,
    liquidate_order,
    resolve_transfer_reconciliation,
    start_order_attention,
    submit_liquidation,
    validate_liquidation,
)
from apps.work_orders.tests.base import WorkOrderTestCase


class TransferWorkflowTests(WorkOrderTestCase):
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

    def _take_and_start(self, order, technician=None):
        technician = technician or self.technician
        order.assign_technician(
            technician,
            assigned_by=technician,
        )
        start_order_attention(order, user=technician)
        order.refresh_from_db()
        return technician

    def test_internal_transfer_keeps_snapshot_of_s20_and_proposes_no_real_debt(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
        )

        detail = order.transfer_detail
        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertEqual(detail.base_fee_snapshot, Decimal("20.00"))
        self.assertEqual(detail.customer_agreed_amount, Decimal("20.00"))
        self.assertEqual(
            detail.charge_mode,
            TransferDetail.ChargeMode.UPFRONT_BASE,
        )
        self.assertEqual(proposal.description, "TRASLADO INTERNO")
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_external_transfer_can_be_scheduled_for_another_branch(self):
        destination_branch = Branch.objects.create(
            code="SED02",
            name="Sede Destino",
        )
        destination_zone = Zone.objects.create(
            branch=destination_branch,
            name="Zona Destino",
        )

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=destination_branch,
            destination_zone=destination_zone,
            requested_address_text="Av. Nueva 500",
            estimated_extra_amount=Decimal("15.00"),
            charge_mode=TransferDetail.ChargeMode.UPFRONT_FULL,
        )

        detail = order.transfer_detail

        self.assertEqual(order.branch, destination_branch)
        self.assertEqual(order.zone, destination_zone)
        self.assertEqual(detail.base_fee_snapshot, Decimal("30.00"))
        self.assertEqual(detail.estimated_extra_amount, Decimal("15.00"))
        self.assertEqual(detail.customer_agreed_amount, Decimal("45.00"))
        self.assertEqual(self.subscription.address, self.address)

    def test_external_transfer_does_not_change_address_when_only_attended(self):
        destination_branch = Branch.objects.create(
            code="SED02",
            name="Sede Destino",
        )
        destination_zone = Zone.objects.create(
            branch=destination_branch,
            name="Zona Destino",
        )
        technician = User.objects.create_user(
            username="tecnico_destino",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=destination_branch,
        )

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=destination_branch,
            destination_zone=destination_zone,
            requested_address_text="Av. Nueva 500",
        )

        self._take_and_start(order, technician)

        transfer = confirm_external_transfer_destination(
            order=order,
            user=technician,
            address="Av. Nueva 520",
            district="Distrito Destino",
            zone=destination_zone,
            reference="Frente al parque",
            supply_code="SUM-9001",
            latitude=Decimal("-11.5200000"),
            longitude=Decimal("-75.9000000"),
        )

        attend_order(
            order,
            result=self.transfer_success,
            user=technician,
        )

        self.subscription.refresh_from_db()

        self.assertEqual(self.subscription.address, self.address)
        self.assertEqual(transfer.new_address.electrical_supply_code, "SUM-9001")
        self.assertEqual(transfer.confirmed_by, technician)

    def test_external_transfer_changes_address_only_when_liquidated(self):
        destination_branch = Branch.objects.create(
            code="SED02",
            name="Sede Destino",
        )
        destination_zone = Zone.objects.create(
            branch=destination_branch,
            name="Zona Destino",
        )
        technician = User.objects.create_user(
            username="tecnico_destino",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=destination_branch,
        )

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=destination_branch,
            destination_zone=destination_zone,
            requested_address_text="Av. Nueva 500",
        )
        self._take_and_start(order, technician)

        transfer = confirm_external_transfer_destination(
            order=order,
            user=technician,
            address="Av. Nueva 520",
            district="Distrito Destino",
            zone=destination_zone,
            supply_code="SUM-9001",
            latitude=Decimal("-11.5200000"),
            longitude=Decimal("-75.9000000"),
        )

        attend_order(order, result=self.transfer_success, user=technician)

        liquidate_order(
            order,
            user=technician,
            resolution_detail="Traslado externo ejecutado y domicilio confirmado.",
        )

        self.subscription.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(self.subscription.address, transfer.new_address)
        self.assertEqual(order.status, WorkOrder.Status.LIQUIDATED)

    def test_external_transfer_cannot_be_liquidated_without_confirmed_destination(self):
        destination_branch = Branch.objects.create(
            code="SED02",
            name="Sede Destino",
        )
        destination_zone = Zone.objects.create(
            branch=destination_branch,
            name="Zona Destino",
        )
        technician = User.objects.create_user(
            username="tecnico_destino",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=destination_branch,
        )

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=destination_branch,
            destination_zone=destination_zone,
            requested_address_text="Av. Nueva 500",
        )
        self._take_and_start(order, technician)
        attend_order(order, result=self.transfer_success, user=technician)

        with self.assertRaises(ValidationError):
            liquidate_order(
                order,
                user=technician,
                resolution_detail="Intento sin domicilio confirmado.",
            )

        self.assertFalse(
            WorkOrderLiquidation.objects.filter(work_order=order).exists()
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.address, self.address)

    def test_internal_transfer_never_changes_service_address_on_liquidation(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Segundo piso",
        )
        technician = self._take_and_start(order)

        attend_order(order, result=self.transfer_success, user=technician)
        liquidate_order(
            order,
            user=technician,
            resolution_detail="Traslado interno ejecutado.",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.address, self.address)

    def test_future_work_after_cross_branch_transfer_uses_service_address_branch(self):
        destination_branch = Branch.objects.create(
            code="SED02",
            name="Sede Destino",
        )
        destination_zone = Zone.objects.create(
            branch=destination_branch,
            name="Zona Destino",
        )
        technician = User.objects.create_user(
            username="tecnico_destino",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=destination_branch,
        )

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=destination_branch,
            destination_zone=destination_zone,
            requested_address_text="Av. Nueva 500",
        )
        self._take_and_start(order, technician)
        confirm_external_transfer_destination(
            order=order,
            user=technician,
            address="Av. Nueva 520",
            district="Distrito Destino",
            zone=destination_zone,
        )
        attend_order(order, result=self.transfer_success, user=technician)
        liquidate_order(
            order,
            user=technician,
            resolution_detail="Traslado ejecutado.",
        )

        from apps.work_orders.services import create_work_order

        next_order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
        )

        self.assertEqual(next_order.branch, destination_branch)
        self.assertEqual(next_order.zone, destination_zone)

    def test_liquidation_calculates_real_billable_cost_without_auto_charge(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
        )
        technician = self._take_and_start(order)
        attend_order(order, result=self.transfer_success, user=technician)

        liquidate_order(
            order,
            user=technician,
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
                {
                    "movement_type": "USED",
                    "material_name": "Conector operativo",
                    "quantity": Decimal("1.00"),
                    "unit_of_measure": "UNIT",
                    "is_billable": False,
                },
            ],
        )

        detail = TransferDetail.objects.get(work_order=order)

        self.assertEqual(detail.actual_extra_amount, Decimal("8.00"))
        self.assertEqual(detail.actual_total, Decimal("28.00"))
        self.assertEqual(detail.reconciliation_difference, Decimal("8.00"))
        self.assertEqual(
            detail.reconciliation_status,
            TransferDetail.ReconciliationStatus.REQUIRES_DECISION,
        )
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_liquidation_marks_reconciliation_matched_when_real_equals_agreed(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
            estimated_extra_amount=Decimal("8.00"),
            charge_mode=TransferDetail.ChargeMode.UPFRONT_FULL,
            customer_agreed_amount=Decimal("28.00"),
        )
        technician = self._take_and_start(order)
        attend_order(order, result=self.transfer_success, user=technician)

        liquidate_order(
            order,
            user=technician,
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

        detail = TransferDetail.objects.get(work_order=order)

        self.assertEqual(detail.actual_total, Decimal("28.00"))
        self.assertEqual(detail.reconciliation_difference, Decimal("0.00"))
        self.assertEqual(
            detail.reconciliation_status,
            TransferDetail.ReconciliationStatus.MATCHED,
        )

    def test_regularization_decision_is_audited_and_does_not_create_charge(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
        )
        proposal = ProposedCharge.objects.get(work_order=order)
        accept_proposed_charge(
            proposal=proposal,
            user=self.atc_user,
            amount=Decimal("20.00"),
            due_date=date(2026, 9, 30),
        )
        technician = self._take_and_start(order)
        attend_order(order, result=self.transfer_success, user=technician)

        liquidation = liquidate_order(
            order,
            user=technician,
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

        submit_liquidation(liquidation, user=technician)

        validator = self.atc_user
        validator.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="work_orders",
                codename="validate_liquidation",
            ),
            Permission.objects.get(
                content_type__app_label="work_orders",
                codename="resolve_transfer_reconciliation",
            ),
        )
        validate_liquidation(liquidation, validator=validator)

        detail = TransferDetail.objects.get(work_order=order)
        resolve_transfer_reconciliation(
            transfer=detail,
            user=validator,
            action=TransferDetail.ReconciliationAction.CHARGE_DIFFERENCE,
            note="Se autoriza cobrar la diferencia en una operación separada.",
        )

        detail.refresh_from_db()

        self.assertEqual(
            detail.reconciliation_status,
            TransferDetail.ReconciliationStatus.RESOLVED,
        )
        self.assertEqual(
            detail.reconciliation_action,
            TransferDetail.ReconciliationAction.CHARGE_DIFFERENCE,
        )
        self.assertEqual(detail.reconciled_by, validator)
        self.assertIsNotNone(detail.reconciled_at)
        self.assertIn("operación separada", detail.reconciliation_note)
        charges = Charge.objects.filter(customer=self.customer)
        self.assertEqual(charges.count(), 1)
        self.assertEqual(charges.get().amount, Decimal("20.00"))

    def test_after_technical_suggests_real_cost_only_after_liquidation(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
            charge_mode=TransferDetail.ChargeMode.AFTER_TECHNICAL,
        )
        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertIsNone(suggested_proposed_charge_amount(proposal))

        technician = self._take_and_start(order)
        attend_order(order, result=self.transfer_success, user=technician)
        liquidate_order(
            order,
            user=technician,
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

        proposal.refresh_from_db()
        self.assertEqual(
            suggested_proposed_charge_amount(proposal),
            Decimal("28.00"),
        )
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_after_technical_accepting_real_cost_closes_reconciliation(self):
        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.internal_subtype,
            previous_location="Sala",
            new_location="Dormitorio",
            charge_mode=TransferDetail.ChargeMode.AFTER_TECHNICAL,
        )
        proposal = ProposedCharge.objects.get(work_order=order)

        technician = self._take_and_start(order)
        attend_order(order, result=self.transfer_success, user=technician)
        liquidate_order(
            order,
            user=technician,
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

        accept_proposed_charge(
            proposal=proposal,
            user=self.atc_user,
            amount=Decimal("28.00"),
            due_date=date(2026, 9, 30),
        )

        detail = TransferDetail.objects.get(work_order=order)
        proposal.refresh_from_db()

        self.assertEqual(detail.customer_agreed_amount, Decimal("28.00"))
        self.assertEqual(detail.reconciliation_difference, Decimal("0.00"))
        self.assertEqual(
            detail.reconciliation_status,
            TransferDetail.ReconciliationStatus.MATCHED,
        )
        self.assertEqual(proposal.charge.amount, Decimal("28.00"))

    def test_external_transfer_same_branch_keeps_service_code(self):
        destination_zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Sur",
        )
        original_code = self.subscription.service_code

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=self.branch,
            destination_zone=destination_zone,
            requested_address_text="Jr. Nueva 500",
            requested_supply_code="12345678",
        )
        technician = self._take_and_start(order)

        confirm_external_transfer_destination(
            order=order,
            user=technician,
            address="Jr. Nueva 500",
            district="Distrito Destino",
            zone=destination_zone,
            supply_code="12345678",
        )
        attend_order(order, result=self.transfer_success, user=technician)
        liquidate_order(
            order,
            user=technician,
            resolution_detail="Traslado externo dentro de la misma sede.",
        )

        self.subscription.refresh_from_db()
        detail = TransferDetail.objects.get(work_order=order)

        self.assertEqual(self.subscription.service_code, original_code)
        self.assertEqual(detail.previous_service_code, original_code)
        self.assertEqual(detail.resulting_service_code, original_code)
        self.assertEqual(self.subscription.address.zone.branch, self.branch)

    def test_external_transfer_cross_branch_changes_service_code_and_keeps_history(self):
        destination_branch = Branch.objects.create(
            code="JAUJA",
            name="Jauja",
        )
        destination_zone = Zone.objects.create(
            branch=destination_branch,
            name="Zona Jauja",
        )
        technician = User.objects.create_user(
            username="tecnico_jauja_codigo",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=destination_branch,
        )
        original_code = self.subscription.service_code

        order = create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.atc_user,
            subtype=self.external_subtype,
            destination_branch=destination_branch,
            destination_zone=destination_zone,
            requested_address_text="Jr. Destino 700",
            requested_supply_code="87654321",
        )
        self._take_and_start(order, technician)

        confirm_external_transfer_destination(
            order=order,
            user=technician,
            address="Jr. Destino 700",
            district="Jauja",
            zone=destination_zone,
            supply_code="87654321",
        )
        attend_order(order, result=self.transfer_success, user=technician)
        liquidate_order(
            order,
            user=technician,
            resolution_detail="Traslado entre sedes ejecutado.",
        )

        self.subscription.refresh_from_db()
        detail = TransferDetail.objects.get(work_order=order)

        self.assertNotEqual(self.subscription.service_code, original_code)
        self.assertTrue(
            self.subscription.service_code.startswith("JA01-A")
        )
        self.assertTrue(
            self.subscription.service_code.endswith("-INTERNET-01")
        )
        self.assertEqual(detail.previous_service_code, original_code)
        self.assertEqual(
            detail.resulting_service_code,
            self.subscription.service_code,
        )
        self.assertEqual(
            self.subscription.address.zone.branch,
            destination_branch,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.code, "CLI001")

