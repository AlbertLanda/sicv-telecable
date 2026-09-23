"""Prepara una base local limpia para demostrar el flujo comercial.

Este comando NO es un seeder de producción. Crea usuarios y datos ficticios
para una presentación de gerencia y se niega a ejecutarse fuera de DEBUG.

Escenarios:
1. Un contrato DUO ya firmado, instalado y liquidado.
2. Un segundo domicilio del mismo abonado con otra suscripción/contrato y
   una OT en atención, lista para firmarse en vivo desde el portal técnico.
"""

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
from apps.organization.models import Branch, Zone
from apps.payments.models import Issuer
from apps.services.commercial import build_commercial_quote
from apps.services.models import Plan, Subscription
from apps.work_orders.models import OrderReason, OrderResult, WorkOrder
from apps.work_orders.services import (
    attend_order,
    create_installation_work_order,
    liquidate_order,
    start_order_attention,
)


DEMO_PASSWORD = "Demo2026!"
DEMO_DOCUMENT = "00000000"
DEMO_USERNAMES = (
    "gerencia_demo",
    "atc_demo",
    "tecnico_demo",
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
        self.stdout.write(f"  Técnico:       tecnico_demo / {DEMO_PASSWORD}")
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

        technician = User.objects.create_user(
            username="tecnico_demo",
            password=DEMO_PASSWORD,
            first_name="Técnico",
            last_name="Demo",
            role=User.Role.TECHNICIAN,
            branch=branch,
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
            email="cliente.demo@example.com",
            is_active=True,
        )

        address_one = CustomerAddress.objects.create(
            customer=customer,
            zone=zone,
            address="Jr. Demostración 100",
            reference="Frente a la plaza - dato ficticio",
            district="Jauja",
            is_primary=True,
            is_active=True,
        )

        address_two = CustomerAddress.objects.create(
            customer=customer,
            zone=zone,
            address="Jr. Demostración 200",
            reference="Segunda vivienda - dato ficticio",
            district="Jauja",
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
            technician=technician,
            signed=False,
        )

        return {
            "firmada": signed,
            "pendiente": pending,
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
                "Instalación de demostración para presentación de gerencia."
            ),
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

        liquidate_order(
            order,
            user=technician,
            resolution_detail=(
                "Instalación ejecutada correctamente. Servicio operativo "
                "y contrato firmado para demostración."
            ),
            technical_notes="Registro ficticio para presentación de gerencia.",
            network_element="NAP-DEMO-01",
            network_port="01",
            equipment_serial="ONU-DEMO-0001",
        )

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
