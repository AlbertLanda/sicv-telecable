from django.db import models


class Equipment(models.Model):
    """Equipo físico (decodificador, router, ONT/módem) asignable a una suscripción."""

    class EquipmentType(models.TextChoices):
        DECODER = "DECODER", "Decodificador"
        ROUTER = "ROUTER", "Router"
        ONT = "ONT", "ONT/Módem"
        OTHER = "OTHER", "Otro"

    class Status(models.TextChoices):
        IN_STOCK = "IN_STOCK", "En stock"
        ASSIGNED = "ASSIGNED", "Asignado"
        RETIRED = "RETIRED", "Retirado"
        DAMAGED = "DAMAGED", "Dañado/Baja"

    equipment_type = models.CharField(
        max_length=20,
        choices=EquipmentType.choices,
        verbose_name="Tipo",
    )

    brand = models.CharField(
        max_length=100,
        verbose_name="Marca",
    )

    model = models.CharField(
        max_length=100,
        verbose_name="Modelo",
    )

    serial_or_mac = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Número de serie o MAC",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_STOCK,
        verbose_name="Estado",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"
        ordering = ["equipment_type", "brand", "model"]

    def __str__(self):
        return f"{self.get_equipment_type_display()} {self.brand} {self.model} — SN/MAC {self.serial_or_mac}"