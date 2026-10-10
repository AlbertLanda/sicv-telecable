# Conciliación bancaria y ajustes de deuda · QA

Este bloque agrega **Reportes → Conciliación bancaria** y **Cobranza → Ajustes
de deuda**. No conecta con bancos, SUNAT ni SIRE. La conexión fiscal y SIRE
automático siguen pospuestos por instrucción del usuario.

## Conciliación bancaria

1. Administración configura empresa titular, banco, número completo de cuenta
   y nombre. Se trabaja en PEN, como el motor de cobros actual. La identidad de
   la cuenta no se edita después. Contabilidad utiliza los accesos por empresa
   ya configurados para el espacio contable; cambiar la sede activa no amplía
   esos accesos. Importar, confirmar y consultar requieren permisos separados.
2. Descargar la plantilla e importar un **CSV normalizado UTF-8** del extracto
   (coma o punto y coma), máximo 2 MB y 10000 filas. No se presupone un formato
   de BBVA, BCP u otro banco sin su muestra y especificación.
3. Revisar movimientos pendientes. Las sugerencias buscan empresa, importe y
   operación con fechas dentro de tres días. Puede haber varias: nunca se
   confirma automáticamente. Para pagos antiguos sin cuenta bancaria estructurada,
   Contabilidad verifica explícitamente el destino antes de confirmar el vínculo.
4. Confirmar un cobro vigente no efectivo o un depósito de caja con el mismo
   importe y empresa. Un depósito debe coincidir además en banco y cuenta. El
   ingreso del banco corresponde al importe positivo del depósito, aunque en
   caja figure como salida. Se permite identificación manual por ID con motivo
   obligatorio, incluso si fecha/referencia difieren.
5. Descargar el Excel con estados, historial y fuentes. El archivo original se
   conserva en la base de datos, con SHA-256 y descarga autenticada por empresa.
   La descarga verifica su huella. No se escribe evidencia bancaria en GitHub,
   directorios públicos ni carpetas de medios sin autorización.

| Columna | Regla |
|---|---|
| `id_movimiento` | ID estable del banco, obligatorio. No usar número de fila. |
| `fecha` | AAAA-MM-DD, desde 2000 hasta hoy en Lima. |
| `operacion` | Referencia original como texto; conservar ceros iniciales. |
| `descripcion` | Descripción del banco, hasta 500 caracteres. |
| `moneda` | PEN. |
| `ingreso` | Positivo, punto decimal, sin miles; vacío o cero si es salida. |
| `salida` | Positivo, punto decimal, sin miles; vacío o cero si es ingreso. |
| `cuenta` | Número completo de la cuenta elegida; conservar ceros iniciales. |

Un ID repetido en el mismo archivo se rechaza. Archivos solapados vinculan los
movimientos existentes sin sumarlos otra vez; si un ID conocido contiene datos
distintos se rechaza **todo** el archivo, para revisar la normalización/origen.
No se reemplaza evidencia con un nuevo archivo de igual nombre. Un archivo
idéntico devuelve su importación original.

Cada movimiento bancario y cada cobro/depósito admite un único vínculo activo,
incluso entre cuentas. Se puede deshacer con motivo conservando el vínculo y su
evidencia. Primero se debe deshacer una conciliación para anular su cobro o
revertir el depósito; deshacerla no anula el movimiento operativo.

Las salidas, comisiones, diferencias de importe, liquidaciones agrupadas y
movimientos no identificados permanecen pendientes y admiten observaciones.
Esta entrega concilia ingresos **uno a uno** con cobros/depósitos; no simula un
libro mayor, cuentas por pagar ni conciliaciones por sumas o importes netos de
comisiones. Las observaciones no marcan un movimiento como conciliado. El total
importado es el neto de las filas cargadas, no el saldo bancario completo.

## Ajustes comerciales de deuda

ATC solicita reducciones para errores, duplicados o diferencias comerciales,
desde la ficha de deuda o buscando por código/documento del abonado. Contabilidad
también puede solicitar en su ámbito. Se exigen importe, motivo y sustento.
La solicitud no modifica el saldo hasta que otra persona la aprueba.

Contabilidad revisa la sede asignada y las sedes de oficinas autorizadas;
Administración puede revisar todas. La sede del cargo se obtiene de la zona de
su servicio, con la sede del abonado como respaldo. No existe autoaprobación,
incluso para administradores. La revisión conserva responsable, fecha, decisión,
comentario y saldo anterior/posterior. Si cambió el cargo o sus cobros desde la
solicitud, se debe rechazar y presentar otra con información actualizada.

Los créditos aprobados se restan del saldo mediante registros vinculados. El
importe original del cargo no se cambia y no se crea un pago ficticio. Una
regularización completa sin cobro queda como **Regularizado por ajuste**. Las
reducciones no pueden consumir dinero ya cobrado ni alterar cargos anulados.
La deuda, el cobro y los indicadores SQL consideran los ajustes aprobados.

El pronto pago sigue sujeto a su vencimiento. Para neutralizar por completo un
cargo duplicado, debe usarse el saldo **sin descuento temporal**, mostrado junto
al saldo de hoy. El descuento temporal y el ya ganado son el mismo beneficio:
no se suman dos veces al restituir un ajuste. Una reducción parcial que solo
deja saldo cero mientras dura el descuento no oculta el remanente al vencer.

Para corregir un ajuste aprobado, se solicita una restitución por su ID y su
importe completo. Requiere nueva aprobación y solo puede aplicarse una vez.
El ajuste inicial permanece aprobado en el historial y la restitución compensa
su efecto. Esto puede reabrir deuda, pero no cambia recibos ni cierres de caja.
No constituye nota fiscal, devolución de dinero ni condonación automática de
periodos posteriores. Los pagos pendientes con importes ya desactualizados no
pueden confirmarse sin revisar el cobro.

## Ejemplos de aceptación con datos sintéticos

- Banco: transferencia de prueba 80, operación `0000042`, y una fila de extracto
  del mismo importe. Importar dos veces debe mantener una fila. Confirmar el
  vínculo, intentar anular el cobro (rechazado), deshacer con motivo y comprobar
  que el historial permanece.
- Caja: depósito de 50 desde caja es un ingreso bancario de 50, con empresa,
  banco y cuenta coincidentes. Un depósito conciliado no se revierte sin
  deshacer antes el vínculo bancario.
- Deuda: cargo original 80, ajuste aprobado 20 → saldo 60, original 80. Una
  restitución aprobada del ajuste vuelve a 80; sin crear movimientos de caja.
- Pronto pago: cargo 80 con beneficio 5 y ajuste 20 → se cobran 55 dentro del
  plazo. El descuento ganado es 5. Si después se restituye el ajuste, vuelve
  deuda 20, sin conceder nuevamente los 5.

Los tests de PostgreSQL verifican importaciones simultáneas, doble conciliación,
conciliación frente a anulación/reversión y aprobación de ajustes frente a
cobros concurrentes. Las migraciones son aditivas: no importan extractos reales,
no crean cuentas bancarias reales y no aplican ajustes a abonados existentes.
