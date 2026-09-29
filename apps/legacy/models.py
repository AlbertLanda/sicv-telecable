from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone


class LegacyRecord(models.Model):
    """Rastro inmutable de un registro recuperado del sistema anterior.

    `raw_payload` conserva exactamente lo recibido desde SICAV. La
    interpretación que use SICV vive en `normalized_payload` y sí puede ser
    corregida, pero cada cambio queda registrado en LegacyRecordCorrection.
    """

    class Source(models.TextChoices):
        SICAV = "SICAV", "SICAV"

    class EntityType(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Abonado"
        ADDRESS = "ADDRESS", "Dirección"
        SUBSCRIPTION = "SUBSCRIPTION", "Suscripción"
        CONTRACT = "CONTRACT", "Contrato"
        PLAN_HISTORY = "PLAN_HISTORY", "Historial de plan"
        WORK_ORDER = "WORK_ORDER", "Orden de trabajo"
        CHARGE = "CHARGE", "Cargo / deuda"
        PAYMENT = "PAYMENT", "Pago"
        PAYMENT_ALLOCATION = "PAYMENT_ALLOCATION", "Aplicación de pago"
        RECEIPT = "RECEIPT", "Comprobante"
        EVIDENCE = "EVIDENCE", "Evidencia"
        EQUIPMENT = "EQUIPMENT", "Equipo"
        AUDIT_EVENT = "AUDIT_EVENT", "Auditoría"

    class ReviewStatus(models.TextChoices):
        IMPORTED = "IMPORTED", "Importado"
        REVIEW = "REVIEW", "Por revisar"
        VALIDATED = "VALIDATED", "Validado"
        CORRECTED = "CORRECTED", "Corregido"

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.SICAV,
        verbose_name="Origen",
    )
    entity_type = models.CharField(
        max_length=30,
        choices=EntityType.choices,
        verbose_name="Tipo de registro",
    )
    legacy_id = models.CharField(
        max_length=120,
        verbose_name="ID en sistema anterior",
    )

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="legacy_records",
        null=True,
        blank=True,
        verbose_name="Abonado SICV",
    )
    subscription = models.ForeignKey(
        "services.Subscription",
        on_delete=models.PROTECT,
        related_name="legacy_records",
        null=True,
        blank=True,
        verbose_name="Suscripción SICV",
    )

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="legacy_records",
        verbose_name="Tipo de objeto normalizado",
    )
    target_object_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        verbose_name="ID de objeto normalizado",
    )
    target_object = GenericForeignKey(
        "target_content_type",
        "target_object_id",
    )

    raw_payload = models.JSONField(
        default=dict,
        verbose_name="Payload original",
        help_text="Copia inmutable del dato recuperado de SICAV.",
    )
    normalized_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Interpretación normalizada",
        help_text=(
            "Representación editable usada para revisar o corregir el mapeo "
            "sin modificar el dato original."
        ),
    )

    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.IMPORTED,
        verbose_name="Estado de revisión",
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name="Notas de revisión",
    )

    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_records_imported",
        null=True,
        blank=True,
        verbose_name="Importado por",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_records_validated",
        null=True,
        blank=True,
        verbose_name="Validado por",
    )
    validated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Validado el",
    )
    imported_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Importado el",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Actualizado el",
    )

    class Meta:
        verbose_name = "Registro legacy"
        verbose_name_plural = "Registros legacy"
        ordering = ["entity_type", "legacy_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "entity_type", "legacy_id"],
                name="legacy_unique_source_entity_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source", "entity_type", "legacy_id"],
                name="legacy_source_entity_idx",
            ),
            models.Index(
                fields=["review_status"],
                name="legacy_review_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.source} · {self.get_entity_type_display()} · {self.legacy_id}"

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values_list(
                "raw_payload",
                flat=True,
            ).first()
            if original is not None and original != self.raw_payload:
                raise ValidationError({
                    "raw_payload": (
                        "El payload original de un registro legacy es "
                        "inmutable. Corrija la interpretación normalizada."
                    )
                })
        return super().save(*args, **kwargs)

    @transaction.atomic
    def apply_normalized_correction(self, new_payload, *, user=None, reason=""):
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError({
                "reason": "Indique el motivo de la corrección."
            })

        previous = self.normalized_payload
        if previous == new_payload:
            return None

        correction = LegacyRecordCorrection.objects.create(
            record=self,
            previous_payload=previous,
            new_payload=new_payload,
            reason=reason,
            corrected_by=user,
        )
        self.normalized_payload = new_payload
        self.review_status = self.ReviewStatus.CORRECTED
        self.save(update_fields=[
            "normalized_payload",
            "review_status",
            "updated_at",
        ])
        return correction

    def mark_validated(self, *, user=None, notes=""):
        self.review_status = self.ReviewStatus.VALIDATED
        self.validated_by = user
        self.validated_at = timezone.now()
        if notes:
            self.review_notes = notes
        self.save(update_fields=[
            "review_status",
            "validated_by",
            "validated_at",
            "review_notes",
            "updated_at",
        ])


class LegacyRecordCorrection(models.Model):
    """Auditoría de una corrección hecha sobre la interpretación legacy."""

    record = models.ForeignKey(
        LegacyRecord,
        on_delete=models.CASCADE,
        related_name="corrections",
        verbose_name="Registro legacy",
    )
    previous_payload = models.JSONField(
        default=dict,
        verbose_name="Valor anterior",
    )
    new_payload = models.JSONField(
        default=dict,
        verbose_name="Valor nuevo",
    )
    reason = models.TextField(
        verbose_name="Motivo de la corrección",
    )
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_record_corrections",
        null=True,
        blank=True,
        verbose_name="Corregido por",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de corrección",
    )

    class Meta:
        verbose_name = "Corrección legacy"
        verbose_name_plural = "Correcciones legacy"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Corrección {self.record} · {self.created_at:%Y-%m-%d %H:%M}"



class LegacyContractSnapshot(models.Model):
    """Contrato histórico recuperado sin convertirlo en contrato operativo.

    Puede conservar planes/estados que hoy contradicen la suscripción vigente
    porque describe lo que SICAV mostraba en ese momento. El contrato normal
    sigue aplicando sus reglas estrictas para nuevas operaciones.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        ACTIVE = "ACTIVE", "Activo"
        SUSPENDED = "SUSPENDED", "Suspendido"
        CANCELLED = "CANCELLED", "Cancelado"
        FINISHED = "FINISHED", "Finalizado"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    class Modality(models.TextChoices):
        SALE = "SALE", "Venta"
        RENTAL = "RENTAL", "Alquiler"
        OWNED = "OWNED", "Propio"
        LOAN = "LOAN", "Préstamo"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="legacy_contracts",
        verbose_name="Abonado",
    )
    subscription = models.ForeignKey(
        "services.Subscription",
        on_delete=models.PROTECT,
        related_name="legacy_contracts",
        verbose_name="Suscripción",
    )
    service_type = models.ForeignKey(
        "services.ServiceType",
        on_delete=models.PROTECT,
        related_name="legacy_contracts",
        null=True,
        blank=True,
        verbose_name="Servicio normalizado",
    )
    plan = models.ForeignKey(
        "services.Plan",
        on_delete=models.PROTECT,
        related_name="legacy_contracts",
        null=True,
        blank=True,
        verbose_name="Plan normalizado",
    )

    legacy_contract_number = models.CharField(
        max_length=60,
        blank=True,
        verbose_name="Número de contrato SICAV",
    )
    service_name_snapshot = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="Servicio histórico",
    )
    plan_name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Plan histórico",
    )
    equipment_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Equipo histórico",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNKNOWN,
        verbose_name="Estado histórico normalizado",
    )
    legacy_status = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Estado original",
    )
    modality = models.CharField(
        max_length=20,
        choices=Modality.choices,
        default=Modality.UNKNOWN,
        verbose_name="Modalidad normalizada",
    )
    installments = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Cuotas",
    )

    start_date = models.DateField(verbose_name="Inicio")
    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fin",
    )
    last_activation_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Última activación",
    )
    last_cut_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Último corte",
    )
    notes = models.TextField(blank=True, verbose_name="Observaciones")
    is_validated = models.BooleanField(default=False, verbose_name="Validado")
    validation_notes = models.TextField(
        blank=True,
        verbose_name="Notas de validación",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato histórico SICAV"
        verbose_name_plural = "Contratos históricos SICAV"
        ordering = ["subscription", "start_date", "pk"]

    def clean(self):
        super().clean()
        if self.subscription_id and self.customer_id:
            if self.subscription.customer_id != self.customer_id:
                raise ValidationError({
                    "subscription": "La suscripción no pertenece al abonado."
                })
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({
                "end_date": "La fecha final no puede ser anterior al inicio."
            })
        if self.plan_id and self.service_type_id:
            if self.plan.service_type_id != self.service_type_id:
                raise ValidationError({
                    "plan": "El plan normalizado no pertenece al servicio."
                })

    def normalized_snapshot(self):
        return {
            "subscription_id": self.subscription_id,
            "service_type_id": self.service_type_id,
            "plan_id": self.plan_id,
            "legacy_contract_number": self.legacy_contract_number,
            "service_name_snapshot": self.service_name_snapshot,
            "plan_name_snapshot": self.plan_name_snapshot,
            "equipment_snapshot": self.equipment_snapshot,
            "status": self.status,
            "legacy_status": self.legacy_status,
            "modality": self.modality,
            "installments": self.installments,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "last_activation_date": (
                self.last_activation_date.isoformat()
                if self.last_activation_date else None
            ),
            "last_cut_date": (
                self.last_cut_date.isoformat() if self.last_cut_date else None
            ),
            "notes": self.notes,
            "is_validated": self.is_validated,
            "validation_notes": self.validation_notes,
        }

    def __str__(self):
        number = self.legacy_contract_number or "sin número"
        return f"{number} · {self.subscription.service_code}"


class LegacyWorkOrderSnapshot(models.Model):
    """Orden histórica consultable sin publicarla al flujo operativo actual."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        ASSIGNED = "ASSIGNED", "Asignada"
        DERIVED = "DERIVED", "Derivada"
        IN_PROGRESS = "IN_PROGRESS", "En atención"
        ATTENDED = "ATTENDED", "Atendida"
        LIQUIDATED = "LIQUIDATED", "Liquidada"
        REPROGRAMMED = "REPROGRAMMED", "Reprogramada"
        REJECTED = "REJECTED", "Rechazada"
        NOT_FEASIBLE = "NOT_FEASIBLE", "No factible"
        CANCELLED = "CANCELLED", "Anulada"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    class AttentionType(models.TextChoices):
        SYSTEM = "SYSTEM", "Sistema"
        FIELD = "FIELD", "Física"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    class Responsibility(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Cliente"
        COMPANY = "COMPANY", "Empresa"
        OTHER = "OTHER", "Otros"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="legacy_work_orders",
        verbose_name="Abonado",
    )
    subscription = models.ForeignKey(
        "services.Subscription",
        on_delete=models.PROTECT,
        related_name="legacy_work_orders",
        verbose_name="Suscripción",
    )
    order_type = models.ForeignKey(
        "work_orders.OrderType",
        on_delete=models.PROTECT,
        related_name="legacy_work_orders",
        null=True,
        blank=True,
        verbose_name="Tipo normalizado",
    )
    reason = models.ForeignKey(
        "work_orders.OrderReason",
        on_delete=models.PROTECT,
        related_name="legacy_work_orders",
        null=True,
        blank=True,
        verbose_name="Motivo normalizado",
    )
    branch = models.ForeignKey(
        "organization.Branch",
        on_delete=models.PROTECT,
        related_name="legacy_work_orders",
        verbose_name="Sede",
    )
    zone = models.ForeignKey(
        "organization.Zone",
        on_delete=models.PROTECT,
        related_name="legacy_work_orders",
        null=True,
        blank=True,
        verbose_name="Zona",
    )

    legacy_order_number = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Número de orden SICAV",
    )
    order_type_name_snapshot = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="Tipo histórico",
    )
    reason_name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Motivo histórico",
    )
    legacy_type_code = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Código de tipo original",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNKNOWN,
        verbose_name="Estado normalizado",
    )
    legacy_status = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Estado original",
    )
    attention_type = models.CharField(
        max_length=20,
        choices=AttentionType.choices,
        default=AttentionType.UNKNOWN,
        verbose_name="Tipo de atención",
    )
    responsibility = models.CharField(
        max_length=20,
        choices=Responsibility.choices,
        default=Responsibility.UNKNOWN,
        verbose_name="Responsabilidad",
    )

    detail = models.TextField(blank=True, verbose_name="Detalle de emisión")
    attention_detail = models.TextField(
        blank=True,
        verbose_name="Detalle de atención / resultado",
    )
    technical_notes = models.TextField(
        blank=True,
        verbose_name="Observaciones técnicas",
    )

    issued_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Emitida el",
    )
    attended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Atendida el",
    )

    nap = models.CharField(max_length=100, blank=True, verbose_name="NAP")
    terminal = models.CharField(max_length=40, blank=True, verbose_name="Borne")
    equipment_code = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="MAC / equipo",
    )
    seal_number = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Precinto",
    )

    derived_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="derived_orders",
        null=True,
        blank=True,
        verbose_name="Derivada de",
        help_text=(
            "Solo se llena si el expediente confirma la relación. "
            "No se infiere únicamente por cercanía de fechas."
        ),
    )

    is_validated = models.BooleanField(default=False, verbose_name="Validado")
    validation_notes = models.TextField(
        blank=True,
        verbose_name="Notas de validación",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Orden histórica SICAV"
        verbose_name_plural = "Órdenes históricas SICAV"
        ordering = ["-issued_at", "-pk"]

    def clean(self):
        super().clean()
        if self.subscription_id and self.customer_id:
            if self.subscription.customer_id != self.customer_id:
                raise ValidationError({
                    "subscription": "La suscripción no pertenece al abonado."
                })
        if self.reason_id and self.order_type_id:
            if self.reason.order_type_id != self.order_type_id:
                raise ValidationError({
                    "reason": "El motivo no pertenece al tipo de orden."
                })
        if self.attended_at and self.issued_at and self.attended_at < self.issued_at:
            raise ValidationError({
                "attended_at": "La atención no puede ser anterior a la emisión."
            })
        if self.derived_from_id and self.derived_from_id == self.pk:
            raise ValidationError({
                "derived_from": "Una orden no puede derivarse de sí misma."
            })
        if (
            self.derived_from_id
            and self.subscription_id
            and self.derived_from.subscription_id != self.subscription_id
        ):
            raise ValidationError({
                "derived_from": (
                    "La orden de origen debe pertenecer a la misma "
                    "suscripción histórica."
                )
            })

    def normalized_snapshot(self):
        payload = {
            "subscription_id": self.subscription_id,
            "order_type_id": self.order_type_id,
            "reason_id": self.reason_id,
            "branch_id": self.branch_id,
            "zone_id": self.zone_id,
            "legacy_order_number": self.legacy_order_number,
            "order_type_name_snapshot": self.order_type_name_snapshot,
            "reason_name_snapshot": self.reason_name_snapshot,
            "legacy_type_code": self.legacy_type_code,
            "status": self.status,
            "legacy_status": self.legacy_status,
            "attention_type": self.attention_type,
            "responsibility": self.responsibility,
            "detail": self.detail,
            "attention_detail": self.attention_detail,
            "technical_notes": self.technical_notes,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "attended_at": self.attended_at.isoformat() if self.attended_at else None,
            "nap": self.nap,
            "terminal": self.terminal,
            "equipment_code": self.equipment_code,
            "seal_number": self.seal_number,
            "derived_from_id": self.derived_from_id,
            "is_validated": self.is_validated,
            "validation_notes": self.validation_notes,
        }

        if not self.pk:
            payload["participants"] = []
            payload["materials"] = []
            payload["evidences"] = []
            return payload

        payload["participants"] = [
            {
                "legacy_user_code": item.legacy_user_code,
                "name_snapshot": item.name_snapshot,
                "role_snapshot": item.role_snapshot,
                "started_at": (
                    item.started_at.isoformat() if item.started_at else None
                ),
                "ended_at": item.ended_at.isoformat() if item.ended_at else None,
                "notes": item.notes,
            }
            for item in self.participants.order_by("pk")
        ]
        payload["materials"] = [
            {
                "legacy_material_code": item.legacy_material_code,
                "name_snapshot": item.name_snapshot,
                "quantity": str(item.quantity),
                "unit_snapshot": item.unit_snapshot,
                "movement_type": item.movement_type,
                "notes": item.notes,
            }
            for item in self.materials.order_by("pk")
        ]
        payload["evidences"] = [
            {
                "original_name": item.original_name,
                "legacy_reference": item.legacy_reference,
                "file": item.file.name if item.file else "",
                "description": item.description,
            }
            for item in self.evidences.order_by("pk")
        ]
        return payload

    def __str__(self):
        number = self.legacy_order_number or f"ID {self.pk}"
        return f"{number} · {self.order_type_name_snapshot or 'OT histórica'}"


class LegacyWorkOrderParticipant(models.Model):
    work_order = models.ForeignKey(
        LegacyWorkOrderSnapshot,
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name="Orden histórica",
    )
    legacy_user_code = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Código de usuario SICAV",
    )
    name_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Nombre histórico",
    )
    role_snapshot = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Rol / participación",
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Inicio",
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fin",
    )
    notes = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Participante de OT histórica"
        verbose_name_plural = "Participantes de OT histórica"
        ordering = ["work_order", "pk"]

    def clean(self):
        super().clean()
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValidationError({
                "ended_at": "El fin no puede ser anterior al inicio."
            })


class LegacyWorkOrderMaterial(models.Model):
    class MovementType(models.TextChoices):
        INSTALLED = "INSTALLED", "Instalado"
        REMOVED = "REMOVED", "Retirado"
        USED = "USED", "Utilizado"

    work_order = models.ForeignKey(
        LegacyWorkOrderSnapshot,
        on_delete=models.CASCADE,
        related_name="materials",
        verbose_name="Orden histórica",
    )
    legacy_material_code = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Código SICAV",
    )
    name_snapshot = models.CharField(
        max_length=180,
        verbose_name="Material histórico",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=5,
        validators=[MinValueValidator(Decimal("0.00001"))],
        verbose_name="Cantidad",
    )
    unit_snapshot = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Unidad",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        default=MovementType.USED,
        verbose_name="Movimiento",
    )
    notes = models.TextField(blank=True, verbose_name="Observación")

    class Meta:
        verbose_name = "Material de OT histórica"
        verbose_name_plural = "Materiales de OT histórica"
        ordering = ["work_order", "pk"]


class LegacyWorkOrderEvidence(models.Model):
    work_order = models.ForeignKey(
        LegacyWorkOrderSnapshot,
        on_delete=models.CASCADE,
        related_name="evidences",
        verbose_name="Orden histórica",
    )
    original_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Nombre original",
    )
    legacy_reference = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Referencia SICAV",
        help_text=(
            "Ruta/identificador histórico. No contiene cookies ni tokens."
        ),
    )
    file = models.FileField(
        upload_to="legacy/work_orders/evidence/",
        blank=True,
        verbose_name="Archivo migrado",
    )
    description = models.CharField(
        max_length=240,
        blank=True,
        verbose_name="Descripción",
    )

    class Meta:
        verbose_name = "Evidencia de OT histórica"
        verbose_name_plural = "Evidencias de OT histórica"
        ordering = ["work_order", "pk"]



class LegacyChargeSnapshot(models.Model):
    """Concepto financiero histórico que ya no forma parte de la deuda viva."""

    class Status(models.TextChoices):
        PAID = "PAID", "Pagado"
        PENDING = "PENDING", "Pendiente"
        CANCELLED = "CANCELLED", "Anulado"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="legacy_charge_snapshots",
        verbose_name="Abonado",
    )
    subscription = models.ForeignKey(
        "services.Subscription",
        on_delete=models.PROTECT,
        related_name="legacy_charge_snapshots",
        null=True,
        blank=True,
        verbose_name="Suscripción",
    )
    description = models.CharField(
        max_length=180,
        verbose_name="Concepto histórico",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=5,
        default=Decimal("1.00000"),
        validators=[MinValueValidator(Decimal("0.00001"))],
        verbose_name="Cantidad",
    )
    currency = models.CharField(
        max_length=3,
        default="PEN",
        verbose_name="Moneda",
    )
    period_start = models.DateField(
        null=True,
        blank=True,
        verbose_name="Periodo desde",
    )
    period_end = models.DateField(
        null=True,
        blank=True,
        verbose_name="Periodo hasta",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Monto histórico",
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Vencimiento",
    )
    legacy_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha legacy",
        help_text=(
            "Fecha conservada desde SICAV cuya semántica exacta todavía "
            "puede estar pendiente de validación."
        ),
    )
    document_snapshot = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Documento mostrado",
    )
    observation = models.TextField(
        blank=True,
        verbose_name="Observación",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PAID,
        verbose_name="Estado histórico",
    )
    is_validated = models.BooleanField(default=False, verbose_name="Validado")
    validation_notes = models.TextField(
        blank=True,
        verbose_name="Notas de validación",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cargo histórico SICAV"
        verbose_name_plural = "Cargos históricos SICAV"
        ordering = ["period_start", "due_date", "pk"]

    def clean(self):
        super().clean()
        if self.subscription_id and self.customer_id:
            if self.subscription.customer_id != self.customer_id:
                raise ValidationError({
                    "subscription": "La suscripción no pertenece al abonado."
                })
        if self.period_end and self.period_start:
            if self.period_end < self.period_start:
                raise ValidationError({
                    "period_end": "El fin del periodo no puede preceder al inicio."
                })

    def normalized_snapshot(self):
        return {
            "subscription_id": self.subscription_id,
            "description": self.description,
            "quantity": str(self.quantity),
            "currency": self.currency,
            "period_start": (
                self.period_start.isoformat() if self.period_start else None
            ),
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "amount": str(self.amount),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "legacy_date": self.legacy_date.isoformat() if self.legacy_date else None,
            "document_snapshot": self.document_snapshot,
            "observation": self.observation,
            "status": self.status,
            "is_validated": self.is_validated,
            "validation_notes": self.validation_notes,
        }

    def __str__(self):
        return f"{self.description} · {self.currency} {self.amount}"


class LegacyPaymentSnapshot(models.Model):
    """Un cobro histórico real; no equivale a una línea del historial."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        REGISTERED = "REGISTERED", "Pagado"
        VOIDED = "VOIDED", "Anulado"
        UNKNOWN = "UNKNOWN", "Sin clasificar"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="legacy_payment_snapshots",
        verbose_name="Abonado",
    )
    branch = models.ForeignKey(
        "organization.Branch",
        on_delete=models.PROTECT,
        related_name="legacy_payment_snapshots",
        null=True,
        blank=True,
        verbose_name="Sede",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Total histórico",
    )
    currency = models.CharField(
        max_length=3,
        default="PEN",
        verbose_name="Moneda",
    )
    method_code = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Código método SICAV",
    )
    method_snapshot = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Método de pago",
    )
    reference = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Referencia / operación",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
        verbose_name="Estado histórico",
    )
    issued_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Emitido el",
    )
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Pagado el",
    )
    registered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Registrado el",
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Vencimiento del cobro",
    )
    collector_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Cobrador histórico",
    )
    registered_by_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Usuario histórico",
    )
    note = models.TextField(blank=True, verbose_name="Observación")
    is_validated = models.BooleanField(default=False, verbose_name="Validado")
    validation_notes = models.TextField(
        blank=True,
        verbose_name="Notas de validación",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pago histórico SICAV"
        verbose_name_plural = "Pagos históricos SICAV"
        ordering = ["-paid_at", "-issued_at", "-pk"]

    def normalized_snapshot(self):
        return {
            "branch_id": self.branch_id,
            "amount": str(self.amount),
            "currency": self.currency,
            "method_code": self.method_code,
            "method_snapshot": self.method_snapshot,
            "reference": self.reference,
            "status": self.status,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "registered_at": (
                self.registered_at.isoformat() if self.registered_at else None
            ),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "collector_snapshot": self.collector_snapshot,
            "registered_by_snapshot": self.registered_by_snapshot,
            "note": self.note,
            "is_validated": self.is_validated,
            "validation_notes": self.validation_notes,
        }

    def __str__(self):
        return f"{self.method_snapshot or 'Pago'} · {self.currency} {self.amount}"


class LegacyPaymentAllocationSnapshot(models.Model):
    """Qué concepto histórico cubrió un pago histórico."""

    payment = models.ForeignKey(
        LegacyPaymentSnapshot,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name="Pago histórico",
    )
    charge = models.ForeignKey(
        LegacyChargeSnapshot,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name="Cargo histórico",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Monto aplicado",
    )
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Descuento",
    )
    notes = models.CharField(
        max_length=240,
        blank=True,
        verbose_name="Observación",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Aplicación de pago histórica"
        verbose_name_plural = "Aplicaciones de pago históricas"
        ordering = ["payment", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "charge"],
                name="legacy_unique_payment_charge_allocation",
            ),
        ]

    def clean(self):
        super().clean()
        if self.payment_id and self.charge_id:
            if self.payment.customer_id != self.charge.customer_id:
                raise ValidationError({
                    "charge": "El cargo y el pago pertenecen a abonados distintos."
                })

    def normalized_snapshot(self):
        return {
            "payment_id": self.payment_id,
            "charge_id": self.charge_id,
            "amount": str(self.amount),
            "discount": str(self.discount),
            "notes": self.notes,
        }

    def __str__(self):
        return f"{self.payment} → {self.charge} · {self.amount}"


def legacy_receipt_pdf_path(instance, filename):
    return f"legacy/receipts/payment-{instance.payment_id}/pdf/{filename}"


def legacy_receipt_xml_path(instance, filename):
    return f"legacy/receipts/payment-{instance.payment_id}/xml/{filename}"


class LegacyReceiptSnapshot(models.Model):
    """Comprobante histórico y, cuando se recupere, sus archivos PDF/XML."""

    payment = models.OneToOneField(
        LegacyPaymentSnapshot,
        on_delete=models.CASCADE,
        related_name="receipt",
        verbose_name="Pago histórico",
    )
    document_snapshot = models.CharField(
        max_length=120,
        verbose_name="Documento",
    )
    series = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Serie",
    )
    number = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="Número",
    )
    document_type_snapshot = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Tipo de documento",
    )
    issuer_snapshot = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Emisor",
    )
    taxable_base = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Base gravada",
    )
    igv_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="IGV",
    )
    exempt_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Importe exonerado",
    )
    other_tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Otros tributos",
    )
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Total documento",
    )
    issued_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Emitido el",
    )
    pdf_file = models.FileField(
        upload_to=legacy_receipt_pdf_path,
        blank=True,
        verbose_name="PDF histórico",
    )
    xml_file = models.FileField(
        upload_to=legacy_receipt_xml_path,
        blank=True,
        verbose_name="XML histórico",
    )
    legacy_pdf_reference = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Referencia PDF SICAV",
    )
    legacy_xml_reference = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Referencia XML SICAV",
    )
    is_validated = models.BooleanField(default=False, verbose_name="Validado")
    validation_notes = models.TextField(
        blank=True,
        verbose_name="Notas de validación",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Comprobante histórico SICAV"
        verbose_name_plural = "Comprobantes históricos SICAV"
        ordering = ["-issued_at", "-pk"]

    def normalized_snapshot(self):
        return {
            "payment_id": self.payment_id,
            "document_snapshot": self.document_snapshot,
            "series": self.series,
            "number": self.number,
            "document_type_snapshot": self.document_type_snapshot,
            "issuer_snapshot": self.issuer_snapshot,
            "taxable_base": (
                str(self.taxable_base) if self.taxable_base is not None else None
            ),
            "igv_amount": (
                str(self.igv_amount) if self.igv_amount is not None else None
            ),
            "exempt_amount": (
                str(self.exempt_amount) if self.exempt_amount is not None else None
            ),
            "other_tax_amount": str(self.other_tax_amount),
            "total": str(self.total),
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "legacy_pdf_reference": self.legacy_pdf_reference,
            "legacy_xml_reference": self.legacy_xml_reference,
            "is_validated": self.is_validated,
            "validation_notes": self.validation_notes,
        }

    def __str__(self):
        return self.document_snapshot
