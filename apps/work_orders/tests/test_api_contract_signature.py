"""La contrata del abonado firmada desde el móvil del técnico.

El contrato se firma donde está el abonado. El canal del técnico entrega el
mismo documento que imprime SICV y recoge encima la firma, así que estas
pruebas fijan las tres cosas que distinguen ese canal del de oficina: que el
PDF llegue por token, que solo se pueda firmar durante la atención y que lo
firmado sea del contrato y no de la orden por la que se entró.
"""

import json
import tempfile
from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image as PILImage, ImageDraw
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.contracts.models import Contract, ContractSignature
from apps.work_orders.models import WorkOrder
from apps.work_orders.tests.base import WorkOrderTestCase


def trazo_png(ancho=600, alto=200):
    """Un PNG transparente, como el que entrega el lienzo del portal."""

    lienzo = PILImage.new("RGBA", (ancho, alto), (255, 255, 255, 0))
    ImageDraw.Draw(lienzo).line(
        [(20, alto - 40), (ancho // 2, 30), (ancho - 20, alto - 50)],
        fill=(16, 24, 64, 255),
        width=6,
    )

    archivo = BytesIO()
    lienzo.save(archivo, format="PNG")

    return SimpleUploadedFile(
        "firma.png",
        archivo.getvalue(),
        content_type="image/png",
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="sicv-firmas-api-"))
class TechnicianContractSignatureAPITests(WorkOrderTestCase):
    """El apartado Contrata del portal, visto desde la API que lo sostiene."""

    def setUp(self):
        super().setUp()

        self.api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        self.contract = Contract.objects.create(
            contract_number="CONT-000009",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=date(2026, 9, 14),
            status=Contract.Status.ACTIVE,
        )

    def url(self, name, order):
        return reverse(f"work_orders_api:{name}", args=[order.pk])

    def firmar(self, order, imagen=None):
        return self.api.post(
            self.url("contract_signature", order),
            {"image": imagen or trazo_png()},
            format="multipart",
        )

    # -----------------------------------------------------------------
    # QUÉ ÓRDENES TIENEN CONTRATA
    # -----------------------------------------------------------------

    def test_la_instalacion_publica_la_contrata_del_abonado(self):
        order = self.create_assigned_order()

        response = self.api.get(self.url("contract", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["available"])
        self.assertEqual(response.data["contract"]["number"], "CONT-000009")
        self.assertIsNone(response.data["signature"])

    def test_una_orden_que_no_es_instalacion_no_trae_contrata(self):
        """Un corte no firma nada: lo que se firma es el alta del servicio."""

        order = self.create_assigned_order(order_type=self.cut_type)

        response = self.api.get(self.url("contract", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["available"])
        self.assertFalse(response.data["can_sign"])

    def test_una_instalacion_sin_contrato_registrado_lo_dice(self):
        """No es un error del técnico: es una venta sin contrato en SICV."""

        self.contract.delete()
        order = self.create_assigned_order()

        response = self.api.get(self.url("contract", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["available"])
        self.assertIn("contrata", response.data["detail"])

    def test_la_orden_de_otro_tecnico_no_existe_para_este(self):
        order = self.create_order()
        order.assign_technician(
            technician=self.other_technician,
            assigned_by=self.supervisor,
        )

        response = self.api.get(self.url("contract", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sin_token_no_hay_contrata(self):
        order = self.create_assigned_order()

        anonimo = APIClient()
        response = anonimo.get(self.url("contract", order))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -----------------------------------------------------------------
    # EL DOCUMENTO
    # -----------------------------------------------------------------

    def test_el_tecnico_recibe_el_contrato_en_pdf(self):
        """El mismo documento de SICV, por el canal que el técnico sí tiene."""

        order = self.create_assigned_order()

        response = self.api.get(self.url("contract_document", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))

    def test_el_documento_sigue_disponible_con_la_orden_cerrada(self):
        """A ese domicilio ya no se vuelve: lo firmado tiene que poder mirarse."""

        order = self.create_order_in_progress()
        self.firmar(order)

        order.status = WorkOrder.Status.ATTENDED
        order.save(update_fields=["status"])

        response = self.api.get(self.url("contract_document", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_una_orden_sin_contrata_no_entrega_documento(self):
        order = self.create_assigned_order(order_type=self.cut_type)

        response = self.api.get(self.url("contract_document", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -----------------------------------------------------------------
    # LA FIRMA
    # -----------------------------------------------------------------

    def test_el_abonado_firma_durante_la_atencion(self):
        order = self.create_order_in_progress()

        response = self.firmar(order)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["signature"]["signer_name"],
            str(self.customer),
        )

        firma = ContractSignature.objects.get(contract=self.contract)
        self.assertEqual(firma.work_order, order)
        self.assertEqual(firma.captured_by, self.technician)

    def test_no_se_firma_antes_de_iniciar_la_atencion(self):
        """Mismo límite que la ficha técnica y las evidencias."""

        order = self.create_assigned_order()

        response = self.firmar(order)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(ContractSignature.objects.exists())

    def test_no_se_firma_con_la_orden_ya_cerrada(self):
        order = self.create_order_in_progress()
        order.status = WorkOrder.Status.ATTENDED
        order.save(update_fields=["status"])

        response = self.firmar(order)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_volver_a_firmar_reemplaza_la_firma_anterior(self):
        order = self.create_order_in_progress()

        self.firmar(order)
        self.firmar(order, trazo_png(ancho=400, alto=150))

        self.assertEqual(ContractSignature.objects.count(), 1)

    def test_rechazar_la_firma_la_borra(self):
        order = self.create_order_in_progress()
        self.firmar(order)

        response = self.api.delete(self.url("contract_signature", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["signature"])
        self.assertFalse(ContractSignature.objects.exists())

    def test_la_firma_tiene_que_ser_un_dibujo(self):
        order = self.create_order_in_progress()

        response = self.api.post(
            self.url("contract_signature", order),
            {
                "image": SimpleUploadedFile(
                    "firma.png",
                    b"esto no es una imagen",
                    content_type="image/png",
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ContractSignature.objects.exists())

    def test_la_firma_no_llega_en_un_formato_con_fondo(self):
        """El PNG transparente es lo que deja ver la línea del contrato."""

        order = self.create_order_in_progress()

        con_fondo = BytesIO()
        PILImage.new("RGB", (400, 120), (255, 255, 255)).save(
            con_fondo,
            format="JPEG",
        )

        response = self.api.post(
            self.url("contract_signature", order),
            {
                "image": SimpleUploadedFile(
                    "firma.jpg",
                    con_fondo.getvalue(),
                    content_type="image/jpeg",
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_el_pdf_viaja_con_el_hueco_donde_va_la_firma(self):
        """El visor coloca el trazo donde lo diga este PDF, no otro."""

        order = self.create_assigned_order()

        response = self.api.get(self.url("contract_document", order))
        b"".join(response.streaming_content)

        hueco = json.loads(response["X-Contrata-Ancla"])

        self.assertEqual(hueco["pagina"], 4)
        self.assertGreater(hueco["ancho"], 0)
        self.assertIn("pagina_alto", hueco)

    def test_el_tecnico_puede_mover_y_agrandar_la_firma(self):
        order = self.create_order_in_progress()

        response = self.api.post(
            self.url("contract_signature", order),
            {
                "image": trazo_png(),
                "offset_x": "15.5",
                "offset_y": "8.25",
                "width": "140",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        firma = ContractSignature.objects.get(contract=self.contract)
        self.assertEqual(firma.offset_x, 15.5)
        self.assertEqual(firma.offset_y, 8.25)
        self.assertEqual(firma.width, 140)

    def test_una_firma_sin_ajuste_la_coloca_el_papel(self):
        order = self.create_order_in_progress()

        self.firmar(order)

        firma = ContractSignature.objects.get(contract=self.contract)
        self.assertIsNone(firma.colocacion)

    # -----------------------------------------------------------------
    # VOLVER A COGER UNA FIRMA YA REGISTRADA
    # -----------------------------------------------------------------

    def test_el_pdf_dice_donde_quedo_el_trazo(self):
        """Con eso el visor puede ofrecer la firma al toque.

        Sin este dato, una firma que nadie movió -la que el papel centra por
        su cuenta- no estaría en ningún campo que el navegador pueda leer.
        """

        order = self.create_order_in_progress()
        self.firmar(order)

        response = self.api.get(self.url("contract_document", order))
        b"".join(response.streaming_content)

        trazo = json.loads(response["X-Contrata-Ancla"])["trazo"]

        self.assertIsNotNone(trazo)
        self.assertGreater(trazo["ancho"], 0)
        self.assertGreater(trazo["alto"], 0)

    def test_sin_firmar_no_hay_trazo_que_coger(self):
        order = self.create_assigned_order()

        response = self.api.get(self.url("contract_document", order))
        b"".join(response.streaming_content)

        self.assertIsNone(json.loads(response["X-Contrata-Ancla"])["trazo"])

    def test_el_documento_se_puede_pedir_sin_la_firma(self):
        """Es lo que se mira mientras se arrastra: con el trazo debajo se
        verían dos firmas y solo una sería la que se va a guardar."""

        order = self.create_order_in_progress()
        self.firmar(order)

        con_firma = self.api.get(self.url("contract_document", order))
        sin_firma = self.api.get(
            f"{self.url('contract_document', order)}?sin_firma=1"
        )

        self.assertIsNone(
            json.loads(sin_firma["X-Contrata-Ancla"])["trazo"],
        )
        self.assertGreater(
            len(b"".join(con_firma.streaming_content)),
            len(b"".join(sin_firma.streaming_content)),
        )

    def test_el_tecnico_recupera_el_trazo_que_firmo_el_abonado(self):
        """Lo que se mueve es el mismo dibujo, no una copia repintada."""

        order = self.create_order_in_progress()
        self.firmar(order)

        response = self.api.get(self.url("contract_signature", order))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_sin_firma_registrada_no_hay_trazo_que_devolver(self):
        order = self.create_order_in_progress()

        response = self.api.get(self.url("contract_signature", order))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mover_la_firma_no_es_volver_a_firmarla(self):
        """El trazo y la fecha son los mismos: cambia dónde se apoya."""

        order = self.create_order_in_progress()
        self.firmar(order)

        firma = ContractSignature.objects.get(contract=self.contract)
        archivo = firma.image.name
        firmada_el = firma.signed_at

        response = self.api.patch(
            self.url("contract_signature", order),
            {"offset_x": 25, "offset_y": 12, "width": 130},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        firma.refresh_from_db()
        self.assertEqual(firma.image.name, archivo)
        self.assertEqual(firma.signed_at, firmada_el)
        self.assertEqual(firma.colocacion, {"x": 25.0, "y": 12.0, "ancho": 130.0})

    def test_no_se_mueve_una_firma_que_no_existe(self):
        order = self.create_order_in_progress()

        response = self.api.patch(
            self.url("contract_signature", order),
            {"offset_x": 10},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_se_mueve_la_firma_con_la_orden_cerrada(self):
        order = self.create_order_in_progress()
        self.firmar(order)

        order.status = WorkOrder.Status.ATTENDED
        order.save(update_fields=["status"])

        response = self.api.patch(
            self.url("contract_signature", order),
            {"offset_x": 10},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_la_firma_movida_sale_en_el_papel_donde_se_dejo(self):
        order = self.create_order_in_progress()
        self.firmar(order)

        self.api.patch(
            self.url("contract_signature", order),
            {"offset_x": 18, "offset_y": 6, "width": 120},
            format="json",
        )

        response = self.api.get(self.url("contract_document", order))
        b"".join(response.streaming_content)

        ancla = json.loads(response["X-Contrata-Ancla"])

        self.assertAlmostEqual(ancla["trazo"]["x"], 18, places=1)
        self.assertAlmostEqual(ancla["trazo"]["y"], 6, places=1)
        self.assertAlmostEqual(ancla["trazo"]["ancho"], 120, places=1)

    def test_la_firma_queda_en_el_documento_que_se_entrega(self):
        """Lo que el técnico ve después de firmar es el contrato firmado."""

        order = self.create_order_in_progress()

        sin_firma = self.api.get(self.url("contract_document", order))
        en_blanco = b"".join(sin_firma.streaming_content)

        self.firmar(order)

        con_firma = self.api.get(self.url("contract_document", order))
        firmado = b"".join(con_firma.streaming_content)

        self.assertGreater(len(firmado), len(en_blanco))

    def test_la_firma_se_recoge_en_la_orden_pero_es_del_contrato(self):
        """Por eso SICV la ve sin saber nada de la orden de instalación."""

        order = self.create_order_in_progress()
        self.firmar(order)

        self.assertTrue(
            ContractSignature.objects
            .filter(contract=self.contract)
            .exists()
        )
