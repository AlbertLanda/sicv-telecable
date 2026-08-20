from django.db import models

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

    includes_internet = models.BooleanField(
        default=True,
        verbose_name="Incluye Internet",
        help_text="Marca si este servicio provee conexión a Internet.",
    )

    includes_catv = models.BooleanField(
        default=False,
        verbose_name="Incluye CATV",
        help_text="Marca si este servicio provee TV por cable.",
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
        ]

    def __str__(self):
        return f"{self.customer} - {self.plan}"