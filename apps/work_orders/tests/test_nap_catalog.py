from pathlib import Path
from tempfile import NamedTemporaryFile

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.organization.models import Branch
from apps.work_orders.models import WorkOrderFieldSheet
from apps.work_orders.nap_catalog import NetworkAccessPoint
from apps.work_orders.tests.base import WorkOrderTestCase


class TechnicianNapCatalogTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.technician)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def url(self, name, order):
        return reverse(f"work_orders_api:{name}", args=[order.pk])

    def test_search_filters_naps_by_order_branch_and_query(self):
        order = self.create_assigned_order()
        matching = NetworkAccessPoint.objects.create(
            legacy_id=10390,
            branch=self.branch,
            code="2866741",
            name="SAN JERONIMO - CONCEPCION - 2866741",
        )
        NetworkAccessPoint.objects.create(
            legacy_id=10391,
            branch=self.branch,
            code="2866742",
            name="SAN JERONIMO - CONCEPCION - 2866742",
        )
        other_branch = Branch.objects.create(code="OTR01", name="Otra sede")
        NetworkAccessPoint.objects.create(
            legacy_id=7138,
            branch=other_branch,
            code="2866387",
            name="LA OROYA - ALTO PERÚ - NORMANKING - 2866387",
        )

        response = self.api.get(self.url("nap_search", order), {"q": "2866741"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["catalog_enabled"])
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], matching.pk)
        self.assertEqual(response.data["results"][0]["code"], "2866741")

    def test_field_sheet_rejects_free_text_when_branch_catalog_is_enabled(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        NetworkAccessPoint.objects.create(
            branch=self.branch,
            code="2642865",
            name="EL TAMBO - SAN AGUSTIN DE CAJAS - SECTOR 04 - 2642865",
        )

        response = self.api.patch(
            self.url("field_sheet", order),
            {"nap": "NAP INVENTADA", "terminal": "8"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WorkOrderFieldSheet.objects.filter(work_order=order).exists())

    def test_field_sheet_accepts_exact_nap_selected_from_branch_catalog(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        nap = NetworkAccessPoint.objects.create(
            legacy_id=10390,
            branch=self.branch,
            code="2866741",
            name="SAN JERONIMO - CONCEPCION - 2866741",
        )

        response = self.api.patch(
            self.url("field_sheet", order),
            {"nap": nap.name, "terminal": "5"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sheet = WorkOrderFieldSheet.objects.get(work_order=order)
        self.assertEqual(sheet.nap, nap.name)
        self.assertEqual(sheet.terminal, "5")

    def test_terminal_accepts_01_to_16_and_uses_historical_storage_format(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")

        response = self.api.patch(
            self.url("field_sheet", order),
            {"terminal": "08"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sheet = WorkOrderFieldSheet.objects.get(work_order=order)
        self.assertEqual(sheet.terminal, "8")

        response = self.api.patch(
            self.url("field_sheet", order),
            {"terminal": "16"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sheet.refresh_from_db()
        self.assertEqual(sheet.terminal, "16")

    def test_terminal_rejects_values_outside_01_to_16(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")

        response = self.api.patch(
            self.url("field_sheet", order),
            {"terminal": "17"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("terminal", response.data)
        self.assertFalse(WorkOrderFieldSheet.objects.filter(work_order=order).exists())

    def test_existing_legacy_nap_can_be_kept_while_other_fields_change(self):
        order = self.create_assigned_order()
        self.api.post(self.url("start", order), {}, format="json")
        WorkOrderFieldSheet.objects.create(
            work_order=order,
            nap="NAP-LEGADA-01",
            updated_by=self.technician,
        )
        NetworkAccessPoint.objects.create(
            branch=self.branch,
            code="2642865",
            name="EL TAMBO - SAN AGUSTIN DE CAJAS - SECTOR 04 - 2642865",
        )

        response = self.api.patch(
            self.url("field_sheet", order),
            {"nap": "NAP-LEGADA-01", "terminal": "7"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sheet = WorkOrderFieldSheet.objects.get(work_order=order)
        self.assertEqual(sheet.nap, "NAP-LEGADA-01")
        self.assertEqual(sheet.terminal, "7")


class ImportNetworkAccessPointsCommandTests(TestCase):
    def setUp(self):
        # organization.0002 ya siembra las sedes reales. Reutilizarlas evita
        # crear homónimos que el propio importador debe rechazar por seguridad.
        self.huancayo = Branch.objects.get(name__iexact="Huancayo")
        self.oroya = Branch.objects.get(name__iexact="La Oroya")

    def test_import_skips_empty_incomplete_and_other_branch_rows(self):
        content = "\n".join(
            [
                "7695\t- -",
                "1216\tEL TAMBO - -",
                "7138\tLA OROYA - ALTO PERÚ - NORMANKING - 2866387",
                "10390\tSAN JERONIMO - CONCEPCION - 2866741",
                "2055\tTAMBO - COVICA - 2642458",
            ]
        )
        with NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
            handle.write(content)
            file_path = Path(handle.name)

        try:
            call_command("importar_naps", str(file_path), sede="Huancayo")
        finally:
            file_path.unlink(missing_ok=True)

        naps = NetworkAccessPoint.objects.filter(branch=self.huancayo).order_by("code")
        self.assertEqual(naps.count(), 2)
        self.assertEqual(
            set(naps.values_list("code", flat=True)),
            {"2866741", "2642458"},
        )
        self.assertFalse(NetworkAccessPoint.objects.filter(legacy_id=7138).exists())
        self.assertFalse(NetworkAccessPoint.objects.filter(legacy_id=7695).exists())
