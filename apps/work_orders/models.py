from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

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
        ASSIGNED = "ASSIGNED", "Asignada"
        DERIVED = "DERIVED", "Derivada"
        IN_PROGRESS = "IN_PROGRESS", "En atención"
        ATTENDED = "ATTENDED", "Atendida"
        REPROGRAMMED = "REPROGRAMMED", "Reprogramada"
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

    # Matriz oficial de transiciones. Un estado que no aparece como clave,
    # o cuya lista está vacía, es un estado terminal: no admite salidas.
    ALLOWED_TRANSITIONS = {
        Status.PENDING: [
            Status.ASSIGNED,
            Status.DERIVED,
            Status.CANCELLED,
        ],
        Status.ASSIGNED: [
            Status.IN_PROGRESS,
            Status.REPROGRAMMED,
            Status.REJECTED,
            Status.NOT_FEASIBLE,
            Status.CANCELLED,
        ],
        Status.DERIVED: [
            Status.ASSIGNED,
            Status.IN_PROGRESS,
            Status.CANCELLED,
        ],
        Status.IN_PROGRESS: [
            Status.ATTENDED,
            Status.REPROGRAMMED,
            Status.NOT_FEASIBLE,
        ],
        Status.REPROGRAMMED: [
            Status.ASSIGNED,
            Status.IN_PROGRESS,
            Status.CANCELLED,
        ],
        Status.ATTENDED: [],
        Status.REJECTED: [],
        Status.NOT_FEASIBLE: [],
        Status.CANCELLED: [],
    }

    # Estados en los que la orden ya está cerrada operativamente y no debe
    # admitir asignación, reasignación ni inicio de atención.
    TERMINAL_STATUSES = [
        Status.ATTENDED,
        Status.REJECTED,
        Status.NOT_FEASIBLE,
        Status.CANCELLED,
    ]

    # Estados desde los que se puede asignar o reasignar un técnico.
    ASSIGNABLE_STATUSES = [
        Status.PENDING,
        Status.ASSIGNED,
        Status.DERIVED,
        Status.REPROGRAMMED,
    ]

    # Estados desde los que se puede iniciar la atención.
    STARTABLE_STATUSES = [
        Status.ASSIGNED,
        Status.DERIVED,
        Status.REPROGRAMMED,
    ]

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

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Inicio real de atención"
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

        from apps.accounts.models import User

        if (
            self.assigned_technician
            and self.assigned_technician.role != User.Role.TECHNICIAN
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

    def can_transition_to(self, new_status):
        """Indica si la transición desde el estado actual está permitida."""
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, [])

    @property
    def is_closed(self):
        """La orden está cerrada operativamente y no admite más operación."""
        return self.status in self.TERMINAL_STATUSES

    @transaction.atomic
    def change_status(self, new_status, user=None, remarks=""):
        """
        Mecanismo oficial de cambio de estado.

        Valida la transición contra ALLOWED_TRANSITIONS y deja trazabilidad
        en WorkOrderStatusHistory. Si la transición no está permitida lanza
        ValidationError sin modificar la orden ni el historial.
        """
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

        if not self.can_transition_to(new_status):
            raise ValidationError({
                "status": (
                    f"Transición no permitida: "
                    f"{self.get_status_display()} -> "
                    f"{self.Status(new_status).label}."
                )
            })

        previous_status = self.status
        updated_fields = ["status", "updated_at"]

        self.status = new_status

        if new_status == self.Status.ATTENDED and not self.attended_at:
            self.attended_at = timezone.now()
            updated_fields.append("attended_at")

        self.save(update_fields=updated_fields)

        WorkOrderStatusHistory.objects.create(
            work_order=self,
            previous_status=previous_status,
            new_status=new_status,
            changed_by=user,
            remarks=remarks,
        )

        return True

    @transaction.atomic
    def assign_technician(self, technician, assigned_by=None, remarks=""):
        """
        Asignación o reasignación formal de un técnico.

        Cierra la asignación vigente (conservando al técnico anterior) y
        abre una nueva en WorkOrderAssignment. Si la orden aún no estaba
        asignada, la mueve a ASSIGNED por el mecanismo oficial.
        """
        from apps.accounts.models import User

        if technician is None:
            raise ValidationError({
                "assigned_technician": "Debe indicar un técnico."
            })

        if technician.role != User.Role.TECHNICIAN:
            raise ValidationError({
                "assigned_technician": (
                    "El usuario asignado debe tener el rol de Técnico."
                )
            })

        if not technician.is_active:
            raise ValidationError({
                "assigned_technician": (
                    "El usuario asignado debe estar activo."
                )
            })

        if self.status not in self.ASSIGNABLE_STATUSES:
            raise ValidationError({
                "status": (
                    "No se puede asignar un técnico a una orden en estado "
                    f"{self.get_status_display()}."
                )
            })

        now = timezone.now()

        # Trazabilidad del técnico anterior: la asignación vigente se cierra,
        # nunca se borra ni se sobrescribe.
        self.assignments.filter(unassigned_at__isnull=True).update(
            unassigned_at=now
        )

        assignment = WorkOrderAssignment.objects.create(
            work_order=self,
            technician=technician,
            assigned_by=assigned_by,
            assigned_at=now,
            remarks=remarks,
        )

        self.assigned_technician = technician
        self.save(update_fields=["assigned_technician", "updated_at"])

        if self.status != self.Status.ASSIGNED:
            self.change_status(
                self.Status.ASSIGNED,
                user=assigned_by,
                remarks=remarks,
            )

        return assignment

    @transaction.atomic
    def start_attention(self, user=None, remarks=""):
        """Registra el inicio real de la atención y pasa a IN_PROGRESS."""
        if self.status not in self.STARTABLE_STATUSES:
            raise ValidationError({
                "status": (
                    "No se puede iniciar la atención de una orden en estado "
                    f"{self.get_status_display()}."
                )
            })

        if not self.assigned_technician:
            raise ValidationError({
                "assigned_technician": (
                    "La orden debe tener un técnico asignado "
                    "antes de iniciar la atención."
                )
            })

        self.started_at = timezone.now()
        self.save(update_fields=["started_at", "updated_at"])

        self.change_status(
            self.Status.IN_PROGRESS,
            user=user,
            remarks=remarks,
        )

        return self.started_at

    @transaction.atomic
    def reprogram(self, new_schedule, user=None, reason=""):
        """
        Reprograma la atención conservando el histórico.

        Guarda la fecha anterior en WorkOrderReprogramming, actualiza
        scheduled_at y mueve la orden a REPROGRAMMED.
        """
        if new_schedule is None:
            raise ValidationError({
                "scheduled_at": "Debe indicar la nueva fecha de atención."
            })

        if not self.can_transition_to(self.Status.REPROGRAMMED):
            raise ValidationError({
                "status": (
                    "No se puede reprogramar una orden en estado "
                    f"{self.get_status_display()}."
                )
            })

        previous_schedule = self.scheduled_at

        if previous_schedule and new_schedule == previous_schedule:
            raise ValidationError({
                "scheduled_at": (
                    "La nueva fecha debe ser diferente "
                    "a la fecha programada actual."
                )
            })

        if new_schedule <= timezone.now():
            raise ValidationError({
                "scheduled_at": (
                    "La nueva fecha de atención debe ser futura."
                )
            })

        reprogramming = WorkOrderReprogramming.objects.create(
            work_order=self,
            previous_schedule=previous_schedule,
            new_schedule=new_schedule,
            reason=reason,
            created_by=user,
        )

        self.scheduled_at = new_schedule
        self.save(update_fields=["scheduled_at", "updated_at"])

        self.change_status(
            self.Status.REPROGRAMMED,
            user=user,
            remarks=reason,
        )

        return reprogramming

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

class WorkOrderAssignment(models.Model):
    """Historial de asignaciones y reasignaciones de técnico."""

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="Orden"
    )

    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_order_assignments",
        verbose_name="Técnico"
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_order_assignments_made",
        null=True,
        blank=True,
        verbose_name="Asignado por"
    )

    assigned_at = models.DateTimeField(
        verbose_name="Fecha de asignación"
    )

    unassigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de desasignación"
    )

    remarks = models.TextField(
        blank=True,
        verbose_name="Observación"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Asignación de orden"
        verbose_name_plural = "Historial de asignaciones"
        ordering = ["-assigned_at"]

        indexes = [
            models.Index(fields=["work_order"], name="wo_assignment_order_idx"),
            models.Index(fields=["technician"], name="wo_assignment_tech_idx"),
        ]

    @property
    def is_active(self):
        """La asignación sigue vigente mientras no haya sido cerrada."""
        return self.unassigned_at is None

    def __str__(self):
        return f"{self.work_order.order_number} -> {self.technician}"


class WorkOrderReprogramming(models.Model):
    """Historial de reprogramaciones de la atención."""

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="reprogrammings",
        verbose_name="Orden"
    )

    previous_schedule = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha programada anterior"
    )

    new_schedule = models.DateTimeField(
        verbose_name="Nueva fecha programada"
    )

    reason = models.TextField(
        blank=True,
        verbose_name="Motivo de la reprogramación"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="work_order_reprogrammings",
        null=True,
        blank=True,
        verbose_name="Registrado por"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro"
    )

    class Meta:
        verbose_name = "Reprogramación de orden"
        verbose_name_plural = "Historial de reprogramaciones"
        ordering = ["-created_at"]

        indexes = [
            models.Index(fields=["work_order"], name="wo_reprog_order_idx"),
        ]

    def __str__(self):
        return f"{self.work_order.order_number}: {self.new_schedule:%d/%m/%Y %H:%M}"


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