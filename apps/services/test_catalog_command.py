from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.organization.models import Zone
from apps.services.models import (
    CommercialCoverageRule,
    InstallationMaterialRule,
    Plan,
    PlanTariff,
    ServiceType,
)


class CommercialCatalogCommandTests(TestCase):
    def test_command_loads_only_confirmed_catalog(self):
        output = StringIO()

        call_command("cargar_catalogo_comercial", stdout=output)

        self.assertEqual(ServiceType.objects.filter(code__in=["INTERNET", "CABLE", "DUO"]).count(), 3)
        self.assertEqual(Plan.objects.count(), 24)
        self.assertEqual(PlanTariff.objects.filter(plan__code="CABLE-GENERAL").count(), 2)
        self.assertEqual(CommercialCoverageRule.objects.count(), 1)
        self.assertEqual(InstallationMaterialRule.objects.count(), 12)

        # Las zonas no se inventan: se cargaran cuando ATC valide la
        # nomenclatura geografica completa.
        self.assertEqual(Zone.objects.count(), 0)

        self.assertIn("Catalogo comercial cargado correctamente", output.getvalue())

    def test_command_is_idempotent(self):
        call_command("cargar_catalogo_comercial", stdout=StringIO())
        first_counts = (
            ServiceType.objects.count(),
            Plan.objects.count(),
            PlanTariff.objects.count(),
            CommercialCoverageRule.objects.count(),
            InstallationMaterialRule.objects.count(),
        )

        call_command("cargar_catalogo_comercial", stdout=StringIO())
        second_counts = (
            ServiceType.objects.count(),
            Plan.objects.count(),
            PlanTariff.objects.count(),
            CommercialCoverageRule.objects.count(),
            InstallationMaterialRule.objects.count(),
        )

        self.assertEqual(second_counts, first_counts)

    def test_dry_run_rolls_back_everything(self):
        call_command("cargar_catalogo_comercial", "--dry-run", stdout=StringIO())

        self.assertFalse(ServiceType.objects.filter(code__in=["INTERNET", "CABLE", "DUO"]).exists())
        self.assertEqual(Plan.objects.count(), 0)
        self.assertEqual(PlanTariff.objects.count(), 0)
        self.assertEqual(CommercialCoverageRule.objects.count(), 0)
        self.assertEqual(InstallationMaterialRule.objects.count(), 0)
