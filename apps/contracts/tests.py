from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription

from .models import Contract


User = get_user_model()


class ContractCreateTests(TestCase):

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

        self.client.login(
            username="colaborador",
            password="123",
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
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Principal 123",
            district="Huancayo",
            is_primary=True,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        self.create_url = reverse(
            "contracts:contract_create",
            kwargs={
                "customer_pk": self.customer.pk,
            },
        )

    # -------------------------------------------------------------
    # ACCESO
    # -------------------------------------------------------------

    def test_usuario_autenticado_puede_abrir_formulario(self):
        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 200)

    def test_usuario_anonimo_no_puede_crear_contrato(self):
        self.client.logout()

        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 302)

    # -------------------------------------------------------------
    # FORMULARIO
    # -------------------------------------------------------------

    def test_formulario_solo_muestra_suscripciones_presale_del_cliente(self):
        response = self.client.get(self.create_url)

        form = response.context["form"]

        subscriptions = list(
            form.fields["subscription"].queryset
        )

        self.assertIn(
            self.subscription,
            subscriptions,
        )

    def test_formulario_no_muestra_suscripcion_activa(self):
        active_subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=2,
        )

        response = self.client.get(self.create_url)

        subscriptions = list(
            response.context["form"]
            .fields["subscription"]
            .queryset
        )

        self.assertNotIn(
            active_subscription,
            subscriptions,
        )

    def test_formulario_no_muestra_suscripcion_de_otro_cliente(self):
        other_customer = Customer.objects.create(
            code="CLI-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="87654321",
            person_type=Customer.PersonType.NATURAL,
            first_name="Maria",
            paternal_surname="Lopez",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Jr. Secundario 456",
            district="Huancayo",
            is_primary=True,
        )

        other_subscription = Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        response = self.client.get(self.create_url)

        subscriptions = list(
            response.context["form"]
            .fields["subscription"]
            .queryset
        )

        self.assertNotIn(
            other_subscription,
            subscriptions,
        )

    # -------------------------------------------------------------
    # CREACIÓN CORRECTA
    # -------------------------------------------------------------

    def test_crear_contrato_desde_suscripcion_presale(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "Contrato de prueba",
            },
        )

        self.assertEqual(response.status_code, 302)

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.customer,
            self.customer,
        )

        self.assertEqual(
            contract.subscription,
            self.subscription,
        )

        self.assertEqual(
            contract.start_date,
            date(2026, 8, 20),
        )

        self.assertEqual(
            contract.notes,
            "Contrato de prueba",
        )

    # -------------------------------------------------------------
    # NÚMERO AUTOMÁTICO
    # -------------------------------------------------------------

    def test_numero_de_contrato_se_genera_automaticamente(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.contract_number,
            "CONT-000001",
        )

    # -------------------------------------------------------------
    # ESTADO INICIAL
    # -------------------------------------------------------------

    def test_contrato_se_crea_activo(self):
        self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.status,
            Contract.Status.ACTIVE,
        )

        self.assertTrue(contract.is_active)

    # -------------------------------------------------------------
    # VALIDACIÓN DE FECHAS
    # -------------------------------------------------------------

    def test_fecha_final_no_puede_ser_anterior_a_fecha_inicio(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "2026-08-19",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "end_date",
            (
                "La fecha de finalización no puede "
                "ser anterior a la fecha de inicio."
            ),
        )

        self.assertFalse(
            Contract.objects.filter(
                subscription=self.subscription
            ).exists()
        )

    # -------------------------------------------------------------
    # CONTRATO DUPLICADO
    # -------------------------------------------------------------

    def test_no_permite_segundo_contrato_activo_para_misma_suscripcion(self):
        Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 8, 1),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "subscription",
            (
                "La suscripción seleccionada ya tiene "
                "un contrato activo registrado."
            ),
        )

        self.assertEqual(
            Contract.objects.filter(
                subscription=self.subscription,
                is_active=True,
            ).count(),
            1,
        )

    # -------------------------------------------------------------
    # SUSCRIPCIÓN DE OTRO CLIENTE
    # -------------------------------------------------------------

    def test_no_permite_suscripcion_de_otro_cliente(self):
        other_customer = Customer.objects.create(
            code="CLI-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="87654321",
            person_type=Customer.PersonType.NATURAL,
            first_name="Maria",
            paternal_surname="Lopez",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Jr. Secundario 456",
            district="Huancayo",
            is_primary=True,
        )

        other_subscription = Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        response = self.client.post(
            self.create_url,
            {
                "subscription": other_subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "subscription",
            "Escoja una opción válida. Esa opción no está entre las disponibles.",
        )

        self.assertEqual(
            Contract.objects.count(),
            0,
        )

    # -------------------------------------------------------------
    # SUSCRIPCIÓN NO PRESALE
    # -------------------------------------------------------------

    def test_no_permite_contrato_para_suscripcion_activa(self):
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save()

        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Contract.objects.count(),
            0,
        )