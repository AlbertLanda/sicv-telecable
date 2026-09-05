# Programación y toma de órdenes

## Flujo operativo confirmado

ATC registra y consulta las órdenes. Los técnicos se organizan desde su
aplicativo y toman las OT disponibles mediante la API existente. La toma
registra al técnico responsable y lleva la OT de PENDING a ASSIGNED.

La bandeja `/work-orders/dispatch/` fue retirada por decisión operativa.
No se debe restaurar ni convertir el tablero en un paso obligatorio de
asignación por ATC. La ruta de consulta y programación es
`/work-orders/schedule/`.

El tablero muestra órdenes abiertas, por sede activa y semana. Incluye los
distintos tipos operativos que genere el sistema —instalaciones, averías,
incidencias y demás OT— mientras sigan abiertas. Las atendidas y liquidadas
continúan consultándose en la ficha del cliente y en sus fichas de OT.

## Programación no es asignación

El calendario responde **cuándo** se espera atender una orden. La API técnica
responde **quién** la toma. Son ejes distintos.

Una OT en `PENDING` puede programarse o cambiar de día aunque todavía no tenga
`assigned_technician`. Ese movimiento conserva `PENDING`, no crea
`WorkOrderAssignment` y no obliga a que un técnico la tome artificialmente.
La trazabilidad del cambio queda en `WorkOrderReprogramming`.

Cuando un técnico decide atenderla utiliza `claim/`; recién entonces la orden
pasa de `PENDING` a `ASSIGNED` y queda asociada a ese mismo técnico.

Para órdenes que ya estaban `ASSIGNED` o `IN_PROGRESS` se conserva por ahora
el comportamiento histórico de `WorkOrder.reprogram()`, incluida la transición
a `REPROGRAMMED`. Esta compatibilidad evita alterar de golpe el flujo de campo
mientras se separa gradualmente agenda y estado operativo.

## Reprogramación autorizada

Consultar requiere `view_workorder`. Mover una fecha conserva temporalmente
el permiso funcional existente `assign_workorder`; este cambio no concede
permisos nuevos. La creación futura de un permiso específico como
`reschedule_workorder` debe hacerse en una migración separada.

No hay acciones de asignación en el tablero. La toma normal sigue perteneciendo
al aplicativo del técnico.

Se conserva la hora prevista cuando ya existía una. Sin fecha anterior, el
tablero semanal todavía utiliza 09:00 como hora técnica por compatibilidad con
el `DateTimeField` actual. Esto **no debe interpretarse como una promesa de
atención a las 09:00**: el caso de negocio «día acordado, sin hora» requiere
modelarse explícitamente en una evolución posterior para no inventar una hora
que el cliente nunca pactó.

Hoy es un destino válido solo si la hora resultante aún es futura; el backend
decide. Cada cambio deja `WorkOrderReprogramming`.

El endpoint valida un objeto JSON con `date` y `reason` opcional. Las fechas
imposibles, los tipos incorrectos y los extremos que desbordan la navegación
se rechazan. La consulta con una semana inválida vuelve a la semana actual.

Después de mover la OT, el navegador actualiza fecha/hora, estado, contadores
de columnas e indicadores globales con la respuesta del servidor. Mientras
guarda se bloquean nuevos arrastres; ante rechazo se devuelve la tarjeta.

## Datos del contrato en el portal técnico

`plan_details.included_tv_points` representa las cortesías realmente otorgadas
en la suscripción, junto a `annex_count` y `total_tv_points`. No representa el
máximo del plan. Una TV inicial concede una cortesía, sin reservar la segunda.

Los campos `base_installation_fee`, `base_monthly_fee`, `annex_monthly_charge`
y `total_monthly_price` vienen de la suscripción. El portal distingue la
mensualidad base, anexos y total antes del pronto pago. El precio de catálogo
(`monthly_price`) y la referencia actual de tarifa (`tariff`) se mantienen en
la API por compatibilidad, pero no sustituyen los importes contratados.

No se alteran políticas de cobro, cortes, descuentos, cálculo de metrajes,
materiales, stock ni permisos de liquidación técnica.

## Protección ante peticiones simultáneas

La reprogramación obtiene la OT dentro de una transacción con bloqueo de fila
en PostgreSQL. Para una `PENDING`, la actualización de agenda también exige
que sigan coincidiendo su estado y su `scheduled_at` previamente leído, para
no sobrescribir silenciosamente otra programación concurrente.

`change_status()` mantiene además su UPDATE condicionado para los cambios de
estado. En SQLite, los conflictos de escritura se informan y las regresiones
cubren las escrituras desactualizadas; el bloqueo real de fila se verificará
en PostgreSQL cuando se prepare ese entorno.

## Verificación

- `test_pending_scheduling.py`: una OT PENDING se programa y mueve de día sin
  técnico, sin asignación y sin abandonar PENDING.
- `test_schedule_safety.py`: entradas, permisos, CSRF, fecha/hora, indicadores
  y escrituras desde instancias desactualizadas.
- `test_web_schedule_board.py`: semana, sedes, estados e historial.
- `test_api_work_order_detail.py`: una cortesía, anexos, cinco TV, precios
  contratados distintos del catálogo y una instalación gratuita sin tarifa.
- `test_supply_lookup.py`: GPS de ocho decimales hasta guardar el domicilio.
- Suite completa en Python 3.11 / Django 5.2.17 / SQLite.
