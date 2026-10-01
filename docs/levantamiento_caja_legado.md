# Levantamiento: Caja, comprobantes y facturación del SICV legado

Entregable del issue #22. Fecha: 2026-09-30.

**Fuentes.** Los hallazgos del área que Albert Landa registró en el issue,
coordinados por Kevin Rivera con el área, y la revisión del código del SICV
nuevo en la rama `feature/reporte-ingresos-usuario`.

**Método.** Solo lectura: navegación normal de la interfaz del legado, sin
crear, modificar, condonar ni anular nada.

**Privacidad.** El repositorio es público. Este documento no contiene nombres,
documentos de identidad, direcciones, importes, series concretas, usuarios,
capturas ni archivos reales. La evidencia concreta se entregó a Albert por un
canal privado.

Estado en el SICV nuevo: **Existe**, **Parcial**, **Falta** o **Por validar**.
«No relevado» quiere decir que la pantalla no se revisó en este levantamiento
y entra en la lista de dudas (sección 4).

---

## 1. Resumen

- **Caja en el legado son cuatro registros:** comprobantes, gastos, depósitos
  y composición (arqueo). El SICV nuevo solo tiene comprobantes.
- **Los reportes de caja no cuadran entre sí.** Para el mismo periodo y la
  misma sede, Consolidado de ingresos, Movimiento caja, Resumen de caja y
  Registro de ventas dan totales de entrada distintos. Antes de replicar más
  reportes hay que saber cuál es la fuente de verdad. Es el punto crítico del
  levantamiento.
- **El legado declara comprobantes ante SUNAT y el SICV nuevo no.** El
  mecanismo técnico del legado no se ha determinado.
- **Las condonaciones corrigen cargos duplicados** de mensualidad. No son una
  anulación fiscal.
- **Contabilidad vigila los acumulados por razón social** en un Excel aparte,
  cada quince días aproximadamente.

---

## 2. Fichas por pantalla

### 2.1 Caja

#### Control de comprobantes

| | |
|---|---|
| Objetivo | Alta, listado y detalle de comprobantes, con control de su estado. |
| Campos y filtros | No detallados en el levantamiento. |
| Estados | Pendiente, Anulado y Extraviado. |
| Acciones | Alta y consulta del detalle. Auditoría básica: usuario, fecha y acción. |
| Rol | Por validar. |
| Dependencias | Talonario o serie y empresa emisora. |
| SICV nuevo | **Parcial.** El comprobante nace al registrar el cobro, no hay alta suelta. El pago tiene los estados Cancelado, Pendiente y Anulado, y la anulación guarda usuario, fecha y motivo. No existe el estado Extraviado. |

#### Buscar / Listar comprobantes

| | |
|---|---|
| Objetivo | Consultar comprobantes emitidos y descargar su PDF o XML. |
| Campos, filtros y estados | No relevados. |
| SICV nuevo | **Parcial.** «Comprobantes» lista los de la sede activa, con filtro por día y búsqueda por serie, número, código, documento o nombre del abonado. Ofrece el PDF, pero no hay XML. |

#### Nota de crédito y Nota de crédito 2

| | |
|---|---|
| Objetivo | Anular o corregir un comprobante emitido. |
| Diferencia entre las dos | No relevada. |
| SICV nuevo | **Falta.** Figura como pendiente en el menú Caja. |

#### Gastos

| | |
|---|---|
| Objetivo | Registrar los egresos de caja. |
| Campos | Empresa, fecha, tipo de documento, serie y número, motivo, descripción, monto, cajero y anulación. |
| Estados | Vigente o anulado. |
| Efecto en caja | Aparecen en el Haber de Movimiento caja y reducen el saldo. En el consolidado entran como egreso. |
| Tipos y relación con comprobantes | Por validar. |
| SICV nuevo | **Falta.** La fila de gastos del consolidado sale en 0. |

#### Depósitos

| | |
|---|---|
| Objetivo | Registrar el dinero de caja depositado en el banco. |
| Campos | Empresa, fecha, cuenta bancaria, número de operación, monto, medio o referencia de pago, cajero, anulación y observaciones. |
| Estados | Vigente o anulado. |
| Efecto en caja | Egreso del consolidado («Depósito MN»). |
| Cuentas y bancos, sede u oficina | Por validar. |
| SICV nuevo | **Falta.** La fila de depósitos del consolidado sale en 0. |

#### Composición

| | |
|---|---|
| Objetivo | Arqueo físico de la caja. |
| Campos | Importes en billetes de 200, 100, 50, 20 y 10, monedas, cheques, vales, otros y el total calculado. |
| Persistencia | Por validar: si se guarda por día, por cajero o por oficina. |
| SICV nuevo | **Falta.** La sección de composición del consolidado sale en 0. |

### 2.2 Reportes

Todos se sacan por sede y periodo.

| Reporte | Para qué sirve | Quién lo usa | SICV nuevo | Prioridad |
|---|---|---|---|---|
| Consolidado de emisión | Cuadre de la sede: saldo anterior, ventas por tipo de documento y por serie, egresos, saldo en caja y composición. | Contabilidad | **Existe**, en Reportes › Cierre de caja, con Excel y PDF. Los egresos y la composición salen en 0. | P0 (cuadre en paralelo) |
| Consolidado de ingresos | Misma estructura que el de emisión. Su aritmética interna cuadra, pero su total de entradas difiere del de Movimiento caja. | Contabilidad | **Por validar** si es el mismo reporte que el de emisión o una variante. | P0 (validar) |
| Ingresos por usuario | Una fila por concepto cobrado, con su comprobante y quién lo registró, y el total al pie. Sin usuario elegido salen todos. | Contabilidad | **Existe** desde esta rama. | P0 (cuadre en paralelo) |
| Movimiento caja | Libro cronológico con Debe, Haber y saldo acumulado. Los cobros entran al Debe y los gastos al Haber. | Contabilidad | **Falta.** Necesita gastos y depósitos. | P1 |
| Resumen de caja | Resumen del periodo. En la muestra observada da ingreso 0 y «CAJA NO CUADRA», aunque hubo cobros. | Por validar | **Falta.** | P1, después de la duda 3 |
| Caja por día | No relevado. | Por validar | **Por validar** si equivale a la «Caja del día» del SICV nuevo (un día, agrupado por razón social). | P2 |
| Gastos | Listado de gastos del periodo. | Por validar | **Falta.** | P1, con el registro de gastos |
| Depósitos | Listado de depósitos del periodo con su total. | Por validar | **Falta.** | P1, con el registro de depósitos |
| Registro ventas | Detalle por concepto: un comprobante puede ocupar varias filas. Lleva tipo de documento (factura, boleta y recibo de servicio), empresa emisora y anulado. | Contabilidad | **Falta.** No hay libro de ventas. | P2 |
| Resumen comprobantes SUNAT | No relevado. | Por validar | **Falta.** | P1, con la emisión electrónica |
| Archivos Facturador SUNAT | No relevado. | Por validar | **Falta.** | P1, con la emisión electrónica |

Observaciones del Registro ventas:

- Gravado, Exonerado, IGV y Total vienen vacíos; el valor está en Monto.
- Algunas filas, sobre todo de facturas, traen la fecha de pago 01/01/1900. Se
  tratan como «sin dato» hasta validar qué significan.
- Su total no coincide con el del consolidado del mismo periodo.

### 2.3 Facturación electrónica

| Punto | Legado | SICV nuevo |
|---|---|---|
| ¿Declara ante SUNAT? | **Sí.** Un comprobante emitido por el legado figura como aceptado en la consulta pública de validez de SUNAT (verificado el 2026-09-14). | **No.** |
| Artefactos | PDF y XML desde Buscar/Listar comprobantes. Hay además pantallas de resumen y de archivos para SUNAT. | Solo el PDF (representación impresa con QR). |
| Generación, firma, envío, respuesta (CDR), baja y contingencia | **Por validar.** La interfaz revisada no muestra el mecanismo, y no se asume ni proveedor ni método. | **Falta.** |

Riesgo: los talonarios del SICV nuevo continúan las mismas series reales que
declara el legado. Si los dos sistemas emiten a la vez sobre el mismo
talonario, el correlativo de una serie que SUNAT vigila quedaría con números
repetidos o con huecos.

### 2.4 Organización y permisos

| Dimensión | Legado | SICV nuevo |
|---|---|---|
| Sede | Todos los reportes de caja se sacan por sede. | Cada pago tiene sede; los reportes usan la sede activa. |
| Oficina | «Consolidado oficinas» en el cierre de caja. | Cada pago tiene oficina (opcional en los cobros antiguos); el cierre filtra por la oficina activa. |
| Empresa emisora | Filtro «Empresa» en los reportes. El Registro ventas trae la empresa de cada fila. | Cada talonario tiene emisora; el cierre filtra por empresa y abre en «Todas». |
| Serie o talonario | El consolidado da un subtotal por serie. | Talonarios por oficina, con correlativo propio. |
| Usuario | Comprobantes, gastos y depósitos registran al cajero. Existe «Ingresos por usuario». | Cada pago registra quién lo cobró; existe «Ingresos por usuario». |
| Rol | **No relevado.** Falta la matriz de quién consulta y quién opera cada pantalla. | Contabilidad: solo el cierre de caja. Atención al Cliente: cobra y consulta comprobantes. Administrador: lo de Atención al Cliente más el cierre de caja. |

### 2.5 Prácticas operativas

**Condonaciones.**

- Legado: se usan para corregir mensualidades duplicadas que generó el sistema
  y evitar cobrarlas dos veces al cliente.
- SICV nuevo: **Parcial.**
  - Ya está la protección: una suscripción no puede tener dos mensualidades
    del mismo periodo, así que volver a correr la generación no duplica deuda.
  - No hay una operación trazable para anular o condonar un cargo con motivo y
    usuario. El cargo tiene el estado «Anulado», pero no guarda ni quién ni
    por qué.

**Control por razón social.**

- Legado: Contabilidad consolida en un Excel aparte la emisión por razón
  social y sede, cada quince días aproximadamente, para ver qué emisor se
  acerca a su límite operativo o tributario.
- SICV nuevo: **Parcial.** La caja del día agrupa por razón social y el cierre
  filtra por empresa, pero no hay acumulados quincenales ni mensuales.

---

## 3. Lo que ya quedó en el SICV nuevo

Detalle en [`accounting_gap_analysis.md`](accounting_gap_analysis.md), sección
A.1.

- **Reportes › Cierre de caja › Ingresos por usuario**: el formato del legado
  en Excel y PDF, con una fila por concepto cobrado y el total al pie.
- «Empresa» abre en «Todas», y «Usuario» queda bloqueado salvo en «Ingresos
  por usuario».

---

## 4. Dudas POR VALIDAR

**Fuente de verdad y reportes**

1. ¿Qué reporte es la fuente de verdad del cuadre: Consolidado de ingresos o
   Movimiento caja? ¿Qué significa exactamente «Total de Ventas»?
2. ¿Consolidado de emisión y Consolidado de ingresos son el mismo reporte o
   dos variantes? Hipótesis: uno parte de la emisión y el otro de la cobranza.
3. ¿Por qué Resumen de caja da ingreso 0 y «CAJA NO CUADRA» en un periodo con
   cobros? ¿Depende de algo que se registra aparte, como la composición?
4. ¿Por qué el total del Registro ventas no coincide con el del consolidado?
5. En Registro ventas, ¿las columnas Gravado, Exonerado, IGV y Total vacías
   son diseño del reporte o una limitación?
6. ¿Qué significa la fecha de pago 01/01/1900: no pagado o sin dato?
7. En Ingresos por usuario:
   - ¿recorta por fecha de emisión o por fecha de pago?
   - ¿«Usuario» es quien registra el cobro o el cobrador?
   - ¿qué pone en «Pagó hasta» cuando el concepto no cubre un periodo?

**Caja**

8. En Control de comprobantes, ¿qué es el «alta» (la emisión o el registro de
   un comprobante físico)? ¿Cuándo pasa un comprobante a Extraviado?
9. ¿En qué se diferencian Nota de crédito y Nota de crédito 2, y cuál es el
   flujo de cada una?
10. Gastos: ¿cuál es el catálogo de tipos y motivos, y cómo se relacionan con
    los comprobantes?
11. Depósitos: ¿cuál es el catálogo de cuentas y bancos? ¿Se registran por
    oficina?
12. Composición: ¿es el arqueo? ¿Se guarda por día, por cajero o por oficina?
    ¿Alimenta el Resumen de caja?
13. ¿Caja por día equivale a la «Caja del día» del SICV nuevo?

**Facturación electrónica**

14. ¿Quién genera, firma y envía hoy los comprobantes: desarrollo propio,
    facturador de SUNAT u OSE? ¿Qué hacen Resumen comprobantes SUNAT y Archivos
    Facturador SUNAT? ¿Cómo se manejan la baja y la contingencia?
15. Durante el piloto, ¿desde qué sistema se emite cada talonario?

**Organización**

16. Matriz de roles del legado: ¿quién consulta y quién opera cada pantalla de
    caja y de reportes?
17. ¿Qué límite vigila Contabilidad por razón social, y cada cuánto? Sin
    publicar cifras.

---

## 5. Propuesta de prioridad

Ningún punto se implementa antes de cerrar las dudas de las que depende.

### P0 · antes del piloto

- **Fuente de verdad del cuadre** (dudas 1 a 4). Sin ella no se replica ningún
  otro reporte de caja.
- **Emisión durante el piloto** (dudas 14 y 15): decidir qué sistema emite
  cada talonario, para no romper correlativos declarados.
- **Cuadre en paralelo:** sacar Consolidado de emisión e Ingresos por usuario
  en los dos sistemas para el mismo periodo y sede, y compararlos serie por
  serie.

### P1 · antes de producción

- **Gastos, depósitos y composición** (dudas 10 a 12), con sus reportes. Sin
  ellos el saldo en caja del SICV nuevo no sirve para un arqueo.
- **Movimiento caja y Resumen de caja**, una vez definida la fuente de verdad.
- **Cierre guardado:** congelar un periodo cuadrado para que una anulación o
  confirmación posterior no lo cambie.
- **Emisión electrónica** según el flujo que se valide (duda 14), con Resumen
  comprobantes SUNAT, Archivos Facturador SUNAT y la baja.
- **Notas de crédito** (duda 9).
- **Corrección trazable de cargos:** anular o condonar un cargo duplicado con
  motivo y usuario, sin borrarlo.
- **Permisos por rol** según la matriz del legado (duda 16).

### P2 · posterior

- **Registro ventas y libro de ventas** (dudas 5 y 6).
- **Tablero de acumulados por razón social**, sede, serie y tipo de
  comprobante, con vistas quincenal y mensual, para reemplazar el Excel manual
  (duda 17).
- **Caja por día**, si resulta distinta de la Caja del día (duda 13).
- **Más filtros en Comprobantes:** estado, tipo y rango de fechas.
