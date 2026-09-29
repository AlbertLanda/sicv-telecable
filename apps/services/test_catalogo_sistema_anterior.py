from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.services.catalogo_sistema_anterior import (
    PLANES,
    RENOMBRES,
    sembrar_planes_sistema_anterior,
)
from apps.services.forms import SubscriptionCreateForm
from apps.services.models import Plan, ServiceType


class CatalogoSistemaAnteriorTests(TestCase):
    """Los planes de SICAV que la migración manual necesita elegir."""

    def setUp(self):
        call_command("cargar_catalogo_comercial", stdout=StringIO())

    def test_todos_los_planes_de_sicav_aparecen_en_la_venta(self):
        disponibles = set(
            SubscriptionCreateForm().fields["plan"].queryset.values_list(
                "name", flat=True
            )
        )
        esperados = {name for _, name, _, _ in PLANES} | {
            name for _, name in RENOMBRES
        }

        self.assertEqual(esperados - disponibles, set())

    def test_cada_plan_aparece_una_sola_vez(self):
        for _, name, _, _ in PLANES:
            with self.subTest(plan=name):
                self.assertEqual(Plan.objects.filter(name=name).count(), 1)

    def test_los_planes_renombrados_conservan_precio_y_politica(self):
        plan = Plan.objects.get(code="INT-2025-STD-300")

        self.assertEqual(plan.name, "INTERNET 300MG - 2025")
        self.assertEqual(plan.monthly_price, Decimal("65.00"))
        self.assertIsNotNone(plan.billing_policy)
        self.assertFalse(Plan.objects.filter(name="APP PREMIUM PLUS - RPR").exists())

    def test_los_planes_nuevos_nacen_sin_precio_ni_politica(self):
        nuevos = Plan.objects.filter(code__startswith="SICAV-")

        self.assertEqual(nuevos.count(), len(PLANES))
        self.assertFalse(nuevos.exclude(monthly_price=0).exists())
        self.assertFalse(nuevos.filter(billing_policy__isnull=False).exists())
        self.assertFalse(nuevos.filter(generation__isnull=False).exists())

    def test_tv_cable_ftth_45_es_otro_plan_con_dos_tv(self):
        plan = Plan.objects.get(name="TV CABLE FTTH - 45")

        self.assertEqual(plan.service_type.code, "CABLE")
        self.assertEqual(plan.included_tv_points, 2)
        self.assertTrue(Plan.objects.filter(name="TV CABLE FTTH - 40").exists())

    def test_volver_a_cargar_no_pisa_el_precio_configurado(self):
        Plan.objects.filter(code="SICAV-011").update(monthly_price=Decimal("60.00"))

        call_command("cargar_catalogo_comercial", stdout=StringIO())
        sembrar_planes_sistema_anterior(Plan, ServiceType)

        self.assertEqual(
            Plan.objects.get(code="SICAV-011").monthly_price, Decimal("60.00")
        )
        self.assertEqual(
            Plan.objects.filter(code__startswith="SICAV-").count(), len(PLANES)
        )

    def test_un_plan_creado_a_mano_con_el_mismo_nombre_no_se_duplica(self):
        Plan.objects.filter(code="SICAV-079").delete()
        Plan.objects.create(
            code="MANUAL-RSJ",
            name="rsj internet 100mg",
            service_type=ServiceType.objects.get(code="INTERNET"),
        )

        sembrar_planes_sistema_anterior(Plan, ServiceType)

        self.assertFalse(Plan.objects.filter(code="SICAV-079").exists())
