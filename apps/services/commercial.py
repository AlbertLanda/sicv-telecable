from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import CommercialCoverageRule, PlanTariff


def _active_on(queryset, on_date):
    return queryset.filter(
        is_active=True,
        valid_from__lte=on_date,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on_date))


def branch_for_address(address):
    if address.zone_id:
        return address.zone.branch
    return address.customer.branch


def resolve_plan_tariff(*, plan, address, on_date=None):
    """Devuelve la tarifa más específica: zona primero, luego sede."""
    on_date = on_date or timezone.localdate()
    branch = branch_for_address(address)

    tariffs = _active_on(
        PlanTariff.objects.filter(plan=plan, branch=branch).select_related(
            "plan", "branch", "zone"
        ),
        on_date,
    )

    if address.zone_id:
        tariff = tariffs.filter(zone=address.zone).order_by("-valid_from", "-pk").first()
        if tariff:
            return tariff

    return tariffs.filter(zone__isnull=True).order_by("-valid_from", "-pk").first()


def coverage_rules_for(*, plan, address, on_date=None):
    """
    Obtiene las reglas del ámbito más específico para generación y domicilio.

    Si existe cualquier regla configurada para la zona, esa zona gobierna el
    ámbito. En caso contrario se usan las reglas generales de la sede.
    """
    if not plan.generation:
        return CommercialCoverageRule.objects.none()

    on_date = on_date or timezone.localdate()
    branch = branch_for_address(address)

    base = _active_on(
        CommercialCoverageRule.objects.filter(
            generation=plan.generation,
            branch=branch,
        ).select_related("branch", "zone"),
        on_date,
    )

    if address.zone_id:
        zone_rules = base.filter(zone=address.zone)
        if zone_rules.exists():
            return zone_rules

    return base.filter(zone__isnull=True)


def validate_plan_commercial_availability(*, plan, address, on_date=None):
    """
    Aplica restricciones territoriales sin codificar nombres de sedes/zonas.

    - REQUIRED obliga a esa categoría en el ámbito.
    - NOT_AVAILABLE bloquea la categoría.
    - RECOMMENDED/ALLOWED permiten continuar.
    - Sin configuración explícita, el flujo permanece permitido para facilitar
      la carga progresiva de catálogos históricos.
    """
    rules = coverage_rules_for(plan=plan, address=address, on_date=on_date)

    if not rules.exists() or not plan.commercial_category:
        return None

    required = rules.filter(
        availability=CommercialCoverageRule.Availability.REQUIRED
    ).values_list("commercial_category", flat=True).first()

    if required and plan.commercial_category != required:
        required_label = dict(plan.Category.choices).get(required, required)
        raise ValidationError(
            f"Para este domicilio la categoría {required_label} es obligatoria."
        )

    selected_rule = rules.filter(
        commercial_category=plan.commercial_category
    ).order_by("-valid_from", "-pk").first()

    if selected_rule and selected_rule.availability == CommercialCoverageRule.Availability.NOT_AVAILABLE:
        raise ValidationError(
            "La categoría comercial seleccionada no está disponible para este domicilio."
        )

    return selected_rule


def build_commercial_quote(*, plan, address, on_date=None):
    """Resuelve disponibilidad, tarifa y política para una nueva suscripción."""
    rule = validate_plan_commercial_availability(
        plan=plan,
        address=address,
        on_date=on_date,
    )
    tariff = resolve_plan_tariff(plan=plan, address=address, on_date=on_date)

    if plan.requires_geographic_tariff and tariff is None:
        raise ValidationError(
            "No existe una tarifa vigente para este plan en la sede/zona del domicilio."
        )

    installation_fee = tariff.installation_fee if tariff else 0
    monthly_fee = tariff.monthly_fee if tariff else plan.monthly_price

    return {
        "tariff": tariff,
        "coverage_rule": rule,
        "billing_policy": plan.billing_policy,
        "installation_fee": installation_fee,
        "monthly_fee": monthly_fee,
    }
