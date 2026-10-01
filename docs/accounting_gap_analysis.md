# Contabilidad y cobranza: qué tiene SICV y qué falta

Auditoría técnica y funcional de Caja/Contabilidad, actualizada al 2026-10-01.
La implementación revisada parte de `feature/sicav-legacy-import`, incorpora el
MVP contable revisado y el reporte `Ingresos por usuario`.

La evidencia operativa concreta se mantiene fuera del repositorio público.

## Resumen

- SICV ya registra casi todo lo necesario **por pago**: sede, oficina, empresa
  emisora, talonario, método, referencia, usuario, cobrador, fecha de emisión,
  fecha real de pago, pendientes y anulados.
- **Consolidado de emisión** es el reporte que Contabilidad usa realmente para
  el cuadre diario. Movimiento caja e Ingresos por usuario son vistas
  complementarias; no se debe asumir que emisión y cobranza siempre coinciden.
- **Ingresos por usuario** ya existe en Excel/PDF y fue contrastado contra el
  legado: `NINGUNO` devuelve todos los usuarios, un usuario seleccionado
  recorta solo sus ingresos y el periodo se filtra por **fecha real de pago**,
  no por fecha de emisión del comprobante.
- Falta la parte administrativa del cierre: **gastos, depósitos, composición
  (arqueo) y cierre persistido/inmutable**.
- El legado participa en la emisión fiscal de comprobantes de clientes, pero el
  mecanismo técnico exacto de XML/firma/transporte/respuesta sigue sin
  determinarse. El SICV nuevo todavía no debe afirmar integración SUNAT real.
- Registro de Ventas y varios reportes fiscales legacy existen, pero
  Contabilidad indicó que no forman parte de su operación actual; no deben
  replicarse por defecto.

---

## A. Lo que SICV ya tiene

### A.1 Reportes › Cierre de caja

| Pieza | Dónde |
|---|---|
| Construcción del consolidado | `apps/reports/cash_closing.py` |
| Salidas Excel/PDF | `apps/reports/cash_closing_exporters.py` |
| Ingresos por usuario | `apps/reports/user_income.py`, `user_income_exporters.py` |
| Formulario/vista | `apps/reports/forms.py`, `apps/reports/views.py` |
| Pantalla | `apps/reports/templates/reports/cash_closing.html` |
| Ruta | `/reportes/cierre-caja/` |
| Permiso | `payments.view_cash_closing` |
| Pruebas | `apps/reports/tests/test_cash_closing.py`, `test_user_income.py` |

La pantalla conserva los filtros principales del legado: Empresa, Desde,
Hasta, Reporte, Usuario, Serie, Formato y Consolidado oficinas.

- La sede es la activa.
- Sin «Consolidado oficinas», se limita a la oficina activa.
- Empresa vacía significa todas las empresas de la sede.
- Usuario solo se habilita en «Ingresos por usuario»; en el consolidado no debe
  recortar resultados.

#### Consolidado de emisión

Es la **referencia operativa del cuadre diario de Contabilidad**.

La estructura observada incluye:

```
CONTROL ADMINISTRATIVO EMISIÓN
SALDO ANTERIOR
INGRESOS
  Facturas
  Boletas
  Recibos de servicios públicos
  Garantías / Otros
EGRESOS
  Depósitos
  Gastos
SALDO EN CAJA
COMPOSICIÓN
```

El SICV nuevo reproduce actualmente el bloque documental principal y las
salidas Excel/PDF, pero los movimientos que aún no existen en el dominio
(gastos, depósitos, composición y saldo de apertura persistido) no pueden
cuadrarse de forma completa.

**No imponer** `Movimiento caja == Consolidado de emisión`: el primero refleja
movimiento de dinero/cobranza y el segundo agrupa emisión documental por tipo y
serie. Una diferencia entre ambos puede ser válida y debe poder explicarse.

#### Ingresos por usuario

El reporte produce una fila por concepto/cargo cubierto, no por comprobante.
Un mismo comprobante puede ocupar varias filas.

Columnas:

```
Código
Fecha
Abonado
Dirección
Fecha pago
Detalle
Pagó hasta
Monto
Documento
Usuario
```

Validado contra exportaciones reales del legado:

- `NINGUNO` = todos los usuarios.
- Con un usuario elegido solo aparecen sus registros.
- Las líneas del mismo comprobante permanecen juntas.
- `Pagó hasta` se informa por concepto.
- El total del pie coincide con la suma de las filas.

La semántica temporal ya quedó validada con exportaciones reales donde
`Fecha` y `Fecha pago` difieren: la fila aparece en el día de
`Fecha pago`, no en el día de emisión. La implementación del SICV nuevo fue
corregida para recortar por `Payment.paid_at`.

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

### A.2 Exportación del historial de pagos

En la ficha del abonado, Historial de pagos permite exportar Excel/PDF.

| Pieza | Dónde |
|---|---|
| Excel/PDF | `apps/payments/history_export.py` |
| Vista | `CustomerPaymentHistoryView.get` |
| Pruebas | `apps/payments/tests/test_history_export.py` |

- Exporta todas las filas del historial, no solo la página visible.
- Incluye operación/referencia y observación o motivo de anulación.
- Usa el mismo permiso que la consulta del historial.
- Los textos destinados a Excel se protegen contra formula injection.

### A.3 Capacidades existentes

| Necesidad | Estado | Soporte / observación |
|---|---|---|
| Total por día/rango | Existe | `DailyCashView`, `reports.cash_closing` |
| Sede | Existe | `Payment.branch` |
| Oficina/caja | Existe | `Payment.office` |
| Empresa emisora | Existe | `Issuer`, `ReceiptSequence.issuer` |
| Serie/talonario | Existe | `ReceiptSequence`, `Receipt` |
| Usuario que registra | Existe | `Payment.received_by`, Ingresos por usuario |
| Cobrador | Parcial | `Payment.collector`, sin reporte específico |
| Medio de pago | Existe/Parcial | `Payment.method`; disponible en detalle |
| Pendientes | Existe | `Payment.Status.PENDING` |
| Anulados | Parcial | Se audita el pago, pero un cambio posterior altera reportes históricos recalculados |
| Fecha emisión vs pago | Existe | `Receipt.issued_at`, `Payment.paid_at` |
| Deuda por abonado | Existe | cargos y deuda de cliente |
| Pagos parciales | Capacidad técnica; fuera del flujo ATC confirmado | `PaymentAllocation` admite parciales; ATC confirmó cobro completo del plan. Falta contrastar la pantalla nueva con esta regla. |
| Compromisos | Existe | modelos de compromisos/cuotas |
| Saldo a favor | Parcial | `Payment.unallocated_amount`; sin tablero propio |
| PDF de comprobante | Existe | representación impresa |
| Cierre guardado | Falta | hoy se recalcula en cada consulta |
| Gastos | Falta | no hay entidad operativa equivalente |
| Depósitos | Falta | no hay entidad operativa equivalente |
| Composición/arqueo | Falta | no hay snapshot de efectivo declarado |
| Banco/conciliación | Falta | sin módulo contable/bancario |
| Proveedores/CxP | Fuera del alcance actual | el flujo legado relevado es de clientes |
| Libro de ventas | Falta / no prioritario | el área indicó que no usa actualmente el reporte legacy |
| Emisión fiscal real | Falta | no hay XML firmado/transmisión/CDR demostrados |
| Notas de crédito | Falta | requiere validar el flujo real |
| Plan contable/asientos/EEFF | Fuera del alcance | no construir sin requerimiento |

---

## B. Hallazgos operativos que cambian el diseño

### B.1 Gastos, depósitos y composición pertenecen al cierre de ATC

ATC registra los movimientos de su caja y cada cajero realiza su cierre. Por
tanto, no basta un reporte global de fechas: el modelo futuro debe poder
identificar, como mínimo:

- sede y oficina;
- cajero/responsable;
- apertura o saldo base;
- cobros;
- gastos;
- depósitos;
- composición declarada;
- saldo esperado y diferencia;
- estado de cierre;
- usuario/fecha de cierre.

El cierre final debe ser persistido y auditable. Un pago anulado después no
debe reescribir silenciosamente un cierre ya aprobado.

### B.2 Condonación = ajuste comercial, no anulación fiscal

El legado usa condonaciones para más de un caso:

- neutralizar mensualidades duplicadas por error del generador;
- corregir diferencias de una mensualidad/cobro.

El SICV nuevo ya debe impedir duplicación por diseño/idempotencia, pero además
necesita una operación explícita de ajuste:

```
ChargeAdjustment
- cargo
- tipo/motivo
- monto
- usuario
- fecha
- referencia
```

No borrar el cargo original.

### B.3 Control por entidad legal

Contabilidad mantiene un control auxiliar de **recaudación/pagos de clientes
por entidad legal**, hoy revisado aproximadamente cada quince días.

El SICV debería ofrecer un tablero diario con acumulados por:

- entidad legal;
- sede/oficina;
- serie;
- periodo;
- medio de pago cuando aporte valor.

Los umbrales deben ser configurables/administrativos y el sistema debe
**informar**, no cambiar automáticamente de entidad legal al alcanzar un
umbral.

La dotación de personal por entidad legal pertenece al dominio RR. HH.; puede
mostrarse en un tablero gerencial, pero no debe formar parte de la lógica de
caja.

### B.4 Unidades operativas legacy

El selector legado mezcla conceptos distintos.

**APP Perú**

- unidad comercial lógica para IPTV/app;
- la plataforma técnica de aprovisionamiento es externa al SICV;
- Plan, disponibilidad por unidad y Tarifa son conceptos separados;
- el corte/activación técnica es manual en la plataforma externa;
- el flujo observado usa recibo interno y no tiene integración fiscal completa.

**Eco Net**

- operación ISP territorial con oficina/local propio;
- usa Internet FTTH, suscripciones, deuda, facturas, pagos y OTs;
- se observaron tarifas históricas por fecha;
- un plan real tenía tarifa/suscripciones pero no relación `Plan x Sucursal`,
  evidencia de inconsistencia tolerada por el legado;
- una OT existía enlazada desde la suscripción aunque el listado general no la
  mostraba.

Implicación arquitectónica: separar **unidad/marca**, **sede**, **oficina**,
**plan**, **disponibilidad**, **tarifa**, **suscripción** y **aprovisionamiento**.

---

## C. Fiscal: qué sabemos y qué no

### Confirmado funcionalmente

- El legado emite comprobantes de clientes.
- Contabilidad revisa posteriormente si esos comprobantes llegaron/figuran
  correctamente en una herramienta externa de SUNAT.
- Hay casos que requieren revisión por error humano o del sistema.
- El legado conserva PDF/XML para parte de sus comprobantes.
- Los reportes legacy `Resumen comprobantes SUNAT`,
  `Archivos Facturador SUNAT` y `Emisión de comprobantes electrónicos` no
  forman parte actualmente del flujo cotidiano del área.

### No confirmado técnicamente

No se sabe todavía si el legado usa:

- envío directo;
- Facturador SUNAT;
- PSE/OSE;
- otro servicio intermedio.

Tampoco están documentados todavía:

- formato XML exacto;
- firma;
- CDR/respuesta;
- reintentos;
- baja;
- contingencia;
- relación exacta de notas de crédito.

Por ello el SICV nuevo no debe codificar una integración fiscal suponiendo el
mecanismo.

Una acción legacy llamada «eliminar/anular» tampoco prueba que el documento
desaparezca fiscalmente. El modelo nuevo debe conservar el documento y su
historial de estados/correcciones.

---

## D. Requerimientos confirmados

1. **Consolidado de emisión** es la fuente principal del cuadre diario.
2. Contabilidad y Administrador deben poder consultarlo.
3. El cuadre se realiza por sede y puede consolidar oficinas.
4. ATC registra gastos, depósitos y composición de su caja.
5. Cada cajero realiza su cierre.
6. `Ingresos por usuario`: sin usuario salen todos; con usuario se filtra y
   Desde/Hasta recorta por fecha real de pago.
7. Registro de Ventas no es un reporte operativo actual de Contabilidad.
8. Los tres reportes fiscales legacy relevados no deben replicarse por defecto.
9. El control auxiliar por entidad legal se basa en recaudación/pagos de
   clientes y conviene ofrecerlo diariamente.
10. SUNAT sigue fuera de esta iteración hasta validar el mecanismo técnico real.

---

## E. Backlog propuesto

### P0 · antes del piloto financiero

- Cuadrar **Consolidado de emisión** legado vs nuevo con mismos filtros.
- Contrastar la pantalla de cobro nueva con la regla ATC de importe completo;
  `Pagó hasta` ante pago parcial queda no aplicable al flujo actual.
- Definir propiedad exclusiva de series/talonarios durante convivencia.
- Mantener generación mensual idempotente y pruebas de reejecución.
- Diseñar estados fiscales internos sin implementar aún el transporte SUNAT.

### P1 · antes de producción

- Gastos.
- Depósitos.
- Composición/arqueo.
- Cierre persistido/inmutable.
- Movimiento de caja como ledger.
- Ajustes/condonaciones de cargos con auditoría.
- Dashboard diario por entidad legal.
- Notas de crédito y flujo fiscal real una vez validado.
- Matriz definitiva de permisos.

### P2/P3 · solo por necesidad confirmada

- Consolidado de ingresos separado.
- Resumen de caja legacy.
- Registro de ventas legacy.
- Reportes legacy de archivos/resumen SUNAT.
- Contabilidad ERP (proveedores, libro mayor, asientos, EEFF).

---

## F. Riesgos

- **Correlativos compartidos.** Durante el piloto un mismo talonario no puede
  emitirse simultáneamente desde legado y nuevo.
- **Periodos mutables.** El cierre actual se recalcula; una anulación posterior
  puede cambiar un periodo ya cuadrado.
- **Saldo incompleto.** Sin gastos/depósitos/composición, el saldo del SICV
  nuevo no constituye un arqueo real.
- **Metadatos históricos mutables.** El reporte consulta datos actuales de
  talonarios/emisores; un snapshot/cierre debe congelarlos.
- **Datos legacy inconsistentes.** Se observaron relaciones y fechas que no
  siempre son coherentes entre pantallas. La migración debe preservar
  `raw_payload`, normalizar solo reglas demostradas (por ejemplo sentinels) y
  marcar casos dudosos para revisión.
- **`01/01/1900`.** Se usa como ausencia de fecha en varios contextos; se
  normaliza a `NULL` cuando esa semántica esté demostrada, conservando el raw.

---

## G. Evidencia y estado técnico

La rama de entrega `feature/reporte-ingresos-usuario` quedó con CI verde y
pruebas específicas para:

- filtros por sede, oficina, empresa, serie y usuario;
- pendientes/anulados fuera de recaudación;
- totales por grupo/serie;
- permisos;
- aislamiento por sede;
- Excel/PDF;
- `NINGUNO` = todos los usuarios;
- protección contra formula injection.

Todos los datos automatizados son sintéticos. La rama de continuación es
`fix/accounting-legacy-validation`.

La lógica de fecha de `Ingresos por usuario` ya se ajustó a la evidencia del
legado: el rango filtra por `Payment.paid_at`.
