from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.organization.models import Branch, Zone
from apps.work_orders.nap_catalog import NetworkAccessPoint


class OperationalCatalogCommandTests(TestCase):
    def setUp(self):
        self.jauja = Branch.objects.get(code="JAUJA")
        self.huancayo = Branch.objects.get(code="HUANCAYO")
        self.oroya = Branch.objects.get(code="OROYA")

    def _load(self, *args):
        call_command(
            "cargar_catalogos_operativos",
            *args,
            stdout=StringIO(),
        )

    def test_loads_the_official_zone_and_nap_catalogs(self):
        self._load()

        self.assertEqual(
            Zone.objects.filter(branch=self.jauja, is_active=True).count(),
            25,
        )
        self.assertEqual(
            Zone.objects.filter(branch=self.huancayo, is_active=True).count(),
            9,
        )
        self.assertEqual(
            Zone.objects.filter(branch=self.oroya, is_active=True).count(),
            41,
        )

        self.assertEqual(
            NetworkAccessPoint.objects.filter(
                branch=self.jauja,
                is_active=True,
            ).count(),
            1113,
        )
        self.assertEqual(
            NetworkAccessPoint.objects.filter(
                branch=self.huancayo,
                is_active=True,
            ).count(),
            830,
        )
        self.assertEqual(
            NetworkAccessPoint.objects.filter(
                branch=self.oroya,
                is_active=True,
            ).count(),
            590,
        )

        self.assertTrue(
            NetworkAccessPoint.objects.filter(
                branch=self.jauja,
                code="2348308",
                name="JAUJA - 4 DE ENERO - 2348308",
            ).exists()
        )
        self.assertTrue(
            NetworkAccessPoint.objects.filter(
                branch=self.huancayo,
                code="2642458",
                name="TAMBO - COVICA - 2642458",
            ).exists()
        )
        self.assertTrue(
            NetworkAccessPoint.objects.filter(
                branch=self.oroya,
                code="2866311",
                name="LA OROYA - ALTO MARCAVALLE - 2866311",
            ).exists()
        )

    def test_command_is_idempotent(self):
        self._load()
        first_counts = (
            Zone.objects.count(),
            NetworkAccessPoint.objects.count(),
        )

        self._load()
        second_counts = (
            Zone.objects.count(),
            NetworkAccessPoint.objects.count(),
        )

        self.assertEqual(second_counts, first_counts)
        self.assertEqual(second_counts, (75, 2533))

    def test_dry_run_does_not_persist_catalogs(self):
        self._load("--dry-run")

        self.assertEqual(Zone.objects.count(), 0)
        self.assertEqual(NetworkAccessPoint.objects.count(), 0)
