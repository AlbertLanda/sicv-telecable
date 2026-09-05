# Asignación de órdenes: canal vigente

## Decisión operativa

La asignación manual de técnicos desde el portal web está retirada.

ATC puede registrar una orden, consultar su estado y programar o reprogramar
su fecha de atención. Ninguna de esas acciones adjudica la OT a un técnico.

El flujo vigente es:

```text
ATC registra OT
      ↓
PENDING / sin técnico
      ↓
ATC puede programar fecha
      ↓
PENDING / sin técnico
      ↓
Técnico consulta órdenes disponibles
      ↓
Técnico toma una OT (claim)
      ↓
ASSIGNED
```

## Compatibilidad temporal

El nombre de URL `work_orders:assign` se conserva temporalmente para enlaces
históricos, pero el endpoint responde HTTP 410 Gone y no procesa POST de
asignación. No consulta la existencia de la OT ni modifica estado, técnico o
historial.

La pantalla asociada solo informa al operador que la adjudicación ocurre en el
portal técnico.

## Invariante

Una acción web de ATC nunca debe crear `WorkOrderAssignment`, establecer
`assigned_technician` ni mover una OT de `PENDING` a `ASSIGNED`.

La adjudicación se produce exclusivamente en el canal técnico mediante la
operación de claim, que mantiene sus controles de elegibilidad, concurrencia y
trazabilidad.
