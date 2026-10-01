# Contabilidad y cobranza: qué tiene SICV y qué falta

Auditoría del issue #20 («Auditoría contable integral + MVP de recaudación
para Contabilidad»), hecha sobre `feature/accounting-audit-kevin`, que parte
de `feature/sicav-legacy-import` (`fe23eb5`). Fecha: 2026-09-29.

Resumen:

- SICV ya registra casi todo lo que un cuadre de caja necesita **por pago**:
  sede, oficina, empresa emisora, talonario, método, referencia, usuario,
  cobrador, fecha de emisión, fecha real de pago, pendientes y anulados.
- Esta rama cubre **uno de los reportes de cierre validados en esta
  iteración**: **Reportes › Cierre de caja › Consolidado de emisión**, y agrega
  la exportación a Excel y PDF del historial de pagos del abonado. El sistema
  legado dispone de más reportes contables/fiscales; su uso y prioridad deben
  validarse antes de replicarlos.
- No existe nada de contabilidad administrativa (gastos, depósitos, bancos,
  cierres guardados, libro de ventas) ni emisión fiscal real a SUNAT. SUNAT
  queda fuera de esta iteración.

---

## A. Lo que SICV ya tiene

### A.1 Nuevo en esta rama: Reportes › Cierre de caja

El MVP del issue. Solo lee: no toca pagos ni comprobantes.

| Pieza | Dónde |
|---|---|
| Construcción del consolidado | `apps/reports/cash_closing.py` |
| Salidas Excel y PDF | `apps/reports/cash_closing_exporters.py` |
| Filtros y vista | `apps/reports/forms.py` (`CashClosingForm`), `apps/reports/views.py` (`CashClosingView`) |
| Pantalla | `apps/reports/templates/reports/cash_closing.html` |
| Ruta | `/reportes/cierre-caja/` (el formulario viaja por GET a la misma ruta) |
| Permiso | `payments.view_cash_closing` (migración `payments/0021`), disponible para **Contabilidad** y **Administrador** mediante la matriz base de roles |
| Pruebas | `apps/reports/tests/test_cash_closing.py` y `test_user_income.py` |

**Pantalla.** Mismo diseño que el reporte de materiales, con los campos de
SICAV en su orden: Empresa, Desde, Hasta, Reporte (Consolidado de emisión
o Ingresos por usuario), Usuario, Serie, Formato (Excel o PDF) y Consolidado
oficinas. El botón
**Exportar** saca el consolidado en el formato elegido.

El formulario abre con el mes en curso. La sede es siempre la activa. Sin
«Consolidado oficinas», el cierre se limita a la oficina activa de la barra
superior. «Empresa» abre en **Todas**: sin elegir una, el cierre suma todas
las empresas de la sede.

**Usuario** está bloqueado salvo en «Ingresos por usuario». En el consolidado
no recorta nada, aunque llegue en la dirección.

**Ingresos por usuario** (`apps/reports/user_income.py` y
`user_income_exporters.py`) es el «Reporte de ingresos» de SICAV, en Excel o
PDF apaisado:

- Título «Reporte de ingresos: desde - hasta Usuarios» (o el usuario elegido),
  la hora en la esquina y la sede a la derecha.
- Una fila por concepto cobrado, no por comprobante: Código, Fecha, Abonado,
  Dirección, Fecha pago, Detalle, Pagó hasta, Monto, Documento y Usuario. Lo
  que un pago no aplicó a ningún cargo sale como «Saldo a favor».
- El **total** al pie, bajo Monto.
- Sin usuario salen todos, como con el «NINGUNO» de SICAV.
- Mismas reglas que el consolidado (solo cancelados, recorte por emisión), así
  que con los mismos filtros su total es el Total de Ventas.

POR VALIDAR contra SICAV: si recorta por emisión o por fecha de pago, qué
pone en «Pagó hasta» cuando el concepto no cubre un periodo (SICV lo deja en
blanco), y si «Usuario» es quien registra o el cobrador.

**La hoja** es la de SICAV fila por fila, con sus mismos textos:

```
usuario dd/mm/aaaa hh:mm:ss                                   <Sede>
                 CONTROL ADMINISTRATIVO EMISIÓN
                 Desde dd/mm/aaaa Hasta dd/mm/aaaa
SALDO ANTERIOR      Total
INGRESOS            Total de Ventas
                      . Facturas / . Boletas / . Recibos de servicios públicos
                        .. Serie <MARCA> - <número>   (una línea por talonario)
                    Garantias, Otros, ... TOTAL
EGRESOS             (-)Garantias, (-)Deposito MN, (-)Gastos RECIBO, ... TOTAL
SALDO EN CAJA
COMPOSICION         Billetes de 200/100/50/20/10, Monedas, Cheques,
                    Vales Personal, Otros, ... TOTAL
```

Las series visibles en el consolidado siguen el orden observado en el sistema
legado y figuran aunque no hayan emitido. El padrón operativo de talonarios se
mantiene separado para no cambiar qué puede emitir cada ventanilla. Si aparece
un talonario con movimiento que no estaba en la lista de referencia, se agrega
al final de su grupo para no omitir montos. Los detalles exactos de series y
catálogos reales se mantienen fuera de esta documentación pública. El Excel
tiene una segunda pestaña, **Detalle**, con un comprobante por fila y totales
por estado. El total cancelado del detalle coincide con el Total de Ventas.

**Reglas acordadas con Contabilidad** (sección D):

1. Solo suman los comprobantes de pagos **cancelados**. Pendientes y anulados
   quedan en la pestaña Detalle, con su estado.
2. El periodo se recorta por la **fecha de emisión** del comprobante.
3. Las filas que SICV no registra (saldo anterior, garantías, otros, depósito
   MN, gastos y la composición) salen en **0**.
4. La hoja es **igual a la de SICAV**: nada que la de SICAV no tenga.

**Diferencias de padrón.** Se detectaron diferencias entre el catálogo del
sistema legado y el catálogo sembrado en SICV. Antes del piloto se debe
conciliar el padrón real (serie, emisor, correlativo y sede) en documentación
interna; no se publican aquí identificadores operativos concretos.

### A.2 Nuevo en esta rama: exportar el historial de pagos

En la ficha del abonado, pestaña **Historial de pagos**, la tarjeta «Pagos»
tiene un botón **Exportar** con dos opciones: **Excel (.xlsx)** y **PDF**.

| Pieza | Dónde |
|---|---|
| Excel y PDF | `apps/payments/history_export.py` |
| Vista | `CustomerPaymentHistoryView.get` (`?exportar=excel` / `pdf`) |
| Botón | `payments/customer_payment_history.html` |
| Pruebas | `apps/payments/tests/test_history_export.py` (8 pruebas) |

- Exporta **todas las filas** del historial, no solo la página a la vista.
- Lleva las columnas de la tabla en su orden. El número de operación y la
  observación (o el motivo de la anulación), que en pantalla aparecen al
  pasar el cursor, van en columnas propias.
- Usa el mismo permiso que el historial: quien lo ve puede exportarlo.

También se probó un componente «Recaudación» con resumen, tablas y detalle
bajo el cierre de caja, pero se retiró a pedido de Contabilidad. De ese
intento quedó `payments.services.paid_between`, la regla del día de cobro que
ahora usa la caja del día.

### A.3 Lo que ya existía

| Necesidad contable | Existe | Parcial | No existe | Archivo/modelo que lo soporta | Observación |
|---|:-:|:-:|:-:|---|---|
| **Recaudación / caja** | | | | | |
| Total por día | ✓ | | | `payments.views.DailyCashView`; `reports.cash_closing` | La caja del día muestra un día. El cierre admite cualquier rango. |
| Por sede | ✓ | | | `Payment.branch` | Los dos reportes usan la sede activa. |
| Por oficina/caja | ✓ | | | `Payment.office`, `organization.Office` | La oficina es opcional en pagos antiguos, anteriores al padrón de oficinas. |
| Por razón social/RUC | ✓ | | | `Issuer`, `ReceiptSequence.issuer` | La caja del día agrupa por emisora y el cierre filtra por emisora. |
| Por medio de pago | | ✓ | | `Payment.method` | La caja del día agrupa por método. El cierre no lo desglosa, porque la hoja de SICAV tampoco; el detalle del Excel trae el método. |
| Por usuario que registra | ✓ | | | `Payment.received_by` | Reporte «Ingresos por usuario» del cierre. |
| Por cobrador | | ✓ | | `Payment.collector` | Solo aparece en el detalle del Excel del cierre; no hay filtro ni subtotal. |
| Pagos pendientes | ✓ | | | `Payment.Status.PENDING`, `Payment.confirm()` | No bajan deuda ni suman en caja. |
| Pagos anulados | | ✓ | | `Payment.Status.VOIDED`, `voided_at/by`, `void_reason` | Anular un pago después cambia un periodo ya consultado (ver riesgos). |
| Referencia Yape/Plin/transferencia | ✓ | | | `Payment.reference`, `METHODS_REQUIRING_REFERENCE` | |
| Correlativos/talonarios | ✓ | | | `ReceiptSequence` (`select_for_update`), `OfficeSequence`, `Receipt` único por talonario y número | |
| Fecha de emisión vs. fecha real de pago | ✓ | | | `Receipt.issued_at`, `Payment.paid_at` | El detalle del cierre muestra las dos. |
| Cierre de caja guardado / arqueo | | | ✓ | — | El cierre se recalcula en cada consulta; no se guarda. |
| **Cuentas por cobrar** | | | | | |
| Deuda total del abonado | ✓ | | | `services.customer_debt`, `CustomerDebtView` | Por abonado, no por sede. |
| Vencida / no vencida | | ✓ | | `Charge.overdue()`, `Charge.is_overdue()` | Solo en la ficha del abonado. |
| Antigüedad (0–30, 31–60, 61–90, 90+) | | | ✓ | — | |
| Deuda por sede | | | ✓ | — | No hay reporte («Deudores» y «Cobranza» siguen pendientes). |
| Deuda por servicio/plan | | | ✓ | — | |
| Cargos parciales | ✓ | | | `Charge.Status.PARTIALLY_PAID`, `PaymentAllocation` | |
| Compromisos de pago | ✓ | | | `PaymentCommitment`, `PaymentCommitmentInstallment`, `PaymentCommitmentListView` | |
| Saldo a favor | | ✓ | | `Payment.unallocated_amount` | Se calcula por pago; no hay reporte. |
| **Comprobantes / fiscal** | | | | | |
| Boleta, factura, recibo de servicio | ✓ | | | `ReceiptSequence.SunatCode` (03, 01, 14) | Es la representación impresa, no una emisión fiscal. |
| Serie y número | ✓ | | | `Receipt.series`, `Receipt.number` | |
| Empresa emisora | ✓ | | | `Issuer` | |
| Base gravada e IGV | | ✓ | | `payments/invoicing.py` (`receipt_totals`) | Se calcula para imprimir; no se guarda ni se reporta. |
| Anulaciones | | ✓ | | `Payment.void()` | Es una anulación interna; no hay comunicación de baja a SUNAT. |
| PDF / representación impresa | ✓ | | | `payments/pdf.py`, `ReceiptPdfView` | |
| XML, envío a SUNAT, CDR | | | ✓ | — | `pdf.py` aclara que no hay XML firmado. |
| Notas de crédito/débito | | | ✓ | — | Figuran como pendientes en el menú Caja. |
| Detracción | | | ✓ | — | `docs/payments_module.md` la deja para cuando exista la factura electrónica. |
| **Contabilidad administrativa** | | | | | |
| Ingresos distintos a cobros de abonados | | | ✓ | — | La fila «Otros» del cierre sale en 0. |
| Egresos, gastos, caja chica | | | ✓ | — | «Gastos» figura como pendiente en el menú Caja. |
| Depósitos al banco / movimientos entre cajas | | | ✓ | — | «Depósitos» figura como pendiente en el menú Caja. |
| Bancos y conciliación bancaria | | | ✓ | — | Ojo: `TransferReconciliation*` es de traslados de servicio, no bancaria. |
| Cuentas por pagar, proveedores | | | ✓ | — | |
| Libro de ventas / PLE | | | ✓ | — | |
| Exportación para Contabilidad | | ✓ | | `reports.cash_closing_exporters`, `payments.history_export` | El cierre (Excel y PDF) y el historial de pagos del abonado (Excel y PDF). Falta el libro de ventas. |
| Plan contable, asientos, estados financieros | | | ✓ | — | El issue pide no construirlos sin validar el flujo. |

## B. Lo que está parcial

- **Método de pago y cobrador:** la hoja del cierre no los desglosa, porque
  la de SICAV tampoco; están en la pestaña Detalle del Excel.
- **Anulaciones:** el pago anulado conserva su comprobante y su motivo, pero
  anularlo en octubre cambia el cierre de septiembre la próxima vez que se
  consulte.
- **Cuentas por cobrar:** hay deuda, vencimientos y saldo a favor por
  abonado, pero ningún reporte de sede (antigüedad, por plan, deudores).
- **IGV:** se calcula para el papel, pero no queda guardado ni se reporta.

## C. Lo que no existe

En lo fiscal hay que distinguir tres niveles:

1. **Representación impresa y cálculo:** existe. El papel dice boleta,
   factura o recibo, con serie, número, emisora, base, IGV y QR
   (`payments/pdf.py`, `payments/invoicing.py`).
2. **Emisión fiscal real** (XML UBL firmado): no existe.
3. **Envío y estado en SUNAT** (OSE, CDR, aceptado o rechazado, baja): no
   existe.

Además no existen:

Emisión fiscal real (XML, firma, envío a SUNAT, CDR, baja), notas de crédito y
débito, gastos, depósitos, garantías, caja chica, cierres guardados y arqueo,
bancos y conciliación bancaria, cuentas por pagar, libro de ventas, plan
contable, asientos y estados financieros.

## D. Requerimientos confirmados

Los confirmó Kevin Rivera con el área el 2026-09-29. No hubo entrevista con
Sandra: no interviene en este reporte.

1. El reporte lo usa el **personal de Contabilidad** y debe poder consultarlo
   también un usuario **Administrador**.
2. Se cuadra **por sede**, una a la vez.
3. Va en **Reportes › Cierre de caja**, como en SICAV.
4. El formato de trabajo es el **Consolidado de emisión** exportado a Excel.
5. Suman **solo los cancelados**; pendientes y anulados quedan en la
   pestaña Detalle del Excel.
6. Las filas que SICV no registra salen **en 0**.
7. El periodo del cierre se recorta por **emisión del comprobante**.
8. El personal de Contabilidad **usa el Cierre de caja**. El componente de
   recaudación bajo el cierre se probó y se retiró; en su lugar, el historial
   de pagos del abonado se exporta a Excel y PDF.
9. **SUNAT** queda fuera de esta iteración. La revisión administrativa del
   legado confirma que existen funciones fiscales y archivos electrónicos,
   pero todavía falta determinar el mecanismo técnico de generación, firma,
   envío, respuesta y contingencia antes de diseñar la integración.

**Preguntas que siguen abiertas** (de las sugeridas por el issue):

- ¿Qué reportes se entregan a gerencia?
- ¿Qué datos necesitan para SUNAT?
- ¿Cómo manejan Yape, Plin y transferencias (quién los confirma y cuándo)?
- ¿Qué es indispensable antes de usar SICV en paralelo con SICAV?

## E. Backlog propuesto

### P0 · antes del piloto

- **Cuadre en paralelo:** sacar el mismo periodo y la misma sede en SICAV y en
  SICV y comparar el Total de Ventas talonario por talonario.
- **Asignar el rol Contabilidad** a las cuentas del área y aplicar la
  migración `payments/0021` en cada entorno.
- **Decidir quién emite ante SUNAT durante el piloto.** SICAV declara hoy los
  comprobantes y los talonarios de SICV continúan esas mismas series (ver
  riesgos).

### P1 · antes de producción

- **Egresos de caja:** gastos con recibo, depósitos en moneda nacional y
  garantías. Sin ellos el SALDO EN CAJA de SICV será mayor que el de SICAV.
- **Cierre guardado:** congelar el cierre de un periodo para que las
  anulaciones posteriores no lo cambien, y sacar de ahí el saldo anterior.
  Incluye el arqueo.
- **Emisión electrónica:** definir primero el flujo real del legado y el
  mecanismo autorizado para producción; después implementar XML, firma,
  transmisión, respuesta/constancia, bajas y notas de crédito según ese flujo.
- **Otros tipos de reporte** del desplegable de SICAV, cuando Contabilidad
  diga cuáles usa.
- **Reportes Deudores y Cobranza:** deuda por sede, antigüedad y por plan.

### P2 · posterior

Libro de ventas y exportación PLE, bancos y conciliación bancaria, cuentas por
pagar y proveedores, plan contable, asientos y estados financieros.

## F. Riesgos

- **SUNAT y correlativos compartidos.** SICAV declara comprobantes a SUNAT y
  SICV continúa las mismas series reales. Si los dos sistemas emiten a la vez
  sobre el mismo talonario, se repiten números o quedan huecos en una serie
  que SUNAT vigila. Durante el piloto, cada talonario debería emitirse desde
  un solo sistema.
- **Periodos que cambian.** El cierre se recalcula en cada consulta. Una
  anulación posterior o la confirmación posterior de un pago pendiente puede
  cambiar un periodo que Contabilidad ya dio por cuadrado. Mitigación:
  persistir un cierre guardado/auditable antes de producción.
- **Saldo en caja incompleto.** Sin gastos ni depósitos, el saldo en caja de
  SICV no descuenta nada, y la hoja no lo advierte porque es igual a la de
  SICAV. No sirve todavía para un arqueo físico.
- **Pagos sin oficina.** Los cobros anteriores al padrón de oficinas no
  tienen oficina: entran en el consolidado de la sede, pero no en el de
  ninguna oficina.
- **Metadatos históricos del talonario.** El reporte todavía consulta parte
  de la configuración actual del talonario (emisor, tipo y etiqueta). Un
  cambio posterior de catálogo podría alterar cómo se presenta un periodo
  antiguo. El cierre guardado o snapshots fiscales deben congelar esos datos.

## G. Evidencia

Comandos ejecutados en la rama:

```
python manage.py check                              → sin problemas
python manage.py makemigrations --check --dry-run   → sin cambios pendientes
python manage.py test apps.reports.tests.test_cash_closing
python manage.py test                               → suite completa
```

La revisión posterior añade cobertura para acceso de Administrador y para
evitar que textos que comienzan como fórmulas sean evaluados por Excel. La
cantidad final de pruebas queda sujeta al CI de la rama de revisión.

- filtros por fecha (extremos incluidos), sede, oficina, razón social, serie
  y usuario;
- que pendientes y anulados no inflen la recaudación;
- totales por grupo y por serie, y las series y el orden de la hoja de SICAV;
- permisos (Contabilidad y Administrador sí; ATC y anónimo no);
- aislamiento por sede;
- exportación: el Excel del cierre (y que su detalle suma el Total de
  Ventas), su PDF, y el historial de pagos en Excel y PDF con todas sus
  filas.

Todos los datos de prueba son sintéticos. El trabajo original está en
`feature/accounting-audit-kevin` y la revisión técnica en
`fix/accounting-audit-review`.
