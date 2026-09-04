from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Material(models.Model):
    """Catálogo liviano de materiales/equipos usados en una OT.

    En esta etapa no representa stock ni kardex. Solo normaliza el nombre y la
    unidad con la que el técnico declara lo instalado o retirado en domicilio.
    El módulo de inventario podrá enlazar estos mismos códigos más adelante.
    """

    class Unit(models.TextChoices):
        UNIT = "UNIT", "Unidad"
        METER = "METER", "Metro"
        ROLL = "ROLL", "Rollo"
        SET = "SET", "Juego"

    code = models.CharField(max_length=40, unique=True, verbose_name="Código")
    name = models.CharField(max_length=150, verbose_name="Material")
    unit_of_measure = models.CharField(
        max_length=20,
        choices=Unit.choices,
        default=Unit.UNIT,
        verbose_name="Unidad de medida",
    )
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Material"
        verbose_name_plural = "Materiales"
        ordering = ["name"]

    def __str__(self):
        return self.name


class WorkOrderMaterialMovement(models.Model):
    """Material que entra o sale del domicilio durante la atención de una OT."""

    class MovementType(models.TextChoices):
        INSTALLED = "INSTALLED", "Instalado en domicilio"
        REMOVED = "REMOVED", "Retirado de domicilio"

    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.PROTECT,
        related_name="field_material_movements",
        verbose_name="Orden de trabajo",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name="work_order_movements",
        verbose_name="Material",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        verbose_name="Tipo de movimiento",
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Cantidad",
    )
    remarks = models.CharField(
        max_length=250,
        blank=True,
        verbose_name="Observación",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_work_order_materials",
        verbose_name="Registrado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Movimiento de material en OT"
        verbose_name_plural = "Movimientos de materiales en OT"
        ordering = ["movement_type", "material__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "material", "movement_type"],
                name="unique_material_movement_per_work_order",
            )
        ]
        indexes = [
            models.Index(fields=["work_order", "movement_type"], name="inv_wo_material_move_idx"),
        ]

    def __str__(self):
        return (
            f"{self.work_order} - {self.get_movement_type_display()} - "
            f"{self.material}: {self.quantity}"
        )
