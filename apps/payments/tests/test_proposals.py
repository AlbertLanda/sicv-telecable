"""
La deuda que un traslado propone, y lo que la ventanilla hace con ella.

Lo que se fija aquí es el límite entre proponer y cobrar: registrar la orden no
le debe mover el saldo al abonado, y lo que lo mueve es alguien aceptando la
propuesta con un monto puesto a mano.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.payments.models import Charge, ChargeConcept, ProposedCharge
from apps.payments.proposals import (
    accept_proposed_charge,
    discard_proposed_charge,
    propose_transfer_charge,
)
from apps.payments.services import customer_debt
from apps.payments.tests.base import PaymentsTestCase
from apps.work_orders.models import OrderSubtype, OrderType
from apps.work_orders.services import (
    create_transfer_work_order,
    create_work_order,
)


class TransferProposalTestCase(PaymentsTestCase):
    """Base común: el catálogo mínimo para que un traslado exista."""

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
        self.requirement = OrderType.objects.create(
            code="REQUIREMENT",
            name="REQUERIMIENTO",
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

    def make_transfer_order(self):
        # Se informa al abonado el mismo monto que luego se acepta, para que
        # aceptar no exija la observación de ajuste.
        return create_transfer_work_order(
            subscription=self.subscription,
            customer=self.customer,
            created_by=self.operator,
            subtype=self.internal,
            previous_location="Sala",
            new_location="Dormitorio",
            customer_agreed_amount=Decimal("50.00"),
        )


class ProposalCreationTests(TransferProposalTestCase):

    def test_orden_de_traslado_deja_la_deuda_propuesta(self):
        order = self.make_transfer_order()

        proposal = ProposedCharge.objects.get(work_order=order)

        self.assertEqual(proposal.status, ProposedCharge.Status.PENDING)
        self.assertEqual(proposal.customer, self.customer)
        self.assertEqual(proposal.subscription, self.subscription)
        self.assertEqual(proposal.concept_item, self.concept)
        self.assertEqual(proposal.description, "TRASLADO INTERNO")

    def test_proponer_no_emite_deuda_ni_mueve_el_saldo(self):
        antes = customer_debt(self.customer)["total"]

        self.make_transfer_order()

        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())
        self.assertEqual(customer_debt(self.customer)["total"], antes)

    def test_orden_de_otro_tipo_no_propone_nada(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.requirement,
            created_by=self.operator,
        )

        self.assertFalse(ProposedCharge.objects.filter(work_order=order).exists())

    def test_proponer_dos_veces_la_misma_orden_no_duplica_la_deuda(self):
        order = self.make_transfer_order()

        repetida = propose_transfer_charge(work_order=order)

        self.assertEqual(
            ProposedCharge.objects.filter(work_order=order).count(), 1
        )
        self.assertEqual(repetida.work_order_id, order.pk)

    def test_dos_traslados_distintos_proponen_su_propia_deuda(self):
        primera = self.make_transfer_order()
        segunda = self.make_transfer_order()

        self.assertNotEqual(primera.pk, segunda.pk)
        self.assertEqual(
            ProposedCharge.objects.filter(customer=self.customer).count(), 2
        )


class ProposalResolutionTests(TransferProposalTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_transfer_order()
        self.proposal = ProposedCharge.objects.get(work_order=self.order)

    def test_aceptar_emite_el_cargo_por_el_monto_que_puso_el_operador(self):
        accept_proposed_charge(
            proposal=self.proposal,
            user=self.operator,
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 30),
        )

        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposedCharge.Status.ACCEPTED)
        self.assertEqual(self.proposal.charge.amount, Decimal("50.00"))
        self.assertEqual(self.proposal.charge.due_date, date(2026, 9, 30))
        self.assertEqual(self.proposal.resolved_by, self.operator)
        self.assertIsNotNone(self.proposal.resolved_at)

    def test_el_cargo_aceptado_entra_en_la_deuda_con_el_detalle_del_traslado(self):
        accept_proposed_charge(
            proposal=self.proposal,
            user=self.operator,
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 30),
        )

        deuda = customer_debt(self.customer)
        self.proposal.refresh_from_db()

        self.assertEqual(deuda["total"], Decimal("50.00"))
        self.assertIn(self.proposal.charge, list(deuda["charges"]))
        self.assertEqual(
            self.proposal.charge.description, "TRASLADO INTERNO"
        )

    def test_una_propuesta_ya_aceptada_no_se_acepta_otra_vez(self):
        accept_proposed_charge(
            proposal=self.proposal,
            user=self.operator,
            amount=Decimal("50.00"),
            due_date=date(2026, 9, 30),
        )

        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=self.proposal,
                user=self.operator,
                amount=Decimal("80.00"),
                due_date=date(2026, 9, 30),
            )

        self.assertEqual(Charge.objects.filter(customer=self.customer).count(), 1)

    def test_descartar_deja_el_motivo_y_no_emite_deuda(self):
        discard_proposed_charge(
            proposal=self.proposal,
            user=self.operator,
            reason="Traslado sin costo autorizado.",
        )

        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposedCharge.Status.DISCARDED)
        self.assertEqual(self.proposal.resolved_by, self.operator)
        self.assertIsNone(self.proposal.charge)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_descartar_sin_motivo_no_se_permite(self):
        with self.assertRaises(ValidationError):
            discard_proposed_charge(
                proposal=self.proposal,
                user=self.operator,
                reason="   ",
            )

        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposedCharge.Status.PENDING)

    def test_una_propuesta_descartada_ya_no_se_acepta(self):
        discard_proposed_charge(
            proposal=self.proposal,
            user=self.operator,
            reason="Cortesía comercial autorizada.",
        )

        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=self.proposal,
                user=self.operator,
                amount=Decimal("50.00"),
                due_date=date(2026, 9, 30),
            )


class ProposalWebTests(TransferProposalTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.make_transfer_order()
        self.proposal = ProposedCharge.objects.get(work_order=self.order)

        self.resolver = self.make_user(
            "resuelve1", permissions=["view_charge", "resolve_proposedcharge"]
        )
        self.consultant = self.make_user("consulta1", permissions=["view_charge"])

    def debt_url(self):
        return reverse("payments:debt", args=[self.customer.pk])

    def resolve_url(self, customer=None, proposal=None):
        return reverse(
            "payments:proposal_resolve",
            kwargs={
                "pk": (customer or self.customer).pk,
                "proposal_pk": (proposal or self.proposal).pk,
            },
        )

    def accept_post(self, **overrides):
        data = {
            "accion": "aceptar",
            "selected": "on",
            "amount": "50.00",
            "due_date": "2026-09-30",
            "note": "",
        }
        data.update(overrides)

        return self.client.post(self.resolve_url(), data)

    def test_la_propuesta_sale_encima_de_la_tabla_y_no_dentro(self):
        self.login(self.resolver)

        response = self.client.get(self.debt_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deuda traslado")
        self.assertIn(self.proposal, response.context["pending_proposals"])
        self.assertEqual(list(response.context["debt"]["charges"]), [])

    def test_la_pantalla_muestra_el_traslado_como_linea_de_deuda(self):
        self.login(self.resolver)

        response = self.client.get(self.resolve_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TRASLADO INTERNO")
        self.assertContains(response, self.order.order_number)

    def test_los_campos_llevan_el_trazo_visual_de_las_demas_pantallas(self):
        """Sin la clase compartida, «Paga hasta» sale con el aspecto por
        defecto del navegador y la pantalla parece de otra aplicación."""
        self.login(self.resolver)

        response = self.client.get(self.resolve_url())
        form = response.context["form"]

        self.assertEqual(
            form.fields["due_date"].widget.attrs.get("class"), "form-control"
        )
        self.assertEqual(
            form.fields["amount"].widget.attrs.get("class"), "form-control"
        )
        self.assertEqual(
            form.fields["selected"].widget.attrs.get("class"),
            "form-check-input",
        )

    def test_paga_hasta_arranca_en_la_fecha_de_hoy(self):
        from django.utils import timezone

        self.login(self.resolver)

        response = self.client.get(self.resolve_url())

        self.assertContains(
            response, f'value="{timezone.localdate():%Y-%m-%d}"'
        )

    def test_quien_solo_consulta_ve_el_aviso_pero_no_el_enlace(self):
        self.login(self.consultant)

        response = self.client.get(self.debt_url())

        self.assertContains(response, "Deuda traslado")
        self.assertFalse(response.context["can_resolve_proposal"])
        self.assertNotContains(response, self.resolve_url())

    def test_aceptar_emite_el_cargo_y_lo_manda_a_la_tabla(self):
        self.login(self.resolver)

        response = self.accept_post()

        self.assertRedirects(response, self.debt_url())

        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposedCharge.Status.ACCEPTED)
        self.assertEqual(self.proposal.charge.amount, Decimal("50.00"))

        tablero = self.client.get(self.debt_url())

        self.assertEqual(tablero.context["pending_proposals"], [])
        self.assertIn(
            self.proposal.charge, list(tablero.context["debt"]["charges"])
        )

    def test_sin_marcar_la_deuda_no_se_emite_nada(self):
        self.login(self.resolver)

        response = self.accept_post(selected="")

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "selected", "Marque la deuda para aceptarla."
        )
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_sin_monto_no_se_emite_nada(self):
        self.login(self.resolver)

        response = self.accept_post(amount="")

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "amount", "Indique el monto que se le cobra."
        )
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_descartar_exige_motivo(self):
        self.login(self.resolver)

        response = self.client.post(
            self.resolve_url(), {"accion": "descartar", "note": ""}
        )

        self.assertEqual(response.status_code, 200)

        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposedCharge.Status.PENDING)

    def test_descartar_con_motivo_cierra_la_propuesta_sin_deuda(self):
        self.login(self.resolver)

        response = self.client.post(
            self.resolve_url(),
            {"accion": "descartar", "note": "Traslado sin costo."},
        )

        self.assertRedirects(response, self.debt_url())

        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposedCharge.Status.DISCARDED)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_sin_permiso_no_se_puede_resolver(self):
        self.login(self.consultant)

        response = self.accept_post()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_no_se_resuelve_la_propuesta_de_otro_abonado(self):
        from apps.customers.models import Customer

        otro = Customer.objects.create(
            code="CLI002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10203040",
            first_name="Ana",
            paternal_surname="Quispe",
        )

        self.login(self.resolver)

        response = self.client.get(self.resolve_url(customer=otro))

        self.assertEqual(response.status_code, 404)
