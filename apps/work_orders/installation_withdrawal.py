from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.contracts.models import ContractSignature
from apps.customers.models import Customer, CustomerAddress
from apps.inventory.models import WorkOrderMaterialMovement
from apps.payments.models import Charge, ProposedCharge
from apps.services.models import Subscription

from .models import (
    InstallationWithdrawal,
    WorkOrder,
    WorkOrderEvidence,
    WorkOrderFieldSheet,
    WorkOrderLiquidation,
)


WITHDRAWABLE_ORDER_STATUSES = {
    WorkOrder.Status.PENDING,
    WorkOrder.Status.ASSIGNED,
    WorkOrder.Status.DERIVED,
    WorkOrder.Status.IN_PROGRESS,
    WorkOrder.Status.REPROGRAMMED,
    WorkOrder.Status.CANCELLED,
}

WITHDRAWABLE_SUBSCRIPTION_STATUSES = {
    Subscription.Status.PRESALE,
    Subscription.Status.INSTALLATION,
}


def installation_withdrawal_issues(order):
    """Razones por las que un alta ya no puede borrarse como provisional."""
    issues = []

    if order.pk is None:
        return ["La orden de instalación no está registrada."]

    if order.order_type_id is None or order.order_type.code != "INSTALLATION":
        return ["El desistimiento solo aplica a órdenes de instalación."]

    if order.subscription_id is None:
        return ["La instalación no tiene una suscripción asociada."]

    subscription = order.subscription

    if subscription.status not in WITHDRAWABLE_SUBSCRIPTION_STATUSES:
        issues.append(
            "La suscripción ya no está en preventa/en instalación."
        )

    if subscription.installation_date is not None:
        issues.append(
            "La suscripción ya tiene fecha de instalación registrada."
        )

    installation_orders = subscription.work_orders.filter(
        order_type__code="INSTALLATION"
    )
    other_orders = subscription.work_orders.exclude(
        order_type__code="INSTALLATION"
    )

    if other_orders.exists():
        issues.append(
            "La suscripción ya tiene otras órdenes de trabajo asociadas."
        )

    if installation_orders.exclude(
        status__in=WITHDRAWABLE_ORDER_STATUSES
    ).exists():
        issues.append(
            "Existe una instalación con resultado técnico o cierre definitivo."
        )

    if ContractSignature.objects.filter(
        contract__subscription=subscription
    ).exists():
        issues.append(
            "El contrato ya fue firmado por el abonado."
        )

    if subscription.contracts.filter(
        last_activation_date__isnull=False
    ).exists():
        issues.append(
            "Existe un contrato que ya registra activación del servicio."
        )

    if Charge.objects.filter(subscription=subscription).exists():
        issues.append(
            "La suscripción ya tiene cargos/deuda emitida."
        )

    if ProposedCharge.objects.filter(subscription=subscription).exists():
        issues.append(
            "La suscripción ya tiene una propuesta económica asociada."
        )

    if WorkOrderMaterialMovement.objects.filter(
        work_order__in=installation_orders
    ).exists():
        issues.append(
            "El técnico ya registró movimientos de materiales."
        )

    if WorkOrderEvidence.objects.filter(
        work_order__in=installation_orders
    ).exists():
        issues.append(
            "La instalación ya tiene evidencias de campo."
        )

    if WorkOrderFieldSheet.objects.filter(
        work_order__in=installation_orders
    ).exists():
        issues.append(
            "La instalación ya tiene ficha técnica de campo."
        )

    if WorkOrderLiquidation.objects.filter(
        work_order__in=installation_orders
    ).exists():
        issues.append(
            "La instalación ya tiene liquidación técnica."
        )

    return issues


def installation_withdrawal_preview(order):
    issues = installation_withdrawal_issues(order)
    subscription = order.subscription
    customer = subscription.customer
    address = subscription.address

    return {
        "eligible": not issues,
        "issues": issues,
        "service_code": subscription.service_code,
        "customer_code": customer.code,
        "customer_would_be_deleted": not customer.subscriptions.exclude(
            pk=subscription.pk
        ).exists(),
        "address_would_be_orphan": not address.subscriptions.exclude(
            pk=subscription.pk
        ).exists(),
    }


@transaction.atomic
def withdraw_pending_installation(*, order, user, reason):
    """Elimina una contratación que nunca llegó a convertirse en servicio.

    Solo borra datos provisionales. Si existe un hecho técnico, contractual o
    económico real, se rechaza y el caso debe seguir los flujos de anulación
    que conservan historial.
    """
    if user is None or user.pk is None or not user.is_active:
        raise ValidationError(
            "Debe indicar un usuario activo que registre el desistimiento."
        )

    if not user.has_perm("work_orders.withdraw_installation"):
        raise ValidationError(
            "El usuario no está autorizado para registrar desistimientos."
        )

    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValidationError(
            "Indique el motivo del desistimiento con al menos 5 caracteres."
        )

    try:
        locked_order = (
            WorkOrder.objects
            .select_for_update()
            .select_related(
                "order_type",
                "subscription__customer__branch",
                "subscription__address__zone__branch",
            )
            .get(pk=order.pk)
        )
    except WorkOrder.DoesNotExist as exc:
        raise ValidationError(
            "La orden ya no existe o ya fue retirada."
        ) from exc

    subscription = (
        Subscription.objects
        .select_for_update()
        .select_related(
            "customer__branch",
            "address__zone__branch",
            "service_type",
        )
        .get(pk=locked_order.subscription_id)
    )
    locked_order.subscription = subscription

    issues = installation_withdrawal_issues(locked_order)
    if issues:
        raise ValidationError(issues)

    customer = Customer.objects.select_for_update().get(
        pk=subscription.customer_id
    )
    address_id = subscription.address_id

    order_number = locked_order.order_number
    customer_code = customer.code
    service_code = subscription.service_code
    branch_code = (
        subscription.address.zone.branch.code
        if subscription.address.zone_id
        else customer.branch.code
    )

    installation_orders = subscription.work_orders.filter(
        order_type__code="INSTALLATION"
    )

    try:
        # Todo lo que cuelga de estas OTs es exclusivamente provisional en
        # este punto: las validaciones anteriores ya descartaron material,
        # evidencia, ficha técnica, liquidación y firma.
        installation_orders.delete()

        # Los contratos sin firma ni activación son documentos provisionales.
        subscription.contracts.all().delete()

        # La suscripción es la que mantiene ocupado el service_number/código.
        subscription.delete()
    except ProtectedError as exc:
        raise ValidationError(
            "La contratación tiene información histórica protegida y no puede "
            "eliminarse como alta provisional."
        ) from exc

    # Si el domicilio fue creado solo para esta contratación, se retira. Si
    # alguna evidencia histórica lo protege, se conserva sin abortar el resto.
    if address_id:
        address = CustomerAddress.objects.filter(pk=address_id).first()
        if address is not None and not address.subscriptions.exists():
            try:
                with transaction.atomic():
                    address.delete()
            except ProtectedError:
                pass

    customer_deleted = False
    customer = Customer.objects.filter(pk=customer.pk).first()

    # Un abonado con otro servicio sigue siendo la misma persona: solo se
    # elimina el Customer si esta alta era lo único que tenía y ninguna otra
    # relación histórica/financiera lo protege.
    if customer is not None and not customer.subscriptions.exists():
        try:
            with transaction.atomic():
                customer.delete()
            customer_deleted = True
        except ProtectedError:
            customer_deleted = False

    withdrawal = InstallationWithdrawal.objects.create(
        order_number=order_number,
        branch_code=branch_code,
        released_customer_code=customer_code if customer_deleted else "",
        released_service_code=service_code,
        reason=reason,
        withdrawn_by=user,
        customer_deleted=customer_deleted,
    )

    return {
        "withdrawal": withdrawal,
        "order_number": order_number,
        "service_code": service_code,
        "customer_code": customer_code,
        "customer_deleted": customer_deleted,
    }
