from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from apps.services.models import Subscription


INCOMPLETE_STAGES = {
    "SUBSCRIPTION",
    "CONTRACT",
    "INSTALLATION_ORDER",
}


def customer_onboarding_state(customer):
    """Deriva el progreso real del alta comercial sin guardar un estado duplicado."""
    subscriptions = list(
        customer.subscriptions
        .filter(is_active=True)
        .select_related("service_type", "plan")
        .prefetch_related("contracts", "work_orders__order_type")
        .order_by("created_at", "pk")
    )

    active = [
        item for item in subscriptions
        if item.status == Subscription.Status.ACTIVE
    ]
    pending = [
        item for item in subscriptions
        if item.status in (
            Subscription.Status.PRESALE,
            Subscription.Status.INSTALLATION,
        )
    ]

    if not subscriptions:
        return {
            "stage": "SUBSCRIPTION",
            "label": "Alta incompleta",
            "detail": "Falta registrar el servicio y plan.",
            "incomplete": True,
            "next_url": reverse(
                "services:subscription_create",
                kwargs={"customer_pk": customer.pk},
            ),
            "next_label": "Continuar alta",
            "subscription": None,
            "contract": None,
        }

    for subscription in pending:
        contract = (
            subscription.contracts
            .filter(is_active=True)
            .order_by("-created_at", "-pk")
            .first()
        )

        if contract is None:
            return {
                "stage": "CONTRACT",
                "label": "Alta incompleta",
                "detail": (
                    f"{subscription.service_code}: falta generar el contrato."
                ),
                "incomplete": True,
                "next_url": (
                    reverse(
                        "contracts:contract_create",
                        kwargs={"customer_pk": customer.pk},
                    )
                    + f"?subscription={subscription.pk}"
                ),
                "next_label": "Continuar alta",
                "subscription": subscription,
                "contract": None,
            }

        installation = (
            subscription.work_orders
            .filter(order_type__code="INSTALLATION")
            .order_by("-created_at", "-pk")
            .first()
        )

        if installation is None:
            return {
                "stage": "INSTALLATION_ORDER",
                "label": "Alta incompleta",
                "detail": (
                    f"{subscription.service_code}: falta generar la OT de instalación."
                ),
                "incomplete": True,
                "next_url": reverse(
                    "contracts:generate_installation_order",
                    kwargs={
                        "customer_pk": customer.pk,
                        "pk": contract.pk,
                    },
                ),
                "next_label": "Continuar alta",
                "subscription": subscription,
                "contract": contract,
            }

        return {
            "stage": "PENDING_INSTALLATION",
            "label": "Pendiente de instalación",
            "detail": (
                f"{subscription.service_code}: la contratación ya tiene OT "
                "de instalación."
            ),
            "incomplete": False,
            "next_url": reverse(
                "customers:orders",
                kwargs={"pk": customer.pk},
            ),
            "next_label": "Ver instalación",
            "subscription": subscription,
            "contract": contract,
        }

    if active:
        return {
            "stage": "ACTIVE",
            "label": "Cliente activo",
            "detail": "Tiene al menos un servicio instalado.",
            "incomplete": False,
            "next_url": reverse(
                "customers:detail",
                kwargs={"pk": customer.pk},
            ),
            "next_label": "Ver ficha",
            "subscription": active[0],
            "contract": None,
        }

    return {
        "stage": "HISTORICAL",
        "label": "Sin alta pendiente",
        "detail": "No hay una contratación incompleta para continuar.",
        "incomplete": False,
        "next_url": reverse(
            "customers:detail",
            kwargs={"pk": customer.pk},
        ),
        "next_label": "Ver ficha",
        "subscription": subscriptions[0] if subscriptions else None,
        "contract": None,
    }


def incomplete_registration_issues(customer):
    """Bloqueos que impiden borrar físicamente una alta aún incompleta."""
    from apps.contracts.models import ContractSignature
    from apps.payments.models import Charge, Payment, PaymentCommitment, ProposedCharge

    subscriptions = customer.subscriptions.all()

    invalid_status = subscriptions.exclude(
        status=Subscription.Status.PRESALE
    ).exists()
    issues = []

    if invalid_status:
        issues.append(
            "Existe una suscripción que ya no está únicamente en preventa."
        )

    if subscriptions.filter(installation_date__isnull=False).exists():
        issues.append("Existe un servicio con fecha de instalación.")

    if subscriptions.filter(work_orders__isnull=False).exists():
        issues.append(
            "Ya existe una orden de trabajo. Use el flujo de desistimiento "
            "de la instalación para conservar su trazabilidad."
        )

    if ContractSignature.objects.filter(
        contract__customer=customer
    ).exists():
        issues.append("Existe un contrato firmado por el abonado.")

    if customer.contracts.filter(
        last_activation_date__isnull=False
    ).exists():
        issues.append("Existe un contrato que ya registra activación.")

    if Charge.objects.filter(customer=customer).exists():
        issues.append("El abonado ya tiene cargos/deuda emitida.")

    if ProposedCharge.objects.filter(customer=customer).exists():
        issues.append("El abonado ya tiene propuestas económicas.")

    if Payment.objects.filter(customer=customer).exists():
        issues.append("El abonado ya tiene pagos/comprobantes registrados.")

    if PaymentCommitment.objects.filter(customer=customer).exists():
        issues.append("El abonado ya tiene compromisos de pago.")

    return issues


@transaction.atomic
def discard_incomplete_registration(*, customer, user, reason):
    """Elimina un alta comercial que nunca produjo un hecho real."""
    if user is None or user.pk is None or not user.is_active:
        raise ValidationError(
            "Debe indicar un usuario activo que descarte el alta."
        )

    if not user.has_perm("customers.discard_incomplete_registration"):
        raise ValidationError(
            "El usuario no está autorizado para descartar altas incompletas."
        )

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationError(
            "Indique el motivo del descarte con al menos 5 caracteres."
        )

    from apps.customers.models import Customer, IncompleteRegistrationDiscard

    try:
        locked = (
            Customer.objects
            .select_for_update()
            .select_related("branch")
            .get(pk=customer.pk)
        )
    except Customer.DoesNotExist as exc:
        raise ValidationError("El alta ya no existe.") from exc

    state = customer_onboarding_state(locked)
    if not state["incomplete"]:
        raise ValidationError(
            "Este abonado ya no tiene un alta incompleta que pueda descartarse."
        )

    issues = incomplete_registration_issues(locked)
    if issues:
        raise ValidationError(issues)

    customer_code = locked.code
    branch_code = locked.branch.code
    stage = state["stage"]

    try:
        # Solo quedan contratos sin firma/activación y suscripciones PRESALE,
        # porque las validaciones anteriores excluyen cualquier hecho real.
        locked.contracts.all().delete()
        locked.subscriptions.all().delete()
        locked.delete()
    except ProtectedError as exc:
        raise ValidationError(
            "El alta tiene información histórica protegida y no puede "
            "eliminarse físicamente."
        ) from exc

    audit = IncompleteRegistrationDiscard.objects.create(
        released_customer_code=customer_code,
        branch_code=branch_code,
        stage=stage,
        reason=reason,
        discarded_by=user,
    )

    return audit
