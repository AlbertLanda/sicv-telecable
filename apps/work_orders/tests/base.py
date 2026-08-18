"""
Base común para las pruebas del módulo de órdenes.

Construye el escenario mínimo (sede, zona, cliente, suscripción, usuarios y
catálogos de orden) para no repetir el armado en cada módulo de pruebas.
Los catálogos se crean con los códigos estables que consume services.py.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import (
    OrderCause,
    OrderReason,
    OrderResult,
    OrderSubtype,
    OrderType,
    WorkOrder,
)

User = get_user_model()


class WorkOrderTestCase(TestCase):
    """Escenario base reutilizable por todas las pruebas del módulo."""

    def setUp(self):
        self.branch = Branch.objects.create(code="SED01", name="Sede Central")

        self.zone = Zone.objects.create(branch=self.branch, name="Zona Norte")

        self.customer = Customer.objects.create(
            code="CLI001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678912",
            first_name="Juan",
            paternal_surname="Pérez",
            maternal_surname="Ramos",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Los Álamos 123",
            district="Chachapoyas",
            is_primary=True,
        )

        self.other_address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Amazonas 456",
            district="Chachapoyas",
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100",
            name="Fibra 100 Mbps",
            speed_mbps=100,
            monthly_price=80,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
        )

        # --- Usuarios -----------------------------------------------------
        self.technician = User.objects.create_user(
            username="tecnico1",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        self.other_technician = User.objects.create_user(
            username="tecnico2",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        self.inactive_technician = User.objects.create_user(
            username="tecnico3",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
            is_active=False,
        )

        self.atc_user = User.objects.create_user(
            username="atc1",
            password="test1234",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.supervisor = User.objects.create_user(
            username="supervisor1",
            password="test1234",
            role=User.Role.SUPERVISOR,
            branch=self.branch,
        )

        # --- Catálogos de orden -------------------------------------------
        self.installation_type = OrderType.objects.create(
            code="INSTALLATION",
            name="Instalación",
        )

        self.cut_type = OrderType.objects.create(
            code="CUT",
            name="Corte",
        )

        self.reconnection_type = OrderType.objects.create(
            code="RECONNECTION",
            name="Reconexión",
        )

        self.transfer_type = OrderType.objects.create(
            code="TRANSFER",
            name="Traslado",
        )

        # Subtipos
        self.temporary_subtype = OrderSubtype.objects.create(
            order_type=self.cut_type,
            code="TEMPORARY",
            name="Corte temporal",
        )

        self.definitive_subtype = OrderSubtype.objects.create(
            order_type=self.cut_type,
            code="DEFINITIVE",
            name="Corte definitivo",
        )

        self.internal_subtype = OrderSubtype.objects.create(
            order_type=self.transfer_type,
            code="INTERNAL",
            name="Traslado interno",
        )

        self.external_subtype = OrderSubtype.objects.create(
            order_type=self.transfer_type,
            code="EXTERNAL",
            name="Traslado externo",
        )

        # Motivos
        self.installation_reason = OrderReason.objects.create(
            order_type=self.installation_type,
            code="NEW_CLIENT",
            name="Cliente nuevo",
            classification=OrderReason.Classification.TECHNICAL,
        )

        self.cut_reason = OrderReason.objects.create(
            order_type=self.cut_type,
            code="NON_PAYMENT",
            name="Falta de pago",
            classification=OrderReason.Classification.ADMINISTRATIVE,
        )

        # Causas
        self.installation_cause = OrderCause.objects.create(
            order_type=self.installation_type,
            code="NO_SIGNAL",
            name="Sin señal en el punto",
        )

        self.cut_cause = OrderCause.objects.create(
            order_type=self.cut_type,
            code="DEBT",
            name="Deuda vencida",
        )

        # Resultados
        self.installation_success = OrderResult.objects.create(
            order_type=self.installation_type,
            code="SUCCESSFUL",
            name="Exitoso",
            is_success=True,
        )

        self.cut_success = OrderResult.objects.create(
            order_type=self.cut_type,
            code="SUCCESSFUL",
            name="Exitoso",
            is_success=True,
        )

        self.reconnection_success = OrderResult.objects.create(
            order_type=self.reconnection_type,
            code="SUCCESSFUL",
            name="Exitoso",
            is_success=True,
        )

        self.transfer_success = OrderResult.objects.create(
            order_type=self.transfer_type,
            code="SUCCESSFUL",
            name="Exitoso",
            is_success=True,
        )

        self._order_sequence = 0

    def create_order(self, order_type=None, **kwargs):
        """Crea una orden con los datos mínimos obligatorios."""
        self._order_sequence += 1

        defaults = {
            "order_number": f"OT-{self._order_sequence:05d}",
            "subscription": self.subscription,
            "order_type": order_type or self.installation_type,
            "branch": self.branch,
            "zone": self.zone,
            "created_by": self.atc_user,
        }

        defaults.update(kwargs)

        return WorkOrder.objects.create(**defaults)

    def create_assigned_order(self, order_type=None, **kwargs):
        """Crea una orden ya asignada a un técnico."""
        order = self.create_order(order_type=order_type, **kwargs)

        order.assign_technician(
            technician=self.technician,
            assigned_by=self.supervisor,
        )

        return order

    def create_order_in_progress(self, order_type=None, **kwargs):
        """Crea una orden con la atención ya iniciada."""
        order = self.create_assigned_order(order_type=order_type, **kwargs)

        order.start_attention(user=self.technician)

        return order

    def create_attended_order(self, order_type=None, result=None, **kwargs):
        """Crea una orden ya atendida, lista para liquidarse."""
        from apps.work_orders.services import attend_order

        order = self.create_order_in_progress(order_type=order_type, **kwargs)

        attend_order(
            order,
            result=result or self.installation_success,
            user=self.technician,
        )

        return order
