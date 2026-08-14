from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organization.models import Branch, Zone
from apps.services.models import Subscription
from apps.customers.models import CustomerAddress


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

class OrderSubtype(models.Model):
    """
    Subtipo opcional de una orden.

    Ejemplos:
    - CORTE -> TEMPORAL / DEFINITIVO
    - TRASLADO -> INTERNO / EXTERNO
    """

    order_type = models.ForeignKey(
        OrderType,
        on_delete=models.PROTECT,
        related_name="subtypes",
        verbose_name="Tipo de orden"
    )

    code = models.CharField(
        max_length=30,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=120,
        verbose_name="Subtipo"
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
        verbose_name = "Subtipo de orden"
        verbose_name_plural = "Subtipos de orden"
        ordering = ["order_type", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["order_type", "code"],
                name="unique_subtype_code_per_order_type"
            )
        ]

    def __str__(self):
        return f"{self.order_type.name} - {self.name}"

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

class OrderCause(models.Model):
    """
    Causa real identificada durante la atención de una orden.

    Ejemplos:
    - DROP ROTO
    - ONU AVERIADA
    - CONFIGURACIÓN INCORRECTA
    - CLIENTE AUSENTE
    """

    order_type = models.ForeignKey(
        OrderType,
        on_delete=models.PROTECT,
        related_name="causes",
        verbose_name="Tipo de orden"
    )

    code = models.CharField(
        max_length=30,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=150,
        verbose_name="Causa"
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
        verbose_name = "Causa de orden"
        verbose_name_plural = "Causas de orden"
        ordering = ["order_type", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["order_type", "code"],
                name="unique_cause_code_per_order_type"
            )
        ]

    def __str__(self):
        return f"{self.order_type.name} - {self.name}"

class OrderResult(models.Model):
    """
    Resultado operativo final de una orden.

    Ejemplos:
    - INSTALACIÓN EXITOSA
    - NO FACTIBLE
    - RESUELTA EN CAMPO
    - RESUELTA EN NOC
    - CORTE EJECUTADO
    - TRASLADO EXITOSO
    """

    order_type = models.ForeignKey(
        OrderType,
        on_delete=models.PROTECT,
        related_name="results",
        verbose_name="Tipo de orden"
    )

    code = models.CharField(
        max_length=30,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=150,
        verbose_name="Resultado"
    )

    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )

    is_success = models.BooleanField(
        default=False,
        verbose_name="Resultado exitoso"
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
        verbose_name = "Resultado de orden"
        verbose_name_plural = "Resultados de orden"
        ordering = ["order_type", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["order_type", "code"],
                name="unique_result_code_per_order_type"
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

    subtype = models.ForeignKey(
        OrderSubtype,
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
        verbose_name="Subtipo"
    )

    reason = models.ForeignKey(
        OrderReason,
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
        verbose_name="Motivo"
    )

    cause = models.ForeignKey(
        OrderCause,
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
        verbose_name="Causa"
    )

    result = models.ForeignKey(
        OrderResult,
        on_delete=models.PROTECT,
        related_name="work_orders",
        null=True,
        blank=True,
        verbose_name="Resultado"
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
            self.subtype
            and self.order_type_id
            and self.subtype.order_type_id != self.order_type_id
        ):
            raise ValidationError({
                "subtype": "El subtipo seleccionado no pertenece al tipo de orden."
            })

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

        if (
            self.cause
            and self.order_type_id
            and self.cause.order_type_id != self.order_type_id
        ):
            raise ValidationError({
                "cause": "La causa seleccionada no pertenece al tipo de orden."
            })

        if (
            self.result
            and self.order_type_id
            and self.result.order_type_id != self.order_type_id
        ):
            raise ValidationError({
                "result": "El resultado seleccionado no pertenece al tipo de orden."
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

class CutDetail(models.Model):
    work_order = models.OneToOneField(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="cut_detail",
        verbose_name="Orden de corte"
    )

    requested_start_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha solicitada de inicio"
    )

    expected_return_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha estimada de retorno"
    )

    cancellation_reason_detail = models.TextField(
        blank=True,
        verbose_name="Detalle del motivo"
    )

    competitor = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Operador al que migra"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Detalle de corte"
        verbose_name_plural = "Detalles de corte"

    def clean(self):
        super().clean()

        if self.work_order.order_type.code != "CUT":
            raise ValidationError({
                "work_order": (
                    "El detalle de corte solo puede asociarse "
                    "a una orden de tipo CORTE."
                )
            })

        subtype = self.work_order.subtype

        if not subtype:
            raise ValidationError({
                "work_order": (
                    "La orden de corte debe indicar si es "
                    "temporal o definitiva."
                )
            })

        if subtype.code == "TEMPORARY":
            if not self.expected_return_date:
                raise ValidationError({
                    "expected_return_date": (
                        "Un corte temporal debe indicar "
                        "una fecha estimada de retorno."
                    )
                })

            if self.competitor:
                raise ValidationError({
                    "competitor": (
                        "El operador de destino solo aplica "
                        "a un corte definitivo."
                    )
                })

        elif subtype.code == "DEFINITIVE":
            if self.expected_return_date:
                raise ValidationError({
                    "expected_return_date": (
                        "Un corte definitivo no debe tener "
                        "fecha estimada de retorno."
                    )
                })

        else:
            raise ValidationError({
                "work_order": "El subtipo de corte no es válido."
            })

    def __str__(self):
        return f"Detalle corte - {self.work_order.order_number}"

class TransferDetail(models.Model):
    work_order = models.OneToOneField(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="transfer_detail",
        verbose_name="Orden de traslado"
    )

    previous_address = models.ForeignKey(
        CustomerAddress,
        on_delete=models.PROTECT,
        related_name="transfer_origins",
        null=True,
        blank=True,
        verbose_name="Dirección anterior"
    )

    new_address = models.ForeignKey(
        CustomerAddress,
        on_delete=models.PROTECT,
        related_name="transfer_destinations",
        null=True,
        blank=True,
        verbose_name="Nueva dirección"
    )

    previous_location = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Ubicación interna anterior"
    )

    new_location = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Nueva ubicación interna"
    )

    requires_additional_cabling = models.BooleanField(
        default=False,
        verbose_name="Requiere cableado adicional"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Detalle de traslado"
        verbose_name_plural = "Detalles de traslado"

    def clean(self):
        super().clean()

        if self.work_order.order_type.code != "TRANSFER":
            raise ValidationError({
                "work_order": (
                    "El detalle de traslado solo puede asociarse "
                    "a una orden de tipo TRASLADO."
                )
            })

        subtype = self.work_order.subtype

        if not subtype:
            raise ValidationError({
                "work_order": (
                    "La orden de traslado debe indicar "
                    "si es interna o externa."
                )
            })

        customer = self.work_order.subscription.customer
        current_address = self.work_order.subscription.address

        if self.previous_address:
            if self.previous_address.customer_id != customer.id:
                raise ValidationError({
                    "previous_address": (
                        "La dirección anterior debe pertenecer "
                        "al cliente de la suscripción."
                    )
                })

        if self.new_address:
            if self.new_address.customer_id != customer.id:
                raise ValidationError({
                    "new_address": (
                        "La nueva dirección debe pertenecer "
                        "al cliente de la suscripción."
                    )
                })

        if subtype.code == "INTERNAL":
            if self.new_address:
                raise ValidationError({
                    "new_address": (
                        "Un traslado interno no debe cambiar "
                        "la dirección del servicio."
                    )
                })

            if not self.previous_location:
                raise ValidationError({
                    "previous_location": (
                        "Debe indicar la ubicación interna anterior."
                    )
                })

            if not self.new_location:
                raise ValidationError({
                    "new_location": (
                        "Debe indicar la nueva ubicación interna."
                    )
                })

        elif subtype.code == "EXTERNAL":
            if not self.previous_address:
                raise ValidationError({
                    "previous_address": (
                        "Un traslado externo debe indicar "
                        "la dirección anterior."
                    )
                })

            if not self.new_address:
                raise ValidationError({
                    "new_address": (
                        "Un traslado externo requiere "
                        "una nueva dirección."
                    )
                })

            if (
                self.previous_address_id
                and self.previous_address_id != current_address.id
            ):
                raise ValidationError({
                    "previous_address": (
                        "La dirección anterior debe coincidir "
                        "con la dirección actual de la suscripción."
                    )
                })

            if (
                self.previous_address_id
                and self.new_address_id
                and self.previous_address_id == self.new_address_id
            ):
                raise ValidationError({
                    "new_address": (
                        "En un traslado externo la nueva dirección "
                        "debe ser diferente de la actual."
                    )
                })

        else:
            raise ValidationError({
                "work_order": "El subtipo de traslado no es válido."
            })

    def __str__(self):
        return f"Detalle traslado - {self.work_order.order_number}"