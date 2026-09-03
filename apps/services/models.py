from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.customers.models import Customer, CustomerAddress


class ServiceType(models.Model):
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Servicio"
    )

    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )

    supports_tv_annexes = models.BooleanField(
        default=False,
        verbose_name="Permite anexos de TV",
        help_text=(
            "Activar solo para servicios que incluyen señal de cable, "
            "por ejemplo CABLE o DUO."
        ),
    )

    annex_installation_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("5.00"),
        verbose_name="Costo de instalación por anexo",
        help_text=(
            "Cobro único por cada anexo nuevo. El retiro de anexos no "
            "genera costo de instalación."
        ),
    )

    annex_monthly_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("5.00"),
        verbose_name="Cargo mensual por anexo",
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
        verbose_name = "Tipo de servicio"
        verbose_name_plural = "Tipos de servicio"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Plan(models.Model):
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="plans",
        verbose_name="Tipo de servicio"
    )

    code = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Código"
    )

    name = models.CharField(
        max_length=150,
        verbose_name="Plan"
    )

    speed_mbps = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Velocidad Mbps"
    )

    technology = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Tecnología"
    )

    monthly_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Precio mensual"
    )

    included_tv_points = models.PositiveIntegerField(
        default=0,
        verbose_name="TV incluidos",
        help_text=(
            "Cantidad de televisores incluidos sin costo de anexo. "
            "Para planes CABLE/DUO actuales corresponde 2."
        ),
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
        verbose_name = "Plan"
        verbose_name_plural = "Planes"
        ordering = ["service_type", "name"]

    def clean(self):
        super().clean()

        if (
            self.included_tv_points
            and self.service_type_id
            and not self.service_type.supports_tv_annexes
        ):
            raise ValidationError({
                "included_tv_points": (
                    "Un plan solo puede incluir puntos de TV cuando su "
                    "tipo de servicio permite anexos de TV."
                )
            })

    def __str__(self):
        return self.name


class Subscription(models.Model):

    class Status(models.TextChoices):
        PRESALE = "PRESALE", "Preventa"
        INSTALLATION = "INSTALLATION", "En instalación"
        ACTIVE = "ACTIVE", "Activo"
        CUT = "CUT", "Cortado"
        SUSPENDED = "SUSPENDED", "Suspendido"
        CANCELLED = "CANCELLED", "Cancelado"

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Cliente"
    )

    address = models.ForeignKey(
        CustomerAddress,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Dirección"
    )

    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Servicio"
    )

    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Plan"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PRESALE,
        verbose_name="Estado"
    )

    service_number = models.PositiveIntegerField(
        default=1,
        verbose_name="Número de servicio"
    )

    billing_cycle = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Ciclo de facturación"
    )

    annex_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Anexos de TV",
        help_text=(
            "Cantidad de anexos adicionales vigentes/solicitados. "
            "Los TV incluidos por el plan no se cuentan como anexos."
        ),
    )

    installation_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de instalación"
    )

    cut_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de corte"
    )

    reconnection_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de reconexión"
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
        verbose_name = "Suscripción"
        verbose_name_plural = "Suscripciones"
        ordering = ["customer", "service_number"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "customer",
                    "service_type",
                    "service_number",
                ],
                name="unique_customer_service_number",
            ),
            models.UniqueConstraint(
                fields=[
                    "customer",
                    "address",
                    "service_type",
                ],
                condition=Q(is_active=True) & ~Q(status="CANCELLED"),
                name="unique_open_service_per_address",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.address_id
            and self.customer_id
            and self.address.customer_id != self.customer_id
        ):
            raise ValidationError({
                "address": "La dirección seleccionada no pertenece al cliente."
            })

        if (
            self.plan_id
            and self.service_type_id
            and self.plan.service_type_id != self.service_type_id
        ):
            raise ValidationError({
                "plan": "El plan seleccionado no pertenece al tipo de servicio."
            })

        if (
            self.service_type_id
            and not self.service_type.supports_tv_annexes
            and self.annex_count
        ):
            raise ValidationError({
                "annex_count": (
                    "Los anexos de TV no aplican al tipo de servicio seleccionado."
                )
            })

    @property
    def included_tv_points(self):
        if not self.service_type.supports_tv_annexes:
            return 0

        return self.plan.included_tv_points

    @property
    def total_tv_points(self):
        if not self.service_type.supports_tv_annexes:
            return 0

        return self.included_tv_points + self.annex_count

    @property
    def annex_installation_charge(self):
        """Cobro único correspondiente a los anexos del alta actual."""
        if not self.service_type.supports_tv_annexes:
            return Decimal("0.00")

        return (
            Decimal(self.annex_count)
            * self.service_type.annex_installation_price
        )

    @property
    def annex_monthly_charge(self):
        if not self.service_type.supports_tv_annexes:
            return Decimal("0.00")

        return Decimal(self.annex_count) * self.service_type.annex_monthly_price

    @property
    def total_monthly_price(self):
        return self.plan.monthly_price + self.annex_monthly_charge

    def __str__(self):
        return f"{self.customer} - {self.plan}"
