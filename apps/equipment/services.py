"""Movimientos de equipos serializados; no modifica stock ni cargos."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.customers.models import Customer
from apps.services.models import Subscription
from apps.work_orders.models import WorkOrder

from .models import Equipment, EquipmentAssignment, EquipmentReview


def require_permission(user, permission):
    if not user or not user.pk or not user.is_active or not user.has_perm(permission):
        raise PermissionDenied


@transaction.atomic
def register_equipment(*, branch, user, **fields):
    require_permission(user, "equipment.add_equipment")
    if branch is None or not branch.is_active:
        raise ValidationError("Selecciona una sede activa.")
    equipment = Equipment(branch=branch, created_by=user, **fields)
    equipment.full_clean()
    try:
        with transaction.atomic():
            equipment.save()
    except IntegrityError as error:
        raise ValidationError("Ya existe un equipo con esa serie o MAC. Revisa el registro antes de continuar.") from error
    return equipment


@transaction.atomic
def assign_equipment(*, equipment, subscription, branch, user, operation_id, work_order=None, notes=""):
    require_permission(user, "equipment.assign_equipment")
    if branch is None or not branch.is_active:
        raise ValidationError("Selecciona una sede activa.")
    # Bloqueo del equipo: serializa asignaciones y retiros. La restricción
    # parcial protege también contra escritores que no usen este servicio.
    equipment = Equipment.objects.select_for_update().get(pk=equipment.pk)
    if equipment.branch_id != branch.pk:
        raise ValidationError("El equipo no pertenece a la sede activa.")
    notes = notes.strip()
    if operation_id is None:
        raise ValidationError("Falta la clave de la operación. Vuelve a abrir el formulario.")
    previous = EquipmentAssignment.objects.filter(operation_id=operation_id).first()
    if previous:
        if (previous.equipment_id, previous.subscription_id, previous.assigned_by_id, previous.work_order_id, previous.notes) != (
            equipment.pk, subscription.pk, user.pk, getattr(work_order, "pk", None), notes
        ):
            raise ValidationError("Esta operación ya fue utilizada con otros datos. Vuelve a abrir el formulario.")
        return previous  # Incluso retirada: un formulario antiguo no reactiva equipos.
    try:
        subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
        customer = Customer.objects.get(pk=subscription.customer_id)
    except (Subscription.DoesNotExist, Customer.DoesNotExist) as error:
        raise ValidationError("El servicio ya no está disponible.") from error
    if customer.branch_id != branch.pk:
        raise ValidationError("El servicio no pertenece a la sede activa.")
    if not customer.is_active or not subscription.is_active or subscription.status == Subscription.Status.CANCELLED:
        raise ValidationError("No se puede asignar un equipo a un abonado o servicio inactivo/cancelado.")
    if equipment.status != Equipment.Status.AVAILABLE or equipment.assignments.filter(removed_at__isnull=True).exists():
        raise ValidationError("El equipo ya está asignado o no está disponible.")
    if work_order is not None:
        work_order = WorkOrder.objects.get(pk=work_order.pk)
        if work_order.subscription_id != subscription.pk:
            raise ValidationError("La orden de trabajo no corresponde al servicio seleccionado.")
    assignment = EquipmentAssignment(
        equipment=equipment, subscription=subscription, assigned_by=user,
        operation_id=operation_id, work_order=work_order, notes=notes,
        service_code_snapshot=subscription.service_code,
    )
    assignment.full_clean()
    try:
        with transaction.atomic():
            assignment.save()
    except IntegrityError as error:
        raise ValidationError("La asignación cambió mientras se guardaba. Actualiza la ficha antes de continuar.") from error
    equipment.status = Equipment.Status.ASSIGNED
    equipment.save(update_fields=["status", "updated_at"])
    return assignment


@transaction.atomic
def review_equipment(*, equipment, branch, user, reason, return_status, operation_id):
    require_permission(user, "equipment.change_equipment")
    equipment = Equipment.objects.select_for_update().get(pk=equipment.pk)
    if branch is None or not branch.is_active or equipment.branch_id != branch.pk:
        raise ValidationError("El equipo no pertenece a la sede activa.")
    reason = reason.strip()
    previous = EquipmentReview.objects.filter(operation_id=operation_id).first()
    if previous:
        if (previous.equipment_id, previous.reviewed_by_id, previous.status, previous.reason) != (equipment.pk, user.pk, return_status, reason):
            raise ValidationError("Esta revisión ya fue registrada con otros datos. Abre un nuevo formulario.")
        return equipment
    if equipment.status == Equipment.Status.ASSIGNED or equipment.assignments.filter(removed_at__isnull=True).exists():
        raise ValidationError("Primero registra el retiro del equipo asignado.")
    if return_status not in (Equipment.Status.AVAILABLE, Equipment.Status.REVIEW, Equipment.Status.DAMAGED):
        raise ValidationError("El estado de revisión no es válido.")
    if len(reason) < 5:
        raise ValidationError("Explica el resultado de la revisión con al menos 5 caracteres.")
    if equipment.status == return_status:
        raise ValidationError("El equipo ya tiene ese estado. No se registró otro cambio.")
    review = EquipmentReview(equipment=equipment, previous_status=equipment.status, status=return_status, reason=reason, reviewed_by=user, operation_id=operation_id)
    review.full_clean()
    review.save()
    equipment.status = return_status
    equipment.save(update_fields=["status", "updated_at"])
    return equipment


@transaction.atomic
def remove_equipment(*, assignment, branch, user, reason, return_status):
    require_permission(user, "equipment.assign_equipment")
    equipment = Equipment.objects.select_for_update().get(pk=assignment.equipment_id)
    if branch is None or not branch.is_active or equipment.branch_id != branch.pk:
        raise ValidationError("El equipo no pertenece a la sede activa.")
    assignment = EquipmentAssignment.objects.select_for_update().get(pk=assignment.pk)
    if assignment.removed_at is not None:
        return assignment  # Un POST antiguo nunca retira la asignación siguiente.
    reason = reason.strip()
    if len(reason) < 5:
        raise ValidationError("Explica el motivo del retiro con al menos 5 caracteres.")
    if return_status not in (Equipment.Status.AVAILABLE, Equipment.Status.REVIEW, Equipment.Status.DAMAGED):
        raise ValidationError("Selecciona el estado del equipo después del retiro.")
    assignment.removed_at = timezone.now()
    assignment.removed_by = user
    assignment.removal_reason = reason
    assignment.return_status = return_status
    assignment.full_clean()
    assignment.save(update_fields=["removed_at", "removed_by", "removal_reason", "return_status"])
    equipment.status = return_status
    equipment.save(update_fields=["status", "updated_at"])
    return assignment
