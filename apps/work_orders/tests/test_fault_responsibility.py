"""Averías con responsable: alta, portal del técnico y deuda al finalizar.

Lo que se fija aquí es que la responsabilidad del cliente -y solo esa-
termina en una deuda propuesta: la atención de la avería más lo instalado al
precio del catálogo, sin mover el saldo hasta que la ventanilla la acepte.
"""

import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.inventory.models import Material
from apps.payments.models import Charge, ChargeConcept, ProposedCharge
from apps.payments.proposals import (
    accept_proposed_charge,
    suggested_proposed_charge_amount,
)
from apps.services.models import Subscription
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.faults import (
    create_fault_work_order,
    fault_charge_breakdown,
)
from apps.work_orders.forms import WorkOrderCreateForm
from apps.work_orders.models import (
    FaultDetail,
    OrderReason,
    OrderResult,
    OrderType,
    WorkOrder,
)
from apps.work_orders.services import create_work_order
from apps.work_orders.tests.base import WorkOrderTestCase


MEDIA_ROOT = tempfile.mkdtemp(prefix="sicv-test-averias-")

CUSTOMER = FaultDetail.Responsibility.CUSTOMER
COMPANY = FaultDetail.Responsibility.COMPANY


def evidence_file(name="averia.jpg", content_type="image/jpeg"):
    return SimpleUploadedFile(
        name,
        b"contenido-binario-de-prueba",
        content_type=content_type,
    )


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class FaultTestCase(WorkOrderTestCase):
    """Base común: una avería de internet con su motivo y resultado."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()

        # Las evidencias de prueba no deben sobrevivir a la corrida.
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()

        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save(update_fields=["status"])

        self.fault_type, _ = OrderType.objects.update_or_create(
            code="INTERNET_FAULT",
            defaults={"name": "AVERÍA INTERNET", "is_active": True},
        )
        self.fault_type.service_types.add(self.service_type)
        self.fault_reason = OrderReason.objects.create(
            order_type=self.fault_type,
            code="FAULTY_CPE",
            name="EQUIPO AVERIADO",
            classification=OrderReason.Classification.TECHNICAL,
            is_active=True,
        )
        self.fault_success = OrderResult.objects.create(
            order_type=self.fault_type,
            code="SUCCESSFUL",
            name="Exitoso",
            is_success=True,
        )

        ChargeConcept.objects.update_or_create(
            code="averia-cliente",
            defaults={
                "name": "AVERÍA CLIENTE",
                "family": Charge.Concept.OTHER,
                "is_active": True,
            },
        )

    def create_fault(self, **overrides):
        data = {
            "subscription": self.subscription,
            "order_type": self.fault_type,
            "created_by": self.atc_user,
            "customer": self.customer,
            "reason": self.fault_reason,
        }
        data.update(overrides)
        return create_fault_work_order(**data)


class FaultCreationTests(FaultTestCase):

    def test_la_averia_arranca_como_responsabilidad_de_la_empresa(self):
        order = self.create_fault()

        detail = FaultDetail.objects.get(work_order=order)

        self.assertEqual(detail.responsibility, COMPANY)
        self.assertEqual(detail.responsibility_source, FaultDetail.Source.OPERATOR)
        self.assertEqual(detail.responsibility_set_by, self.atc_user)
        self.assertEqual(order.attention_type, WorkOrder.AttentionType.FIELD)
        self.assertFalse(ProposedCharge.objects.filter(work_order=order).exists())

    def test_la_averia_entra_al_pool_del_tecnico(self):
        order = self.create_fault()

        self.assertIn(order, available_work_orders(technician=self.technician))

    def test_cliente_sin_sustento_no_se_registra(self):
        with self.assertRaises(ValidationError):
            self.create_fault(responsibility=CUSTOMER)

        self.assertFalse(
            WorkOrder.objects.filter(order_type=self.fault_type).exists()
        )

    def test_la_evidencia_solo_acompana_la_responsabilidad_del_cliente(self):
        with self.assertRaises(ValidationError):
            self.create_fault(
                responsibility=COMPANY,
                evidence_files=[evidence_file()],
            )

    def test_registrar_cliente_no_emite_deuda(self):
        order = self.create_fault(
            responsibility=CUSTOMER,
            responsibility_note="El abonado cortó el drop al remodelar.",
        )

        self.assertFalse(ProposedCharge.objects.filter(work_order=order).exists())
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())


class FaultCreateWebTests(FaultTestCase):

    def setUp(self):
        super().setUp()
        self.url = reverse(
            "work_orders:fault_create",
            kwargs={"customer_pk": self.customer.pk},
        )
        self.client.login(username="atc1", password="test1234")

    def post_data(self, **overrides):
        data = {
            "subscription": self.subscription.pk,
            "order_type": self.fault_type.pk,
            "reason": self.fault_reason.pk,
            "responsibility": "COMPANY",
            "responsibility_note": "",
            "priority": "NORMAL",
            "detail": "Sin internet desde ayer.",
        }
        data.update(overrides)
        return data

    def test_el_menu_de_la_ficha_ofrece_averia(self):
        response = self.client.get(
            reverse("customers:orders", kwargs={"pk": self.customer.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)

    def test_la_pantalla_ofrece_responsable_con_empresa_por_defecto(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nueva avería")
        self.assertEqual(response.context["form"]["responsibility"].value(), "COMPANY")
        self.assertContains(
            response,
            '<option value="COMPANY" selected>Empresa</option>',
            html=True,
        )

    def test_empresa_registra_la_averia_sin_sustento(self):
        response = self.client.post(self.url, self.post_data())

        self.assertEqual(response.status_code, 302)
        order = WorkOrder.objects.get(order_type=self.fault_type)
        self.assertEqual(order.fault_detail.responsibility, COMPANY)

    def test_cliente_registra_sustento_y_evidencia(self):
        response = self.client.post(
            self.url,
            self.post_data(
                responsibility="CUSTOMER",
                responsibility_note="El abonado cortó el drop al remodelar.",
                responsibility_evidence=[
                    evidence_file("drop-cortado.jpg"),
                    evidence_file("roseta.png", "image/png"),
                ],
            ),
        )

        self.assertEqual(response.status_code, 302)
        detail = FaultDetail.objects.get(work_order__order_type=self.fault_type)
        self.assertEqual(detail.responsibility, CUSTOMER)
        self.assertEqual(
            detail.responsibility_note,
            "El abonado cortó el drop al remodelar.",
        )
        self.assertEqual(detail.evidences.count(), 2)
        self.assertEqual(
            set(detail.evidences.values_list("source", flat=True)),
            {FaultDetail.Source.OPERATOR},
        )

    def test_cliente_sin_sustento_vuelve_al_formulario(self):
        response = self.client.post(
            self.url,
            self.post_data(responsibility="CUSTOMER"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "responsibility_note",
            "Sustente por qué la avería es responsabilidad del cliente.",
        )
        self.assertFalse(
            WorkOrder.objects.filter(order_type=self.fault_type).exists()
        )

    def test_evidencia_con_formato_no_permitido_se_rechaza(self):
        response = self.client.post(
            self.url,
            self.post_data(
                responsibility="CUSTOMER",
                responsibility_note="Daño causado por el abonado.",
                responsibility_evidence=[
                    evidence_file("programa.exe", "application/octet-stream"),
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "responsibility_evidence",
            "Formato no permitido. Use JPG, PNG, WEBP o PDF.",
        )

    def test_empresa_descarta_el_sustento_cargado_antes_de_cambiar(self):
        response = self.client.post(
            self.url,
            self.post_data(
                responsibility="COMPANY",
                responsibility_note="Texto que quedó al cambiar de opción.",
                responsibility_evidence=[evidence_file()],
            ),
        )

        self.assertEqual(response.status_code, 302)
        detail = FaultDetail.objects.get(work_order__order_type=self.fault_type)
        self.assertEqual(detail.responsibility_note, "")
        self.assertEqual(detail.evidences.count(), 0)

    def test_formulario_generico_ya_no_ofrece_averias(self):
        form = WorkOrderCreateForm(customer=self.customer)

        self.assertNotIn(self.fault_type, form.fields["order_type"].queryset)

    def test_la_ficha_de_la_ot_muestra_la_responsabilidad(self):
        order = self.create_fault(
            responsibility=CUSTOMER,
            responsibility_note="Cable cortado por el abonado.",
        )

        response = self.client.get(
            reverse("work_orders:detail", kwargs={"pk": order.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Responsabilidad de la avería")
        self.assertContains(response, "Cable cortado por el abonado.")
        self.assertContains(response, "Cobro estimado")


class FaultFieldTestCase(FaultTestCase):
    """Base con el recorrido del técnico por la API: tomar, iniciar, liquidar."""

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def url(self, name, order):
        return reverse(f"work_orders_api:{name}", args=[order.pk])

    def start(self, order):
        order.assign_technician(self.technician, assigned_by=self.technician)
        response = self.api.post(self.url("start", order), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        order.refresh_from_db()
        return order

    def mark_customer(self, order, note="Conector roto por el abonado.", files=()):
        return self.api.post(
            self.url("fault_responsibility", order),
            {"responsibility": "CUSTOMER", "note": note, "files": list(files)},
            format="multipart",
        )

    def register_material(self, order, code, quantity):
        material = Material.objects.get(code=code)
        response = self.api.post(
            self.url("field_materials", order),
            {
                "material_id": material.pk,
                "movement_type": "INSTALLED",
                "quantity": quantity,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def complete(self, order):
        completed = self.api.post(
            self.url("complete", order),
            {"result_id": self.fault_success.pk},
            format="json",
        )
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.data)

        order.refresh_from_db()
        return order

    def liquidate(self, order):
        liquidated = self.api.post(
            self.url("liquidate", order),
            {"resolution_detail": "Se reemplazó el conector y el cable."},
            format="json",
        )
        self.assertEqual(liquidated.status_code, status.HTTP_200_OK, liquidated.data)

        order.refresh_from_db()
        return order

    def complete_and_liquidate(self, order):
        return self.liquidate(self.complete(order))


class FaultTechnicianAPITests(FaultFieldTestCase):

    def test_averia_derivada_sin_detalle_se_lee_como_empresa(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.fault_type,
            created_by=self.atc_user,
            customer=self.customer,
            reason=self.fault_reason,
            attention_type=WorkOrder.AttentionType.FIELD,
        )
        self.start(order)

        response = self.api.get(self.url("fault_responsibility", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["responsibility"], "COMPANY")
        self.assertFalse(response.data["is_registered"])
        self.assertTrue(response.data["editable"])

    def test_la_app_del_tecnico_no_recibe_montos(self):
        """El cobro al cliente sale en su deuda, no en la app del técnico."""
        order = self.start(self.create_fault())
        self.mark_customer(order)
        self.register_material(order, "ONU", "1")

        response = self.api.get(self.url("fault_responsibility", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("charge", response.data)
        self.assertNotIn("tariff", response.data)

    def test_tecnico_marca_cliente_con_sustento_y_evidencia(self):
        order = self.start(self.create_fault())

        response = self.mark_customer(order, files=[evidence_file("conector.jpg")])

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        detail = FaultDetail.objects.get(work_order=order)
        self.assertEqual(detail.responsibility, CUSTOMER)
        self.assertEqual(detail.responsibility_source, FaultDetail.Source.TECHNICIAN)
        self.assertEqual(detail.responsibility_set_by, self.technician)
        self.assertEqual(detail.evidences.count(), 1)
        self.assertEqual(response.data["responsibility"], "CUSTOMER")
        self.assertEqual(len(response.data["evidences"]), 1)

    def test_el_estimado_de_la_ficha_suma_el_material_registrado(self):
        """Antes de liquidar, la ficha web de la OT estima con lo registrado."""
        order = self.start(self.create_fault())
        self.mark_customer(order)
        self.register_material(order, "CONECTOR_MECANICO", "1")

        breakdown = fault_charge_breakdown(order)

        self.assertFalse(breakdown["is_final"])
        self.assertEqual(breakdown["total"], Decimal("35.00"))
        self.assertEqual(breakdown["lines"][0]["code"], "CONECTOR_MECANICO")

    def test_tecnico_no_marca_cliente_sin_sustento(self):
        order = self.start(self.create_fault())

        response = self.mark_customer(order, note="")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            FaultDetail.objects.get(work_order=order).responsibility,
            COMPANY,
        )

    def test_la_responsabilidad_solo_se_registra_en_atencion(self):
        order = self.create_fault()
        order.assign_technician(self.technician, assigned_by=self.technician)

        response = self.mark_customer(order)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_otro_tecnico_no_ve_la_responsabilidad(self):
        order = self.start(self.create_fault())
        token, _ = Token.objects.get_or_create(user=self.other_technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.api.get(self.url("fault_responsibility", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_orden_que_no_es_averia_responde_404(self):
        order = self.create_assigned_order()

        response = self.api.get(self.url("fault_responsibility", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_liquidar_averia_del_cliente_propone_atencion_mas_materiales(self):
        order = self.start(self.create_fault())
        self.mark_customer(order)
        self.register_material(order, "CONECTOR_MECANICO", "1")
        self.register_material(order, "CABLE_RG6", "12")
        # Sin precio en el catálogo: se declara pero no se cobra.
        self.register_material(order, "SPLITTER_2", "1")

        order = self.complete_and_liquidate(order)

        proposal = ProposedCharge.objects.get(work_order=order)
        self.assertEqual(proposal.status, ProposedCharge.Status.PENDING)
        self.assertEqual(proposal.concept_item.code, "averia-cliente")
        self.assertEqual(proposal.display_title, "Deuda avería")
        self.assertEqual(suggested_proposed_charge_amount(proposal), Decimal("47.00"))
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

        items = {item.material_code: item for item in order.liquidation.items.all()}
        self.assertTrue(items["CONECTOR_MECANICO"].is_billable)
        self.assertEqual(items["CONECTOR_MECANICO"].unit_price, Decimal("25.00"))
        self.assertEqual(items["CABLE_RG6"].unit_price, Decimal("1.00"))
        self.assertFalse(items["SPLITTER_2"].is_billable)
        self.assertEqual(
            FaultDetail.objects.get(work_order=order).service_fee_snapshot,
            Decimal("10.00"),
        )

    def test_finalizar_la_atencion_ya_propone_la_deuda(self):
        order = self.start(self.create_fault())
        self.mark_customer(order)
        self.register_material(order, "CONECTOR_MECANICO", "1")

        order = self.complete(order)

        self.assertEqual(order.status, WorkOrder.Status.ATTENDED)
        proposal = ProposedCharge.objects.get(work_order=order)
        self.assertEqual(proposal.status, ProposedCharge.Status.PENDING)
        # Atención 10 + conector mecánico 25.
        self.assertEqual(suggested_proposed_charge_amount(proposal), Decimal("35.00"))
        self.assertTrue(fault_charge_breakdown(order)["is_final"])
        self.assertEqual(
            FaultDetail.objects.get(work_order=order).service_fee_snapshot,
            Decimal("10.00"),
        )
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())

    def test_caja_emite_antes_de_liquidar_y_liquidar_no_duplica(self):
        order = self.start(self.create_fault())
        self.mark_customer(order)
        self.register_material(order, "CONECTOR_MECANICO", "1")
        order = self.complete(order)
        proposal = ProposedCharge.objects.get(work_order=order)

        accept_proposed_charge(
            proposal=proposal,
            user=self.supervisor,
            amount=Decimal("35.00"),
            due_date=None,
        )
        self.liquidate(order)

        self.assertEqual(ProposedCharge.objects.filter(work_order=order).count(), 1)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ProposedCharge.Status.ACCEPTED)
        self.assertEqual(proposal.charge.amount, Decimal("35.00"))

    def test_mientras_esta_en_atencion_caja_no_puede_emitir(self):
        order = self.start(
            self.create_fault(
                responsibility=CUSTOMER,
                responsibility_note="Daño causado por el abonado.",
            )
        )
        # La propuesta solo nace al finalizar; aquí se fuerza para probar la
        # regla de la ventanilla con los materiales todavía abiertos.
        from apps.payments.proposals import propose_fault_charge

        proposal = propose_fault_charge(work_order=order)

        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=proposal,
                user=self.supervisor,
                amount=Decimal("10.00"),
                due_date=None,
            )

    def test_liquidar_averia_de_la_empresa_no_propone_deuda(self):
        order = self.start(self.create_fault())
        self.register_material(order, "CONECTOR_MECANICO", "1")

        order = self.complete_and_liquidate(order)

        self.assertFalse(ProposedCharge.objects.filter(work_order=order).exists())
        self.assertFalse(
            order.liquidation.items.get(material_code="CONECTOR_MECANICO").is_billable
        )

    def test_el_tecnico_puede_corregir_al_operador(self):
        order = self.start(
            self.create_fault(
                responsibility=CUSTOMER,
                responsibility_note="El abonado dice que se cayó el router.",
            )
        )

        response = self.api.post(
            self.url("fault_responsibility", order),
            {"responsibility": "COMPANY", "note": ""},
            format="multipart",
        )
        order = self.complete_and_liquidate(order)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        detail = FaultDetail.objects.get(work_order=order)
        self.assertEqual(detail.responsibility, COMPANY)
        self.assertEqual(detail.responsibility_note, "")
        self.assertFalse(ProposedCharge.objects.filter(work_order=order).exists())


class FaultDebtWebTests(FaultFieldTestCase):
    """La ventanilla ve la deuda avería, su desglose, y la emite."""

    def setUp(self):
        super().setUp()

        order = self.start(
            self.create_fault(
                responsibility=CUSTOMER,
                responsibility_note="Daño causado por el abonado.",
            )
        )
        self.register_material(order, "ONU", "1")
        self.register_material(order, "CABLE_UTP", "5")
        self.order = self.complete_and_liquidate(order)
        self.proposal = ProposedCharge.objects.get(work_order=self.order)

        self.resolver = self.supervisor
        for app_label, codename in (
            ("payments", "view_charge"),
            ("payments", "resolve_proposedcharge"),
        ):
            self.resolver.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
            )
        self.client.force_login(self.resolver)

    def resolve_url(self):
        return reverse(
            "payments:proposal_resolve",
            kwargs={"pk": self.customer.pk, "proposal_pk": self.proposal.pk},
        )

    def test_la_ficha_de_deuda_muestra_la_deuda_averia(self):
        response = self.client.get(
            reverse("payments:debt", args=[self.customer.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deuda avería")
        self.assertIn(self.proposal, response.context["pending_proposals"])
        self.assertEqual(list(response.context["debt"]["charges"]), [])

    def test_la_resolucion_desglosa_atencion_y_materiales(self):
        response = self.client.get(self.resolve_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Atención de la avería")
        self.assertContains(response, "ONU")
        self.assertContains(response, "CABLE UTP")
        # Atención 10 + ONU 100 + 5 m de UTP a 2, en moneda localizada.
        self.assertContains(response, "S/ 120,00")
        self.assertContains(response, "Daño causado por el abonado.")
        self.assertEqual(
            response.context["form"]["amount"].value(),
            Decimal("120.00"),
        )

    def test_aceptar_emite_el_total_calculado(self):
        response = self.client.post(
            self.resolve_url(),
            {
                "accion": "aceptar",
                "selected": "on",
                "amount": "120.00",
                "due_date": "2026-09-30",
                "note": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("payments:debt", args=[self.customer.pk]),
        )
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposedCharge.Status.ACCEPTED)
        self.assertEqual(self.proposal.charge.amount, Decimal("120.00"))
        self.assertEqual(
            self.proposal.charge.description,
            "AVERÍA INTERNET - RESPONSABILIDAD DEL CLIENTE",
        )

    def test_otro_monto_exige_observacion(self):
        with self.assertRaises(ValidationError):
            accept_proposed_charge(
                proposal=self.proposal,
                user=self.resolver,
                amount=Decimal("100.00"),
                due_date=None,
            )

        accept_proposed_charge(
            proposal=self.proposal,
            user=self.resolver,
            amount=Decimal("100.00"),
            due_date=None,
            note="Descuento autorizado por supervisión.",
        )

        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.charge.amount, Decimal("100.00"))

    def test_descartar_exige_motivo_y_no_emite(self):
        response = self.client.post(
            self.resolve_url(),
            {"accion": "descartar", "note": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposedCharge.Status.PENDING)
        self.assertFalse(Charge.objects.filter(customer=self.customer).exists())
