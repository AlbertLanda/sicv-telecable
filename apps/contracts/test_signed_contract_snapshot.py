import tempfile
from datetime import date
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image as PILImage, ImageDraw

from apps.contracts.models import Contract, ContractSignature
from apps.contracts.signatures import firmar_contrato
from apps.work_orders.tests.base import WorkOrderTestCase


def firma_png():
    canvas = PILImage.new("RGBA", (500, 160), (255, 255, 255, 0))
    ImageDraw.Draw(canvas).line(
        [(20, 120), (220, 25), (470, 110)],
        fill=(0, 0, 0, 255),
        width=5,
    )
    output = BytesIO()
    canvas.save(output, format="PNG")
    return SimpleUploadedFile(
        "firma.png",
        output.getvalue(),
        content_type="image/png",
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="sicv-contract-snapshot-"))
class SignedContractSnapshotTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.contract = Contract.objects.create(
            contract_number="CONT-SNAPSHOT-1",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=date(2026, 9, 23),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

    def test_firmar_archiva_pdf_hash_y_ancla(self):
        order = self.create_order_in_progress()

        firma = firmar_contrato(
            self.contract,
            firma_png(),
            usuario=self.technician,
            orden=order,
        )

        self.assertTrue(firma.signed_pdf.name)
        self.assertEqual(len(firma.signed_pdf_sha256), 64)
        self.assertIsNotNone(firma.signed_pdf_created_at)
        self.assertGreater(firma.document_anchor.get("ancho", 0), 0)

    def test_la_descarga_firmada_no_cambia_si_cambia_el_cliente(self):
        order = self.create_order_in_progress()
        firmar_contrato(
            self.contract,
            firma_png(),
            usuario=self.technician,
            orden=order,
        )

        self.client.force_login(self.atc_user)
        url = reverse(
            "contracts:contract_document",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(url)
        original = b"".join(response.streaming_content)

        self.customer.first_name = "Nombre cambiado después de firmar"
        self.customer.save(update_fields=["first_name"])

        response = self.client.get(url)
        despues = b"".join(response.streaming_content)

        self.assertEqual(original, despues)

    def test_backend_rechaza_una_firma_fuera_de_la_hoja(self):
        order = self.create_order_in_progress()

        with self.assertRaises(ValidationError):
            firmar_contrato(
                self.contract,
                firma_png(),
                usuario=self.technician,
                orden=order,
                colocacion={"x": 999999, "y": 0, "ancho": 120},
            )

        self.assertFalse(
            ContractSignature.objects.filter(contract=self.contract).exists()
        )

    def test_no_admite_dos_contratos_activos_para_la_misma_suscripcion(self):
        segundo = Contract(
            contract_number="CONT-SNAPSHOT-2",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=date(2026, 9, 23),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            segundo.full_clean()
