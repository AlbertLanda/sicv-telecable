from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone

from .models import Plan, ServiceType, Subscription


User = get_user_model()


class SubscriptionCreateTests(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            code="HYO",
            name="Sede Huancayo",
        )

        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Centro",
        )

        self.user = User.objects.create_user(
            username="atc_services",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET",
            name="Internet",
            is_active=True,
        )

        self.service_type_2 = ServiceType.objects.create(
            code="TV",
            name="Televisión",
            is_active=True,
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100",
            name="Plan 100 Mbps",
            speed_mbps=100,
            monthly_price=100,
            is_active=True,
        )

        self.plan_2 = Plan.objects.create(
            service_type=self.service_type_2,
            code="TV-BASICO",
            name="TV Básico",
            is_active=True,
        )

        self.customer = Customer.objects.create(
            code="CLI-SERV-001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678901",
            person_type=Customer.PersonType.NATURAL,
            first_name="Juan",
            paternal_surname="Perez",
            maternal_surname="Gomez",
        )

        self.customer_2 = Customer.objects.create(
            code="CLI-SERV-002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678902",
            person_type=Customer.PersonType.NATURAL,
            first_name="Maria",
            paternal_surname="Lopez",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Principal 123",
            district="Huancayo",
            is_primary=True,
            is_active=True,
        )

        self.other_address = CustomerAddress.objects.create(
            customer=self.customer_2,
            zone=self.zone,
            address="Av. Otra 456",
            district="Huancayo",
            is_primary=True,
            is_active=True,
        )

        self.subscription_url = reverse(
            "services:subscription_create",
            kwargs={
                "customer_pk": self.customer.pk,
            },
        )

        self.client.login(
            username="atc_services",
            password="123",
        )

    # -------------------------------------------------------------
    # ACCESO
    # -------------------------------------------------------------

    def test_usuario_autenticado_puede_abrir_formulario(self):
        response = self.client.get(
            self.subscription_url
        )

        self.assertEqual(response.status_code, 200)

    def test_usuario_anonimo_no_puede_crear_suscripcion(self):
        self.client.logout()

        response = self.client.get(
            self.subscription_url
        )

        self.assertEqual(response.status_code, 302)

    # -------------------------------------------------------------
    # REGISTRO CORRECTO
    # -------------------------------------------------------------

    def test_crear_suscripcion_registra_cliente_correcto(self):
        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 1,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 302)

        subscription = Subscription.objects.get(
            customer=self.customer,
            service_type=self.service_type,
            service_number=1,
        )

        self.assertEqual(
            subscription.address,
            self.address,
        )

        self.assertEqual(
            subscription.plan,
            self.plan,
        )

    # -------------------------------------------------------------
    # PRESALE
    # -------------------------------------------------------------

    def test_nueva_suscripcion_inicia_en_presale(self):
        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 1,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 302)

        subscription = Subscription.objects.get(
            customer=self.customer,
            service_type=self.service_type,
            service_number=1,
        )

        self.assertEqual(
            subscription.status,
            Subscription.Status.PRESALE,
        )

    # -------------------------------------------------------------
    # DIRECCIÓN
    # -------------------------------------------------------------

    def test_no_permite_direccion_de_otro_cliente(self):
        response = self.client.post(
            self.subscription_url,
            {
                "address": self.other_address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 1,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "address",
            "Escoja una opción válida. Esa opción no está entre las disponibles.",
        )

        self.assertEqual(
            Subscription.objects.count(),
            0,
        )

    def test_no_permite_direccion_inactiva(self):
        self.address.is_active = False
        self.address.save(update_fields=["is_active"])

        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 1,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Subscription.objects.count(),
            0,
        )

    # -------------------------------------------------------------
    # PLAN / SERVICIO
    # -------------------------------------------------------------

    def test_no_permite_plan_de_otro_tipo_de_servicio(self):
        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan_2.pk,
                "service_number": 1,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "plan",
            (
                "El plan seleccionado no pertenece "
                "al tipo de servicio elegido."
            ),
        )

        self.assertEqual(
            Subscription.objects.count(),
            0,
        )

    # -------------------------------------------------------------
    # DUPLICADOS
    # -------------------------------------------------------------

    def test_no_permite_numero_de_servicio_duplicado(self):
        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            service_number=1,
            status=Subscription.Status.PRESALE,
        )

        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 1,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "service_number",
            (
                "El cliente ya tiene registrado este "
                "número de servicio para el tipo de "
                "servicio seleccionado."
            ),
        )

        self.assertEqual(
            Subscription.objects.count(),
            1,
        )

    # -------------------------------------------------------------
    # NÚMERO DE SERVICIO
    # -------------------------------------------------------------

    def test_numero_de_servicio_debe_ser_mayor_o_igual_a_uno(self):
        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 0,
                "billing_cycle": 1,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "service_number",
            "El número de servicio debe ser mayor o igual a 1.",
        )

        self.assertEqual(
            Subscription.objects.count(),
            0,
        )

    # -------------------------------------------------------------
    # CICLO DE FACTURACIÓN
    # -------------------------------------------------------------

    def test_ciclo_de_facturacion_puede_quedar_vacio(self):
        response = self.client.post(
            self.subscription_url,
            {
                "address": self.address.pk,
                "service_type": self.service_type.pk,
                "plan": self.plan.pk,
                "service_number": 1,
                "billing_cycle": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        subscription = Subscription.objects.get(
            customer=self.customer,
            service_type=self.service_type,
            service_number=1,
        )

        self.assertIsNone(
            subscription.billing_cycle
        )