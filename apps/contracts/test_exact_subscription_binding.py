from django.test import TestCase

from apps.contracts.forms import ContractCreateForm
from apps.contracts.subscriptions import codigo_de_suscripcion
from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription


class ExactSubscriptionBindingTests(TestCase):
    def setUp(self):
        branch = Branch.objects.create(code="CBIND", name="Sede Binding")
        zone = Zone.objects.create(branch=branch, name="Zona Binding")
        self.customer = Customer.objects.create(
            code="CB01-A0000001",
            branch=branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70000002",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Binding",
        )
        self.service = ServiceType.objects.create(
            code="INTERNET-BIND",
            name="Internet Binding",
        )
        self.plan = Plan.objects.create(
            service_type=self.service,
            code="PLAN-BIND",
            name="Plan Binding",
        )

        def crear(numero, direccion):
            address = CustomerAddress.objects.create(
                customer=self.customer,
                zone=zone,
                address=direccion,
                district="Jauja",
                is_primary=numero == 1,
            )
            return Subscription.objects.create(
                customer=self.customer,
                address=address,
                service_type=self.service,
                plan=self.plan,
                status=Subscription.Status.PRESALE,
                service_number=numero,
            )

        self.first = crear(1, "Jr. Primero 100")
        self.second = crear(2, "Jr. Segundo 200")

    def datos(self, subscription_id=None):
        data = {
            "service_type": self.service.pk,
            "plan": self.plan.pk,
            "modality": "SALE",
            "installments": 1,
            "start_date": "2026-09-23",
            "playhub_email": "",
            "playhub_phone": "",
        }
        if subscription_id is not None:
            data["subscription_id"] = str(subscription_id)
        return data

    def test_el_id_del_resumen_fija_la_suscripcion_exacta(self):
        form = ContractCreateForm(
            data=self.datos(self.second.pk),
            customer=self.customer,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.subscription_resuelta, self.second)
        self.assertEqual(form.instance.subscription, self.second)
        self.assertEqual(
            codigo_de_suscripcion(self.second),
            self.second.service_code,
        )

    def test_sin_id_no_adivina_entre_dos_domicilios_del_mismo_plan(self):
        form = ContractCreateForm(
            data=self.datos(),
            customer=self.customer,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Hay más de una suscripción disponible",
            " ".join(form.non_field_errors()),
        )
