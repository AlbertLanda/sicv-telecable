# Caja operativa · piloto QA

La entrada **Cobranza → Caja operativa** implementa apertura, cobros vinculados,
gastos, depósitos de efectivo al banco, otros ingresos, garantías recibidas,
reversiones, arqueo por denominaciones y revisión por otra persona.

## Operación

1. Seleccionar sede y oficina física autorizada. Abrir la caja de hoy indicando
   únicamente el fondo inicial, sin sumar los cobros del día. La primera
   apertura exige explicar el origen. Los cobros ya registrados hoy por el mismo
   cajero y oficina se incorporan una vez; pendientes y anulados no se suman.
2. Cobrar desde el flujo habitual del abonado. Una vez que un cajero empieza a
   usar caja operativa en una oficina, sus nuevos cobros allí requieren su caja
   abierta de hoy. No se permite cambiar la fecha para evadir el cierre. Los
   cobros anteriores a la primera apertura conservan su comportamiento.
3. Registrar movimientos de efectivo. Los gastos exigen motivo, tipo y número de
   sustento. Los depósitos exigen empresa, banco, cuenta y operación. No volver a
   registrar aquí un pago bancario de un cliente: ese pago entra por cobranza.
4. Contar billetes y monedas. Se muestra el total y su diferencia contra el
   efectivo esperado. Explicar toda diferencia y enviar a revisión. Desde ese
   momento no se pueden añadir movimientos ni confirmar/anular sus cobros.
5. Contabilidad o Administración revisa el arqueo, las diferencias y los
   sustentos. Puede aprobar o devolver con comentario obligatorio. La misma
   persona que abrió la caja no puede aprobarla, incluso siendo administrador.
6. Si se devuelve, el cajero corrige y envía otra versión. Todas las versiones
   permanecen descargables. Si se aprueba, no se reabre ni reescribe el cierre.
   La próxima apertura propone el efectivo contado aprobado; cualquier cambio
   del fondo exige motivo. Primero se debe aprobar la caja anterior.

Se admite una caja por cajero/oficina/día (hora de Lima), en PEN. Una caja puede
cobrar para varias empresas; cada movimiento conserva su empresa/RUC, sin
repartir arbitrariamente entre empresas el fondo o el arqueo físico compartido.
La interfaz permite revisar movimientos netos por empresa y medio, separados del
fondo inicial. Las garantías se identifican como tales, no como ventas.

**Efectivo esperado** = fondo inicial + entradas en efectivo − salidas en
efectivo, incluyendo reversiones. Yape, Plin, transferencias, depósitos recibidos
de clientes, tarjetas y cheques no aumentan el efectivo físico. Los cheques y
vales no se convierten en efectivo al contarlos. Su conciliación documental y
bancaria queda en el siguiente bloque de trabajo.

## Correcciones y evidencia

- Los movimientos no se editan ni eliminan. Una reversión crea el importe
  contrario y enlaza el original, con motivo, persona y fecha.
- Se puede revertir un movimiento manual propio de la caja abierta o de una
  caja anterior aprobada del mismo cajero/oficina. Solo una vez. Debe existir
  regularización física del dinero; el sistema no devuelve dinero del banco.
- Los cobros se anulan desde su comprobante y solo si su caja vinculada sigue
  abierta. Si está en revisión se debe devolver el cierre primero. Un cobro
  incluido en una caja aprobada queda bloqueado: una futura devolución o ajuste
  de deuda requiere un flujo específico, no alterar el cierre ni reemplazarlo
  por una reversión manual.
- Cada envío guarda importes, arqueo, listado de movimientos, referencias,
  empresa/RUC, responsable, fecha, explicación y huella SHA-256 de la evidencia.
  Las decisiones se agregan al historial. La huella detecta diferencias con el
  contenido guardado; no es una firma digital ni un archivo inalterable externo.
- Excel contiene resumen, movimientos con saldo de efectivo, arqueo, medios,
  empresas y revisiones. Los importes son números y el texto es literal para
  evitar fórmulas introducidas mediante motivos/referencias. El Excel de una
  versión conserva sus importes; su hoja Revisiones refleja el historial
  disponible al descargar.
- El administrador de Django tiene consulta de solo lectura de estas entidades.
  Las escrituras operativas pasan por servicios transaccionales, con bloqueo de
  oficina y restricciones de unicidad. El acceso directo de administración de
  la base sigue siendo una responsabilidad de infraestructura.

## Acceso

| Capacidad | ATC | Contabilidad | Administración |
|---|---|---|---|
| Abrir/operar | Caja propia en oficina física autorizada | Solo con permiso explícito `payments.operate_cash` | Caja propia |
| Consultar/revisar | Solo caja propia | Sede asignada y oficinas habilitadas explícitamente | Todas las oficinas |
| Aprobar caja propia | No | No | No |

`payments.review_cash` es un permiso operativo sobre la caja completa (incluye
las empresas que comparten la caja). No utiliza ni amplía `CompanyAccess` de
SIRE. Cambiar la sede activa no amplía los permisos de revisión. Si Contabilidad
no tiene sede ni oficinas asignadas, no verá cajas hasta configurarlas. Las
autorizaciones se comprueban también en POST y exportaciones. Las oficinas
marcadas como depósito bancario no son cajas físicas y no abren sesión.

## Separación de reportes y alcance pendiente

**Consolidado de emisión** sigue agrupando por fecha del comprobante. No se
rellenan sus filas con importes de una caja de distinto alcance o fecha; su
aviso señala que no incorpora la caja física. **Caja del día** e **Ingresos por
usuario** conservan sus criterios de cobranza. Las diferencias entre emisión y
cobranza no constituyen automáticamente un error.

Quedan fuera de esta entrega: conexión real con SUNAT, sincronización automática
de SIRE, aceptación fiscal, conciliación con extractos bancarios, ajustes de deuda,
devoluciones de cobros ya cerrados, inventario documental de cheques/vales,
multimoneda y traspasos físicos entre cajeros. La conexión SUNAT/SIRE se mantiene
pospuesta expresamente hasta la etapa final.

## Recorrido de aceptación (solo datos de prueba)

- Fondo 100; cobro efectivo 80; cobro Yape 30; gasto efectivo 10; depósito al
  banco 50. Efectivo esperado: **120**. Yape neto: **30**, fuera del arqueo.
- Contar un billete de 100 y uno de 20, enviar y revisar con otra cuenta.
- Repetir un formulario: un solo movimiento. Intentar el mismo depósito con
  otra solicitud: rechazo por empresa/día/banco/cuenta/operación.
- Devolver con comentario, corregir por reversión y volver a enviar; verificar
  que la primera versión conserva sus importes.
- Probar otra oficina y otro cajero sin permisos: no deben poder consultar,
  exportar, operar ni aprobar la caja.
- Aprobar y comprobar que un nuevo cobro/anulación no modifica esa versión.

No se crean aperturas, movimientos, cuentas ni permisos reales mediante la
migración. El primer uso es una activación explícita por cajero/oficina y debe
ensayarse con usuarios y cobros sintéticos en QA.
