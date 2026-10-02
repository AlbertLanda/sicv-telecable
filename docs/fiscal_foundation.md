# Base de preparación de facturación

Primera entrega mientras Contabilidad confirma las reglas fiscales. Continúa
desde `fix/accounting-legacy-validation` en `feature/fiscal-foundation`.
No fusionar ni desplegar automáticamente. El PR de esta entrega permanece Draft.

## Qué se puede revisar ahora

- Pantalla **Comercial → Preparación de facturación**, ruta `/facturacion/`.
- Buscar un abonado por su código exacto dentro de la sede activa y seleccionar
  cargos existentes para guardar un borrador de factura, boleta o recibo de
  servicios públicos. El tipo es una propuesta, no una habilitación del emisor.
- Ver una copia de emisor, receptor propuesto, conceptos, cantidades, periodos,
  importes y decisiones pendientes tal como estaban al preparar el borrador.
- Descartar un borrador con motivo, usuario y fecha sin borrar su evidencia.
- Guardar por emisor modalidad, nombre de proveedor, tipos de documento,
  momento de emisión y referencias de decisiones contables. Cada guardado
  desde la pantalla o el admin crea una revisión de configuración.

La preparación está separada de `Payment` y `Receipt`: también admite cargos
no pagados. Toma **importes originales**, no saldos pendientes. Conserva la
información de pronto pago, pero todavía no determina su tratamiento fiscal.
No calcula IGV ni concede descuentos fiscales de forma implícita.

Los borradores son copias para revisión. Un cargo puede aparecer en más de un
borrador; todavía no existe una operación de emisión que decida el documento
fiscal definitivo o reserve ese cargo. No sumarlos como ventas ni ingresos.

## Controles implementados

- Una solicitud repetida con la misma clave y datos devuelve el mismo
  borrador, sin añadir otro evento de creación. La clave incluye usuario,
  emisor, abonado, sede, fecha, tipo y cargos; reutilizarla con otros datos falla.
- Preparación y evento se guardan en una sola transacción. Se bloquean el
  abonado y los cargos en PostgreSQL. La suite SQLite prueba idempotencia
  secuencial y atomicidad, no acredita concurrencia real en PostgreSQL.
- Los cargos deben pertenecer al abonado de la sede activa, no estar anulados
  y compartir moneda. No se acepta una lista vacía ni cargos repetidos.
- Los borradores no modifican deuda, pagos, recibos o talonarios internos.
- Lectura, creación, configuración y descarte requieren permisos explícitos.
  Las URLs de detalle, preparación y descarte respetan la sede activa.
- El contenido del borrador se congela en `save`; el admin de documentos,
  eventos y revisiones es de solo lectura. La base restringe los estados a
  borrador o descartado, sin permitir una aceptación fiscal ficticia.
- El descarte es transaccional, requiere motivo y no duplica eventos al repetir
  la operación. `submit_document` siempre rechaza la emisión: completar la
  configuración no puede habilitarla.

Estos controles son del dominio y de las rutas del producto. No constituyen
protección contra alguien con acceso directo de escritura a la base de datos;
no utilizar `QuerySet.update`, SQL o scripts para alterar evidencia fiscal.

## Preparación local

Con las variables de entorno del proyecto y su entorno virtual:

```bash
python manage.py migrate
python manage.py check
python manage.py test apps.fiscal
```

Un superusuario puede revisar las pantallas. Los demás usuarios necesitan
permisos asignados explícitamente mediante el administrador de usuarios:

| Acción | Permisos |
| --- | --- |
| Consultar | `fiscal.view_fiscaldocument` |
| Preparar borradores | consulta y `fiscal.add_fiscaldocument` |
| Descartar | consulta y `fiscal.cancel_fiscaldocument` |
| Configurar por empresa | `fiscal.add_fiscalprofile` y `fiscal.change_fiscalprofile` |

No se cambian los permisos base de ATC, Contabilidad o Administración.
La asignación definitiva permanece pendiente del área. La primera configuración
se crea desde la pantalla por empresa; el admin puede consultar o modificar
perfiles ya existentes y conserva sus revisiones.

## Decisiones que quedan para Rosa

| Confirmación | Qué se completará después |
| --- | --- |
| Qué documentos emite cada RUC y por qué modalidad | Validaciones por emisor y adaptador fiscal compatible |
| Emisión mensual, al cobrar u otra regla | Disparador de emisión independiente del registro de dinero |
| Receptor fiscal y domicilio, distintos del titular cuando corresponda | Datos fiscales específicos por operación |
| Impuestos, conceptos, descuentos, anticipos y condiciones de crédito | Cálculo versionado y validado con casos de Contabilidad |
| Series y correlativos, propietario durante la coexistencia | Numeración fiscal única y corte de operación |
| Casos y reportes para dar conformidad | Pruebas de aceptación y conciliación |
| Alcance de registro de ventas/SIRE | Entrega posterior si Contabilidad la requiere |

No es necesario esperar estas respuestas para revisar pantallas y trazabilidad.
Una confirmación posterior no recalcula un borrador antiguo: se prepara uno
nuevo para conservar las distintas versiones revisadas.

## Lo que esta entrega todavía no hace

No genera XML/UBL, firma, PDF fiscal, QR fiscal, series oficiales ni envío a
SUNAT/PSE/OSE. No simula aceptación y no añade documentos a reportes de caja.
No implementa notas de crédito/débito, bajas, resúmenes, consulta de tickets,
entrega al cliente, contingencia o SIRE. Tampoco resuelve por sí sola los
pendientes de cobro completo, concurrencia de pagos, egresos o cierres de caja
identificados en `levantamiento_caja_legado.md`.

La entrega posterior `feature/ose-connector-foundation` añade una estructura
por empresa, un contrato interno y un simulador de envío/consulta recuperable.
La guía está en [ose_connector_foundation.md](ose_connector_foundation.md).
El simulador no implementa el contrato de un proveedor ni calcula impuestos.
Las reglas de cálculo y el adaptador real continúan pendientes de validación. La
emisión real requerirá además las reglas y habilitación por emisor, archivos y
respuestas verificables, numeración y revisión del procedimiento de cambio.

SUNAT describe los tipos de documento, conservación y respuestas en
[SEE del contribuyente](https://cpe.sunat.gob.pe/sistema_emision/see_contribuyente).
Las condiciones deben verificarse para la modalidad y tipo elegidos. Esta base
es preparación de software, no una certificación o autorización fiscal.

## Validación de esta entrega

- Django 5.2.17, Python 3.11.16: `check` correcto y sin migraciones faltantes.
- Suite completa: 1.850 pruebas correctas, incluidas 28 del nuevo módulo.
- La suite también pasó en el entorno local con Python 3.12.
- No se registraron transacciones en el sistema legado ni se habilitó emisión.
