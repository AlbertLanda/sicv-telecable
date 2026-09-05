# Programación y toma de órdenes

## Flujo operativo confirmado

ATC registra y consulta las órdenes. Los técnicos se organizan desde su
aplicativo y toman las OT disponibles mediante la API existente. La toma
registra al técnico responsable y lleva la OT de PENDING a ASSIGNED.

La bandeja `/work-orders/dispatch/` fue retirada por decisión operativa.
No se debe restaurar ni convertir el tablero en un paso obligatorio de
asignación por ATC. La ruta de consulta es `/work-orders/schedule/`.

El tablero muestra órdenes abiertas, por sede activa y semana. Las atendidas
y liquidadas siguen consultándose en la ficha del cliente y en sus fichas de
OT; no se incluyen entre el trabajo abierto de la semana.

## Reprogramación autorizada

Consultar requiere `view_workorder`. Mover una fecha conserva el permiso
funcional existente `assign_workorder`; este cambio no lo concede a ATC ni
al técnico. No hay acciones de asignación en las tarjetas.

La matriz de estados no cambia: ASSIGNED e IN_PROGRESS admiten reprogramar.
PENDING primero debe pasar por la toma/asignación existente. REPROGRAMMED no
admite otra reprogramación directamente; conserva al técnico, que puede
iniciar o retomar la atención desde el aplicativo.

Se conserva la hora prevista. Sin fecha anterior se utiliza 09:00. Hoy es un
destino válido solo si esa hora aún es futura; el backend decide. Cada cambio
deja `WorkOrderReprogramming` e historial de estado.

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
en PostgreSQL. Además, `change_status()` realiza un UPDATE condicionado al
estado que se validó. Esto protege también las operaciones que ya tenían una
instancia anterior en memoria y funciona sobre SQLite.

Si otra petición cambió el estado, se rechaza la transición. La transacción
revierte sus modificaciones de fecha, resultado e históricos. Se prueban dos
reprogramaciones con la misma lectura y el cruce entre finalizar y reprogramar
en ambos órdenes, sin modificar la matriz de transiciones.

## Verificación

- `test_schedule_safety.py`: entradas, permisos, CSRF, fecha/hora, indicadores
  y escrituras desde instancias desactualizadas.
- `test_web_schedule_board.py`: semana, sedes, estados e historial.
- `test_api_work_order_detail.py`: una cortesía, anexos, cinco TV, precios
  contratados distintos del catálogo y una instalación gratuita sin tarifa.
- `test_supply_lookup.py`: GPS de ocho decimales hasta guardar el domicilio.
- Suite completa en Python 3.11 / Django 5.2.17 / SQLite.

La prueba de bloqueo real de filas requiere PostgreSQL; las pruebas de
regresión sobre SQLite validan el rechazo de escrituras desactualizadas.
