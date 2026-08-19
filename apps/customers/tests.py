from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.contracts.models import Contract
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import (
    OrderCause,
    OrderReason,
    OrderResult,
    OrderSubtype,
    OrderType,
    WorkOrder,
)

from .models import Customer, CustomerAddress


User = get_user_model()


class CustomerUIConsultaTests(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            code="LIM",
            name="Sede Lima",
        )

        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Centro",
        )

        self.user = User.objects.create_user(
            username="colaborador",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.technician = User.objects.create_user(
            username="tecnico",
            password="123",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100",
            name="Plan 100 Mbps",
            speed_mbps=100,
        )

        self.customer = Customer.objects.create(
            code="CLI-0001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="12345678",
            person_type=Customer.PersonType.NATURAL,
            first_name="Juan",
            paternal_surname="Perez",
            maternal_surname="Gomez",
            phone="987654321",
            secondary_phone="912345678",
            email="juan@example.com",
        )

        self.customer_2 = Customer.objects.create(
            code="CLI-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.RUC,
            document_number="20123456789",
            person_type=Customer.PersonType.LEGAL,
            business_name="Empresa Telecable SAC",
            phone="987111222",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Principal 123",
            reference="Frente al parque",
            district="Huancayo",
            meter_number="MED-001",
            latitude="-12.0651",
            longitude="-75.2049",
            gps_link="https://maps.google.com/",
            is_primary=True,
        )

        self.address_2 = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Secundario 456",
            reference="Cerca del mercado",
            district="El Tambo",
            is_primary=False,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
            installation_date=date(2026, 1, 15),
        )

        self.subscription_2 = Subscription.objects.create(
            customer=self.customer,
            address=self.address_2,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.SUSPENDED,
            service_number=2,
        )

        self.contract = Contract.objects.create(
            contract_number="CTR-0001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 1, 15),
            status=Contract.Status.ACTIVE,
        )

        self.order_type = OrderType.objects.create(
            code="INSTALL",
            name="Instalación",
        )

        self.order_subtype = OrderSubtype.objects.create(
            order_type=self.order_type,
            code="STANDARD",
            name="Instalación estándar",
        )

        self.order_reason = OrderReason.objects.create(
            order_type=self.order_type,
            code="NEW",
            name="Nuevo servicio",
        )

        self.order_cause = OrderCause.objects.create(
            order_type=self.order_type,
            code="CLIENT_REQUEST",
            name="Solicitud del cliente",
        )

        self.order_result = OrderResult.objects.create(
            order_type=self.order_type,
            code="SUCCESS",
            name="Instalación exitosa",
            is_success=True,
        )

        self.work_order = WorkOrder.objects.create(
            order_number="OT-0001",
            subscription=self.subscription,
            order_type=self.order_type,
            subtype=self.order_subtype,
            reason=self.order_reason,
            cause=self.order_cause,
            result=self.order_result,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.ATTENDED,
            assigned_technician=self.technician,
            created_by=self.user,
        )

        self.other_subscription = Subscription.objects.create(
            customer=self.customer_2,
            address=CustomerAddress.objects.create(
                customer=self.customer_2,
                zone=self.zone,
                address="Av. Empresa 789",
                district="Huancayo",
                is_primary=True,
            ),
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
        )

        self.other_work_order = WorkOrder.objects.create(
            order_number="OT-0002",
            subscription=self.other_subscription,
            order_type=self.order_type,
            subtype=self.order_subtype,
            reason=self.order_reason,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.PENDING,
            created_by=self.user,
        )

        self.search_url = reverse("customers:search")
        self.detail_url = reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )

        self.client.login(
            username="colaborador",
            password="123",
        )

    # ------------------------------------------------------------------
    # ACCESO Y PERMISOS
    # ------------------------------------------------------------------

    def test_usuario_autenticado_puede_abrir_busqueda(self):
        response = self.client.get(self.search_url)

        self.assertEqual(response.status_code, 200)

    def test_usuario_anonimo_es_redirigido_al_login(self):
        self.client.logout()

        response = self.client.get(self.search_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_usuario_anonimo_no_puede_ver_ficha(self):
        self.client.logout()

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # BÚSQUEDA
    # ------------------------------------------------------------------

    def test_busqueda_por_dni(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "12345678"
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Juan")
        self.assertEqual(response.context["customer_found"], self.customer)

    def test_busqueda_por_ruc(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.RUC,
                "document_number": "20123456789"
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Empresa Telecable SAC")
        self.assertEqual(response.context["customer_found"], self.customer_2)

    def test_busqueda_sin_coincidencias(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "99999999"
            },
        )

        self.assertEqual(len(response.context["customers"]), 0)
        self.assertIsNone(response.context["customer_found"])

    def test_busqueda_vacia_no_devuelve_todos_los_clientes(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": "",
                "document_number": ""
            },
        )

        self.assertEqual(len(response.context["customers"]), 0)

    def test_busqueda_conserva_criterio(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "12345678",
            },
        )

        self.assertEqual(
            response.context["current_document_number"],
            "12345678",
        )
        self.assertEqual(
            response.context["current_document_type"],
            Customer.DocumentType.DNI,
        )

        self.assertContains(response, "12345678")

    def test_busqueda_post_no_permite_modificacion(self):
        response = self.client.post(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "12345678"
            },
        )

        self.assertEqual(response.status_code, 405)

    # ------------------------------------------------------------------
    # FICHA DEL CLIENTE
    # ------------------------------------------------------------------

    def test_ficha_muestra_datos_principales(self):
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CLI-0001")
        self.assertContains(response, "12345678")
        self.assertContains(response, "Juan")
        self.assertContains(response, "Perez")
        self.assertContains(response, "Gomez")
        self.assertContains(response, "987654321")

    def test_ficha_muestra_todas_las_direcciones(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Av. Principal 123")
        self.assertContains(response, "Jr. Secundario 456")

    def test_ficha_identifica_direccion_principal(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Av. Principal 123")

        addresses = list(response.context["addresses"])

        self.assertEqual(addresses[0], self.address)
        self.assertTrue(addresses[0].is_primary)

    def test_ficha_muestra_suscripciones(self):
        response = self.client.get(self.detail_url)

        subscriptions = list(response.context["subscriptions"])

        self.assertEqual(len(subscriptions), 2)
        self.assertIn(self.subscription, subscriptions)
        self.assertIn(self.subscription_2, subscriptions)

    def test_ficha_muestra_plan(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Plan 100 Mbps")

    def test_ficha_muestra_tipo_de_servicio(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Internet")

    def test_ficha_muestra_estado_activo(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Activo")

    def test_ficha_muestra_estado_suspendido(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Suspendido")

    # ------------------------------------------------------------------
    # CONTRATOS
    # ------------------------------------------------------------------

    def test_ficha_muestra_contrato(self):
        response = self.client.get(self.detail_url)

        contracts = list(response.context["contracts"])

        self.assertIn(self.contract, contracts)
        self.assertContains(response, "CTR-0001")

    # ------------------------------------------------------------------
    # ÓRDENES
    # ------------------------------------------------------------------

    def test_ficha_muestra_orden_asociada(self):
        response = self.client.get(self.detail_url)

        work_orders = list(response.context["work_orders"])

        self.assertIn(self.work_order, work_orders)
        self.assertContains(response, "OT-0001")

    def test_ficha_muestra_tipo_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Instalación")

    def test_ficha_muestra_subtipo_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Instalación estándar")

    def test_ficha_muestra_motivo_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Nuevo servicio")

    def test_ficha_muestra_resultado_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Instalación exitosa")

    def test_orden_de_otro_cliente_no_aparece(self):
        response = self.client.get(self.detail_url)

        work_orders = list(response.context["work_orders"])

        self.assertIn(self.work_order, work_orders)
        self.assertNotIn(self.other_work_order, work_orders)
        self.assertContains(response, "OT-0001")
        self.assertNotContains(response, "OT-0002")

    # ------------------------------------------------------------------
    # CASOS ESPECIALES
    # ------------------------------------------------------------------

    def test_cliente_sin_suscripciones_no_genera_error(self):
        customer = Customer.objects.create(
            code="CLI-SIN-SERV",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="88888888",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="SinServicio",
        )

        url = reverse(
            "customers:detail",
            kwargs={"pk": customer.pk},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["subscriptions"]),
            [],
        )

    def test_cliente_inexistente_devuelve_404(self):
        url = reverse(
            "customers:detail",
            kwargs={"pk": 999999},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # SOLO LECTURA
    # ------------------------------------------------------------------

    def test_consultar_ficha_no_modifica_suscripcion(self):
        original_status = self.subscription.status

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status,
            original_status,
        )

    def test_consultar_ficha_no_modifica_work_order(self):
        original_status = self.work_order.status

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)

        self.work_order.refresh_from_db()

        self.assertEqual(
            self.work_order.status,
            original_status,
        )