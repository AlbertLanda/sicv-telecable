"""
Coherencia entre el catálogo sembrado y las reglas de cobertura sembradas.

Las dos cosas salen del mismo comando, y nada verificaba que encajaran. Así
pasó desapercibido que al partir la línea 2026 en cuatro niveles la regla de
La Oroya —«Estándar obligatoria», escrita cuando los ocho planes eran
Estándar— dejara seis de ellos sin poder venderse en esa sede.

La suite estaba verde: el test de la regla `REQUIRED` construye sus propios
datos, así que comprueba el mecanismo pero no el catálogo real. Estas pruebas
cubren justo eso: que lo que el comando siembra se pueda vender donde debe.
"""

from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch
from apps.services.commercial import validate_plan_commercial_availability
from apps.services.models import CommercialCoverageRule, Plan


# Líneas anteriores a 2026. No se venden en La Oroya y eso es deliberado.
RETIRED_LINES = (Plan.Category.ECONOMIC, Plan.Category.SUPER_ECONOMIC)

# Los niveles con los que se vende la línea 2026.
LINE_2026_TIERS = (
    Plan.Category.TELECABLE,
    Plan.Category.STANDARD,
    Plan.Category.PREMIUM,
    Plan.Category.PREMIUM_PLUS,
)


class SeededCatalogCoverageTests(TestCase):
    """El catálogo del comando contra las reglas del mismo comando."""

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_catalogo_comercial", stdout=StringIO())

        cls.oroya = Branch.objects.get(code="OROYA")

    def address_in(self, branch):
        """Un domicilio de esa sede, sin zona: aplica la regla general.

        No se guarda porque la validación solo lee la sede del abonado y la
        zona del domicilio; persistirlo obligaría a inventar un cliente real
        en el padrón de pruebas.
        """
        return CustomerAddress(
            customer=Customer(branch=branch, code="SIM-COBERTURA"),
            zone=None,
            address="Domicilio de prueba",
            district=branch.name,
        )

    def sellable_in(self, branch, plan):
        try:
            validate_plan_commercial_availability(
                plan=plan, address=self.address_in(branch)
            )
        except ValidationError:
            return False

        return True

    def plans_2026(self):
        return Plan.objects.filter(
            generation=2026,
            commercial_category__in=LINE_2026_TIERS,
            is_active=True,
        ).order_by("service_type__code", "speed_mbps")

    def test_every_2026_tier_is_sellable_in_oroya(self):
        """Los cuatro niveles de 2026 se venden en La Oroya.

        Es la regresión concreta: con la regla anterior solo pasaba Estándar,
        y Telecable, Premium y Premium Plus quedaban bloqueados sin que nadie
        lo hubiera decidido.
        """
        plans = list(self.plans_2026())

        self.assertTrue(plans, "El catálogo no sembró planes de la línea 2026.")

        for plan in plans:
            with self.subTest(plan=plan.code):
                self.assertTrue(
                    self.sellable_in(self.oroya, plan),
                    f"{plan.name} no se puede vender en La Oroya.",
                )

    def test_the_four_tiers_are_actually_represented(self):
        """El catálogo cubre los cuatro niveles, no solo uno.

        Sin esto la prueba anterior pasaría con un catálogo que hubiera vuelto
        a tener todo en Estándar, que es el estado que se quiso superar.
        """
        seeded = set(
            self.plans_2026().values_list("commercial_category", flat=True)
        )

        self.assertEqual(seeded, set(LINE_2026_TIERS))

    def test_the_older_lines_stay_blocked_in_oroya(self):
        """Lo que la regla de La Oroya sí debe seguir impidiendo."""
        older = Plan.objects.filter(
            generation=2026,
            commercial_category__in=RETIRED_LINES,
            is_active=True,
        )

        self.assertTrue(older.exists(), "No hay planes de línea anterior que probar.")

        for plan in older:
            with self.subTest(plan=plan.code):
                self.assertFalse(
                    self.sellable_in(self.oroya, plan),
                    f"{plan.name} no debería venderse en La Oroya.",
                )

    def test_the_other_branches_have_no_restriction_yet(self):
        """Jauja y Huancayo no tienen reglas zonales confirmadas todavía.

        Sin configuración el flujo queda permitido a propósito, para poder
        cargar catálogos históricos por partes. Se fija para que el día que se
        añada una regla se note aquí y no en una venta.
        """
        for code in ("JAUJA", "HUANCAYO"):
            branch = Branch.objects.get(code=code)

            for plan in self.plans_2026():
                with self.subTest(sede=code, plan=plan.code):
                    self.assertTrue(self.sellable_in(branch, plan))

    def test_the_retired_required_rule_is_kept_as_history(self):
        """La regla vieja se desactiva, no se borra.

        El histórico tiene que poder explicar qué se vendía antes en esa sede;
        borrarla dejaría el cambio sin rastro.
        """
        retired = CommercialCoverageRule.objects.filter(
            generation=2026,
            branch=self.oroya,
            commercial_category=Plan.Category.STANDARD,
            availability=CommercialCoverageRule.Availability.REQUIRED,
        )

        for rule in retired:
            with self.subTest(rule=rule.pk):
                self.assertFalse(rule.is_active)

    def test_running_the_command_twice_keeps_the_coverage_coherent(self):
        """Recargar el catálogo no debe reactivar la regla retirada."""
        call_command("cargar_catalogo_comercial", stdout=StringIO())

        for plan in self.plans_2026():
            with self.subTest(plan=plan.code):
                self.assertTrue(self.sellable_in(self.oroya, plan))
