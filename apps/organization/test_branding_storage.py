"""Los documentos leen MEDIA sin necesitar disco ni acceso público al blob."""

from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.base import ContentFile, File
from django.core.files.storage import Storage, default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas

from apps.contracts.document import sello_de_la_empresa
from apps.contracts.pdf import _logotipo
from apps.organization import branding
from apps.payments import pdf


class PrivateStorage(Storage):
    def __init__(self):
        self.files = {}
        self.opened = []

    def _save(self, name, content):
        self.files[name] = content.read()
        return name

    def exists(self, name):
        return name in self.files

    def listdir(self, path):
        assert path == ""
        return [], [name for name in self.files if "/" not in name]

    def _open(self, name, mode="rb"):
        source = File(BytesIO(self.files[name]), name=name)
        self.opened.append(source)
        return source

    def path(self, name):
        raise AssertionError("El backend privado no ofrece rutas locales")

    def url(self, name):
        raise AssertionError("El documento debe leer el archivo, no su URL")


class BrandingStorageTests(SimpleTestCase):
    def setUp(self):
        # Recrear el backend en cada prueba evita compartir imágenes en memoria.
        self.storage_override = override_settings(STORAGES={
            "default": {"BACKEND": "apps.organization.test_branding_storage.PrivateStorage"},
        })
        self.storage_override.enable()
        self.addCleanup(self.storage_override.disable)

    def save_image(self, name, *, blank=False, transparent=False):
        image = Image.new("RGBA" if transparent else "RGB", (100, 100),
                          (255, 255, 255, 0) if transparent else "white")
        if not blank:
            ImageDraw.Draw(image).rectangle((20, 20, 79, 79), fill="blue")
        content = BytesIO()
        image.save(content, format="PNG")
        data = content.getvalue()
        default_storage.save(name, ContentFile(data))
        return data

    def test_remote_logo_preserves_selection_and_trims_in_memory(self):
        self.save_image("telecable-logo.jpg")
        self.save_image("telecable-logo (1).png")
        original = self.save_image("TELECABLE-LOGO.PNG")
        logo = branding.buscar_logo()
        self.assertIsNotNone(logo)
        self.assertEqual(logo.name, "TELECABLE-LOGO.PNG")
        with Image.open(branding.logo_sin_margen(logo)) as trimmed:
            self.assertEqual(trimmed.size, (60, 60))
        with default_storage.open(logo.name) as source:
            self.assertEqual(source.read(), original)
        self.assertTrue(all(source.closed for source in default_storage.opened))

    def test_white_remote_logo_is_still_a_readable_image(self):
        self.save_image("telecable-logo.png", blank=True)
        logo = branding.buscar_logo()
        self.assertIsNotNone(logo)
        with Image.open(branding.logo_sin_margen(logo)) as unchanged:
            self.assertEqual(unchanged.size, (100, 100))

    def test_missing_logo_does_not_search_nested_customer_files(self):
        self.save_image("customers/telecable-logo.png")
        self.assertIsNone(branding.buscar_logo())
        self.assertEqual(pdf._logo(10), "")

    def test_receipt_and_contract_embed_private_logos(self):
        self.save_image("telecable-logo.png")
        self.save_image("Logo-telecable-2.png")
        output = BytesIO()
        canvas = Canvas(output)
        logo = pdf._logo(10)
        self.assertNotEqual(logo, "")
        logo.drawOn(canvas, 10, 10)
        _logotipo(canvas, 800)
        canvas.save()
        self.assertTrue(output.getvalue().startswith(b"%PDF-"))
        self.assertIn(b"/Subtype /Image", output.getvalue())
        with patch.object(canvas, "drawImage") as draw:
            _logotipo(canvas, 800)
        draw.assert_called_once()

    def test_company_signature_reads_exact_bytes_and_keeps_transparency(self):
        data = self.save_image("firma_INV.png", transparent=True)
        self.assertEqual(sello_de_la_empresa(SimpleNamespace(code="INV")), data)
        self.assertIsNone(sello_de_la_empresa(SimpleNamespace(code="OTHER")))

    def test_diagnostic_reads_the_configured_storage(self):
        self.save_image("telecable-logo.png")
        output = StringIO()
        call_command("comprobar_logo", stdout=output)
        self.assertIn("Logotipo listo: telecable-logo.png (100x100 px)", output.getvalue())

    def test_diagnostic_missing_logo_does_not_list_customer_files(self):
        default_storage.save("documento-privado.pdf", ContentFile(b"private"))
        output = StringIO()
        call_command("comprobar_logo", stdout=output)
        self.assertIn("No hay logotipo", output.getvalue())
        self.assertNotIn("documento-privado", output.getvalue())

    def test_unavailable_storage_is_distinguished_from_missing_image(self):
        with patch.object(default_storage, "listdir", side_effect=OSError("secret-token")):
            self.assertEqual(pdf._logo(10), "")
            with patch("apps.contracts.pdf.ImageReader") as reader:
                _logotipo(Canvas(BytesIO()), 800)
            reader.assert_not_called()
            with self.assertRaises(CommandError) as caught:
                call_command("comprobar_logo", stdout=StringIO())
        self.assertNotIn("secret-token", str(caught.exception))

    def test_failed_signature_read_is_not_treated_as_missing_signature(self):
        self.save_image("firma_INV.png", transparent=True)
        with patch.object(default_storage, "open", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                sello_de_la_empresa(SimpleNamespace(code="INV"))

    def test_corrupt_image_is_reported_without_stopping_receipt(self):
        default_storage.save("telecable-logo.png", ContentFile(b"broken"))
        self.assertEqual(pdf._logo(10), "")
        with self.assertRaises(CommandError):
            call_command("comprobar_logo", stdout=StringIO())
