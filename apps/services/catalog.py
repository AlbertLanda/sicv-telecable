"""Catalogo comercial servido al navegador.

Servicio y plan son un solo dato en dos combos: elegir el servicio decide que
planes existen. El servidor manda el catalogo completo en la pantalla y el
combo de planes se repinta sin ir y volver, que es como funcionaba ya el alta
de suscripcion.

Vivia dentro de `views.py` de este modulo, privado, cuando la unica pantalla
que lo necesitaba era esa. El contrato de servicio pide exactamente lo mismo,
y una copia del mismo agrupamiento en otra app se separa del original al
primer campo que se agregue al plan.
"""

from collections import defaultdict

from .models import Plan, ServiceType


def plans_by_service_type():
    """Planes activos agrupados por el servicio al que pertenecen."""

    grouped = defaultdict(list)
    plans = (
        Plan.objects
        .filter(is_active=True)
        .select_related("billing_policy", "included_app_plan")
        .order_by(
            "service_type_id",
            "-generation",
            "commercial_category",
            "speed_mbps",
            "name",
        )
    )

    for plan in plans:
        grouped[plan.service_type_id].append(
            {
                "id": plan.pk,
                "label": str(plan),
                "generation": plan.generation,
                "category": (
                    plan.get_commercial_category_display()
                    if plan.commercial_category
                    else ""
                ),
                "initial_tv_courtesy_limit": plan.initial_tv_courtesy_limit,
                "monthly_price": str(plan.monthly_price),
                "included_app_plan_id": plan.included_app_plan_id,
                "included_app_label": (
                    str(plan.included_app_plan)
                    if plan.included_app_plan_id
                    else ""
                ),
                "included_app_component_amount": str(
                    plan.included_app_component_amount
                ),
                "requires_geographic_tariff": plan.requires_geographic_tariff,
                "billing_policy": (
                    str(plan.billing_policy) if plan.billing_policy_id else ""
                ),
            }
        )

    return dict(grouped)


def service_type_config():
    """Lo que cada servicio habilita en la pantalla que lo ofrece."""

    return {
        service_type.pk: {
            "supports_tv_annexes": service_type.supports_tv_annexes,
            "annex_installation_price": str(service_type.annex_installation_price),
            "annex_monthly_price": str(service_type.annex_monthly_price),
            "requires_playhub_account": service_type.requires_playhub_account,
        }
        for service_type in ServiceType.objects.filter(is_active=True)
    }
