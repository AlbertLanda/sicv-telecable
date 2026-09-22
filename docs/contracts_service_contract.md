# Contrato de servicio

Alta del contrato desde la ficha del abonado, reconstruida sobre el
formulario «Nuevo Contrato Servicio» del sistema anterior.

Pantalla: `contracts:contract_create`
(`customers/<id>/contracts/create/`).

## Qué captura la pantalla

Los campos y su orden son los del sistema anterior, porque es la pantalla
que ATC tiene aprendida.

| Campo | Cómo se llena |
|---|---|
| Código | Automático. Es el correlativo interno del contrato; se muestra bloqueado con el valor que le va a tocar. |
| Número | Automático, formato `CONT-000001`. Bloqueado, con el número que va a quedar registrado. |
| Servicio | Se elige. Abre en DUO. Manda sobre el plan. |
| Plan | Se elige entre los del servicio. Abre en el primero del combo. |
| Suscripción | Automática. La resuelven el cliente, el servicio y el plan; se muestra bloqueada y por su código. |
| Estado | Automático y bloqueado: un contrato nuevo nace Activo. Cambia después por lo que pasa con el servicio. |
| Modalidad | Venta, Alquiler, Propio o Préstamo. Abre en Venta, que es lo habitual; sin opción vacía. |
| Cuotas | Número de cuotas pactadas. Mínimo 1. |
| Inicio | Fecha. Llega con la de hoy. |
| Última activación | Bloqueada. La estampa el sistema cuando el servicio queda activo, no el alta. |
| Correo y celular PlayHub | Solo para servicios que se entregan a una cuenta. Obligatorios ahí, rechazados en el resto. |

### Campos que no están

- **Fin** y **Último corte**: en el sistema anterior son casillas que el
  operador tampoco llena —las mueve la operación del servicio, no el alta—.
  El campo `end_date` sigue en el modelo, pero ya no se captura aquí.
- **Equipo**: el equipo instalado consta en la orden de instalación, que es
  donde se sabe cuál se instaló de verdad.
- **Plantilla** y **Medición**: no describen nada que el SICV registre.
- **Observaciones**: el contrato de servicio es un documento de datos. Lo que
  haya que contar de una atención se cuenta en la orden de trabajo, que es
  donde se lee. El campo `notes` sigue en el modelo, pero ya no se captura ni
  se muestra.

Consecuencia a tener presente: con la fecha de fin fuera del formulario
desapareció también la validación de vigencia mínima de seis meses que se
había pedido el 02/09. No había forma de conservarla sin el campo que
miraba. Si negocio sigue exigiendo una vigencia mínima, vuelve con el campo
que la sostenga.

## Servicio y plan son del contrato

El contrato guarda su propio `service_type` y `plan`, no solo el enlace a la
suscripción. El contrato es el documento, y un documento dice lo que se
firmó: si el plan viviera únicamente en la suscripción, cambiarlo mañana
reescribiría hacia atrás lo que el abonado firmó hoy.

Que el mismo dato viva en dos registros obliga a que no se contradigan, y de
eso se encarga `Contract.clean()`:

- el plan tiene que pertenecer al servicio elegido;
- la suscripción tiene que ser del mismo servicio y del mismo plan;
- la suscripción tiene que pertenecer al abonado de la ficha.

La suscripción sigue siendo el registro operativo —es la que instala, corta y
factura—; el contrato, el respaldo comercial.

## La cascada

Servicio manda sobre plan, y los dos deciden qué suscripción recibe el
contrato. El catálogo completo viaja con la página
(`plans_by_service_type`, `service_type_config`, `subscriptions_catalog`) y la
pantalla se repinta en el navegador sin ir y volver al servidor. Es el mismo
mecanismo que ya usaba el alta de suscripción, y por eso ambas leen del mismo
módulo: `apps/services/catalog.py`.

Al cambiar de servicio, el plan queda en el primero de ese servicio —el mismo
que encabeza el combo—, que es lo que hace el servidor al abrir la pantalla.
Así la fila de al lado no queda a medio llenar después de cada cambio.

Nada de eso sustituye la validación. Un POST armado a mano no pasa por ese
javascript, así que el servidor vuelve a resolver la suscripción y el modelo
vuelve a comprobar las tres correspondencias.

## La suscripción no se elige

El operador ya la eligió antes, al registrarla; aquí volvería a decidir lo
mismo con menos información delante. La resuelve `apps/contracts/subscriptions.py`
a partir de lo que el contrato ya dice: la suscripción **en Preventa, activa y
sin contrato vigente** de ese cliente, de ese servicio y de ese plan.

- Si hay más de una —dos altas del mismo plan en dos domicilios—, se toma la
  de menor número de servicio, que es la más antigua.
- Si no hay ninguna, el campo dice **Ninguno**, como en el sistema anterior, y
  al guardar el formulario avisa arriba: lo que falta es registrar la
  suscripción, no corregir un campo de esta pantalla.
- Las ya contratadas quedan fuera del grupo. Es un contrato por suscripción,
  y dejarlas dentro haría que la resolución eligiera justo la que el contrato
  rechaza después.

Se muestra **por su código**, igual que el código del contrato: un
identificador que pone el sistema, en un campo corto y bloqueado. El
domicilio y el plan de esa suscripción se leen en la ficha del abonado, que es
donde viven; en la vista del contrato, además, el domicilio va en la franja de
arriba.

El javascript aplica esa misma regla sobre el catálogo que viaja con la
página, en el mismo orden, para que el campo bloqueado diga desde el primer
momento lo que el servidor va a guardar.

## Cuenta PlayHub

Los campos de correo y celular aparecen solo cuando el servicio contratado se
entrega a una cuenta. Eso lo dice el servicio, no una lista de códigos en el
formulario: `ServiceType.requires_playhub_account`, igual que
`supports_tv_annexes`. Si mañana otro servicio se entrega así, basta activarle
la bandera en Configurar > Servicios.

La regla vale en los dos sentidos: donde el servicio la pide, los dos datos
son obligatorios; donde no, se rechazan. Un correo PlayHub guardado en un
contrato de internet no lo lee nadie.

## Catálogo sembrado

El catálogo vivo solo tenía INTERNET, CABLE y DUO, que son los tres servicios
con precios confirmados y tarifa por sede. El contrato se firma también sobre
lo que se vende fuera de la masiva, así que
`services/migrations/0011_catalogo_contratos_de_servicio.py` siembra:

| Servicio | Planes |
|---|---|
| SERVICIO DE TELÉFONO | RDSVM, UGEL, TELÉFONO TUNANMARCA |
| FIBRA OSCURA | ARRENDAMIENTO FIBRA OSCURA XIRRUS TEC |
| TRANSPORTE DE DATOS | TRANSPORTE DE DATOS 10 MB - OPTICAL NETWORKS |
| APPS | APP ESTANDAR, APP PREMIUM, APP PREMIUM - ST, APP PREMIUM PLUS, APP PREMIUM PLUS - RPR, APP PREMIUM PLUS - ST, APP TELECABLE |
| TV CABLE | TV CABLE FTTH - 40, TV CABLE FTTH - 50 |

Va por migración y no solo desde `cargar_catalogo_comercial` porque las bases
que ya están en uso no vuelven a correr ese comando: si el catálogo llegara
solo por ahí, el combo de servicio aparecería con tres opciones en unas bases
y con siete en otras.

Los dos planes de TV Cable sobre FTTH cuelgan del servicio CABLE, que la
migración no crea: en una base nueva lo crea el comando, que es donde viven
sus tarifas por sede, y allí también nacen esos dos planes. CABLE pasa a
llamarse **TV CABLE**, e INTERNET y DUO se escriben como el resto del
catálogo; ninguno cambia de código, que es lo que referencian el catálogo de
órdenes y las reglas de metraje.

**Pendiente de negocio:** los planes sembrados no tienen mensualidad ni
política de cobro. No están confirmadas, y una cifra inventada saldría en la
cotización como si fuera la oficial. Se configuran en Configurar > Planes.
Hasta entonces esos planes cotizan en S/ 0.00 y se muestran «sin política
asignada».

Dos nombres a confirmar con quien tenga el listado oficial delante:

- el plan se sembró como `APP PREMIUM PLUS - RPR`; en el pedido venía escrito
  «AP PREMIUM PLUS - RPR», que parece un desliz de tipeo frente a sus seis
  hermanos;
- la cortesía inicial de TV de los planes `TV CABLE FTTH - 40/50` quedó en
  cero, porque no se sabe cuántos puntos entran sin cargo. Con cero, cada
  punto adicional se cobra como anexo.

## El contrato registrado

La vista del contrato (`contracts:contract_summary`) muestra los mismos
campos, en el mismo orden y con la misma disposición que la pantalla donde se
registró, todos bloqueados. Es un solo documento: leerlo igual escribiéndolo y
consultándolo ahorra aprender dos pantallas, y es como lo presenta el sistema
que se está reemplazando.

Debajo va la Orden de Instalación, que no es parte del contrato pero sí el
paso siguiente del alta comercial: desde ahí se genera y se consulta.

## El contrato impreso

`contracts:contract_document` entrega el documento que el abonado firma y se
lleva: el contrato de abonado para la prestación de servicios públicos de
telecomunicaciones, con sus doce cláusulas transcritas del contrato vigente.

**Es un archivo, no una pantalla.** Es la misma decisión que cobranza tomó
para sus comprobantes: lo que pasa por la impresora tiene que ser el papel. No
hay página intermedia que duplique el documento ni diálogo que salte sin que
nadie lo pida.

Dos entregas del mismo PDF:

| Enlace | Qué entrega | Para qué |
|---|---|---|
| `?ver=1` | PDF *inline* | **Imprimir contrato**: se abre en la pestaña de al lado, en el visor del navegador, que ya trae imprimir y guardar. |
| sin parámetros | PDF como descarga | Guardarlo o adjuntarlo (`CONT-000001.pdf`). |

Se llega desde dos sitios:

- la columna **Documento** de la tabla de contratos de la ficha del abonado;
- el botón **Imprimir contrato** al pie de la vista del contrato.

### Tres piezas

```
document.py    →  qué datos van en los huecos
clausulas.py   →  el texto del contrato, una sola vez
      └── pdf.py → cómo se dibuja en papel  (ReportLab)
```

Es el reparto que el reporte de materiales ya declara para sus cuatro
salidas: el formato decide **cómo** se dibuja, nunca **qué** entra. El texto
del contrato vive en `clausulas.py` y no dentro del renderizador, así que
`pdf.py` se ocupa solo de tipografía, medidas y dónde parte una hoja.

Ese reparto nació para que un segundo formato no pudiera decir algo distinto
—Word, para editar antes de firmar, que se probó y quedó en espera—, y se
mantiene porque vale por sí solo: el día que ese formato vuelva, solo hay que
añadir un renderizador que recorra los mismos bloques.

El PDF lleva **cabecera con el logotipo, el código del contrato y el del
abonado, y pie con las oficinas y «Página N de M»** en todas las hojas: una
hoja suelta de un contrato tiene que poder identificarse sola.

El logotipo lo resuelve `apps/organization/branding.py`, el mismo módulo
que usa el comprobante de cobranza: dónde viven los archivos y cómo se
recortan se decide una sola vez para toda la empresa.

Lo que cambia entre los dos papeles es **qué dibujo pide cada uno**. El
comprobante usa el isotipo casi cuadrado, que le cabe en su columna estrecha;
el contrato usa el apaisado —marca y lema en una línea—, porque su cabecera es
una franja ancha y baja donde el isotipo saldría como un sello suelto.

Si el archivo falta, el contrato sale igual y la cabecera se queda con los
códigos, que es lo que identifica la hoja.

**Las cláusulas van palabra por palabra.** Es un documento con efectos
legales, no un resumen de lo que dice, así que la plantilla no reformula nada.
Lo único que el SICV pone son los datos que ya tiene, donde el documento
dejaba un corchete para llenar a mano:

| Hueco del documento | De dónde sale |
|---|---|
| Código de contrato | `contract.contract_number` |
| Nombre del cliente, DNI/RUC | el abonado |
| Dirección de instalación | el domicilio de la suscripción |
| Servicio contratado | servicio y plan **del contrato** |
| Fecha de suscripción | `contract.start_date`, también escrita en el cierre |
| Última fecha de pago | el último cobro registrado; en blanco si nunca pagó |
| Plan contratado \[ \] Mbps | `plan.speed_mbps` |
| Instalación S/ \[ \] | `subscription.base_installation_fee` |
| Mensualidad S/ \[ \] | `subscription.base_monthly_fee` |
| Cuenta PlayHub | solo si el servicio la requiere |

**Lo que el sistema no sabe se imprime como la línea en blanco que era.** La
elección de recibir promociones y la firma de la empresa se completan en el
papel.

La del abonado ya no: se recoge en su domicilio, en el móvil del técnico,
durante la instalación, y sale impresa sobre su línea. Ver
[contrata_firma_campo.md](contrata_firma_campo.md).

### Los datos de la empresa

La razón social y el RUC salen de las **empresas emisoras** que ya usa
cobranza (`Issuer`, código `INV`): el RUC de la empresa no puede vivir en dos
sitios que puedan dejar de coincidir. Si ese registro no está cargado, la
pantalla lo avisa en vez de imprimir un contrato sin quién lo firma.

Las oficinas comerciales, el teléfono y la ciudad cuyos tribunales resuelven
cambian por sede y están en `apps/contracts/document.py`. **Las tres sedes
salen de su contrato oficial**, entregados por administración; no hay nada
deducido.

| Sede | Ciudad del contrato |
|---|---|
| JAUJA | Jauja |
| HUANCAYO | Huancayo |
| OROYA | **Yauli – La Oroya** |

La ciudad no siempre es el nombre de la sede, y por eso es un dato aparte:
gobierna el subtítulo del título, los tribunales de la cláusula undécima y la
ciudad donde se suscribe, y La Oroya contrata y litiga como «Yauli – La
Oroya».

Una sede que no esté declarada imprime esos espacios en blanco a propósito: en
un documento que se firma, un espacio para completar a mano es preferible a
una dirección o una jurisdicción inventadas.

### Tres cosas que el documento dice y el sistema todavía no

Salieron al comparar cláusula por cláusula y conviene resolverlas con negocio:

- **Pronto pago:** la cláusula promete el descuento pagando *tres (3) días*
  antes del vencimiento. Las políticas cargadas en el sistema usan otros
  plazos (`CALENDAR_PP5`, `ANNIVERSARY_PP10`). El documento imprime la
  cláusula tal cual; si el plazo real es otro, hay que corregir uno de los
  dos.
- **Puntos de TV:** la cláusula incluye *dos (2)* puntos, y en el sistema es
  un dato por plan (`included_tv_points`). Hoy coinciden en los planes DUO,
  pero un plan con otra cortesía imprimiría una cláusula que no le
  corresponde.
- **Reconexión:** la cláusula trae S/ 15.00 como tarifa referencial escrita
  en el texto, no leída del tarifario.

## Lo que queda abierto

- **Última activación** no la estampa todavía ningún proceso: el campo existe
  y se muestra, pero hasta que la activación del servicio lo escriba, sale
  vacío en todos los contratos.
- **El cierre de la orden no exige la firma del abonado.** Se puede liquidar
  una instalación sin que nadie haya firmado, porque hoy hay altas donde el
  abonado no está presente. Si negocio decide que no debe haberlas, se exige
  en el resumen de cierre de la orden.
- **No hay edición de contrato.** El módulo sigue teniendo alta, resumen y
  generación de la orden de instalación. Corregir un contrato ya registrado
  —o cambiarle el estado a suspendido, cancelado o finalizado— no tiene
  pantalla.
- **Modalidad de los contratos anteriores** quedó vacía. La modalidad del
  equipo no se registraba, así que no hay de dónde deducirla; el formulario
  la exige de ahora en adelante.
- **Dos suscripciones del mismo plan en dos domicilios**: el contrato va a la
  más antigua y no hay forma de dirigirlo a la otra desde esta pantalla. Se
  llega a la correcta entrando desde el resumen de esa suscripción
  (`?subscription=<id>`). Si el caso resulta frecuente, hay que decidir cómo
  se elige sin devolver el combo.
