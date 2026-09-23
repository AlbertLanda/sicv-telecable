import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.contracts.models import Contract, ContractSignature
from apps.customers.models import Customer
from apps.inventory.models import WorkOrderMaterialMovement
from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder


@override_settings(
    DEBUG=True,
    MEDIA_ROOT=tempfile.mkdtemp(prefix="sicv-demo-gerencia-test-"),
)
class DemoGerenciaCommandTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings["MEDIA_ROOT"]
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def test_prepara_dos_domicilios_con_escenario_firmado_y_firma_en_vivo(self):
        output = StringIO()

        call_command("preparar_demo_gerencia", stdout=output)

        customer = Customer.objects.get(document_number="00000000")
        self.assertEqual(customer.secondary_phone, "964123456")

        addresses = list(customer.addresses.order_by("pk"))
        self.assertEqual(len(addresses), 2)
        self.assertIsNotNone(addresses[0].map_latitude)
        self.assertIsNotNone(addresses[0].map_longitude)
        self.assertTrue(addresses[0].map_link)

        subscriptions = list(
            Subscription.objects.filter(customer=customer).order_by("service_number")
        )
        self.assertEqual(
            [subscription.service_code for subscription in subscriptions],
            [
                "JA01-A0000001-DUO-01",
                "JA01-A0000001-DUO-02",
            ],
        )

        signed_contract = Contract.objects.get(
            contract_number="CONT-DEMO-000001"
        )
        pending_contract = Contract.objects.get(
            contract_number="CONT-DEMO-000002"
        )

        signed_order = WorkOrder.objects.get(order_number="OT-2026-000001")
        pending_order = WorkOrder.objects.get(order_number="OT-2026-000002")

        self.assertEqual(signed_order.status, WorkOrder.Status.LIQUIDATED)
        self.assertEqual(pending_order.status, WorkOrder.Status.IN_PROGRESS)

        signed_sheet = signed_order.field_sheet
        self.assertEqual(signed_sheet.nap, "NAP-DEMO-JAUJA-01")
        self.assertEqual(signed_sheet.terminal, "08")
        self.assertEqual(signed_sheet.equipment_code, "ONU-DEMO-4GJ2")
        self.assertEqual(signed_sheet.seal_number, "PRE-DEMO-0001")

        pending_sheet = pending_order.field_sheet
        self.assertEqual(pending_sheet.nap, "NAP-DEMO-JAUJA-02")
        self.assertEqual(pending_sheet.terminal, "12")
        self.assertEqual(pending_sheet.equipment_code, "ONU-DEMO-7KQ9")
        self.assertEqual(pending_sheet.seal_number, "PRE-DEMO-0002")

        self.assertEqual(
            WorkOrderMaterialMovement.objects.filter(
                work_order=signed_order,
            ).count(),
            5,
        )
        self.assertEqual(
            WorkOrderMaterialMovement.objects.filter(
                work_order=pending_order,
            ).count(),
            5,
        )

        self.assertEqual(signed_order.evidences.count(), 3)
        self.assertEqual(pending_order.evidences.count(), 1)

        signed_signature = ContractSignature.objects.get(
            contract=signed_contract,
        )
        self.assertTrue(signed_signature.signed_pdf.name)
        self.assertEqual(len(signed_signature.signed_pdf_sha256), 64)

        self.assertFalse(
            ContractSignature.objects.filter(
                contract=pending_contract,
            ).exists()
        )

        liquidation = signed_order.liquidation
        self.assertEqual(liquidation.network_element, "NAP-DEMO-JAUJA-01")
        self.assertEqual(liquidation.network_port, "08")
        self.assertEqual(liquidation.equipment_serial, "ONU-DEMO-4GJ2")
        self.assertEqual(str(liquidation.signal_level_dbm), "-21.40")
        self.assertEqual(str(liquidation.cable_meters_used), "85.00")
        self.assertEqual(liquidation.krill_reference, "KRILL-DEMO-0001")
        self.assertEqual(liquidation.items.count(), 5)

        self.assertIn("Demo preparada correctamente", output.getvalue())
