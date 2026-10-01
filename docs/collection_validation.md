# Validación de cobranza completa

Entrega del 2026-10-01, rama `fix/full-monthly-collection`, basada en
`feature/fiscal-foundation`. Validar primero en una base de prueba con datos
ficticios. Aplicar las migraciones con `python manage.py migrate`.

## Qué cambia

- El formulario actual de cobro exige cubrir el saldo completo de cada
  mensualidad elegida. Se pueden elegir uno o varios periodos sin pagar toda
  la deuda acumulada. Se respeta el descuento de pronto pago vigente.
- Una misma solicitud produce un solo pago, recibo interno y correlativo.
  Repetir el envío devuelve el recibo original; cambiar los datos con la misma
  clave exige abrir un nuevo cobro. Repetir una solicitud anulada tampoco cobra
  otra vez: devuelve ese registro anulado.
- Un saldo que cambia después de abrir la pantalla obliga a actualizar el
  tablero. Un segundo cobro desde una pantalla antigua no se convierte
  silenciosamente en un adelanto.
- Registrar, confirmar y anular toman el mismo bloqueo del abonado dentro de
  una transacción. Se vuelven a leer cargos y saldos antes de aplicarlos.
- El detalle del recibo permite confirmar un pendiente mediante POST, con los
  permisos `payments.confirm_payment` y `payments.view_receipt`. El nuevo
  permiso se asigna explícitamente al responsable; no se concede a todos.
- Confirmar y anular requieren la sede de cobro activa y una oficina autorizada.
  Los históricos sin oficina se pueden modificar por Administración o en sedes
  que aún no tienen oficinas activas. Cobrar a un abonado de otra sede sigue
  permitido; el ingreso pertenece a la sede que recibe el dinero.
- El detalle muestra eventos de registro, confirmación y anulación con fecha,
  usuario y motivo. Los eventos comienzan con esta entrega; no se inventa un
  historial para operaciones antiguas. Pago, recibo y eventos quedan de solo
  lectura en Django Admin; sus transiciones pasan por el servicio.

## Recorrido para Albert

| Caso | Pasos | Resultado esperado |
|---|---|---|
| Un periodo | Crear dos mensualidades ficticias de S/ 80 y seleccionar una | Cobra S/ 80; la otra sigue pendiente |
| Varios periodos | Seleccionar ambas y cobrar S/ 160 | Las dos quedan pagadas |
| Importe incompleto | Seleccionar S/ 80 e intentar S/ 40 | Rechaza el cobro; no consume número |
| Pronto pago | Crear S/ 80 con descuento de S/ 5 vigente | Cobra S/ 75 y muestra S/ 5 de descuento |
| Reenvío | Reenviar el mismo formulario después de cobrar | Mismo recibo; un solo ingreso |
| Dos pantallas | Abrir la misma deuda dos veces; cobrar en la primera | La segunda exige actualizar el tablero |
| Pendiente | Registrar «Cancelado: No» | Emite constancia pendiente; saldo sin bajar |
| Confirmación | Con permiso y oficina correcta, confirmar en el detalle | Baja deuda, registra ingreso y evento una vez |
| Pendiente desactualizado | Cobrar esa deuda desde otra pantalla o dejar vencer su descuento | La confirmación se rechaza; revisar y preparar un nuevo cobro |
| Anulación | Anular con motivo | Restituye el saldo; conserva recibo y motivo |
| Oficina ajena | ATC sin autorización intenta confirmar/anular por URL | Operación rechazada |

Si un pendiente dejó de representar la deuda actual, el responsable debe
revisarlo, anularlo con motivo y preparar otro cobro. No se edita retroactivamente
su importe o descuento.

## Compatibilidad y límites

La migración conserva pagos anteriores con `full_monthly_only=False`. Los
parciales históricos no se convierten ni se recalculan: el siguiente cobro
completa su saldo restante. El servicio genérico conserva compatibilidad con
importaciones, pruebas históricas y cuotas de equipos; la regla nueva se aplica
al flujo actual de ventanilla y se conserva en el pago para su confirmación.

Los cargos distintos de mensualidades mantienen sus reglas previas. El saldo
a favor por excedentes y los adelantos intencionales siguen disponibles. Esta
entrega no define nuevas excepciones comerciales ni cambia la tarifa del plan.

Los recibos siguen siendo internos. Confirmar/anular un pago no envía documentos
a SUNAT ni modifica documentos fiscales. La base fiscal anterior permanece
bloqueada para emisión real hasta validar configuración y circuito fiscal.

## Pruebas

`python manage.py test apps.payments.tests.test_collection` verifica reglas,
reenvíos, permisos, rutas, descuentos y saldos. La suite completa protege el
resto del sistema. El job `Cobranza simultánea (PostgreSQL)` usa PostgreSQL 16 y
conexiones independientes para cuatro carreras: mismo envío, envíos distintos,
confirmación frente a cobro nuevo y dos anulaciones. SQLite omite esas cuatro
pruebas porque no ofrece el mismo bloqueo de filas; no debe usarse como prueba
de seguridad de caja concurrente.
