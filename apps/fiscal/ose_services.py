"""Preparación y ejecución recuperable de pruebas OSE, sin emisión real."""
from datetime import timedelta
import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.payments.models import Issuer
from .models import (FiscalDocument, OseConnection, OseConnectionRevision,
                     OseSimulation, OseSimulationAttempt, OseSimulationEvent)
from .services import _require
from .ose_transport import (DefinitelyNotSent, DeliveryUncertain, OseEnvelope,
                            OseResponse, payload_bytes, payload_digest, resolve_transport)

CONNECTION_FIELDS = ("mode", "provider_name", "test_endpoint", "production_endpoint",
                     "username_setting", "password_setting", "certificate_setting", "certificate_password_setting")
LEASE_DURATION = timedelta(minutes=3)


def connection_snapshot(connection):
    return {field: getattr(connection, field) for field in CONNECTION_FIELDS}


def simulations_enabled():
    return bool(getattr(settings, "FISCAL_SIMULATION_ENABLED", False)) and (
        not getattr(settings, "PRODUCTION", False)
        or getattr(settings, "FISCAL_QA_SIMULATION_ALLOWED", False)
    )


def _require_simulation(actor):
    _require(actor, "fiscal.simulate_ose")
    _require(actor, "fiscal.view_fiscaldocument")
    if not simulations_enabled():
        raise ValidationError("Las pruebas OSE requieren un entorno de prueba habilitado. No se ejecutan en producción.")


@transaction.atomic
def save_connection(*, actor, issuer_id, values):
    _require(actor, "fiscal.configure_ose")
    issuer = Issuer.objects.select_for_update().get(pk=issuer_id, is_active=True)
    connection = OseConnection.objects.filter(issuer=issuer).first() or OseConnection(issuer=issuer)
    for field in CONNECTION_FIELDS:
        if field in values:
            setattr(connection, field, values[field])
    connection.updated_by = actor
    connection.full_clean()
    connection.save()
    OseConnectionRevision.objects.create(connection=connection, actor=actor, snapshot=connection_snapshot(connection))
    return connection


@transaction.atomic
def prepare_simulation(*, actor, branch, document_id, scenario, request_key):
    _require_simulation(actor)
    try:
        key = uuid.UUID(str(request_key))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Abra un nuevo formulario de prueba.")
    if scenario not in OseSimulation.Scenario.values:
        raise ValidationError("Seleccione un escenario de prueba válido.")
    document = FiscalDocument.objects.select_for_update().filter(pk=document_id, branch=branch).first()
    if document is None or branch is None:
        raise ValidationError("El borrador no pertenece a la sede activa.")
    fingerprint = hashlib.sha256(json.dumps(dict(document=document.pk, actor=actor.pk, scenario=scenario), sort_keys=True).encode()).hexdigest()
    old = OseSimulation.objects.filter(request_key=key).first()
    if old:
        if old.request_fingerprint != fingerprint:
            raise ValidationError("La clave ya corresponde a otra prueba. Abra un nuevo formulario.")
        return old
    if document.status != FiscalDocument.Status.DRAFT or not document.issuer.is_active:
        raise ValidationError("La prueba requiere un borrador vigente y una empresa activa.")
    connection = OseConnection.objects.select_for_update().filter(issuer=document.issuer, mode="SIMULATOR").first()
    if connection is None:
        raise ValidationError("Configure el simulador local para esta empresa antes de preparar la prueba.")
    payload = dict(simulation_only=True, schema="SICV_OSE_SIMULATION_V1",
                   draft_reference=str(document.public_id), issuer_ruc=document.snapshot["issuer"]["ruc"],
                   document_type=document.document_type, currency=document.currency,
                   source_total=str(document.source_total), draft_snapshot=document.snapshot)
    try:
        with transaction.atomic():
            simulation = OseSimulation.objects.create(document=document, request_key=key,
                request_fingerprint=fingerprint, scenario=scenario,
                connection_snapshot=connection_snapshot(connection), payload=payload,
                payload_hash=payload_digest(payload), created_by=actor)
            OseSimulationEvent.objects.create(simulation=simulation, action="CREATED", actor=actor)
    except IntegrityError:
        if OseSimulation.objects.filter(request_key=key).exists():
            raise ValidationError("La clave ya corresponde a otra prueba. Abra un nuevo formulario.")
        raise
    return simulation


@transaction.atomic
def _claim(*, simulation_id, actor, branch):
    _require_simulation(actor)
    # Orden común: borrador, prueba. Nunca bloquear filas mientras se espera al
    # proveedor: el intento se confirma antes de ejecutar el adaptador.
    document_id = OseSimulation.objects.values_list("document_id", flat=True).get(pk=simulation_id)
    document = FiscalDocument.objects.select_for_update().filter(pk=document_id, branch=branch).first()
    if document is None or branch is None:
        raise ValidationError("La prueba no pertenece a la sede activa.")
    simulation = OseSimulation.objects.select_for_update().get(pk=simulation_id)
    if simulation.is_terminal:
        return simulation, None
    if document.status != FiscalDocument.Status.DRAFT or not document.issuer.is_active:
        raise ValidationError("El borrador está descartado o la empresa está inactiva.")
    if not OseConnection.objects.filter(issuer=document.issuer, mode="SIMULATOR").exists():
        raise ValidationError("El simulador de la empresa está deshabilitado.")
    if simulation.connection_snapshot.get("mode") != "SIMULATOR" or payload_digest(simulation.payload) != simulation.payload_hash:
        raise ValidationError("La evidencia de prueba no corresponde al simulador o su contenido cambió.")
    now = timezone.now()
    if simulation.state == OseSimulation.State.WORKING:
        if simulation.lease_until > now:
            raise ValidationError("La prueba ya está en ejecución. Consulte su estado antes de repetirla.")
        interrupted = simulation.attempts.get(token=simulation.lease_token)
        interrupted.outcome, interrupted.finished_at = "ABANDONED", now
        interrupted.message = "Ejecución interrumpida; se consulta antes de repetir el envío."
        interrupted.save(update_fields=["outcome", "finished_at", "message"])
        simulation.state = OseSimulation.State.UNCERTAIN
        OseSimulationEvent.objects.create(simulation=simulation, action="RECOVERED", actor=actor, message=interrupted.message)
    operation = "QUERY" if simulation.state in ("PROCESSING", "UNCERTAIN") else "SUBMIT"
    number = (simulation.attempts.aggregate(last=Max("number"))["last"] or 0) + 1
    token = uuid.uuid4()
    attempt = OseSimulationAttempt.objects.create(simulation=simulation, number=number,
        token=token, operation=operation, actor=actor)
    simulation.state, simulation.lease_token, simulation.lease_until = "WORKING", token, now + LEASE_DURATION
    simulation.save(update_fields=["state", "lease_token", "lease_until"])
    OseSimulationEvent.objects.create(simulation=simulation, action="STARTED", actor=actor, message=f"Intento {number}: {operation} simulado.")
    return simulation, attempt


@transaction.atomic
def _finish(*, simulation_id, attempt, actor, result=None, error=None):
    simulation = OseSimulation.objects.select_for_update().get(pk=simulation_id)
    # Una respuesta atrasada no sobrescribe el resultado de un intento nuevo.
    if simulation.lease_token != attempt.token or simulation.state != "WORKING":
        return simulation
    response = {}
    message = ""
    outcome = "DONE"
    if error == "NOT_SENT" and attempt.operation == "SUBMIT":
        state, outcome = "RETRYABLE", "FAILED"
        message = "El simulador confirmó que no recibió el envío; se permite reintentar."
    elif error:
        state, outcome = "UNCERTAIN", "FAILED"
        message = "Sin respuesta concluyente. Consulte antes de volver a enviar."
    else:
        valid = (isinstance(result, OseResponse) and result.simulated is True
                 and result.request_id == simulation.public_id and result.payload_hash == simulation.payload_hash
                 and result.result in ("ACCEPTED", "OBSERVED", "REJECTED", "PROCESSING", "NOT_FOUND")
                 and isinstance(result.ticket, str) and len(result.ticket) <= 100
                 and isinstance(result.code, str) and 0 < len(result.code) <= 50
                 and isinstance(result.message, str) and len(result.message) <= 200
                 and (result.result != "NOT_FOUND" or attempt.operation == "QUERY")
                 and (result.result not in ("ACCEPTED", "OBSERVED", "REJECTED", "PROCESSING") or bool(result.ticket)))
        if not valid:
            state, outcome = "UNCERTAIN", "FAILED"
            message = "La respuesta no corresponde a esta prueba. Consulte el estado."
        else:
            state = "RETRYABLE" if result.result == "NOT_FOUND" else result.result
            response = result.as_dict()
            message = result.message
            simulation.ticket = result.ticket
    simulation.state, simulation.response = state, response
    simulation.lease_token, simulation.lease_until = None, None
    simulation.save(update_fields=["state", "ticket", "response", "lease_token", "lease_until"])
    current = simulation.attempts.get(token=attempt.token)
    current.outcome, current.response, current.message, current.finished_at = outcome, response, message, timezone.now()
    current.save(update_fields=["outcome", "response", "message", "finished_at"])
    OseSimulationEvent.objects.create(simulation=simulation, action="FINISHED", actor=actor, message=message)
    return simulation


def run_simulation(*, simulation_id, actor, branch):
    simulation, attempt = _claim(simulation_id=simulation_id, actor=actor, branch=branch)
    if attempt is None:
        return simulation
    envelope = OseEnvelope(simulation.public_id, simulation.payload["issuer_ruc"],
        simulation.payload["document_type"], simulation.payload_hash,
        payload_bytes(simulation.payload), "application/vnd.sicv.ose-simulation+json")
    try:
        transport = resolve_transport(simulation.connection_snapshot, scenario=simulation.scenario, attempt_number=attempt.number)
        result = transport.query(envelope, simulation.ticket) if attempt.operation == "QUERY" else transport.submit(envelope)
    except DefinitelyNotSent:
        return _finish(simulation_id=simulation.pk, attempt=attempt, actor=actor, error="NOT_SENT")
    except DeliveryUncertain:
        return _finish(simulation_id=simulation.pk, attempt=attempt, actor=actor, error="UNCERTAIN")
    except Exception:
        # No conservar excepciones arbitrarias: un adaptador puede incluir
        # credenciales en ellas. Estado prudente y mensaje público acotado.
        return _finish(simulation_id=simulation.pk, attempt=attempt, actor=actor, error="UNCERTAIN")
    return _finish(simulation_id=simulation.pk, attempt=attempt, actor=actor, result=result)
