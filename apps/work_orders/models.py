from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organization.models import Branch, Zone
from apps.services.models import Subscription


class OrderType(models.Model):
    """Catálogo de tipos de orden: Instalación, Avería, Corte, Reconexión, etc."""

    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Tipo de orden"
    )

    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Tipo de orden"
        verbose_name_plural = "Tipos de orden"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrderReason(models.Model):
    """Catálogo de motivos, siempre asociados a un tipo de orden."""

    class Classification(models.TextChoices):
        TECHNICAL = "TECHNICAL", "Técnico"
        ADMINISTRATIVE = "ADMINISTRATIVE", "Administrativo"

    order_type = models.ForeignKey(
        OrderType,
        on_delete=models.PROTECT,
        related_name="reasons",
        verbose_name="Tipo de orden"
    )

    code = models.CharField(
        max_length=30,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=150,
        verbose_name="Motivo"
    )

    classification = models.CharField(
        max_length=20,
        choices=Classification.choices,
        blank=True,
        verbose_name="Clasificación"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Motivo de orden"
        verbose_name_plural = "Motivos de orden"
        ordering = ["order_type", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["order_type", "code"],
                name="unique_reason_code_per_order_type"
            )
        ]

    def __str__(self):
        return f"{self.order_type.name} - {self.name}"


class WorkOrder(models.Model):
    """Entidad principal del motor de órdenes."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        DERIVED = "DERIVED", "Derivada"
        ATTENDED = "ATTENDED", "Atendida"
        REJECTED = "REJECTED", "Rechazada"
        NOT_FEASIBLE = "NOT_FEASIBLE", "No factible"
        CANCELLED = "CANCELLED", "Anulada"

    class Priority(models.TextChoices):
        LOW = "LOW", "Baja"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "Alta"
        URGENT = "URGENT", "Urgente"

    class AttentionType(models.TextChoices):
        SYSTEM = "SYSTEM", "Sistema / NOC"
        FIELD = "FIELD", "Campo"

    order_number = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Número de orden"
    )

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="Suscripción"
    )

    order_type = models.ForeignKey(
        OrderType,
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="Tipo de orden"
    )

    reason = models.ForeignKey(
        OrderReason,
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
        verbose_name="Motivo"
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="Sede"
    )

    zone = models.ForeignKey(
        Zone,
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
        verbose_name="Zona"
    )

    attention_type = models.CharField(
        max_length=20,
        choices=AttentionType.choices,
        default=AttentionType.FIELD,
        verbose_name="Tipo de atención"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Estado"
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
        verbose_name="Prioridad"
    )

    detail = models.TextField(
        blank=True,
        verbose_name="Detalle de la solicitud"
    )

    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_work_orders",
        null=True,
        blank=True,
        verbose_name="Técnico asignado"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_work_orders",
        verbose_name="Creado por"
    )

    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha programada de atención"
    )

    attended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha real de atención"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Orden de trabajo"
        verbose_name_plural = "Órdenes de trabajo"
        ordering = ["-created_at"]

        indexes = [
            models.Index(fields=["status"], name="wo_status_idx"),
            models.Index(fields=["subscription"], name="wo_subscription_idx"),
            models.Index(fields=["created_at"], name="wo_created_at_idx"),
        ]

    def clean(self):
        super().clean()

        if (
            self.reason
            and self.order_type_id
            and self.reason.order_type_id != self.order_type_id
        ):
            raise ValidationError({
                "reason": "El motivo seleccionado no pertenece al tipo de orden."
            })

        if (
            self.assigned_technician
            and self.assigned_technician.role != "TECHNICIAN"
        ):
            raise ValidationError({
                "assigned_technician": (
                    "El usuario asignado debe tener el rol de Técnico."
                )
            })

    def change_status(self, new_status, user=None, remarks=""):
        valid_statuses = {
            choice.value
            for choice in self.Status
        }

        if new_status not in valid_statuses:
            raise ValidationError({
                "status": "El estado indicado no es válido."
            })

        if self.status == new_status:
            return False

        previous_status = self.status

        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

        WorkOrderStatusHistory.objects.create(
            work_order=self,
            previous_status=previous_status,
            new_status=new_status,
            changed_by=user,
            remarks=remarks,
        )

        return True

    def __str__(self):
        return f"{self.order_number} - {self.order_type.name}"


class WorkOrderStatusHistory(models.Model):
    """Trazabilidad de cada cambio de estado de una orden."""

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Orden"
    )

    previous_status = models.CharField(
        max_length=20,
        choices=WorkOrder.Status.choices,
        blank=True,
        verbose_name="Estado anterior"
    )

    new_status = models.CharField(
        max_length=20,
        choices=WorkOrder.Status.choices,
        verbose_name="Estado nuevo"
    )

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_order_status_changes",
        null=True,
        blank=True,
        verbose_name="Usuario responsable"
    )

    remarks = models.TextField(
        blank=True,
        verbose_name="Observación"
    )

    changed_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha y hora"
    )

    class Meta:
        verbose_name = "Historial de estado"
        verbose_name_plural = "Historial de estados"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.work_order.order_number}: {self.previous_status or '-'} -> {self.new_status}"
