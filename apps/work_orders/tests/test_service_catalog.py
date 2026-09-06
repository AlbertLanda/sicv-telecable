"""
Pruebas del encadenado Suscripción -> Servicio -> Motivo.

El SICV operativo no ofrece el catálogo completo de órdenes sobre
cualquier suscripción: una avería de cable no existe para un abonado
solo-internet. Aquí se verifica que ese ámbito se respeta en el catálogo,
en el formulario y —sobre todo— en la validación, que es la única capa
que un POST armado a mano no puede saltarse.
"""

from io import StringIO

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.urls import reverse

from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.forms import WorkOrderCreateForm
from apps.work_orders.models import OrderReason, OrderType, WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase
from django.core.exceptions import ValidationError

from apps.work_orders.services import create_work_order

class OrderTypeScopeTests(WorkOrderTestCase):
    """Ámbito por servicio del catálogo de tipos de orden."""

    def setUp(self):
        super().setUp()

        self.cable_service = ServiceType.objects.create(
            code="CABLE",
            name="Cable",
            supports_tv_annexes=True,
        )

        self.cable_fault = OrderType.objects.create(
            code="CABLE_FAULT",
            name="AVERÍA CABLE",
        )
        self.cable_fault.service_types.set([self.cable_service])

    def test_un_tipo_sin_servicios_declarados_es_transversal(self):
        self.assertTrue(
            self.installation_type.applies_to_service_type(self.service_type)
        )

        self.assertTrue(
            self.installation_type.applies_to_service_type(self.cable_service)
        )

        self.assertIn(
            self.installation_type,
            OrderType.objects.for_service_type(self.service_type),
        )

    def test_un_tipo_acotado_solo_aplica_a_su_servicio(self):
        self.assertTrue(
            self.cable_fault.applies_to_service_type(self.cable_service)
        )

        self.assertFalse(
            self.cable_fault.applies_to_service_type(self.service_type)
        )

    def test_for_service_type_excluye_los_tipos_de_otro_servicio(self):
        internet_types = OrderType.objects.for_service_type(self.service_type)

        self.assertNotIn(self.cable_fault, internet_types)
        self.assertIn(self.cable_fault, OrderType.objects.for_service_type(
            self.cable_service
        ))

    def test_applies_to_service_type_acepta_un_id(self):
        self.assertTrue(
            self.cable_fault.applies_to_service_type(self.cable_service.pk)
        )

        self.assertFalse(
            self.cable_fault.applies_to_service_type(self.service_type.pk)
        )


class WorkOrderCreateFormScopeTests(OrderTypeScopeTests):
    """El formulario solo ofrece —y solo acepta— lo emitible."""

    def test_el_selector_de_servicio_omite_lo_que_el_cliente_no_tiene(self):
        form = WorkOrderCreateForm(customer=self.customer)

        offered = list(form.fields["order_type"].queryset)

        # El cliente base solo tiene una suscripción INTERNET.
        self.assertIn(self.installation_type, offered)
        self.assertNotIn(self.cable_fault, offered)

    def test_el_selector_incluye_los_servicios_de_todas_las_suscripciones(self):
        cable_plan = Plan.objects.create(
            service_type=self.cable_service,
            code="CABLE-GEN",
            name="Cable general",
            speed_mbps=0,
            monthly_price=40,
        )

        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.cable_service,
            plan=cable_plan,
            status=Subscription.Status.ACTIVE,
        )

        form = WorkOrderCreateForm(customer=self.customer)

        self.assertIn(self.cable_fault, form.fields["order_type"].queryset)

    def test_se_rechaza_un_servicio_que_no_corresponde_a_la_suscripcion(self):
        # El tipo se fuerza dentro del queryset para aislar la regla que se
        # está probando: sin esto el error sería "opción no válida" y no el
        # de coherencia que interesa verificar.
        form = WorkOrderCreateForm(
            data={
                "subscription": self.subscription.pk,
                "order_type": self.cable_fault.pk,
                "subtype": "",
                "reason": "",
                "branch": self.branch.pk,
                "zone": self.zone.pk,
                "attention_type": WorkOrder.AttentionType.FIELD,
                "priority": WorkOrder.Priority.NORMAL,
                "scheduled_at": "",
                "detail": "Prueba de coherencia.",
            },
            customer=self.customer,
        )

        form.fields["order_type"].queryset = OrderType.objects.all()

        self.assertFalse(form.is_valid())
        self.assertIn("order_type", form.errors)
        self.assertIn("AVERÍA CABLE", form.errors["order_type"][0])

    def test_cascade_data_describe_el_encadenado_completo(self):
        data = WorkOrderCreateForm(customer=self.customer).cascade_data()

        subscription = data["subscriptions"][str(self.subscription.pk)]

        self.assertEqual(subscription["serviceCode"], "INTERNET")
        self.assertEqual(subscription["serviceType"], self.service_type.pk)

        installation = data["orderTypes"][str(self.installation_type.pk)]

        self.assertEqual(installation["name"], self.installation_type.name)
        # Transversal: lista vacía, no ausencia de la clave.
        self.assertEqual(installation["serviceTypes"], [])

        self.assertEqual(
            data["reasons"][str(self.installation_reason.pk)],
            self.installation_type.pk,
        )

class CreateWorkOrderServiceScopeTests(OrderTypeScopeTests):
    """create_work_order() aplica el ámbito aunque no medie el formulario.

    Antes de esto la coherencia servicio<->tipo de orden solo se validaba
    en WorkOrderCreateForm.clean(); un llamador que no pase por ahí -la API
    técnica, create_installation_work_order(), un POST armado a mano-
    la saltaba.
    """

    def test_create_work_order_rechaza_un_tipo_que_no_corresponde_al_servicio(self):
        with self.assertRaises(ValidationError) as ctx:
            create_work_order(
                subscription=self.subscription,  # INTERNET
                order_type=self.cable_fault,      # solo CABLE
                created_by=self.atc_user,
            )

        self.assertIn("AVERÍA CABLE", str(ctx.exception))

    def test_create_work_order_acepta_un_tipo_transversal(self):
        order = create_work_order(
            subscription=self.subscription,
            order_type=self.installation_type,
            created_by=self.atc_user,
            reason=self.installation_reason,
        )

        self.assertEqual(order.order_type, self.installation_type)


class WorkOrderCreateViewCascadeTests(WorkOrderTestCase):
    """La vista entrega al navegador lo necesario para encadenar."""

    def setUp(self):
        super().setUp()

        self.client.login(username="atc1", password="test1234")

        self.atc_user.user_permissions.add(
            Permission.objects.get(
                codename="add_workorder",
                content_type__app_label="work_orders",
            )
        )

        self.url = reverse(
            "work_orders:create",
            kwargs={"customer_pk": self.customer.pk},
        )

    def test_la_pagina_publica_el_mapa_de_cascada(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="wo-cascade"')
        self.assertContains(response, "serviceCode")

    def test_el_alta_muestra_el_resumen_del_abonado(self):
        """El mismo bloque que encabeza la ficha, sobre los datos de la orden."""
        response = self.client.get(self.url)

        self.assertContains(response, "tc-hero")
        self.assertContains(response, str(self.customer))
        self.assertContains(response, self.customer.code)
        self.assertContains(response, self.customer.document_number)

    def test_el_resumen_no_compite_con_el_titulo_de_la_pagina(self):
        """El h1 de la pantalla es «Nueva orden de trabajo», no el abonado."""
        response = self.client.get(self.url)

        body = response.content.decode()

        self.assertEqual(body.count("<h1"), 1)
        self.assertIn('<h2 class="tc-name">', body)

    def test_el_resumen_no_filtra_sintaxis_de_plantilla(self):
        response = self.client.get(self.url)

        self.assertNotContains(response, "{%")
        self.assertNotContains(response, "{#")

    def test_el_selector_se_llama_servicio(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Servicio")


class CargarCatalogoOrdenesTests(WorkOrderTestCase):
    """El comando que siembra el catálogo operativo."""

    def setUp(self):
        super().setUp()

        # El comando exige los tres servicios; el escenario base solo trae
        # INTERNET.
        self.cable_service = ServiceType.objects.create(
            code="CABLE",
            name="Cable",
            supports_tv_annexes=True,
        )

        self.duo_service = ServiceType.objects.create(
            code="DUO",
            name="Duo",
            supports_tv_annexes=True,
        )

    def run_command(self, **options):
        output = StringIO()
        call_command("cargar_catalogo_ordenes", stdout=output, **options)
        return output.getvalue()

    def offered_for(self, service_type):
        return set(
            OrderType.objects
            .for_service_type(service_type)
            .filter(is_active=True)
            .values_list("code", flat=True)
        )

    def test_duo_recibe_internet_y_cable(self):
        self.run_command()

        duo = self.offered_for(self.duo_service)

        self.assertIn("INTERNET_FAULT", duo)
        self.assertIn("CABLE_FAULT", duo)
        self.assertIn("CABLE_SERVICES", duo)
        self.assertIn("NOC_INCIDENT", duo)

    def test_internet_no_recibe_los_servicios_de_cable(self):
        self.run_command()

        internet = self.offered_for(self.service_type)

        self.assertIn("INTERNET_FAULT", internet)
        self.assertNotIn("CABLE_FAULT", internet)
        self.assertNotIn("CABLE_SERVICES", internet)

    def test_cable_no_recibe_los_servicios_de_internet(self):
        self.run_command()

        cable = self.offered_for(self.cable_service)

        self.assertIn("CABLE_FAULT", cable)
        self.assertIn("CABLE_SERVICES", cable)
        self.assertNotIn("INTERNET_FAULT", cable)
        self.assertNotIn("NOC_INCIDENT", cable)

        # Los transversales sí llegan a cable.
        self.assertIn("CUT", cable)
        self.assertIn("RECONNECTION", cable)
        self.assertIn("REQUIREMENT", cable)

    def test_los_motivos_cuelgan_de_su_servicio(self):
        self.run_command()

        fault = OrderType.objects.get(code="INTERNET_FAULT")

        motives = set(
            OrderReason.objects
            .filter(order_type=fault, is_active=True)
            .values_list("name", flat=True)
        )

        self.assertIn("ONT SIN CONEXIÓN", motives)
        self.assertIn("DROP DAÑADO EXTERNO", motives)

        # "SIN SEÑAL" existe en dos servicios distintos y no debe filtrarse
        # entre ellos.
        self.assertNotIn("SIN SEÑAL", motives)

        self.assertIn(
            "SIN SEÑAL",
            set(
                OrderReason.objects
                .filter(order_type__code="CABLE_FAULT")
                .values_list("name", flat=True)
            ),
        )

    def test_incidencia_tac_no_se_ofrece(self):
        self.run_command()

        self.assertNotIn("TAC_INCIDENT", self.offered_for(self.duo_service))
        self.assertNotIn("TAC_INCIDENT", self.offered_for(self.service_type))

    def test_un_tipo_retirado_se_borra_si_nadie_lo_usa(self):
        OrderType.objects.create(code="TAC_INCIDENT", name="INCIDENCIA TAC")

        self.run_command()

        self.assertFalse(
            OrderType.objects.filter(code="TAC_INCIDENT").exists()
        )

    def test_un_tipo_retirado_en_uso_se_desactiva_en_vez_de_borrarse(self):
        tac = OrderType.objects.create(
            code="TAC_INCIDENT",
            name="INCIDENCIA TAC",
        )

        reason = OrderReason.objects.create(
            order_type=tac,
            code="REQUIRED",
            name="REQUERIDO",
        )

        WorkOrder.objects.create(
            order_number="OT-2026-000999",
            subscription=self.subscription,
            order_type=tac,
            reason=reason,
            branch=self.branch,
            zone=self.zone,
            created_by=self.atc_user,
        )

        self.run_command()

        tac.refresh_from_db()
        reason.refresh_from_db()

        # La OT histórica conserva su tipo; simplemente deja de ofrecerse.
        self.assertFalse(tac.is_active)
        self.assertFalse(reason.is_active)
        self.assertNotIn("TAC_INCIDENT", self.offered_for(self.service_type))

    def test_el_comando_es_idempotente(self):
        self.run_command()

        types_after_first = OrderType.objects.count()
        reasons_after_first = OrderReason.objects.count()

        self.run_command()

        self.assertEqual(OrderType.objects.count(), types_after_first)
        self.assertEqual(OrderReason.objects.count(), reasons_after_first)

    def test_dry_run_no_persiste(self):
        before = OrderType.objects.count()

        self.run_command(dry_run=True)

        self.assertEqual(OrderType.objects.count(), before)

    def test_conserva_el_motivo_del_alta_comercial_automatica(self):
        self.run_command()

        self.assertTrue(
            OrderReason.objects.filter(
                order_type__code="INSTALLATION",
                code="NEW_CLIENT",
                is_active=True,
            ).exists()
        )
