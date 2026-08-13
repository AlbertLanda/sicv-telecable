from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.organization.models import Branch, Office


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        ATC = "ATC", "Atención al Cliente"
        SALES = "SALES", "Ventas"
        NOC = "NOC", "NOC"
        TECHNICIAN = "TECHNICIAN", "Técnico"
        WAREHOUSE = "WAREHOUSE", "Almacén"
        SUPERVISOR = "SUPERVISOR", "Supervisor"
        RETENTION = "RETENTION", "Retenciones"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ATC,
        verbose_name="Rol"
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="Sede"
    )

    office = models.ForeignKey(
        Office,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="Oficina"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.get_full_name() or self.username