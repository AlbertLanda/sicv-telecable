import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone


class BillingPolicy(models.Model):
    class Mode(models.TextChoices):
        CALENDAR_MONTH = "CALENDAR_MONTH", "Mes calendario"
        ANNIVERSARY = "ANNIVERSARY", "Aniversario de instalación"

    code = models.CharField(max_length=40, unique=True, verbose_name="Código")
    name = models.CharField(max_length=120, verbose_name="Política de cobro")
    billing_mode = models.CharField(
        max_length=20,
        choices=Mode.choices,
        verbose_name="Modalidad de vencimiento",
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Descuento por pronto pago",
    )
    discount_deadline_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Día límite de pronto pago",
        help_text="Para mes calendario. Si el mes es más corto, se usa su último día.",
    )
    discount_days_before_due = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Días antes del vencimiento para pronto pago",
    )
    cut_day_next_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Día de corte del mes siguiente",
    )
    cut_days_after_due = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Días después del vencimiento para corte",
    )
    first_month_required = models.BooleanField(
        default=True,
        verbose_name="Exige primera mensualidad al instalar",
    )
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Política de cobro"
        verbose_name_plural = "Políticas de cobro"
        ordering = ["name"]

    def clean(self):
        super().clean()

        if self.discount_deadline_day and self.discount_deadline_day > 31:
            raise ValidationError({
                "discount_deadline_day": "El día límite no puede ser mayor a 31."
            })
        if self.cut_day_next_month and self.cut_day_next_month > 31:
            raise ValidationError({
                "cut_day_next_month": "El día de corte no puede ser mayor a 31."
            })

        if self.billing_mode == self.Mode.CALENDAR_MONTH:
            if self.cut_day_next_month is None:
                raise ValidationError({
                    "cut_day_next_month": (
                        "La política por mes calendario debe indicar el día de corte."
                    )
                })
        elif self.billing_mode == self.Mode.ANNIVERSARY:
            if self.cut_days_after_due is None:
                raise ValidationError({
                    "cut_days_after_due": (
                        "La política por aniversario debe indicar cuántos días "
                        "después del vencimiento se realiza el corte."
                    )
                })

    def discount_deadline_for(self, due_date):
        if not due_date or self.discount_amount <= 0:
            return None

        if self.billing_mode == self.Mode.ANNIVERSARY:
            if self.discount_days_before_due is None:
                return None
            return due_date - timedelta(days=self.discount_days_before_due)

        if self.discount_deadline_day is None:
            return None

        last_day = calendar.monthrange(due_date.year, due_date.month)[1]
        day = min(self.discount_deadline_day, last_day)
        return date(due_date.year, due_date.month, day)

    def cut_date_for(self, due_date):
        if not due_date:
            return None

        if self.billing_mode == self.Mode.ANNIVERSARY:
            return due_date + timedelta(days=self.cut_days_after_due or 0)

        if self.cut_day_next_month is None:
            return None

        if due_date.month == 12:
            year, month = due_date.year + 1, 1
        else:
            year, month = due_date.year, due_date.month + 1

        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(self.cut_day_next_month, last_day))

    def __str__(self):
        return self.name


class ServiceType(models.Model):
    code = models.CharField(max_length=20, unique=True, verbose_name="Código")
    name = models.CharField(max_length=100, verbose_name="Servicio")
    description = models.TextField(blank=True, verbose_name="Descripción")

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
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tipo de servicio"
        verbose_name_plural = "Tipos de servicio"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Plan(models.Model):
    class Category(models.TextChoices):
        STANDARD = "STANDARD", "Estándar"
        ECONOMIC = "ECONOMIC", "Económico"
        SUPER_ECONOMIC = "SUPER_ECONOMIC", "Súper económico"

    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="plans",
        verbose_name="Tipo de servicio",
    )
    code = models.CharField(max_length=30, unique=True, verbose_name="Código")
    name = models.CharField(max_length=150, verbose_name="Plan")
    generation = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Generación",
        help_text="Año comercial del plan, por ejemplo 2024, 2025 o 2026.",
    )
    commercial_category = models.CharField(
        max_length=20,
        choices=Category.choices,
        blank=True,
        verbose_name="Categoría comercial",
    )
    billing_policy = models.ForeignKey(
        BillingPolicy,
        on_delete=models.PROTECT,
        related_name="plans",
        null=True,
        blank=True,
        verbose_name="Política de cobro",
    )
    speed_mbps = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Velocidad Mbps",
    )
    technology = models.CharField(max_length=50, blank=True, verbose_name="Tecnología")
    monthly_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Precio mensual referencial",
        help_text=(
            "Se usa como respaldo cuando el plan no requiere tarifa geográfica. "
            "La tarifa por sede/zona prevalece cuando existe."
        ),
    )
    included_tv_points = models.PositiveIntegerField(
        default=0,
        verbose_name="Máximo de TV de cortesía en instalación inicial",
        help_text=(
            "La cortesía solo puede utilizarse durante la instalación inicial. "
            "Una TV no utilizada ese día no queda pendiente para el futuro."
        ),
    )
    requires_geographic_tariff = models.BooleanField(
        default=False,
        verbose_name="Requiere tarifa por sede/zona",
        help_text=(
            "Active esta opción cuando instalación o mensualidad dependen de la "
            "ubicación, como ocurre con Cable."
        ),
    )
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plan"
        verbose_name_plural = "Planes"
        ordering = ["-generation", "commercial_category", "service_type", "speed_mbps"]

    @property
    def initial_tv_courtesy_limit(self):
        """Nombre de dominio para el campo legado `included_tv_points`."""
        return self.included_tv_points

    def clean(self):
        super().clean()

        if (
            self.included_tv_points
            and self.service_type_id
            and not self.service_type.supports_tv_annexes
        ):
            raise ValidationError({
                "included_tv_points": (
                    "Solo CABLE/DUO puede ofrecer cortesía inicial de TV."
                )
            })

    def __str__(self):
        return self.name


class PlanTariff(models.Model):
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="tariffs",
        verbose_name="Plan",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="plan_tariffs",
        verbose_name="Sede",
    )
    zone = models.ForeignKey(
        Zone,
        on_delete=models.PROTECT,
        related_name="plan_tariffs",
        null=True,
        blank=True,
        verbose_name="Zona",
        help_text="Vacío significa que aplica a toda la sede salvo una tarifa más específica.",
    )
    installation_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Costo de instalación",
    )
    monthly_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Mensualidad normal",
    )
    valid_from = models.DateField(default=date.today, verbose_name="Vigente desde")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Vigente hasta")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tarifa de plan"
        verbose_name_plural = "Tarifas de planes"
        ordering = ["plan", "branch", "zone", "-valid_from"]

    def clean(self):
        super().clean()
        if self.zone_id and self.branch_id and self.zone.branch_id != self.branch_id:
            raise ValidationError({"zone": "La zona no pertenece a la sede seleccionada."})
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "La vigencia final no puede ser anterior a la inicial."})

    def __str__(self):
        scope = self.zone.name if self.zone_id else self.branch.name
        return f"{self.plan} - {scope} - S/ {self.monthly_fee}"


class CommercialCoverageRule(models.Model):
    class Availability(models.TextChoices):
        ALLOWED = "ALLOWED", "Permitido"
        RECOMMENDED = "RECOMMENDED", "Recomendado"
        REQUIRED = "REQUIRED", "Obligatorio"
        NOT_AVAILABLE = "NOT_AVAILABLE", "No disponible"

    generation = models.PositiveSmallIntegerField(verbose_name="Generación")
    commercial_category = models.CharField(
        max_length=20,
        choices=Plan.Category.choices,
        verbose_name="Categoría comercial",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="commercial_coverage_rules",
        verbose_name="Sede",
    )
    zone = models.ForeignKey(
        Zone,
        on_delete=models.PROTECT,
        related_name="commercial_coverage_rules",
        null=True,
        blank=True,
        verbose_name="Zona",
    )
    availability = models.CharField(
        max_length=20,
        choices=Availability.choices,
        default=Availability.ALLOWED,
        verbose_name="Regla comercial",
    )
    valid_from = models.DateField(default=date.today, verbose_name="Vigente desde")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Vigente hasta")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regla comercial de cobertura"
        verbose_name_plural = "Reglas comerciales de cobertura"
        ordering = ["-generation", "branch", "zone", "commercial_category"]

    def clean(self):
        super().clean()
        if self.zone_id and self.branch_id and self.zone.branch_id != self.branch_id:
            raise ValidationError({"zone": "La zona no pertenece a la sede seleccionada."})
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "La vigencia final no puede ser anterior a la inicial."})

    def __str__(self):
        scope = self.zone.name if self.zone_id else self.branch.name
        return f"{self.generation} - {scope} - {self.get_commercial_category_display()}"


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
        verbose_name="Cliente",
    )
    address = models.ForeignKey(
        CustomerAddress,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Dirección",
    )
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Servicio",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="Plan",
    )
    tariff = models.ForeignKey(
        PlanTariff,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        null=True,
        blank=True,
        verbose_name="Tarifa aplicada",
    )
    billing_policy = models.ForeignKey(
        BillingPolicy,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        null=True,
        blank=True,
        verbose_name="Política de cobro contratada",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PRESALE,
        verbose_name="Estado",
    )
    service_number = models.PositiveIntegerField(default=1, verbose_name="Número de servicio")
    billing_cycle = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Ciclo de facturación legado",
    )
    base_installation_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Instalación base contratada",
    )
    base_monthly_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Mensualidad base contratada",
    )
    initial_tv_courtesy_granted = models.PositiveIntegerField(
        default=0,
        verbose_name="TV de cortesía otorgadas en instalación inicial",
        help_text=(
            "Es un dato histórico. Las cortesías no utilizadas durante el alta "
            "no quedan disponibles para una instalación futura."
        ),
    )
    annex_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Anexos de TV activos",
        help_text="Cantidad de puntos de TV adicionales que generan cargo mensual.",
    )
    installation_date = models.DateField(null=True, blank=True, verbose_name="Fecha de instalación")
    cut_date = models.DateField(null=True, blank=True, verbose_name="Fecha de corte")
    reconnection_date = models.DateField(null=True, blank=True, verbose_name="Fecha de reconexión")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Suscripción"
        verbose_name_plural = "Suscripciones"
        ordering = ["customer", "service_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "service_type", "service_number"],
                name="unique_customer_service_number",
            ),
        ]

    def clean(self):
        super().clean()
        if self.address_id and self.customer_id and self.address.customer_id != self.customer_id:
            raise ValidationError({"address": "La dirección seleccionada no pertenece al cliente."})
        if self.plan_id and self.service_type_id and self.plan.service_type_id != self.service_type_id:
            raise ValidationError({"plan": "El plan seleccionado no pertenece al tipo de servicio."})
        if self.tariff_id and self.plan_id and self.tariff.plan_id != self.plan_id:
            raise ValidationError({"tariff": "La tarifa aplicada no pertenece al plan seleccionado."})
        if self.service_type_id and not self.service_type.supports_tv_annexes:
            if self.annex_count or self.initial_tv_courtesy_granted:
                raise ValidationError(
                    "Internet puro no puede registrar cortesías ni anexos de TV."
                )
        if self.plan_id and self.initial_tv_courtesy_granted > self.plan.initial_tv_courtesy_limit:
            raise ValidationError({
                "initial_tv_courtesy_granted": (
                    "No se pueden otorgar más TV de cortesía que el máximo del plan."
                )
            })

    @property
    def included_tv_points(self):
        """Compatibilidad: ahora representa cortesías realmente otorgadas."""
        return self.initial_tv_courtesy_granted

    @property
    def total_tv_points(self):
        if not self.service_type.supports_tv_annexes:
            return 0
        return self.initial_tv_courtesy_granted + self.annex_count

    @property
    def annex_installation_charge(self):
        if not self.service_type.supports_tv_annexes:
            return Decimal("0.00")
        return Decimal(self.annex_count) * self.service_type.annex_installation_price

    @property
    def annex_monthly_charge(self):
        if not self.service_type.supports_tv_annexes:
            return Decimal("0.00")
        return Decimal(self.annex_count) * self.service_type.annex_monthly_price

    @property
    def total_monthly_price(self):
        return self.base_monthly_fee + self.annex_monthly_charge

    @property
    def initial_payment_amount(self):
        amount = self.base_installation_fee + self.annex_installation_charge
        if not self.billing_policy or self.billing_policy.first_month_required:
            amount += self.base_monthly_fee + self.annex_monthly_charge
        return amount

    def __str__(self):
        return f"{self.customer} - {self.plan}"


class SubscriptionAnnexAdjustment(models.Model):
    class Operation(models.TextChoices):
        ADD = "ADD", "Aumento de anexos"
        REMOVE = "REMOVE", "Retiro de anexos"

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="annex_adjustments",
        verbose_name="Suscripción",
    )
    work_order = models.OneToOneField(
        "work_orders.WorkOrder",
        on_delete=models.PROTECT,
        related_name="annex_adjustment",
        verbose_name="Orden de trabajo",
    )
    operation = models.CharField(max_length=10, choices=Operation.choices, verbose_name="Operación")
    previous_annex_count = models.PositiveIntegerField(verbose_name="Anexos antes")
    quantity = models.PositiveIntegerField(verbose_name="Cantidad a modificar")
    target_annex_count = models.PositiveIntegerField(verbose_name="Anexos resultantes")
    installation_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Cobro único de instalación",
    )
    monthly_delta = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Variación mensual",
    )
    monthly_charge_after = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Cargo mensual de anexos resultante",
    )
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name="Aplicado en la suscripción")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ajuste de anexos"
        verbose_name_plural = "Ajustes de anexos"
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        if self.quantity < 1:
            raise ValidationError({"quantity": "La cantidad de anexos debe ser mayor a cero."})
        if self.subscription_id and not self.subscription.service_type.supports_tv_annexes:
            raise ValidationError("La suscripción seleccionada no admite anexos de TV.")
        if self.work_order_id and self.subscription_id:
            if self.work_order.subscription_id != self.subscription_id:
                raise ValidationError("La OT de anexos debe pertenecer a la misma suscripción.")

        expected_target = self.previous_annex_count
        if self.operation == self.Operation.ADD:
            expected_target += self.quantity
        elif self.operation == self.Operation.REMOVE:
            if self.quantity > self.previous_annex_count:
                raise ValidationError({"quantity": "No se pueden retirar más anexos de los existentes."})
            expected_target -= self.quantity

        if self.target_annex_count != expected_target:
            raise ValidationError({
                "target_annex_count": "El total resultante no coincide con la operación solicitada."
            })

    def __str__(self):
        return (
            f"{self.subscription} - {self.get_operation_display()} "
            f"({self.previous_annex_count} → {self.target_annex_count})"
        )


class InstallationMaterialRule(models.Model):
    class Material(models.TextChoices):
        UTP = "UTP", "Cable UTP"
        RG6 = "RG6", "Cable coaxial RG6"
        DROP = "DROP", "Fibra óptica Drop"

    material = models.CharField(max_length=10, choices=Material.choices, verbose_name="Material")
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.PROTECT,
        related_name="installation_material_rules",
        verbose_name="Tipo de servicio",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="installation_material_rules",
        null=True,
        blank=True,
        verbose_name="Sede",
        help_text="Vacío significa que la regla aplica a todas las sedes.",
    )
    free_meters = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Metros incluidos",
    )
    excess_price_per_meter = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Precio por metro excedente",
    )
    valid_from = models.DateField(default=date.today, verbose_name="Vigente desde")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Vigente hasta")
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regla de metraje de instalación"
        verbose_name_plural = "Reglas de metraje de instalación"
        ordering = ["material", "service_type", "branch", "-valid_from"]

    def clean(self):
        super().clean()
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "La vigencia final no puede ser anterior a la inicial."})

    def __str__(self):
        scope = self.branch.name if self.branch_id else "Todas las sedes"
        return f"{self.get_material_display()} - {self.service_type} - {scope}"


class InstallationMaterialUsage(models.Model):
    work_order = models.ForeignKey(
        "work_orders.WorkOrder",
        on_delete=models.PROTECT,
        related_name="installation_material_usages",
        verbose_name="Orden de trabajo",
    )
    rule = models.ForeignKey(
        InstallationMaterialRule,
        on_delete=models.PROTECT,
        related_name="usages",
        verbose_name="Regla aplicada",
    )
    meters_used = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Metros utilizados")
    free_meters_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Metros incluidos aplicados",
    )
    excess_price_per_meter_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Precio aplicado por metro excedente",
    )
    excess_meters = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Metros excedentes",
    )
    excess_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Cobro por exceso",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Metraje utilizado en instalación"
        verbose_name_plural = "Metrajes utilizados en instalaciones"
        ordering = ["work_order", "rule__material"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "rule"],
                name="unique_material_rule_per_work_order",
            )
        ]

    def clean(self):
        super().clean()
        if self.meters_used < 0:
            raise ValidationError({"meters_used": "El metraje utilizado no puede ser negativo."})
        if self.work_order_id and self.rule_id:
            if self.work_order.subscription.service_type_id != self.rule.service_type_id:
                raise ValidationError("La regla de material no corresponde al servicio de la OT.")
            if self.rule.branch_id and self.work_order.branch_id != self.rule.branch_id:
                raise ValidationError("La regla de material no corresponde a la sede de la OT.")

    def __str__(self):
        return f"{self.work_order} - {self.rule.get_material_display()} - {self.meters_used} m"
