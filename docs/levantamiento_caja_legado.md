# Levantamiento: Caja, comprobantes y facturación del SICV legado

Entregable del issue #22. Actualizado: 2026-10-01.

**Actualización 2026-10-09:** la nueva [Caja operativa](caja_operativa.md) cubre
apertura, gastos, depósitos, arqueo, versiones y aprobación por cajero/oficina.
Las fichas siguientes conservan el estado del levantamiento original. El
consolidado por emisión sigue separado de la caja física. SUNAT/SIRE automáticos
permanecen pendientes por decisión del usuario.

**Fuentes.** Validaciones funcionales con las áreas usuarias, navegación de solo
lectura del SICV legado y revisión del código del SICV nuevo en
`feature/reporte-ingresos-usuario`.

**Método.** Solo lectura: navegación normal de la interfaz del legado y
exportación de reportes existentes, sin crear, modificar, condonar, anular ni
reintentar operaciones reales.

**Privacidad.** El repositorio es público. Este documento no contiene nombres
de personas, documentos de identidad, direcciones, cuentas bancarias, importes
reales de clientes, series concretas, usuarios, capturas ni archivos reales.
La evidencia concreta se conserva fuera del repositorio.

Estado en el SICV nuevo: **Existe**, **Parcial**, **Falta** o **Por validar**.

---

## 1. Resumen validado

- **La fuente operativa del cuadre diario de Contabilidad es Consolidado de
  emisión.** Movimiento caja y Consolidado de ingresos son vistas auxiliares y
  no deben forzarse a dar el mismo total: emisión y cobranza pueden diferir.
- **Caja en el legado combina comprobantes, gastos, depósitos y composición
  (arqueo).** ATC registra estos movimientos y cada cajero realiza su cierre.
  El SICV nuevo todavía no cubre gastos, depósitos ni composición.
- **Ingresos por usuario** fue contrastado contra exportaciones reales:
  `NINGUNO` significa todos los usuarios; elegir un usuario recorta solo sus
  ingresos. La hoja tiene una fila por concepto cobrado, puede repetir un
  comprobante cuando cubre varios conceptos y **Desde/Hasta filtra por fecha de
  pago**, no por fecha de emisión.
- **Registro de Ventas no se usa actualmente para el cuadre de Contabilidad.**
  Tampoco forman parte del flujo operativo actual los reportes legacy
  `Resumen comprobantes SUNAT`, `Archivos Facturador SUNAT` y
  `Emisión de comprobantes electrónicos`.
- **El SICV legado sí participa en la emisión fiscal de comprobantes de
  clientes.** Contabilidad revisa posteriormente en una herramienta externa de
  SUNAT cuáles llegaron correctamente y cuáles requieren revisión. El mecanismo
  técnico exacto de envío, firma y recepción todavía no está determinado.
- **Las condonaciones son ajustes de deuda**, no equivalen a una anulación
  fiscal. Se usan, entre otros casos, para neutralizar mensualidades duplicadas
  por error del sistema y para corregir diferencias de un cargo.
- **Contabilidad lleva un control auxiliar por entidad legal** basado en la
  recaudación de clientes. Actualmente se revisa aproximadamente cada quince
  días; el SICV nuevo debería ofrecer una vista diaria sin automatizar
  decisiones contables o tributarias.
- El legado usa `01/01/1900` como valor centinela en varios campos de fecha.
  En la migración se normaliza a `NULL` cuando representa ausencia de fecha,
  conservando siempre el valor original en el snapshot legacy.

---

## 2. Fichas por pantalla

### 2.1 Caja

#### Control de comprobantes

| | |
|---|---|
| Objetivo | Alta, listado y detalle de comprobantes, con control de su estado. |
| Campos principales | Serie, número, fecha y estado. |
| Estados observados | Pendiente, Anulado y Extraviado. |
| Auditoría observada | Fecha/hora, usuario y acción. |
| SICV nuevo | **Parcial.** El comprobante nace al registrar el cobro; el pago tiene estados y la anulación es auditable. No existe el estado Extraviado ni un alta suelta equivalente. |

#### Buscar / Listar comprobantes

| | |
|---|---|
| Objetivo | Consultar comprobantes emitidos y descargar artefactos asociados. |
| Legado | Puede exponer PDF y XML según el comprobante. |
| SICV nuevo | **Parcial.** Lista comprobantes de la sede y ofrece representación PDF; no existe todavía el flujo fiscal/XML completo. |

#### Nota de crédito y Nota de crédito 2

| | |
|---|---|
| Objetivo | Corregir o anular documentalmente un comprobante emitido. |
| Diferencia entre ambas pantallas | **Por validar.** |
| SICV nuevo | **Falta.** |

#### Gastos

| | |
|---|---|
| Objetivo | Registrar egresos de caja. |
| Campos observados | Empresa, fecha, tipo de documento, serie/número, motivo, descripción, monto, cajero y anulación. |
| Operación real | ATC registra gastos propios del cierre, por ejemplo movilidad/pasajes. |
| Efecto | Aparecen como egreso y reducen el saldo del consolidado. |
| SICV nuevo | **Falta.** |

#### Depósitos

| | |
|---|---|
| Objetivo | Registrar dinero de caja trasladado a una cuenta bancaria. |
| Campos observados | Empresa, fecha, cuenta bancaria, operación, monto, medio/referencia, cajero, anulación y observaciones. |
| Operación real | ATC lo registra como parte de su cierre cuando corresponde. |
| Efecto | Egreso del consolidado. |
| SICV nuevo | **Falta.** |

#### Composición

| | |
|---|---|
| Objetivo | Arqueo de caja. |
| Campos observados | Importes por denominación, monedas, cheques, vales, otros y total calculado. |
| Operación real | Forma parte del proceso de cierre del cajero. |
| Persistencia exacta | **Por validar**: día, cajero y/o oficina. |
| SICV nuevo | **Falta.** |

### 2.2 Reportes

| Reporte | Uso validado | SICV nuevo | Prioridad |
|---|---|---|---|
| Consolidado de emisión | **Fuente principal del cuadre diario de Contabilidad.** Resume saldo anterior, ventas por tipo de documento/serie, egresos, saldo y composición. | **Existe parcialmente.** Excel/PDF; gastos, depósitos y composición todavía no están modelados. | P0 |
| Ingresos por usuario | Detalle de ingresos por usuario/cajero; una fila por concepto cobrado. `NINGUNO` devuelve todos. | **Existe.** Validado contra muestras reales para esta semántica. | P0 |
| Movimiento caja | Libro cronológico de entradas/salidas con saldo acumulado. | **Falta.** No es la fuente principal del cuadre. | P1 |
| Consolidado de ingresos | Vista auxiliar; su total puede diferir de Movimiento caja y del consolidado de emisión. | **No replicar por defecto** hasta confirmar necesidad actual. | P2 |
| Resumen de caja | En la muestra observada llegó a reportar 0 y «CAJA NO CUADRA» pese a existir movimientos. | **Falta.** | P2 |
| Gastos | Listado de egresos. | **Falta.** | P1 |
| Depósitos | Listado de depósitos. | **Falta.** | P1 |
| Registro de ventas | Reporte detallado legacy. | **No prioritario:** Contabilidad indicó que actualmente no lo usa. | P3 |
| Resumen comprobantes SUNAT | Reporte legacy. | **No replicar por defecto:** no forma parte del flujo operativo actual. | P3 |
| Archivos Facturador SUNAT | Reporte/paquete legacy. | **No replicar por defecto:** no forma parte del flujo operativo actual. | P3 |
| Emisión de comprobantes electrónicos | Reporte legacy separado. | **No replicar por defecto:** no forma parte del flujo operativo actual. | P3 |

### 2.3 Diferencia entre emisión y caja

En una comparación controlada del mismo día se observó que:

- Movimiento caja agrupa **cobros** (por ejemplo, boletas/facturas cobradas).
- Consolidado de emisión agrupa **documentos/series emitidos** e incluye tipos
  documentales que no aparecen con la misma clasificación en Movimiento caja.
- Ambos pueden coincidir en saldo base y egresos y, aun así, tener distinto
  total de ingresos.

Por tanto, el SICV nuevo no debe imponer la falsa invariancia
`movimiento_caja == consolidado_emision`. Debe reconciliar y explicar las
diferencias entre fecha/documento de emisión y movimiento de dinero.

### 2.4 Ingresos por usuario

Validado contra exportaciones reales del legado:

- `NINGUNO` = todos los usuarios.
- Elegir un usuario devuelve solo las filas de ese usuario.
- Una fila representa un concepto/cargo cubierto, no necesariamente un
  comprobante completo.
- Un mismo comprobante puede aparecer en varias filas.
- `Pagó hasta` se informa por concepto.
- El total del pie coincide con la suma de las filas.
- Cuando `Fecha` (emisión) y `Fecha pago` difieren, el registro pertenece al
  día de `Fecha pago`.

**Confirmación funcional de ATC (2026-10-01):** en el flujo operativo actual,
los cobros de los planes se realizan por el importe completo; no se admiten
abonos parciales. Por tanto, la duda de `Pagó hasta` ante pago parcial queda
**no aplicable al alcance actual**. Es una confirmación del área, no una prueba
observada de cómo el legado representaría un caso parcial.

Para un cargo periódico cobrado completo se conserva `Charge.period_end` en
`Pagó hasta`; los conceptos sin periodo siguen sin fecha. No se debe inferir
que el cliente tenga que cancelar toda su deuda acumulada en una sola operación,
ni calcular días proporcionales a partir del importe pagado.

El SICV nuevo dispone técnicamente de `PaymentAllocation` para pagos parciales.
Esta confirmación no elimina esa capacidad ni demuestra que su pantalla de
cobro impida usarlos: antes del piloto debe contrastarse ese flujo con la regla
de cobro completo. Cualquier excepción futura necesita validación funcional
propia y una prueba de regresión para `Pagó hasta`.

### 2.5 Facturación electrónica

| Punto | Legado | SICV nuevo |
|---|---|---|
| Emisión a clientes | El área usuaria indica que el SICV emite comprobantes y luego Contabilidad verifica su recepción/estado en una herramienta externa de SUNAT. | **Falta el flujo fiscal real.** |
| Artefactos | Existen PDF/XML y pantallas fiscales en el legado, aunque varios reportes legacy ya no se usan operativamente. | PDF de representación; no hay ciclo fiscal completo. |
| Estados/errores | Contabilidad revisa comprobantes que llegaron y los que presentan errores. | Falta modelar envío, respuesta, error, reintento/ajuste y trazabilidad. |
| Mecanismo técnico | **Por validar.** No se asume envío directo, proveedor, OSE/PSE ni Facturador SUNAT sin evidencia técnica. | Por diseñar después de validar el mecanismo real. |

El hecho de que un usuario pueda «eliminar/anular» un comprobante en el legado
no prueba que desaparezca fiscalmente. El SICV nuevo no debe borrar documentos
fiscales históricos: cualquier corrección deberá conservar estado, motivo,
usuario y referencia al documento original.

### 2.6 Organización y permisos

| Dimensión | Legado | SICV nuevo |
|---|---|---|
| Sede/unidad | El selector legado mezcla sedes físicas con unidades comerciales/operativas. | Conviene separar unidad/marca de sede física. |
| Oficina | Existe un nivel de oficina/local y el cierre puede consolidarlas. | Los pagos ya admiten oficina; falta cerrar reglas operativas. |
| Empresa emisora | Filtro de empresa en caja/reportes y relación con talonarios. | Existe `Issuer`; falta el control acumulado por entidad legal. |
| Serie/talonario | El consolidado subtotaliza por serie. | Existe `ReceiptSequence`. |
| Usuario/cajero | Cobros, gastos y depósitos quedan vinculados a usuario/cajero. | Los pagos registran `received_by`; Ingresos por usuario ya existe. |
| Roles | ATC registra operaciones de caja; Contabilidad revisa y cuadra. | La matriz final debe reflejar esas responsabilidades sin dar permisos fiscales por defecto. |

### 2.7 Unidades operativas observadas

#### APP Perú

- Es una **unidad comercial lógica**, no una sede física comparable con las
  sedes tradicionales.
- Su negocio observado es IPTV mediante una plataforma/app externa.
- Puede existir como servicio adicional de un cliente de una sede normal o
  como única suscripción de un abonado clasificado en APP Perú.
- El legado separa Plan, Plan x Sucursal y Tarifa; la tarifa puede depender de
  la unidad.
- La activación/corte técnico del servicio se realiza en la plataforma externa;
  el SICV mantiene la suscripción comercial.
- El comprobante observado fue un recibo interno de ingresos; el área indicó
  que esta operación no tiene integración SUNAT completa.

**Implicación:** en el SICV nuevo conviene separar unidad comercial,
producto/plan, plataforma de aprovisionamiento, suscripción y estado técnico.

#### Eco Net

- Se comporta como una **operación ISP territorial** con una unidad/marca y
  una oficina/local territorial diferenciadas.
- Usa Internet FTTH, suscripciones, deuda mensual, facturas, pagos y órdenes
  técnicas del mismo motor general.
- Se observó histórico de tarifas por fecha de inicio.
- En un plan observado existían tarifa y suscripciones para la unidad, pero
  `Plan x Sucursal` estaba vacío: el legado tolera configuraciones
  inconsistentes.
- Una OT de instalación estaba enlazada directamente desde la suscripción,
  aunque el listado general de órdenes del abonado no la mostraba.
- También se observaron datos históricos incompletos/inconsistentes (por
  ejemplo, fechas de emisión/atención no monotónicas o técnico vacío).

**Implicación:** el importador debe preservar el raw legacy y marcar
inconsistencias para revisión; el modelo nuevo debe garantizar una relación
consistente Suscripción → OT y validar disponibilidad/tarifa del plan.

### 2.8 Condonaciones y ajustes

Las condonaciones observadas no son una sola operación fiscal. Se utilizan para:

- neutralizar mensualidades duplicadas generadas por error;
- ajustar diferencias de una mensualidad/cobro;
- dejar trazabilidad de una corrección comercial.

El SICV nuevo debe implementar una operación de ajuste trazable (cargo,
importe, tipo/motivo, usuario, fecha y referencia) y no borrar silenciosamente
el cargo original.

### 2.9 Control por entidad legal

Contabilidad mantiene un Excel auxiliar para vigilar la **recaudación/pagos de
clientes por entidad legal**, aproximadamente cada quince días. El detalle del
umbral y su fundamento no se publica en este repositorio.

Requisito propuesto para el SICV nuevo:

- acumulado diario, quincenal, mensual y anual por entidad legal;
- desglose por sede, oficina, serie y medio cuando aplique;
- alertas configurables;
- solo informar: ninguna selección automática de entidad legal por alcanzar un
  umbral.

La relación con dotación de personal pertenece al dominio de RR. HH. y no debe
mezclarse con la lógica de caja, aunque un tablero gerencial pueda mostrar
ambos indicadores.

---

## 3. Lo que ya quedó en el SICV nuevo

Detalle técnico en
[`accounting_gap_analysis.md`](accounting_gap_analysis.md).

- **Consolidado de emisión** en Excel y PDF.
- **Ingresos por usuario** en Excel y PDF.
- `NINGUNO`/usuario individual validado contra el comportamiento del legado.
- Empresa, sede, oficina y serie como filtros del cierre.
- Protección contra inyección de fórmulas en exportaciones Excel.
- Pruebas automáticas y CI verde en la rama de entrega.

---

## 4. Dudas POR VALIDAR

### P0

1. ¿La pantalla de cobro del SICV nuevo respeta la regla confirmada de importe
   completo del plan? La duda de `Pagó hasta` ante un pago parcial queda no
   aplicable al flujo ATC actual; no se observó un caso parcial en el legado.
2. ¿Cuál es el mecanismo técnico real de emisión fiscal: generación XML,
   firma, transporte, respuesta/CDR, rechazo, baja y contingencia?
3. Durante el piloto, ¿qué sistema es dueño de cada serie/talonario para evitar
   correlativos duplicados?

### P1

4. Persistencia exacta de composición: ¿por día, cajero, oficina o combinación?
5. Reglas de apertura/saldo anterior y cuándo se modifica.
6. Diferencia funcional entre las dos pantallas de nota de crédito.
7. Matriz definitiva de permisos para ATC, Contabilidad, Administración y
   Gerencia.
8. Regla formal de vigencia de tarifas cuando hay más de una tarifa activa por
   fecha.
9. Alcance exacto del control por entidad legal y periodicidad requerida por
   Contabilidad, sin publicar umbrales reales.

### No bloqueantes

10. Por qué el Resumen de caja legacy puede quedar en 0/«no cuadra».
11. Significado y necesidad actual de reportes legacy que Contabilidad ya no
    utiliza.

---

## 5. Prioridad propuesta

### P0 · antes del piloto financiero

- Validar el **Consolidado de emisión** contra el legado para la misma sede,
  oficina, empresa, serie y periodo.
- Mantener **Ingresos por usuario** y contrastar el flujo nuevo de cobro con la
  regla de importe completo del plan confirmada por ATC. La semántica parcial
  de `Pagó hasta` no bloquea la réplica del flujo operativo actual.
- Definir propiedad de series durante la coexistencia legado/nuevo.
- Diseñar el estado fiscal sin asumir todavía el proveedor/mecanismo de SUNAT.
- Mantener la generación de mensualidades idempotente para impedir cargos
  duplicados.

### P1 · antes de producción

- Gastos, depósitos y composición.
- Cierre guardado/inmutable con ajustes posteriores auditados.
- Movimiento de caja como ledger auxiliar.
- Ajustes/condonaciones de cargos con motivo y usuario.
- Notas de crédito y flujo fiscal real después de validar el mecanismo.
- Dashboard diario de recaudación por entidad legal.
- Matriz definitiva de permisos.

### P2/P3 · solo si el área confirma necesidad

- Consolidado de ingresos como reporte separado.
- Resumen de caja.
- Registro de ventas legacy.
- Resumen comprobantes SUNAT.
- Archivos Facturador SUNAT.
- Emisión de comprobantes electrónicos como reporte separado.

No se replica un reporte solo porque exista en el menú legacy.
