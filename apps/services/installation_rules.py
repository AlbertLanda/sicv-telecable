from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import InstallationMaterialRule, InstallationMaterialUsage


@transaction.atomic
def resolve_installation_material_rule(*, work_order, material, on_date=None):
    on_date = on_date or timezone.localdate()

    if work_order.order_type.code != "INSTALLATION":
        raise ValidationError(
            "Las reglas de metraje de instalación solo aplican a órdenes de instalación."
        )

    rules = (
        InstallationMaterialRule.objects
        .filter(
            material=material,
            service_type=work_order.subscription.service_type,
            is_active=True,
            valid_from__lte=on_date,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))
        .select_related("branch", "service_type")
    )

    rule = rules.filter(branch=work_order.branch).order_by("-valid_from", "-pk").first()
    if rule:
        return rule

    return rules.filter(branch__isnull=True).order_by("-valid_from", "-pk").first()


@transaction.atomic
def record_installation_material_usage(*, work_order, material, meters_used, on_date=None):
    try:
        meters_used = Decimal(str(meters_used))
    except Exception as exc:
        raise ValidationError("El metraje utilizado no es válido.") from exc

    if meters_used < 0:
        raise ValidationError("El metraje utilizado no puede ser negativo.")

    rule = resolve_installation_material_rule(
        work_order=work_order,
        material=material,
        on_date=on_date,
    )
    if rule is None:
        raise ValidationError(
            "No existe una regla de metraje vigente para este material, servicio y sede."
        )

    excess_meters = max(meters_used - rule.free_meters, Decimal("0.00"))
    excess_charge = excess_meters * rule.excess_price_per_meter

    usage, _ = InstallationMaterialUsage.objects.update_or_create(
        work_order=work_order,
        rule=rule,
        defaults={
            "meters_used": meters_used,
            "free_meters_snapshot": rule.free_meters,
            "excess_price_per_meter_snapshot": rule.excess_price_per_meter,
            "excess_meters": excess_meters,
            "excess_charge": excess_charge,
        },
    )
    usage.full_clean()
    usage.save()
    return usage


def total_installation_excess_charge(work_order):
    value = (
        work_order.installation_material_usages
        .aggregate(total=Sum("excess_charge"))
        .get("total")
    )
    return value or Decimal("0.00")
