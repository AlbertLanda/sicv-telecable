"""El comando que siembra data de prueba del reporte.

Se prueba porque es la herramienta con la que se valida el reporte a mano: si
siembra mal, lo que se mira en pantalla no es lo que se cree que se está
mirando, y el error se atribuye al reporte.
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer
from apps.inventory.models import WorkOrderMaterialMovement
from apps.organization.models import Branch
from apps.reports.materials import build_report
from apps.work_orders.models import WorkOrder


User = get_user_model()

PREFIJO = "PRB-"


class SeedCommandTests(TestCase):
    def setUp(self):
        # Las sedes reales las siembra `organization.0002_seed_sedes_reales`,
        # así que ya están aquí. Se usan esas y no unas inventadas: el comando
        # elige la primera por código -HUANCAYO- y una sede de prueba extra
        # solo serviría para que el escenario del comando y el de la prueba
        # dejaran de ser el mismo.
        self.branch = Branch.objects.get(code="HUANCAYO")
        self.other = Branch.objects.get(code="JAUJA")

        self.technician = User.objects.create_user(
            username="tecnico1",
            password="x",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )
        self.admin = User.objects.create_user(
            username="admin1",
            password="x",
            role=User.Role.ADMIN,
            branch=self.branch,
            is_superuser=True,
        )

    def sembrar(self, *args):
        salida = StringIO()
        call_command(
            "generar_datos_materiales_prueba", *args, stdout=salida, stderr=salida
        )
        return salida.getvalue()

    def reporte(self, branch=None, scope="ALL"):
        hoy = timezone.localdate()

        return build_report(
            branch=branch or self.branch,
            date_from=hoy,
            date_to=hoy,
            scope=scope,
        )

    # --- lo que siembra ---------------------------------------------------

    def test_it_seeds_rows_the_report_can_read(self):
        self.sembrar()

        report = self.reporte()

        self.assertGreater(report["total"], 0)
        self.assertTrue(
            all(fila["order_number"].startswith(PREFIJO) for fila in report["rows"])
        )

    def test_every_column_comes_out_filled_at_least_once(self):
        """El escenario existe para ver las trece columnas con contenido."""
        self.sembrar()

        report = self.reporte()
        claves = (
            "order_number", "order_type", "issued_on", "customer_code",
            "customer_name", "address", "material", "quantity", "action",
            "mac", "attended_on", "situation", "technician",
        )

        for clave in claves:
            with self.subTest(columna=clave):
                self.assertTrue(
                    any(fila[clave] not in (None, "") for fila in report["rows"]),
                    f"Ninguna fila trae «{clave}».",
                )

    def test_it_covers_the_empty_cases_too(self):
        """Donde se rompen los reportes es en la celda vacía, no en la llena."""
        self.sembrar()

        filas = self.reporte()["rows"]

        self.assertTrue(
            any(fila["mac"] == "" for fila in filas),
            "Falta el escenario sin ficha de campo (MAC vacío).",
        )
        self.assertTrue(
            any(fila["attended_on"] is None for fila in filas),
            "Falta el escenario de orden todavía en atención.",
        )

    def test_it_covers_both_directions_of_the_movement(self):
        self.sembrar()

        filas = self.reporte()["rows"]

        self.assertTrue(any(fila["is_removal"] for fila in filas))
        self.assertTrue(any(not fila["is_removal"] for fila in filas))

    def test_one_order_can_bring_several_rows(self):
        """Una fila por movimiento: es la decisión que define el reporte."""
        self.sembrar()

        filas = self.reporte()["rows"]
        por_orden = {}
        for fila in filas:
            por_orden.setdefault(fila["order_number"], 0)
            por_orden[fila["order_number"]] += 1

        self.assertTrue(any(cuenta > 1 for cuenta in por_orden.values()))

    def test_the_other_branch_is_seeded_but_never_reported(self):
        self.sembrar()

        propia = self.reporte(branch=self.branch)
        ajena = self.reporte(branch=self.other)

        self.assertGreater(ajena["total"], 0)
        self.assertGreater(propia["total"], 0)
        self.assertEqual(
            set(f["order_number"] for f in propia["rows"])
            & set(f["order_number"] for f in ajena["rows"]),
            set(),
        )

    def test_it_seeds_a_type_that_only_shows_under_todo(self):
        self.sembrar()

        todo = self.reporte(scope="ALL")["total"]
        suma_de_opciones = sum(
            self.reporte(scope=alcance)["total"]
            for alcance in (
                "INSTALLATION", "ANNEX", "RECONNECTION",
                "CUT", "SERVICES", "FAULT",
            )
        )

        self.assertGreater(todo, suma_de_opciones)

    # --- idempotencia y limpieza ------------------------------------------

    def test_running_it_twice_does_not_duplicate(self):
        self.sembrar()
        primero = WorkOrderMaterialMovement.objects.count()

        self.sembrar()

        self.assertEqual(WorkOrderMaterialMovement.objects.count(), primero)

    def test_dry_run_writes_nothing(self):
        self.sembrar("--dry-run")

        self.assertEqual(WorkOrderMaterialMovement.objects.count(), 0)
        self.assertEqual(
            WorkOrder.objects.filter(order_number__startswith=PREFIJO).count(), 0
        )

    def test_limpiar_removes_what_it_seeded(self):
        self.sembrar()
        self.assertGreater(WorkOrderMaterialMovement.objects.count(), 0)

        self.sembrar("--limpiar")

        self.assertEqual(WorkOrderMaterialMovement.objects.count(), 0)
        self.assertEqual(
            WorkOrder.objects.filter(order_number__startswith=PREFIJO).count(), 0
        )
        self.assertEqual(
            Customer.objects.filter(code__startswith=PREFIJO).count(), 0
        )

    def test_it_refuses_without_an_active_technician(self):
        """Sin técnico no hay materiales: los declara el técnico asignado."""
        from django.core.management.base import CommandError

        self.technician.is_active = False
        self.technician.save()

        with self.assertRaises(CommandError):
            self.sembrar()

    def test_it_reports_an_unknown_branch(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.sembrar("--sede", "NO-EXISTE")

    def test_it_uses_the_real_catalog_and_never_adds_to_it(self):
        """El catálogo es de la operación, no del comando.

        Una primera versión creaba materiales con códigos propios y dejó
        «CABLE RG-6» dos veces en el padrón, las dos ofreciéndose al técnico
        en el desplegable de su portal. Un comando de datos de prueba no puede
        ensuciar una tabla que se usa en producción.
        """
        from apps.inventory.models import Material

        antes = set(Material.objects.values_list("code", flat=True))

        self.sembrar()

        self.assertEqual(
            set(Material.objects.values_list("code", flat=True)),
            antes,
            "El comando añadió materiales al catálogo.",
        )

    def test_every_material_it_uses_comes_from_the_migration(self):
        from apps.inventory.models import WorkOrderMaterialMovement
        from apps.reports.management.commands.generar_datos_materiales_prueba import (
            MATERIALES,
        )

        self.sembrar()

        usados = set(
            WorkOrderMaterialMovement.objects.values_list(
                "material__code", flat=True
            )
        )

        self.assertTrue(usados)
        self.assertTrue(usados.issubset(set(MATERIALES)))

    def test_it_stops_if_the_catalog_is_missing(self):
        """Sin catálogo no inventa: un material que la operación no tiene no
        puede salir en un reporte que existe para cuadrar el almacén."""
        from django.core.management.base import CommandError

        from apps.inventory.models import Material

        Material.objects.all().delete()

        with self.assertRaises(CommandError):
            self.sembrar()
