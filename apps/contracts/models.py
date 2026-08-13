from django.db import models

from apps.customers.models import Customer
from apps.services.models import Subscription


class Contract(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        ACTIVE = "ACTIVE", "Activo"
        SUSPENDED = "SUSPENDED", "Suspendido"
        CANCELLED = "CANCELLED", "Cancelado"
        FINISHED = "FINISHED", "Finalizado"

    contract_number = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Número de contrato"
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Cliente"
    )

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Suscripción"
    )

    start_date = models.DateField(
        verbose_name="Fecha de inicio"
    )

    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de finalización"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Estado"
    )

    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones"
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
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.contract_number} - {self.customer}"