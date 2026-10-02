"""Contrato interno del adaptador. Esta entrega solo implementa el simulador.

No es el contrato HTTP/SOAP de ningún proveedor. Un adaptador real deberá
traducirlo al contrato publicado por el OSE elegido y consumir artefactos
fiscales validados. El simulador solo admite JSON marcado como prueba.
"""
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol
import uuid

from django.db import transaction

from .models import OseSimulation, OseSimulatorReceipt


def payload_bytes(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def payload_digest(payload):
    return hashlib.sha256(payload_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class OseEnvelope:
    request_id: uuid.UUID
    issuer_ruc: str
    document_type: str
    payload_hash: str
    content: bytes
    content_type: str


@dataclass(frozen=True)
class OseResponse:
    request_id: uuid.UUID
    payload_hash: str
    result: str
    code: str
    message: str
    ticket: str = ""
    simulated: bool = True

    def as_dict(self):
        return dict(request_id=str(self.request_id), payload_hash=self.payload_hash,
                    result=self.result, code=self.code, message=self.message,
                    ticket=self.ticket, simulated=self.simulated)


class DeliveryUncertain(Exception):
    """Puede haber recepción: consultar antes de volver a enviar."""


class DefinitelyNotSent(Exception):
    """El adaptador garantiza que no hubo recepción. Se permite reintentar."""


class OseTransport(Protocol):
    def submit(self, envelope: OseEnvelope) -> OseResponse: ...
    def query(self, envelope: OseEnvelope, ticket: str = "") -> OseResponse: ...


class SimulatedOse:
    """Proveedor ficticio persistente: cero llamadas de red y cero secretos."""
    def __init__(self, scenario, attempt_number):
        self.scenario = scenario
        self.attempt_number = attempt_number

    def _validate(self, envelope):
        if envelope.content_type != "application/vnd.sicv.ose-simulation+json":
            raise ValueError("El simulador solo admite solicitudes de prueba.")
        data = json.loads(envelope.content)
        if (data.get("simulation_only") is not True or data.get("schema") != "SICV_OSE_SIMULATION_V1"
                or data.get("issuer_ruc") != envelope.issuer_ruc or data.get("document_type") != envelope.document_type
                or hashlib.sha256(envelope.content).hexdigest() != envelope.payload_hash):
            raise ValueError("Solicitud simulada inválida.")

    def _response(self, envelope, result, ticket=""):
        return OseResponse(envelope.request_id, envelope.payload_hash, result,
                           f"SIM_{result}", f"Resultado simulado: {result}. Sin validez tributaria.", ticket)

    def submit(self, envelope):
        self._validate(envelope)
        if self.scenario == OseSimulation.Scenario.NOT_SENT and self.attempt_number == 1:
            raise DefinitelyNotSent
        result = {OseSimulation.Scenario.OBSERVED: "OBSERVED", OseSimulation.Scenario.REJECTED: "REJECTED"}.get(self.scenario, "ACCEPTED")
        with transaction.atomic():
            receipt, _ = OseSimulatorReceipt.objects.get_or_create(request_id=envelope.request_id, defaults={
                "payload_hash": envelope.payload_hash, "result": result,
                "ticket": f"SIM-{envelope.request_id}",
                "pending_queries": 1 if self.scenario == OseSimulation.Scenario.DELAYED else 0,
            })
            if receipt.payload_hash != envelope.payload_hash:
                raise ValueError("Una referencia de prueba no puede recibir otro contenido.")
        if self.scenario == OseSimulation.Scenario.LOST_REPLY and self.attempt_number == 1:
            raise DeliveryUncertain
        return self._response(envelope, "PROCESSING" if receipt.pending_queries else receipt.result, receipt.ticket)

    def query(self, envelope, ticket=""):
        self._validate(envelope)
        with transaction.atomic():
            receipt = OseSimulatorReceipt.objects.select_for_update().filter(request_id=envelope.request_id).first()
            if receipt is None:
                return self._response(envelope, "NOT_FOUND")
            if receipt.payload_hash != envelope.payload_hash or (ticket and ticket != receipt.ticket):
                raise ValueError("La respuesta pertenece a otra solicitud de prueba.")
            if receipt.pending_queries:
                receipt.pending_queries -= 1
                receipt.save(update_fields=["pending_queries"])
                return self._response(envelope, "PROCESSING", receipt.ticket)
            return self._response(envelope, receipt.result, receipt.ticket)


def resolve_transport(connection_snapshot, *, scenario, attempt_number):
    # Sin carga dinámica de clases, fallback a producción ni lectura de claves.
    if connection_snapshot.get("mode") != "SIMULATOR":
        raise ValueError("El adaptador real todavía no está implementado.")
    if scenario not in OseSimulation.Scenario.values or not isinstance(attempt_number, int) or attempt_number < 1:
        raise ValueError("Escenario o intento de prueba inválido.")
    return SimulatedOse(scenario, attempt_number)
