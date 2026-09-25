from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.payments.models import Charge, ChargeConcept, ProposedCharge
from apps.payments.proposals import (
    accept_proposed_charge,
    discard_proposed_charge,
    suggested_proposed_charge_amount,
)
from apps.payments.services import customer_debt
from apps.payments.tests.base import PaymentsTestCase
from apps.work_orders.models import OrderSubtype, OrderType, TransferDetail
from apps.work_orders.services import create_transfer_work_order


class TransferProposalTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()

        self.transfer_type = OrderType.objects.create(
            code="TRANSFER",
            name="TRASLADO",
        )
        self.internal = OrderSubtype.objects.create(
            order_type=self.transfer_type,
            code="INTERNAL",
            name="TRASLADO INTERNO",
        )
        self.external = OrderSubtype.objects.create(
            order_type=self.transfer_type,
            code="EXTERNAL",
            name="TRASLADO EXTERNO",
        )
        self.concept, _ = ChargeConcept.objects.update_or_create(
            code="traslado",
            defaults={
                "name": "TRASLADO",
                "family": Charge.Concept.OTHER,
                "is_active": True,
            },
        )
        self.operator = self.make_user("traslados1")

    def make_internal(self, **overrides):
        data = {
            "subscription": self.subscription,
            "customer": self.customer,
            "created_by": self.operator,
            "subtype": self.internal,
            "previous_location": "Sala",
            "new_location": "Dormitorio",
        }
        data.update(overrides)
        return create_transfer_work_order(**data)

    def test_registering_transfer_proposes_but_does_not_emit_debt(self):
        before = customer_debt(self.customer)["total"]

        order = self.make_internal()
        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertEqual(proposal.status, ProposedCharge.Status.PENDING)
        self.assertEqual(proposal.description, "TRASLADO INTERNO")
        self.assertEqual(customer_debt(self.customer)["total"], before)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_internal_base_is_s20_and_is_the_suggested_upfront_amount(self):
        order = self.make_internal()
        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertEqual(
            order.transfer_detail.base_fee_snapshot,
            Decimal("20.00"),
        )
        self.assertEqual(
            suggested_proposed_charge_amount(proposal),
            Decimal("20.00"),
        )

    def test_full_upfront_uses_amount_informed_to_customer(self):
        order = self.make_internal(
            estimated_extra_amount=Decimal("12.00"),
            charge_mode=TransferDetail.ChargeMode.UPFRONT_FULL,
            customer_agreed_amount=Decimal("32.00"),
        )
        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertEqual(
            suggested_proposed_charge_amount(proposal),
            Decimal("32.00"),
        )

    def test_after_technical_has_no_upfront_suggestion(self):
        order = self.make_internal(
            charge_mode=TransferDetail.ChargeMode.AFTER_TECHNICAL,
        )
        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertIsNone(suggested_proposed_charge_amount(proposal))

        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=proposal,
                user=self.operator,
                amount=Decimal("20.00"),
                due_date=date(2026, 9, 30),
            )

        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_accepting_agreed_amount_emits_one_charge(self):
        order = self.make_internal()
        proposal = ProposedCharge.objects.get(work_order=order)

        accept_proposed_charge(
            proposal=proposal,
            user=self.operator,
            amount=Decimal("20.00"),
            due_date=date(2026, 9, 30),
        )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposedCharge.Status.ACCEPTED)
        self.assertEqual(proposal.charge.amount, Decimal("20.00"))
        self.assertEqual(customer_debt(self.customer)["total"], Decimal("20.00"))

    def test_stale_second_acceptance_cannot_emit_a_second_charge(self):
        order = self.make_internal()
        first = ProposedCharge.objects.get(work_order=order)
        stale = ProposedCharge.objects.get(pk=first.pk)

        accept_proposed_charge(
            proposal=first,
            user=self.operator,
            amount=Decimal("20.00"),
            due_date=date(2026, 9, 30),
        )

        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=stale,
                user=self.operator,
                amount=Decimal("20.00"),
                due_date=date(2026, 9, 30),
            )

        self.assertEqual(
            Charge.objects.filter(customer=self.customer).count(),
            1,
        )

    def test_different_amount_requires_audit_note(self):
        order = self.make_internal()
        proposal = ProposedCharge.objects.get(work_order=order)

        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=proposal,
                user=self.operator,
                amount=Decimal("25.00"),
                due_date=date(2026, 9, 30),
            )

        accept_proposed_charge(
            proposal=proposal,
            user=self.operator,
            amount=Decimal("25.00"),
            due_date=date(2026, 9, 30),
            note="Ajuste informado al abonado antes del cobro.",
        )

        proposal.refresh_from_db()
        self.assertEqual(proposal.charge.amount, Decimal("25.00"))
        self.assertIn("Ajuste informado", proposal.note)

    def test_discard_requires_reason_and_never_emits_debt(self):
        order = self.make_internal()
        proposal = ProposedCharge.objects.get(work_order=order)

        with self.assertRaises(ValidationError):
            discard_proposed_charge(
                proposal=proposal,
                user=self.operator,
                reason="",
            )

        discard_proposed_charge(
            proposal=proposal,
            user=self.operator,
            reason="Cortesía autorizada.",
        )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposedCharge.Status.DISCARDED)
        self.assertIsNone(proposal.charge)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())


class TransferProposalWebTests(TransferProposalTests):
    def setUp(self):
        super().setUp()
        self.order = self.make_internal()
        self.proposal = ProposedCharge.objects.get(work_order=self.order)
        self.resolver = self.make_user(
            "resuelve_traslado",
            permissions=["view_charge", "resolve_proposedcharge"],
        )

    def test_resolution_page_prefills_registered_base_amount(self):
        self.login(self.resolver)

        response = self.client.get(
            reverse(
                "payments:proposal_resolve",
                kwargs={
                    "pk": self.customer.pk,
                    "proposal_pk": self.proposal.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].initial["amount"],
            Decimal("20.00"),
        )
        self.assertContains(response, "TRASLADO INTERNO")
        self.assertContains(response, "Cobrar solo tarifa base al solicitar")
