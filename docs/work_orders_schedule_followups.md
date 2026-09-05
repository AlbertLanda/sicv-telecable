# Evoluciones pendientes del calendario de OT

Este archivo separa mejoras posteriores de la corrección funcional actual.

## Día acordado sin hora

El negocio permite comprometer únicamente un día de atención cuando el cliente
no fija una hora. El modelo actual usa `scheduled_at` (`DateTimeField`), por lo
que una OT sin fecha previa recibe temporalmente 09:00 al arrastrarla desde
«Sin programar». Esa hora es técnica y no debe mostrarse como compromiso real.

La evolución debe representar explícitamente:

- fecha + hora: existe una hora pactada;
- fecha + sin hora: puede atenderse durante ese día;
- sin fecha: todavía no está programada.

Debe resolverse en una migración independiente para no mezclar el cambio de
esquema con la corrección de OT PENDING.

## Permiso de reprogramación

El tablero conserva temporalmente `assign_workorder` como permiso para mover
fechas porque ya existe en producción y evita introducir una migración en este
cierre. La acción de programar no equivale a asignar técnico, por lo que la
evolución recomendada es un permiso funcional específico, por ejemplo
`reschedule_workorder`.

## Asignación manual web

El flujo confirmado no requiere que ATC seleccione un técnico. La toma normal
se hace mediante `/api/technicians/work-orders/<id>/claim/`. Las pantallas y
pruebas históricas de asignación web deben retirarse en un cambio dedicado,
comprobando primero todas sus referencias para no romper la ficha del cliente.
