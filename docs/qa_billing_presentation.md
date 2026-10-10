# Muestras de facturación para presentación en QA

La ficha del abonado autorizado HY01-A0000001 muestra ocho casos en
**Comprobantes > Ejemplos de facturación para presentación**. Se agregan mediante
`preparar_muestras_abonado_qa --billing-examples`, exclusivamente en el recurso
Azure `sicv-telecable-qa`. El arranque de ese entorno ejecuta el comando.

| Caso | Importe del ejemplo |
| --- | ---: |
| Plan 2026, pago dentro del plazo de S/10 | S/79 |
| Plan 2026, pago después del plazo | S/89 |
| Mensualidad y reconexión tras corte simulado | S/104 |
| Plan 2025, pronto pago hasta el día 29 | S/84 |
| Plan 2025, pago después del día 29 | S/89 |
| Primer mes calendario, instalación el día 7 | S/74,25 antes de descuento |
| Mensualidad 2026 por cobrar | Saldo vigente según el plazo de pronto pago |
| Mensualidad y reconexión con Yape por confirmar | S/104 pendientes |

Los periodos históricos se calculan al preparar los casos; se usan las políticas
confirmadas y el generador de cargos mensual. El primer mes conserva el prorrateo
comercial de 30 días existente. Las muestras del paquete 2026 desglosan servicio
S/81,50 y APP S/7,50 dentro del total de S/89.

Estos cargos manuales de muestra no ocupan periodos de la suscripción contratada.
La suscripción usada para calcular los casos existe solo en memoria. No se
modifican suscripciones, instalaciones ni órdenes existentes, y no se ejecutan
cortes de red. La reconexión de la muestra es un cargo manual identificado como
simulado; el flujo operativo de corte y reconexión se verifica en sus pruebas.

Los seis pagos/comprobantes nuevos pertenecen al talonario reservado DEMOQA.
La carga guarda un manifiesto de auditoría y es atómica e idempotente. Al repetirse,
conserva cualquier confirmación o anulación hecha por el usuario. Los correlativos
de los talonarios comerciales no se consumen. El estado público del arranque solo
expone conteos de muestras, sin identidad ni importes del abonado.

Un comprobante puede abrirse como **Ticket vertical** de 80 mm o **Media hoja
horizontal** A5 mediante `formato=TICKET` o `formato=SHEET` en la vista PDF. La
impresión no crea otro comprobante ni cambia su número, importes o talonario. El
formato predeterminado sigue siendo el configurado en el talonario; valores
desconocidos devuelven HTTP 400. Los formatos conservan los permisos y el alcance
de sede de la vista. Las fechas impresas corresponden a America/Lima y un pago
pendiente no muestra fecha de cancelación.

Las muestras imprimen el logo disponible, con el logo empaquetado como alternativa,
y la leyenda **Sin validez tributaria. No enviada a SUNAT**. La selección de formato
no realiza envíos fiscales ni movimientos bancarios.
