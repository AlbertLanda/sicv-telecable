"""Pruebas del reporte de materiales.

Cubren lo que el reporte promete: que recorta por sede, por periodo y por tipo
de orden; que cuenta una fila por movimiento y no por orden; y que las cuatro
salidas entregan un archivo del formato que dicen ser.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.organization.models import Branch, Zone
from apps.reports.materials import build_report
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import OrderType, WorkOrder, WorkOrderFieldSheet


User = get_user_model()


class MaterialReportTestCase(TestCase):
    """Escenario mínimo: dos sedes, dos tipos de orden y material declarado."""

    def setUp(self):
        self.today = timezone.localdate()
        self.order_sequence = 0

        self.branch = Branch.objects.create(code="SED01", name="Huancayo")
        self.other_branch = Branch.objects.create(code="SED02", name="Jauja")

        self.zone = Zone.objects.create(branch=self.branch, name="Zona Norte")

        self.service_type = ServiceType.objects.create(
            code="CABLE", name="Cable"
        )
        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100",
            name="Cable HD",
            monthly_price=Decimal("60.00"),
        )

        self.installation_type = OrderType.objects.create(
            code="INSTALLATION", name="INSTALACIÓN"
        )
        self.cut_type = OrderType.objects.create(code="CUT", name="CORTE")

        self.utp = Material.objects.create(
            code="UTP", name="Cable UTP", unit_of_measure=Material.Unit.METER
        )
        self.decoder = Material.objects.create(
            code="DEC", name="Decodificador", unit_of_measure=Material.Unit.UNIT
        )

        self.technician = User.objects.create_user(
            username="tecnico1",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
            first_name="Luis",
            last_name="Quispe",
        )

        self.operator = User.objects.create_user(
            username="logistica1",
            password="test1234",
            role=User.Role.WAREHOUSE,
            branch=self.branch,
        )
        self.operator.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="inventory",
                codename="view_workordermaterialmovement",
            )
        )

    # --- utilidades del escenario ---------------------------------------

    def make_customer(self, code, branch=None):
        customer = Customer.objects.create(
            code=code,
            branch=branch or self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number=f"4567{code[-4:]}",
            first_name="Ana",
            paternal_surname="Torres",
            maternal_surname="Vega",
        )
        address = CustomerAddress.objects.create(
            customer=customer,
            zone=self.zone,
            address=f"Av. Los Álamos {code}",
            district="El Tambo",
            is_primary=True,
        )
        subscription = Subscription.objects.create(
            customer=customer,
            address=address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
        )
        return subscription

    def make_order(self, subscription, order_type=None, branch=None, issued_on=None):
        self.order_sequence += 1

        order = WorkOrder.objects.create(
            order_number=f"OT-{self.order_sequence:05d}",
            subscription=subscription,
            order_type=order_type or self.installation_type,
            branch=branch or self.branch,
            attention_type=WorkOrder.AttentionType.FIELD,
            status=WorkOrder.Status.IN_PROGRESS,
            assigned_technician=self.technician,
            created_by=self.operator,
            detail="Atención de prueba.",
        )

        # `created_at` es auto_now_add: para situar una orden en otro día hay
        # que reescribirla con update(), que no dispara el automatismo.
        if issued_on is not None:
            WorkOrder.objects.filter(pk=order.pk).update(created_at=issued_on)
            order.refresh_from_db()

        return order

    def add_material(self, order, material=None, quantity="12.00", movement=None):
        return WorkOrderMaterialMovement.objects.create(
            work_order=order,
            material=material or self.utp,
            movement_type=(
                movement or WorkOrderMaterialMovement.MovementType.INSTALLED
            ),
            quantity=Decimal(quantity),
            recorded_by=self.technician,
        )

    def report(self, **kwargs):
        options = {
            "branch": self.branch,
            "date_from": self.today,
            "date_to": self.today,
        }
        options.update(kwargs)
        return build_report(**options)


class MaterialReportQueryTests(MaterialReportTestCase):
    def test_one_row_per_movement_not_per_order(self):
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order, self.utp, "30.00")
        self.add_material(
            order,
            self.decoder,
            "1.00",
            WorkOrderMaterialMovement.MovementType.REMOVED,
        )

        report = self.report()

        self.assertEqual(report["total"], 2)
        self.assertEqual(
            {row["material"] for row in report["rows"]},
            {"Cable UTP", "Decodificador"},
        )

    def test_another_branch_never_appears(self):
        propia = self.make_order(self.make_customer("CLI001"))
        ajena = self.make_order(
            self.make_customer("CLI002", branch=self.other_branch),
            branch=self.other_branch,
        )
        self.add_material(propia)
        self.add_material(ajena)

        report = self.report()

        self.assertEqual(report["total"], 1)
        self.assertEqual(report["rows"][0]["customer_code"], "CLI001")

    def test_period_bounds_are_inclusive(self):
        ayer = timezone.now() - timedelta(days=1)
        manana = timezone.now() + timedelta(days=1)

        for etiqueta, momento in (("CLI001", ayer), ("CLI002", manana)):
            orden = self.make_order(
                self.make_customer(etiqueta), issued_on=momento
            )
            self.add_material(orden)

        report = self.report(
            date_from=self.today - timedelta(days=1),
            date_to=self.today + timedelta(days=1),
        )

        self.assertEqual(report["total"], 2)

    def test_orders_outside_the_period_are_left_out(self):
        vieja = self.make_order(
            self.make_customer("CLI001"),
            issued_on=timezone.now() - timedelta(days=10),
        )
        self.add_material(vieja)

        self.assertEqual(self.report()["total"], 0)

    def test_scope_filters_by_order_type(self):
        instalacion = self.make_order(self.make_customer("CLI001"))
        corte = self.make_order(
            self.make_customer("CLI002"), order_type=self.cut_type
        )
        self.add_material(instalacion)
        self.add_material(corte)

        self.assertEqual(self.report(scope="ALL")["total"], 2)
        self.assertEqual(self.report(scope="INSTALLATION")["total"], 1)
        self.assertEqual(self.report(scope="CUT")["total"], 1)

    def test_scope_all_includes_types_without_their_own_option(self):
        """«Todo» no es la suma de las seis opciones del desplegable.

        Un material declarado en un tipo sin opción propia -un retiro, un
        cambio de plan- solo puede aparecer aquí. Si «Todo» no lo trajera, ese
        material no saldría en ninguna de las siete vistas del reporte.
        """
        retiro = OrderType.objects.create(code="WITHDRAWAL", name="RETIRO")
        orden = self.make_order(
            self.make_customer("CLI001"), order_type=retiro
        )
        self.add_material(orden)

        self.assertEqual(self.report(scope="ALL")["total"], 1)
        self.assertEqual(self.report(scope="INSTALLATION")["total"], 0)

    def test_row_carries_every_column_of_the_legacy_sheet(self):
        subscription = self.make_customer("CLI001")
        order = self.make_order(subscription)
        WorkOrderFieldSheet.objects.create(
            work_order=order,
            equipment_code="AA:BB:CC:DD:EE:FF",
            updated_by=self.technician,
        )
        self.add_material(order, self.utp, "45.50")

        fila = self.report()["rows"][0]

        self.assertEqual(fila["order_number"], order.order_number)
        self.assertEqual(fila["order_type"], "INSTALACIÓN")
        self.assertEqual(fila["customer_code"], "CLI001")
        self.assertEqual(fila["customer_name"], str(subscription.customer))
        self.assertEqual(fila["address"], "Av. Los Álamos CLI001")
        self.assertEqual(fila["material"], "Cable UTP")
        self.assertEqual(fila["quantity"], Decimal("45.50"))
        self.assertEqual(fila["unit"], "Metro")
        self.assertEqual(fila["action"], "Instalado en domicilio")
        self.assertFalse(fila["is_removal"])
        self.assertEqual(fila["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(fila["situation"], "En atención")
        self.assertEqual(fila["technician"], "Luis Quispe")

    def test_an_order_without_field_sheet_still_reports_its_material(self):
        """La ficha es opcional; el material que salió del almacén no lo es."""
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(order)

        fila = self.report()["rows"][0]

        self.assertEqual(fila["mac"], "")
        self.assertEqual(self.report()["total"], 1)

    def test_removal_is_marked_as_such(self):
        order = self.make_order(self.make_customer("CLI001"))
        self.add_material(
            order,
            movement=WorkOrderMaterialMovement.MovementType.REMOVED,
        )

        fila = self.report()["rows"][0]

        self.assertTrue(fila["is_removal"])
        self.assertEqual(fila["action"], "Retirado de domicilio")
