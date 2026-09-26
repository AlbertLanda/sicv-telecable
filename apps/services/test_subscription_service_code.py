from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription


class SubscriptionServiceCodeTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="SCODE", name="Sede Código")
        self.zone = Zone.objects.create(branch=self.branch, name="Zona Código")
        self.customer = Customer.objects.create(
            code="SC01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="70000001",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Código",
        )
        self.service = ServiceType.objects.create(
            code="INTERNET-CODE",
            name="Internet Código",
        )
        self.plan = Plan.objects.create(
            service_type=self.service,
            code="PLAN-CODE",
            name="Plan Código",
        )

    def crear(self, numero, direccion):
        address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
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

    def test_dos_domicilios_del_mismo_abonado_tienen_codigos_distintos(self):
        primero = self.crear(1, "Jr. Uno 100")
        segundo = self.crear(2, "Jr. Dos 200")

        self.assertEqual(
            primero.service_code,
            "SC01-A0000001-INTERNET-CODE-01",
        )
        self.assertEqual(
            segundo.service_code,
            "SC01-A0000001-INTERNET-CODE-02",
        )
        self.assertNotEqual(primero.service_code, segundo.service_code)

    def test_numero_de_servicio_eliminado_vuelve_a_quedar_libre(self):
        self.crear(1, "Jr. Uno 100")
        segundo = self.crear(2, "Jr. Dos 200")
        self.crear(3, "Jr. Tres 300")

        segundo.delete()

        self.assertEqual(
            Subscription.next_service_number(
                self.customer,
                self.service,
            ),
            2,
        )

    def test_codigo_para_otra_sede_usa_prefijo_destino_sin_duplicar_cliente(self):
        subscription = self.crear(1, "Jr. Uno 100")
        destination = Branch.objects.get(code="JAUJA")
        original_customer_code = self.customer.code

        relocated_code = subscription.build_service_code_for_branch(
            destination
        )

        self.assertTrue(relocated_code.startswith("JA01-A"))
        self.assertTrue(relocated_code.endswith("-INTERNET-CODE-01"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.code, original_customer_code)

