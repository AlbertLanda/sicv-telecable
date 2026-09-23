"""Prepara una base local limpia para demostrar el flujo comercial.

Este comando NO es un seeder de producción. Crea usuarios y datos ficticios
para una presentación de gerencia y se niega a ejecutarse fuera de DEBUG.

Escenarios:
1. Un contrato DUO ya firmado, instalado y liquidado.
2. Un segundo domicilio del mismo abonado con otra suscripción/contrato y
   una OT en atención, lista para firmarse en vivo desde el portal técnico.
"""

from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image as PILImage, ImageDraw

from apps.accounts.models import User
from apps.contracts.models import Contract
from apps.contracts.signatures import firmar_contrato
from apps.customers.models import Customer, CustomerAddress
from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.inventory.services import record_work_order_material
from apps.organization.models import Branch, Zone
from apps.payments.models import Issuer
from apps.services.commercial import build_commercial_quote
from apps.services.models import Plan, Subscription
from apps.technicians.models import TechnicianProfile
from apps.work_orders.api.field_completion import (
    liquidation_items_from_field,
    liquidation_technical_data_from_field,
)
from apps.work_orders.models import OrderReason, OrderResult, WorkOrder
from apps.work_orders.services import (
    add_work_order_evidence,
    attend_order,
    create_installation_work_order,
    create_outside_plant_order,
    liquidate_order,
    start_order_attention,
    update_field_sheet,
)


DEMO_PASSWORD = "Demo2026!"
DEMO_DOCUMENT = "00000000"
DEMO_USERNAMES = (
    "gerencia_demo",
    "atc_demo",
    "ventas_demo",
    "tecnico_demo",
    "tecnico_pex_demo",
    "tecnico_pex_apoyo_demo",
)


class Command(BaseCommand):
    help = (
        "Crea datos ficticios reproducibles para demostrar contrato, "
        "firma digital y flujo de instalación en una base local limpia."
    )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Este comando es solo para demostraciones locales con DEBUG=True."
            )

        if (
            Customer.objects.exists()
            or Subscription.objects.exists()
            or Contract.objects.exists()
            or WorkOrder.objects.exists()
        ):
            raise CommandError(
                "La base no está limpia. Use una SQLite nueva para la demo "
                "antes de ejecutar preparar_demo_gerencia."
            )

        self.stdout.write(
            self.style.MIGRATE_HEADING("Preparando demo SICV para gerencia")
        )

        # Catálogos reales del proyecto. El comando solo agrega datos ficticios
        # de demostración; no duplica definiciones comerciales ni de órdenes.
        call_command("cargar_catalogo_comercial")
        call_command("cargar_catalogo_ordenes")

        with transaction.atomic():
            contexto = self._crear_datos_demo()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo preparada correctamente."))
        self.stdout.write("")
        self.stdout.write("Credenciales locales de demostración")
        self.stdout.write(f"  Administrador: gerencia_demo / {DEMO_PASSWORD}")
        self.stdout.write(f"  ATC:           atc_demo / {DEMO_PASSWORD}")
        self.stdout.write(f"  Ventas:        ventas_demo / {DEMO_PASSWORD}")
        self.stdout.write(f"  Técnico red:   tecnico_demo / {DEMO_PASSWORD}")
        self.stdout.write(f"  Técnico PEX:   tecnico_pex_demo / {DEMO_PASSWORD}")
        self.stdout.write(f"  Apoyo PEX:     tecnico_pex_apoyo_demo / {DEMO_PASSWORD}")
        self.stdout.write("")
        self.stdout.write("Escenario firmado")
        self.stdout.write(
            f"  Servicio: {contexto['firmada']['subscription'].service_code}"
        )
        self.stdout.write(
            f"  Contrato: {contexto['firmada']['contract'].contract_number}"
        )
        self.stdout.write(
            f"  OT:       {contexto['firmada']['order'].order_number}"
        )
        self.stdout.write(
            f"  SHA-256:  {contexto['firmada']['signature'].signed_pdf_sha256}"
        )
        self.stdout.write("  Ficha:    NAP-DEMO-JAUJA-01 / borne 08 / PRE-DEMO-0001")
        self.stdout.write("  GPS:      -11.7754200, -75.4961800")
        self.stdout.write("")
        self.stdout.write("Escenario listo para firma en vivo")
        self.stdout.write(
            f"  Servicio: {contexto['pendiente']['subscription'].service_code}"
        )
        self.stdout.write(
            f"  Contrato: {contexto['pendiente']['contract'].contract_number}"
        )
        self.stdout.write(
            f"  OT:       {contexto['pendiente']['order'].order_number}"
        )
        self.stdout.write(
            "  Estado:   En atención, asignada al usuario tecnico_demo"
        )
        self.stdout.write("  Ficha:    NAP-DEMO-JAUJA-02 / borne 12 / PRE-DEMO-0002")
        self.stdout.write("  GPS:      -11.7761500, -75.4956000")
        self.stdout.write("")
        self.stdout.write("Escenario Planta Externa")
        self.stdout.write(
            f"  OT:       {contexto['pex']['order'].order_number}"
        )
        self.stdout.write("  Motivo:   CAÍDA DE POSTE")
        self.stdout.write("  Tramo:    Av. Demo PEX - Jr. Red Principal")
        self.stdout.write(
            "  Estado:   Pendiente, disponible solo para cuadrilla PEX"
        )
        self.stdout.write("  Técnico:  tecnico_pex_demo")
        self.stdout.write("  Apoyo:    tecnico_pex_apoyo_demo")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Todos los nombres, documentos, domicilios y firmas creados "
                "por este comando son ficticios y solo sirven para la demo."
            )
        )

    def _crear_datos_demo(self):
        branch = Branch.objects.get(code="JAUJA")

        zone, _ = Zone.objects.get_or_create(
            branch=branch,
            name="DEMO GERENCIA",
            defaults={"is_active": True},
        )

        Issuer.objects.get_or_create(
            code="INV",
            defaults={
                "business_name": (
                    "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C."
                ),
                "ruc": "20603110456",
                "is_active": True,
            },
        )

        admin = User.objects.create_superuser(
            username="gerencia_demo",
            password=DEMO_PASSWORD,
            role=User.Role.ADMIN,
            branch=branch,
        )

        atc = User.objects.create_user(
            username="atc_demo",
            password=DEMO_PASSWORD,
            first_name="ATC",
            last_name="Demo",
            role=User.Role.ATC,
            branch=branch,
        )

        seller = User.objects.create_user(
            username="ventas_demo",
            password=DEMO_PASSWORD,
            first_name="Ventas",
            last_name="Demo",
            role=User.Role.SALES,
            branch=branch,
        )

        technician = User.objects.create_user(
            username="tecnico_demo",
            password=DEMO_PASSWORD,
            first_name="Técnico",
            last_name="Demo",
            role=User.Role.TECHNICIAN,
            branch=branch,
        )

        technician_pex = User.objects.create_user(
            username="tecnico_pex_demo",
            password=DEMO_PASSWORD,
            first_name="Técnico",
            last_name="PEX Demo",
            role=User.Role.TECHNICIAN,
            branch=branch,
        )
        technician_pex.technician_profile.area = TechnicianProfile.Area.PEX
        technician_pex.technician_profile.save(
            update_fields=["area", "updated_at"]
        )

        technician_pex_support = User.objects.create_user(
            username="tecnico_pex_apoyo_demo",
            password=DEMO_PASSWORD,
            first_name="Apoyo",
            last_name="PEX Demo",
            role=User.Role.TECHNICIAN,
            branch=branch,
        )
        technician_pex_support.technician_profile.area = TechnicianProfile.Area.PEX
        technician_pex_support.technician_profile.save(
            update_fields=["area", "updated_at"]
        )

        # Evita que linters marquen el usuario administrador como no usado:
        # su existencia es parte explícita del escenario de demostración.
        _ = admin

        customer = Customer.objects.create(
            code=Customer.generate_code(branch),
            branch=branch,
            document_type=Customer.DocumentType.DNI,
            document_number=DEMO_DOCUMENT,
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="Demo",
            maternal_surname="Gerencia",
            phone="900000000",
            secondary_phone="964123456",
            email="cliente.demo@example.com",
            is_active=True,
        )

        address_one = CustomerAddress.objects.create(
            customer=customer,
            zone=zone,
            address="Jr. Demostración 100",
            reference="Frente a la plaza - dato ficticio",
            district="Jauja",
            meter_number="MED-DEMO-0001",
            electrical_supply_code="SUM-DEMO-000001",
            latitude=Decimal("-11.7754200"),
            longitude=Decimal("-75.4961800"),
            is_primary=True,
            is_active=True,
        )

        address_two = CustomerAddress.objects.create(
            customer=customer,
            zone=zone,
            address="Jr. Demostración 200",
            reference="Segunda vivienda - dato ficticio",
            district="Jauja",
            meter_number="MED-DEMO-0002",
            electrical_supply_code="SUM-DEMO-000002",
            latitude=Decimal("-11.7761500"),
            longitude=Decimal("-75.4956000"),
            is_primary=False,
            is_active=True,
        )

        plan = Plan.objects.select_related(
            "service_type",
            "billing_policy",
        ).get(code="DUO-2026-STD-600")

        signed = self._crear_servicio(
            customer=customer,
            address=address_one,
            plan=plan,
            service_number=1,
            contract_number="CONT-DEMO-000001",
            atc=atc,
            seller=seller,
            technician=technician,
            signed=True,
        )

        pending = self._crear_servicio(
            customer=customer,
            address=address_two,
            plan=plan,
            service_number=2,
            contract_number="CONT-DEMO-000002",
            atc=atc,
            seller=seller,
            technician=technician,
            signed=False,
        )

        pex_reason = OrderReason.objects.get(
            order_type__code="OUTSIDE_PLANT",
            code="FALLEN_POLE",
        )
        pex_order = create_outside_plant_order(
            created_by=atc,
            branch=branch,
            zone=zone,
            route="Av. Demo PEX - Jr. Red Principal",
            reference="Poste ficticio frente al parque de demostración",
            latitude=Decimal("-11.7748000"),
            longitude=Decimal("-75.4970000"),
            reason=pex_reason,
            detail=(
                "Caída de poste ficticia con afectación de red. "
                "Orden preparada para demostrar el flujo de Planta Externa."
            ),
            priority=WorkOrder.Priority.HIGH,
        )

        return {
            "firmada": signed,
            "pendiente": pending,
            "pex": {
                "order": pex_order,
                "technician": technician_pex,
                "support": technician_pex_support,
            },
        }

    def _crear_servicio(
        self,
        *,
        customer,
        address,
        plan,
        service_number,
        contract_number,
        atc,
        seller,
        technician,
        signed,
    ):
        quote = build_commercial_quote(
            plan=plan,
            address=address,
        )

        subscription = Subscription(
            customer=customer,
            address=address,
            service_type=plan.service_type,
            plan=plan,
            tariff=quote["tariff"],
            billing_policy=quote["billing_policy"],
            status=Subscription.Status.PRESALE,
            service_number=service_number,
            billing_cycle=23,
            base_installation_fee=quote["installation_fee"],
            base_monthly_fee=quote["monthly_fee"],
            initial_tv_courtesy_granted=min(
                2,
                plan.included_tv_points,
            ),
            annex_count=0,
            is_active=True,
        )
        subscription.full_clean()
        subscription.save()

        contract = Contract(
            contract_number=contract_number,
            customer=customer,
            subscription=subscription,
            service_type=plan.service_type,
            plan=plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=timezone.localdate(),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        contract.full_clean()
        contract.save()

        reason = OrderReason.objects.get(
            order_type__code="INSTALLATION",
            code="NEW_CLIENT",
        )

        order = create_installation_work_order(
            subscription=subscription,
            created_by=atc,
            customer=customer,
            reason=reason,
            priority=WorkOrder.Priority.NORMAL,
            detail=(
                "Instalación de demostración para presentación de gerencia. "
                f"Vivienda demo N.° {service_number}."
            ),
            seller=seller,
        )

        # Representa la toma desde la app: technician y assigned_by son el
        # mismo usuario, exactamente igual que ClaimWorkOrderView.
        order.assign_technician(
            technician,
            assigned_by=technician,
            remarks="OT tomada por el técnico en escenario de demostración.",
        )

        start_order_attention(
            order,
            user=technician,
            remarks="Inicio de instalación de demostración.",
        )

        self._preparar_trabajo_campo(
            order=order,
            technician=technician,
            service_number=service_number,
            signed=signed,
        )

        if not signed:
            return {
                "subscription": subscription,
                "contract": contract,
                "order": order,
            }

        signature = firmar_contrato(
            contract,
            self._firma_demo(),
            usuario=technician,
            orden=order,
        )

        success = OrderResult.objects.get(
            order_type__code="INSTALLATION",
            code="SUCCESSFUL",
        )

        attend_order(
            order,
            result=success,
            user=technician,
            remarks="Instalación demo aceptada y firmada por el abonado.",
        )

        technical_data = liquidation_technical_data_from_field(order)
        technical_data.update(
            {
                "signal_level_dbm": Decimal("-21.40"),
                "cable_meters_used": Decimal("85.00"),
                "krill_reference": "KRILL-DEMO-0001",
            }
        )

        liquidation = liquidate_order(
            order,
            user=technician,
            resolution_detail=(
                "Instalación DUO de demostración ejecutada correctamente. "
                "Se realizó tendido de fibra Drop, cableado UTP y RG-6, "
                "se instaló/configuró el equipo terminal, se verificó señal "
                "y el abonado ficticio dejó su conformidad mediante firma digital."
            ),
            technical_notes=(
                "Registro totalmente ficticio para presentación interna de "
                "gerencia. NAP, borne, equipo, precinto, materiales, niveles "
                "de señal y evidencias no corresponden a una instalación real."
            ),
            items=liquidation_items_from_field(order),
            remarks="Liquidación técnica demo generada por el escenario de gerencia.",
            **technical_data,
        )

        # Las evidencias se capturaron durante la atención. Para la demo se
        # enlazan también con la liquidación ya creada, de modo que la ficha
        # cerrada muestre qué fotos sustentan ese documento técnico.
        order.evidences.update(liquidation=liquidation)

        order.refresh_from_db()
        subscription.refresh_from_db()
        contract.refresh_from_db()
        signature.refresh_from_db()

        return {
            "subscription": subscription,
            "contract": contract,
            "order": order,
            "signature": signature,
        }

    def _preparar_trabajo_campo(
        self,
        *,
        order,
        technician,
        service_number,
        signed,
    ):
        """Completa una OT demo por los mismos servicios que usa el técnico."""

        if service_number == 1:
            field_data = {
                "nap": "NAP-DEMO-JAUJA-01",
                "terminal": "08",
                "equipment_code": "ONU-DEMO-4GJ2",
                "seal_number": "PRE-DEMO-0001",
                "notes": (
                    "Se verificó potencia óptica, conectividad de Internet y "
                    "señal de TV. Registro ficticio para gerencia."
                ),
            }
            materials = (
                ("FIBRA_DROP", "85.00", "Tendido principal de acometida demo."),
                ("CABLE_UTP", "18.00", "Cableado interior de red demo."),
                ("CABLE_RG6", "32.00", "Distribución de TV demo."),
                ("CONECTOR_F56", "4.00", "Conectores instalados en puntos TV demo."),
                ("SPLITTER_2", "1.00", "Divisor para dos puntos TV de cortesía."),
            )
            evidences = (
                ("nap_demo.png", "Caja NAP utilizada - evidencia ficticia"),
                ("equipo_demo.png", "ONU/router instalado - evidencia ficticia"),
                ("domicilio_demo.png", "Fachada del domicilio - evidencia ficticia"),
            )
        else:
            field_data = {
                "nap": "NAP-DEMO-JAUJA-02",
                "terminal": "12",
                "equipment_code": "ONU-DEMO-7KQ9",
                "seal_number": "PRE-DEMO-0002",
                "notes": (
                    "Instalación preparada para demostrar firma digital en vivo. "
                    "Todos los datos son ficticios."
                ),
            }
            materials = (
                ("FIBRA_DROP", "60.00", "Acometida preparada para la demo."),
                ("CABLE_UTP", "12.00", "Cableado interior preparado."),
                ("CABLE_RG6", "24.00", "Cableado TV preparado."),
                ("CONECTOR_F56", "4.00", "Conectores de demostración."),
                ("SPLITTER_2", "1.00", "Divisor para dos puntos de cortesía."),
            )
            evidences = (
                (
                    "inspeccion_demo.png",
                    "Inspección previa del segundo domicilio - evidencia ficticia",
                ),
            )

        update_field_sheet(
            order,
            user=technician,
            **field_data,
        )

        for code, quantity, remarks in materials:
            material = Material.objects.get(code=code, is_active=True)
            record_work_order_material(
                work_order=order,
                material=material,
                movement_type=(
                    WorkOrderMaterialMovement.MovementType.INSTALLED
                ),
                quantity=Decimal(quantity),
                user=technician,
                remarks=remarks,
            )

        for filename, description in evidences:
            add_work_order_evidence(
                order,
                user=technician,
                file=self._evidencia_demo(
                    filename,
                    order=order,
                    signed=signed,
                ),
                description=description,
            )

    def _evidencia_demo(self, filename, *, order, signed):
        """PNG artificial con marca visible; nunca parece una foto real."""

        canvas = PILImage.new(
            "RGB",
            (900, 560),
            (238, 242, 247),
        )
        draw = ImageDraw.Draw(canvas)

        draw.rectangle(
            [(35, 35), (865, 525)],
            outline=(35, 78, 120),
            width=5,
        )
        draw.text(
            (70, 80),
            "DEMO GERENCIA - EVIDENCIA FICTICIA",
            fill=(15, 55, 95),
        )
        draw.text(
            (70, 150),
            f"Orden: {order.order_number}",
            fill=(30, 30, 30),
        )
        draw.text(
            (70, 205),
            f"Servicio: {order.subscription.service_code}",
            fill=(30, 30, 30),
        )
        draw.text(
            (70, 260),
            (
                "Escenario: instalacion cerrada y firmada"
                if signed
                else "Escenario: instalacion lista para firma en vivo"
            ),
            fill=(30, 30, 30),
        )
        draw.text(
            (70, 350),
            "SIN VALOR OPERATIVO - DATOS DE PRUEBA",
            fill=(120, 25, 25),
        )

        buffer = BytesIO()
        canvas.save(buffer, format="PNG")

        return SimpleUploadedFile(
            filename,
            buffer.getvalue(),
            content_type="image/png",
        )

    def _firma_demo(self):
        """Genera un trazo inequívocamente ficticio para el contrato demo."""

        canvas = PILImage.new(
            "RGBA",
            (520, 170),
            (255, 255, 255, 0),
        )

        draw = ImageDraw.Draw(canvas)
        draw.line(
            [
                (18, 122),
                (85, 66),
                (145, 126),
                (220, 45),
                (292, 121),
                (360, 58),
                (495, 108),
            ],
            fill=(20, 25, 35, 255),
            width=6,
        )

        buffer = BytesIO()
        canvas.save(buffer, format="PNG")

        return SimpleUploadedFile(
            "firma_demo_gerencia.png",
            buffer.getvalue(),
            content_type="image/png",
        )
