"""Archivo del registro manual retirado; la operación vive en las OTs."""

import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


def normalize_mac(value):
    value = (value or "").strip().upper()
    if not value:
        return ""
    compact = re.sub(r"[:.\-]", "", value)
    if not re.fullmatch(r"[0-9A-F]{12}", compact):
        raise ValidationError("Indica una MAC de 12 caracteres hexadecimales.")
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


class Equipment(models.Model):
    class Kind(models.TextChoices):
        ONT = "ONT", "ONT / Módem"
        ROUTER = "ROUTER", "Router"
        DECODER = "DECODER", "Decodificador"
        OTHER = "OTHER", "Otro equipo"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Disponible para asignar"
        ASSIGNED = "ASSIGNED", "Asignado"
        REVIEW = "REVIEW", "Retirado / por revisar"
        DAMAGED = "DAMAGED", "Dañado"

    branch = models.ForeignKey("organization.Branch", on_delete=models.PROTECT, related_name="equipment")
    kind = models.CharField("Tipo", max_length=20, choices=Kind.choices)
    brand = models.CharField("Marca", max_length=80)
    model = models.CharField("Modelo", max_length=100)
    serial_number = models.CharField("Número de serie", max_length=100, blank=True)
    mac_address = models.CharField("Dirección MAC", max_length=17, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registered_equipment")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["serial_number", "mac_address", "pk"]
        verbose_name = "Equipo de abonado"
        verbose_name_plural = "Equipos de abonados"
        permissions = [("assign_equipment", "Puede asignar y retirar equipos de abonados")]
        constraints = [
            models.CheckConstraint(condition=~Q(serial_number="") | ~Q(mac_address=""), name="equipment_has_identifier"),
            models.UniqueConstraint(fields=["serial_number"], condition=~Q(serial_number=""), name="equipment_unique_serial", violation_error_message="Ya existe un equipo con ese número de serie."),
            models.UniqueConstraint(fields=["mac_address"], condition=~Q(mac_address=""), name="equipment_unique_mac", violation_error_message="Ya existe un equipo con esa dirección MAC."),
        ]
        indexes = [models.Index(fields=["branch", "status"], name="equipment_branch_status_idx")]

    def clean(self):
        super().clean()
        self.brand = self.brand.strip()
        self.model = self.model.strip()
        self.serial_number = self.serial_number.strip().upper()
        if not self.brand or not self.model:
            raise ValidationError("Indica la marca y el modelo del equipo.")
        try:
            self.mac_address = normalize_mac(self.mac_address)
        except ValidationError as error:
            raise ValidationError({"mac_address": error.messages}) from error
        if not self.serial_number and not self.mac_address:
            raise ValidationError("Indica al menos el número de serie o la dirección MAC.")

    def __str__(self):
        return f"{self.brand} {self.model} · {self.serial_number or self.mac_address}"


class EquipmentAssignment(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="assignments")
    subscription = models.ForeignKey("services.Subscription", on_delete=models.PROTECT, related_name="equipment_assignments")
    service_code_snapshot = models.CharField(max_length=80)
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    work_order = models.ForeignKey("work_orders.WorkOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="equipment_assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="equipment_assignments")
    assigned_at = models.DateTimeField(default=timezone.now, editable=False)
    notes = models.CharField("Observación", max_length=500, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="equipment_returns")
    removed_at = models.DateTimeField(null=True, blank=True, editable=False)
    removal_reason = models.CharField("Motivo del retiro", max_length=500, blank=True)
    return_status = models.CharField(max_length=20, choices=Equipment.Status.choices, blank=True)

    class Meta:
        ordering = ["-assigned_at", "-pk"]
        verbose_name = "Asignación de equipo"
        verbose_name_plural = "Historial de equipos"
        constraints = [
            models.UniqueConstraint(fields=["equipment"], condition=Q(removed_at__isnull=True), name="equipment_one_active_assignment"),
            models.CheckConstraint(condition=Q(removed_at__isnull=True) | Q(removed_at__gte=F("assigned_at")), name="equipment_return_after_assignment"),
            models.CheckConstraint(
                condition=(Q(removed_at__isnull=True, removed_by__isnull=True, return_status="", removal_reason="")
                           | (Q(removed_at__isnull=False, removed_by__isnull=False, return_status__in=["AVAILABLE", "REVIEW", "DAMAGED"]) & ~Q(removal_reason=""))),
                name="equipment_complete_return",
            ),
        ]

    def __str__(self):
        return f"{self.equipment} → {self.service_code_snapshot}"


class EquipmentReview(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="reviews")
    previous_status = models.CharField(max_length=20, choices=Equipment.Status.choices)
    status = models.CharField(max_length=20, choices=Equipment.Status.choices)
    reason = models.CharField(max_length=500)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["-reviewed_at", "-pk"]
        verbose_name = "Revisión de equipo"
        verbose_name_plural = "Revisiones de equipos"
