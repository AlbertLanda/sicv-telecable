# Módulo de cobranza

Primer bloque del módulo de pagos: qué debe el abonado, qué pagó y con qué
comprobante. Cubre el ciclo completo de ventanilla —consultar, cobrar, emitir
el recibo y anularlo— sobre el modelo de facturación que ya existía en
`apps.services`.

## Decisiones de negocio que lo definen

Tres decisiones tomadas antes de escribir el modelo, porque cambiarlas obliga
a rehacerlo:

1. **La deuda nace de un motor de cargos mensuales.** El sistema emite la
   mensualidad de cada suscripción activa según su `BillingPolicy`. No se
   registra a mano.
2. **El comprobante es un recibo interno de caja.** Numeración propia, sin
   SUNAT. La constancia acredita el pago ante la empresa, no ante la
   administración tributaria.
3. **El alcance incluye cobrar,** no solo consultar: métodos de pago,
   aplicación a cargos y anulación.

Emitir boleta o factura electrónica queda fuera. El modelo lo contempla: el
recibo es una entidad aparte del pago, así que emitir mañana un comprobante
fiscal sobre el mismo pago no obliga a rehacer lo cobrado.

## Entidades

    Charge              lo que se le cobra al abonado, con su vencimiento.
    Payment             el dinero recibido, con su método y dónde entró.
    PaymentAllocation   qué parte de un pago cubre qué cargo.
    Receipt             la constancia numerada que se entrega.
    ReceiptSequence     el talonario del que sale, con su correlativo.

El pago y el cargo no se tocan directamente. Un abonado que entrega S/ 120
sobre dos mensualidades de S/ 60 genera **un** pago y **dos** aplicaciones, y
así el historial responde tanto «cuánto entregó» como «qué mes quedó
cubierto». Amarrar el pago a un solo cargo obligaría a partir el dinero
recibido en registros que el abonado nunca hizo.

## El descuento por pronto pago no se resta al emitir

`Charge.amount` guarda el monto emitido. El descuento viaja aparte en
`early_discount` junto con su `discount_deadline`, y `amount_due_on(día)`
decide cuál de los dos vale.

Se hace así porque hasta que no se sabe *cuándo* paga el abonado no se sabe
cuánto debe. Restarlo al emitir daría por concedido un descuento que todavía
puede perderse, y el historial dejaría de poder explicar por qué se cobró una
cifra distinta a la del cargo.

## Generación de cargos

    python manage.py generar_cargos_mensuales --periodo 2026-09
    python manage.py generar_cargos_mensuales --periodo 2026-09 --dry-run
    python manage.py generar_cargos_mensuales --sede SED01

Se factura una suscripción cuando está `ACTIVE`, tiene política de cobro,
tiene mensualidad mayor a cero y su instalación no es posterior al mes
facturado. Una suscripción sin política **no** se factura: emitir igual
obligaría a inventar un vencimiento, y ese cargo decidiría por su cuenta la
fecha de corte del abonado.

El vencimiento sale de la modalidad de la política:

| Modalidad      | Vence                                  |
|----------------|----------------------------------------|
| Mes calendario | el último día del mes facturado        |
| Aniversario    | el día del mes en que se instaló       |

El comando es idempotente. La restricción única de `(subscription, period)`
para mensualidades lo garantiza en la base, no solo en el servicio: si se
corta a la mitad, se vuelve a lanzar y completa lo que falte sin cobrar dos
veces el mes.

## Pantalla de deudas

Replica el formato del SICV que se está reemplazando, para que el operador no
tenga que reaprender una lista que ya usa a diario:

    Abonado | Fecha | Cantidad | Detalle | Periodo | Moneda | Monto | Documento | Vencimiento | Cobrar

- **Fecha** es `issued_on`, la emisión. Se separa de `created_at` porque la
  mensualidad de septiembre lleva fecha 01/09 aunque la fila se escriba otro día.
- **Cantidad** lleva cinco decimales: el sistema anterior prorratea días de
  servicio y la fracción tiene que caber sin redondear.
- **Detalle** es el plan; el mes va en **Periodo**, como rango
  (`01/09/2026 - 30/09/2026`). Repetirlo en el detalle solo lo haría más largo
  de leer.
- **Documento** son los comprobantes que cancelaron el cargo. Vacío mientras no
  se cobre, y vuelve a vaciarse si el cobro se anula.
- **Cobrar** es la casilla de la fila. Debajo, un selector de filas (20 / 50 /
  100 / 500, por defecto 500).

### Los tres botones actúan sobre lo marcado

Un solo formulario envuelve la tabla y los botones, y cada uno declara su
destino con `formaction`. Los ids marcados se filtran contra la deuda abierta
del abonado: un id ajeno, ya pagado o no numérico que llegue en la URL no
entra ni al cobro ni al compromiso.

| Botón       | Qué hace                                     | Permiso                            |
|-------------|----------------------------------------------|------------------------------------|
| Nuevo       | emite una deuda a mano                       | `payments.add_charge`              |
| Cobrar      | cobra las filas marcadas                     | `payments.add_payment`             |
| Compromiso  | aplaza el corte de las filas marcadas        | `payments.grant_paymentcommitment` |

## Nueva deuda

Formulario del sistema anterior: Código y Fecha los pone el sistema; el
operador indica Cantidad, Concepto, Paga hasta, Monto, Descripción y
«Actualizar automáticamente» —que sale desmarcado, porque una deuda emitida a
mano es fija y no debe recalcularse si cambia el plan.

**Ofrece el concepto «Mensualidad»**, igual que el sistema anterior. Lo que
evita cobrar dos veces el mes de una suscripción no es esconder el concepto,
sino la restricción única de `(subscription, period)`; y como `full_clean()`
la valida antes de tocar la base, el intento se responde con un mensaje en
pantalla y no con un error 500. Si no se indica periodo, se toma el mes de la
fecha de emisión: el formulario no lo pide aparte porque la fecha ya lo dice.

«Calcular días según monto» traduce el monto a días de servicio usando la
mensualidad de la suscripción activa, para prorratear un periodo parcial. Solo
informa: no altera el monto que se guarda.

## Cobrar

Formato de comprobante: **Serie y lugar de cobro** en una misma fila —son los
dos datos que dicen de qué block sale el papel y en qué caja entró el dinero;
el lugar se lee, no se elige—,
**Número** debajo, la tabla de deudas elegidas con
`Cantidad | Abonado | Plan | Mes | Moneda | Monto | Desc | Total`,
el medio de pago, el cobrador y las observaciones.

`Plan` y `Mes` iban antes en una sola celda, el plan con el periodo debajo. El
papel del sistema anterior tiene dos columnas, y el operador que compara una
cosa con la otra tenía que leer una celda partida donde el papel le ofrece dos.
`Cantidad` se muestra entera: son unidades de un cargo, y los cinco decimales
del sistema anterior no describían ninguna cantidad que alguien cobre.

**Descuento** por fila es el pronto pago vigente ese día
(`Charge.current_discount`). Se guarda en la aplicación del pago
(`PaymentAllocation.discount`) para que el papel entregado al abonado pueda
explicar por qué una mensualidad de S/ 79 se cerró con S/ 69. Solo se concede
al cancelar el cargo completo dentro del plazo: un pago parcial no lo gana, o
pagar S/ 1 a tiempo rebajaría el mes entero.

### «Cancelado: No (Pendiente)»

Emite el comprobante sin que el dinero haya entrado. El pago queda en
`PENDING` y **no baja la deuda**: `Charge.paid_amount` solo cuenta pagos
`REGISTERED`. `Payment.confirm()` es lo que lo convierte en cobro real y
recién ahí el saldo baja. Si un pendiente descontara, el abonado quedaría al
día sin haber pagado y el corte no lo alcanzaría.

### Cobrador y usuario son distintos

`received_by` es quien asentó el cobro (el usuario de la sesión) y `collector`
quien trajo el dinero —un vendedor que cobró en campo—. Se ofrecen solo
usuarios del rol Ventas, para que el cuadre por cobrador signifique algo.

**Código de detracción** no se implementó: la detracción es de la factura
electrónica, y aquí el comprobante es interno sin SUNAT. Entra con ese bloque.

## Compromiso de pago

El abonado se obliga a pagar cargos concretos en una fecha, y hasta esa fecha
esos cargos dejan de empujarlo al corte.

**No mueve saldo.** El abonado sigue debiendo lo mismo: si conceder un
compromiso descontara la deuda, quedaría al día sin haber pagado nada. Lo
único que cambia es `Charge.is_protected_from_cut()`.

Se eligen cargos concretos y no «toda la deuda» porque el abonado se
compromete por lo que puede. Dejarlo abierto a lo que aparezca después le
daría protección sobre meses que todavía no existían cuando firmó. El monto
puede ser menor al saldo elegido —así se pactan muchos acuerdos— pero nunca
mayor.

La pantalla sigue el formato del sistema anterior, campo por campo:

    Código · Fecha · Hora · Fecha de pago · Autoriza · Deuda · Total
    Cuota 1 … Cuota 15 · Representante · DNI de rep. · Observaciones · Anulado

`granted_by` es quien lo teclea y `authorized_by` quien lo autoriza —se
ofrecen supervisión, retenciones y administración—: guardar solo al usuario
dejaría sin responsable una decisión comercial.

**La deuda se lee, no se elige.** Se marca en el tablero y la ficha la muestra
en un recuadro con una línea por deuda y su importe, como el papel del sistema
anterior. Volver a ofrecerla aquí para elegir eran dos sitios para decidir lo
mismo. Los cargos marcados viajan escondidos en el formulario: sin ellos el
compromiso se concedería sobre nada.

**Representante y DNI de rep.** son quien firma por el abonado cuando no es él
mismo. El acuerdo lo asume una persona, y si no es el titular hay que poder
decir quién fue.

**«Observaciones» dejó de ser obligatorio.** Se llamaba «motivo» y se exigía
—aplazar el corte de quien ya debe es una decisión que alguien tiene que poder
explicar—; el formulario que se reemplaza lo pide como observaciones y no lo
exige, y al adoptar ese formulario se adoptó también su regla. Lo que sigue en
pie es quién responde: eso lo guarda `authorized_by`.

### Las cuotas son el plan, no otra promesa

Quince filas de cuota —monto y fecha— como el formulario que el operador usa a
diario. Lo normal es llenar dos o tres; las que quedan en blanco no se guardan.

**La fecha que aplaza el corte sigue siendo una sola**, la de arriba. Si cada
cuota protegiera hasta la siguiente, la protección se renovaría sola y un plan
de quince cuotas dejaría al abonado fuera del corte durante meses sin que nadie
lo volviera a decidir. Las cuotas dicen cómo piensa pagarlo, no hasta cuándo
está a salvo.

Dos reglas, las dos por el mismo motivo —el plan describe cómo se paga lo
comprometido, no puede prometer otra cosa—:

- Una cuota necesita **monto y fecha**. Media cuota no dice ni cuánto ni
  cuándo, y guardarla dejaría un plan que no se puede seguir; callarla dejaría
  al operador creyendo que apuntó algo que no quedó. El error nombra la fila.
- La suma de las cuotas **no puede pasar** del monto comprometido. Que sume
  menos sí se acepta: el operador puede dejar apuntadas las dos primeras y el
  resto para cuando se sepa.

Viven en `PaymentCommitmentInstallment` y no en treinta columnas del
compromiso: son quince filas en el formulario pero dos o tres en el acuerdo, y
treinta columnas vacías por compromiso describirían el formulario en vez de lo
pactado. `number` se guarda en vez de deducirse del orden porque el operador
puede llenar la 1 y la 3 y dejar la 2 en blanco.

### El compromiso concedido es la misma ficha, bloqueada

Mismas etiquetas y mismo orden, con todo en `disabled`. El operador que abre un
compromiso está comprobando lo que se acordó, y compararlo contra una ficha
distinta le obliga a traducir entre las dos. Es el mismo criterio del
comprobante emitido frente a la pantalla de cobro, y por eso `disabled` y no
`readonly`: un compromiso concedido no se corrige, se anula y se concede otro.

Ahí solo se pintan **las cuotas que se llenaron**. Las quince filas en blanco
tienen sentido en el alta —son los huecos que el operador puede usar—, pero en
el concedido dirían que se pactaron quince cuotas y trece quedaron sin fecha.

La tabla de **compromisos registrados** salió del alta: lo que se está haciendo
ahí es conceder uno nuevo, y el historial del abonado se consulta desde su
cuenta.

### El papel que el abonado firma

«Imprimir» saca el compromiso en el formato del sistema anterior: logotipo y
teléfono arriba a la izquierda, el título en medio, `Nº 002671` a la derecha, y
el texto de la solicitud de prórroga con las deudas que cubre. Debajo, **tres
recuadros de cinco filas** —`Importe · Vencimiento · Corte`—, el importe total,
quién es el abonado y quién lo representa, y las dos firmas: la del abonado y
la de quien autoriza.

No es un comprobante: no numera caja ni declara impuestos, y por eso acaba en
firmas y no en un recuadro de importes. Vive en `commitment_pdf.py` y no junto
al comprobante: no comparten nada salvo la biblioteca y de dónde sale el
logotipo.

Los tres recuadros son las quince cuotas repartidas en columnas, que es como
caben en media hoja dejando sitio para las firmas. **Sin plan de cuotas se
imprime una sola fila** con el total y la fecha del compromiso: dejar los
recuadros vacíos daría un papel que el abonado firma sin que diga cuánto ni
cuándo.

La columna **Corte** es el día siguiente al vencimiento, como en el papel de
referencia —vence el 23 y corta el 24—. Es del papel y no de la política de
cobro: la `cut_date` del cargo la calcula la política sobre su propio
vencimiento, y aquí lo que se promete es otra fecha.

La razón social que sale impresa es **la primera empresa activa**. Nada ata
todavía un compromiso a una del grupo —no lo emite un talonario, como sí hace
el comprobante— y el papel del sistema anterior siempre dice CABLE LOS ANDES.

El estado se reevalúa al leerlo, porque un compromiso se rompe por el paso del
tiempo y no por una acción de nadie:

    ACTIVE      la fecha no llegó y queda saldo
    FULFILLED   los cargos incluidos quedaron cancelados
    BROKEN      pasó la fecha prometida con saldo pendiente
    CANCELLED   se dejó sin efecto a mano

Conceder exige motivo: aplazar el corte de alguien que ya debe es una decisión
que hay que poder explicar después.

### Se anuncia arriba, en una tarjeta

Mientras el compromiso siga en pie cambia lo que el operador puede decirle al
abonado —esa deuda no empuja al corte hasta la fecha acordada—, así que se lee
**antes** de decidir qué cobrar y no al pie de la pantalla.

Va en una tarjeta encima de la tabla, con el trazo de una tarjeta de cifra:
rótulo pequeño arriba, el dato que importa en grande debajo, el icono en su
cuadro de color y una línea de contexto al pie.

    ┌──────────────────────────────────┐
    │ Compromiso de pago pendiente  👍 │
    │ Paga el 27/09/2026               │
    │ #2 · S/ 70.00                    │
    └──────────────────────────────────┘

La fecha va en grande porque es lo que se responde en ventanilla —«¿hasta
cuándo tengo?»—; el número y el monto quedan al pie, que es lo que se mira
después.

Se pintan en rejilla (`auto-fill`) y no apiladas: ahí se van acumulando cosas
—hoy los compromisos, mañana lo que venga— y puestas en fila caben varias sin
empujar la primera deuda por debajo del pliegue. Una ocupa lo suyo y cuatro se
reparten el ancho.

Toda la tarjeta es el enlace, no un «ver» dentro de ella: el destino es uno
solo y un área grande se acierta sin apuntar. Lleva a la pantalla del
compromiso —su ficha bloqueada, las deudas que cubre y el botón de anular—.

Se probó a abrirla en una ventana emergente y se retiró: de un enlace se
espera que lleve a donde dice, y la pantalla completa se recorre mejor cuando
el abonado tiene muchas deudas.

### La tabla ya no repite el compromiso

La columna **Vencimiento** salió del tablero. Llevaba debajo de la fecha una
etiqueta «Compromiso dd/mm/aaaa» que repite lo que la tarjeta de arriba ya
dice, y al ocupar un segundo renglón hacía esa fila más alta que las demás: en
una lista larga esa diferencia de altura se lee como si fueran bloques
distintos y no filas iguales. Es el mismo motivo por el que antes se había
retirado de ahí la etiqueta «Vencido`.

La fecha de vencimiento sigue viva en el modelo y en todo lo que decide —el
pronto pago, el corte, qué es deuda vencida—; lo que deja de hacer es ocupar
una columna del tablero.

## Cómo se aplica el dinero

Sin reparto explícito se cobra lo marcado en el tablero, cada cargo por su
saldo: es lo que el operador acaba de elegir. Sin nada marcado se aplica **del
cargo más antiguo al más reciente**, que es lo que hace un cajero cuando el
abonado paga «a cuenta», porque lo más viejo es lo que puede llevarlo al corte.

Lo que no se aplique queda como saldo a favor en el pago. No se crea un cargo
para absorberlo: sería deuda que el abonado nunca contrajo y aparecería como
tal en su estado de cuenta.

Todo método distinto de efectivo —depósito, transferencia, tarjeta, cheque,
Yape, Plin— exige número de operación. Sin él no hay forma de cruzar el cobro
con el estado de cuenta del banco y el pago queda sin respaldo.

## Data de prueba

    python manage.py generar_datos_cobranza_prueba
    python manage.py generar_datos_cobranza_prueba --abonado JA01-A0000001 --meses 6
    python manage.py generar_datos_cobranza_prueba --serie B001 B002
    python manage.py generar_datos_cobranza_prueba --dry-run

Siembra deudas, cobros con comprobante y un compromiso sobre un abonado real,
para ver las cuatro pantallas con contenido creíble.

Deja la suscripción facturable antes de emitir —`ACTIVE`, con fecha de
instalación y con mensualidad del plan—: una recién registrada está en
instalación y con tarifa en cero, no genera nada, y la pantalla se vería vacía
sin explicar por qué.

`--serie` emite además un cobro desde cada talonario que se le nombre. Existe
porque los dos formatos de papel no se pueden mirar sin un comprobante emitido
de cada uno: los cobros normales del comando salen del talonario por defecto,
que no es ninguno de los B00x, así que sin esto no había forma de ver el tique.

Ese cobro de muestra cubre **hasta tres deudas** en un solo comprobante. Con
una sola línea no se ve lo que hay que mirar del papel —la tabla del detalle,
el precio unitario a seis decimales y cómo cuadran las tres columnas—, que es
justo lo que se quiere comprobar. Y sale desde una ventanilla que de verdad
ofrezca ese block, según el padrón: sembrado desde otra sería un ejemplo que
la pantalla no dejaría repetir.

Es idempotente **por talonario** y no por abonado: los cobros normales se
saltan si el abonado ya tiene alguno, pero aquí se ha nombrado un block a
propósito. Lo que no hace es emitir dos veces del mismo.

Las mensualidades las emite `generate_monthly_charges`, el mismo ciclo que
producción, y no cargos escritos a mano: así la data sale con los
vencimientos, el pronto pago y las fechas de corte que la política realmente
calcula. Es idempotente —no duplica mensualidades ni inventa caja si el
abonado ya tiene cobros—, porque la reacción natural cuando la pantalla no
muestra lo esperado es volver a correrlo.

## Anulación

Un pago no se borra: se anula con un motivo obligatorio. El registro
permanece, las aplicaciones dejan de contar y la deuda vuelve sola a su sitio.
El historial muestra el pago anulado en lugar de esconderlo, porque un cobro
que desaparece deja un hueco sin explicación justo donde el abonado va a
preguntar qué pasó con su dinero.

## Talonarios y correlativo

Una fila de `ReceiptSequence` es un **talonario**, no una serie. La serie es
solo lo que se imprime, y se repite: en el sistema que se reemplaza «S010»
nombra tres blocks distintos —VELOCIDAD, RED OPTICA y SPEEDY— que van cada uno
por su cuenta (3031, 267 y 569). Por eso manda `code`, que es único, y `series`
puede coincidir entre filas.

De ahí que la restricción de base de datos sea `(sequence, number)` y no
`(series, number)`: exigir que la serie impresa no repita número haría fallar
el segundo block de S010 en cuanto alcanzara al primero, por un choque que en
el papel no existe. La contrapartida está aceptada: dos recibos de blocks
distintos pueden acabar imprimiendo `S010-000300`.

La fila se bloquea con `select_for_update()` antes de incrementarla —mismo
criterio que el correlativo de órdenes—, de modo que dos cajas que cobran a la
vez no emiten el mismo número. Nunca se deduce leyendo el último recibo
emitido: ese cálculo da el mismo resultado a dos transacciones simultáneas.

### El número se propone, no se impone

Elegir la serie completa el número, y el campo queda editable. No es una
comodidad: los blocks de un cobrador (`JU1`, `MR3`, `ST1`…) son papel que él ya
trae numerado, así que el sistema no tiene de dónde sacar el que toca. Esos
talonarios llevan `autonumber=False` y proponen vacío; proponerles uno sería
inventarlo.

Cuando el operador escribe un número por delante en un talonario que sí numera
solo, el correlativo se adelanta hasta ahí. Si se quedara donde estaba, el
siguiente cobro volvería a recorrer números que ya se entregaron.

Los números sembrados son el **próximo a imprimir**, no el último entregado.
`last_number` se guarda uno por debajo: el primer recibo de `B001` sale
`0041314`, que es el que el talonario de papel tiene arriba.

### Cada ventanilla ofrece los suyos

Un talonario es papel, y el papel está en un cajón concreto. La lista de
series que ofrece la pantalla de cobro **depende de la oficina elegida en la
barra superior**: ofrecer en Apata un block que vive en Oroya invita a numerar
algo que nadie tiene delante, y el número que salga no va a coincidir con
ningún talonario real.

De ahí tres hechos que el modelo tuvo que aprender del padrón:

1. **Un block se comparte entre oficinas.** «F001 - CABLE LOS ANDES» va por el
   8323 en el Local Principal de Jauja, en la Oficina 2 y en Apata: un solo
   talonario con un solo correlativo, ofrecido en tres sitios. Por eso la
   relación es muchos a muchos y no una fila por oficina, que daría tres
   correlativos para un block que es uno —y tres cajas emitiendo el mismo
   número sobre el mismo papel—.

2. **La misma serie impresa puede ser dos talonarios distintos.** «B001» es
   CABLE LOS ANDES por el 41316 en Jauja e INVERSIONES por el 49217 en Oroya.
   Ni es el mismo block ni lleva la misma cuenta. Es la misma razón por la que
   «S010» ya nombraba tres blocks, y por la que manda `code` y no `series`.

3. **Cada oficina los apila a su manera.** Los tres «S003» salen en Jauja
   Cajas como SPEEDY, VELOCIDAD, RED ÓPTICA y en Huancayo El Tambo como
   VELOCIDAD, RED ÓPTICA, SPEEDY. Son los mismos tres talonarios, así que el
   orden no cabe en el talonario —ahí solo hay sitio para una respuesta y
   hacen falta dos—: vive en la relación, en `OfficeSequence.position`.

`ReceiptSequence.position` sigue existiendo y ordena la lista completa, que es
la que se ve cuando no hay oficina resuelta.

**El guardia es el servidor, no el desplegable.** La lista pintada se puede
saltar armando el POST a mano, así que el formulario se construye con la misma
oficina al pintar y al validar: `ChoiceField` valida contra esas mismas
opciones y una serie de otra ventanilla no entra. Por eso la vista resuelve la
oficina **antes** de armar el formulario y no después de validarlo.

### Los blocks de un cobrador van a todas partes

`JU*`, `MR*` y `ST*` no son de una ventanilla: son papel que el cobrador lleva
encima. Se ofrecen en todas las oficinas y encabezan cada lista, igual que
encabezaban la global. Como no numeran solos, proponen el número en blanco, y
por eso la pantalla sigue abriendo en el primer block que sí sabe numerar —que
ahora es el primero **de esa oficina**: en Jauja Cajas abre en B003 y no en
B001—.

### El depósito ofrece lo del local principal de su sede

No tiene blocks propios —nadie está parado ahí—, pero es donde cae lo que
llega por banco. Dejarlo sin talonario habría impedido registrar una
transferencia, así que ofrece la lista del local principal de su sede.

### Una oficina que el padrón no nombra cae a la lista completa

Mismo criterio que hace opcional la oficina en el cobro: un despliegue sin
padrón cargado sigue cobrando, porque la sede basta para saber qué caja
recibió el dinero. Quedarse sin series dejaría la ventanilla parada por una
tabla que nadie llenó.

### Los correlativos solo se adelantan

El padrón trae los números al día, y tres de los que ya estaban sembrados
habían seguido emitiendo (B001, B002 y F002). La migración los adelanta pero
**nunca los retrocede**: si esta base ya pasó del número del padrón, volver
atrás repetiría comprobantes ya entregados.

### Dos papeles: la media hoja y el tique

Los blocks de **boleta numerados** (B001 a B007) se entregan en un tique de
rollo de 80 mm en vertical: cabecera centrada con el logotipo, la razón social
y el RUC; los datos del abonado en filas etiqueta/valor; el detalle entre
líneas de guiones; y abajo el recuadro de importes, el importe en letras, el
QR y la leyenda de representación impresa. Las **facturas** F* y los **recibos
de servicio público** S* y V.COND siguen en la media hoja apaisada.

El tique **no lleva alto fijo**: se mide el contenido y la página se corta ahí.
Un rollo no tiene hoja, y darle una dejaría media cuarta en blanco en un cobro
de una línea y cortaría uno de diez.

**Cuál toca lo dice el talonario**, en `print_format`, no la letra de la serie.
Deducirlo de «empieza por B» parece bastar y no basta: los blocks de un
cobrador (`JU*`, `MR*`, `ST*`) también son boletas —lo dice su serie y lo dice
su `document_title`— y se entregan en media hoja. Es el mismo argumento por el
que `document_title` se guarda en vez de deducirse del prefijo: un block puede
cambiar de papel sin cambiar de nombre, y con la regla deducida habría que
renombrarlo para arreglar la impresión.

La aritmética no se duplica. `invoicing` ya calculaba el precio unitario con
seis decimales, el descuento sin impuesto, la operación gravada, el IGV y el
importe en letras, y los dos formatos leen de ahí: lo que cambia entre uno y
otro es dónde se dibuja cada cifra, no cuánto vale.

Los estilos sí son propios de cada uno. Los de la media hoja están pensados
para un papel que se lee a un brazo de distancia sobre el mostrador; el tique
se lee en la mano. Compartirlos habría atado dos formatos que no tienen por
qué moverse juntos.

Los cuerpos del tique salen **medidos del papel de referencia**, no elegidos.
El tique se compara con el del sistema que se reemplaza puesto al lado, y una
escala propia —aunque fuera legible— se nota en cuanto los dos están sobre el
mostrador. Son tres escalones: la identidad del emisor (razón social, RUC,
título y número), el cuerpo del documento (etiquetas, datos, detalle e
importes) y la letra pequeña legal.

El logotipo ocupa **un tercio del ancho del rollo**. Empezó en 11 mm, que en
80 mm de papel lo dejaba en una marca de agua arriba del todo: es lo primero
que dice de quién es el papel, y a esa escala había que acercárselo a los ojos.

En la media hoja el logotipo se mide contra **el recuadro del RUC que tiene
enfrente**, que es la otra pieza de la cabecera: los dos rondan los 24 mm de
alto y la franja queda equilibrada. Estaba en 13 mm dentro de una fila que ya
medía 25 —la marca el recuadro—, así que flotaba en su columna sin llenarla y
se leía como un icono perdido en la esquina, con la razón social a 15 pt al
lado. Subirlo no alarga el papel: ocupa un alto que la cabecera ya tenía.

### El logotipo se recorta al dibujarlo

El archivo que se deja en `MEDIA_ROOT` trae aire dentro de la propia imagen —el
de hoy, un 13% de blanco arriba y un 19% abajo—, y ese aire es parte del
dibujo. Colocado alineado con la parte de arriba de su celda, lo que se ve
arrancaba tres milímetros por debajo de la razón social que tiene al lado y el
logotipo parecía caído.

Se recorta **al dibujar y no en el archivo**: el logotipo lo deja alguien en su
sitio, no viene con el código, así que no es nuestro para reescribirlo; y un
recorte al vuelo sigue valiendo cuando lo cambien por otro con distinto aire,
que es lo que va a pasar. El recorte usa un umbral y no el blanco exacto,
porque un JPEG no guarda el blanco exacto y comparar a pelo no recortaría nada.

Si no se puede recortar —sin Pillow, con el archivo roto, o con un dibujo que
es todo blanco— se dibuja el archivo sin tocar: un logotipo un poco caído es
mejor que una ventanilla que no puede entregar el papel. Por eso mismo `Pillow`
pasa a estar declarado en `requirements.txt`: venía de `reportlab`, y ahora
además se importa aquí.

Buscando esto apareció un fallo que no se había visto: el tique comprobaba el
logotipo con `is not None` y `_logo` devuelve **cadena vacía** cuando no hay
dibujo, así que la cadena pasaba el guardia y el papel reventaba al pedirle
alineación a un texto. Un despliegue al que no le hubieran dejado el archivo no
habría podido cobrar por ese formato.

### INVERSIONES imprime ya sus datos reales

`INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C.`, RUC `20603110456`, con
dos direcciones —Jauja y La Oroya—. Las dos van en el mismo campo separadas
por salto de línea: son dos renglones de la cabecera del papel, no dos
domicilios que el sistema tenga que distinguir.

CABLE LOS ANDES y SPEEDY QUANTICO siguen con RUC de relleno, marcado como tal,
hasta que lleguen los suyos.

### R001 quedó retirado

Era el talonario propio del sistema, el que se usó mientras no había padrón.
No se borra —tiene comprobantes entregados colgando, y un recibo sin el block
del que salió no puede explicarse—: lleva `is_active=False` y deja de
ofrecerse, nada más. Un talonario que el sistema crea al vuelo nace igual de
retirado, porque llegar a crearlo significa que nadie lo eligió y ofrecerlo
después pondría a elegir un block que no existe en papel.

La pantalla abre en el **primer talonario que numera solo** (`B001`), no en el
primero de la lista. Encabezan los blocks de un cobrador, que proponen vacío:
abrir ahí dejaría el número en blanco y un «Aceptar» sin tocar nada devolvería
un error por algo que el operador no eligió.

## Dónde entró el dinero

El pago guarda **sede y oficina**. La sede dice de qué ciudad es la caja; la
oficina dice cuál de sus ventanillas, que es lo que un arqueo de sede con cinco
ventanillas necesita para saber de cuál salió el dinero.

La oficina se elige **en la barra superior y solo ahí**. La pantalla de cobro
la muestra al lado de la serie, en un campo que no se puede escribir.
Preguntarla también ahí eran dos sitios para decidir lo mismo, y el que se
quedaba sin mirar —el de la barra— seguía gobernando el resto de la sesión.

Es opcional a propósito: un despliegue sin padrón de oficinas cargado seguiría
cobrando, porque la sede basta para saber qué caja lo recibió, y exigirla
dejaría la ventanilla parada por una tabla que nadie llenó.

### El depósito es una ubicación más

Lo que llega por transferencia, depósito o billetera no lo recibe nadie en
mostrador, pero sí cae en una sede concreta. Cada sede tiene por eso su
`Deposito`, y se elige en la barra como cualquier ventanilla: quien va a
registrar una transferencia lo elige arriba y después cobra.

Lleva su propia marca (`Office.is_deposit`) en vez de reconocerse por el
nombre, porque de ese hecho depende una regla: **no puede ser la ubicación que
el sistema elige solo** para un operador sin oficina asignada. Si lo fuera, sus
cobros dirían que el dinero entró por banco sin que nadie lo hubiera dicho.

Hoy cualquiera puede elegir el depósito de su sede. Quién debería poder
hacerlo es una decisión de rol que todavía no está tomada, y la marca ya deja
el sitio donde se aplicará cuando lo esté.

### Cambiar de sede u oficina devuelve al buscador

Los dos selectores de la barra superior llevan siempre a la búsqueda de
abonado, nunca de vuelta a la pantalla anterior. Cambiar el ámbito desde el
que se trabaja deja atrás lo que se estaba mirando, y seguir viéndolo es una
pantalla que miente entera: la ficha de un abonado de Jauja con la barra
diciendo Oroya, o un cobro armado con las series de una ventanilla después de
elegir otra —que desde el padrón por oficina ni siquiera son válidas—.

Antes se volvía al `next` que el formulario traía, así que el operador se
quedaba delante de un registro que ya no era del padrón que tenía elegido, sin
nada que lo delatara. Al quitar ese campo desaparece de paso la validación que
necesitaba: el destino ya no lo decide el POST, así que no hay adónde
redirigirlo.

**La sede suelta además el abonado seleccionado** (`selected_customer_id`), que
era del padrón anterior: dejarlo puesto haría que las entradas de cuenta del
menú siguieran abriendo a alguien de la otra sede. **La oficina no lo suelta**,
porque la sede no ha cambiado y el abonado sigue siendo de aquí; lo que deja
de valer es la pantalla, y de eso ya se encarga volver al buscador.

## Navegación

Las tres pantallas cuelgan de un abonado concreto, porque así se consultan en
ventanilla: primero se ubica al cliente y después se mira su cuenta.

    /payments/clientes/<pk>/deuda/
    /payments/clientes/<pk>/historial/
    /payments/clientes/<pk>/comprobantes/
    /payments/clientes/<pk>/cobrar/
    /payments/comprobantes/<pk>/          (con ?print=1 imprime)

En la sección **Clientes** del menú lateral las tres entradas usan rutas sin
`pk` que resuelven el abonado seleccionado en la sesión. **El abonado
seleccionado es el último cuya ficha se abrió**: la fija `CustomerDetailView`,
porque el buscador enlaza directamente a la ficha y no al antiguo botón «Usar
cliente», que la ficha rediseñada ya no muestra. Cuando la selección dependía
de ese botón, las tres pantallas respondían que no había ningún abonado
elegido aunque el operador estuviera viendo uno.

Sin ninguna ficha abierta llevan al padrón de la sede en vez
de abrir una cuenta vacía, que parecería afirmar que el abonado no debe nada.

## Diseño

Las pantallas usan el mismo sistema visual que la ficha del cliente: tarjetas
`tc-card`, tablas `tc-table`, botones `tc-btn` y pestañas `tc-tabs`.

Ese CSS vivía **dentro** de `customers/detail_dashboard.html`, que fue la
primera pantalla en usarlo, así que cobranza nació con una maqueta propia de
Bootstrap crudo y las dos se veían de aplicaciones distintas. Se extrajo a
`templates/_tc_design.html` y ambas lo incluyen desde su bloque `extra_css`:
copiarlo habría bastado para hoy, pero dos copias del mismo CSS se separan al
primer ajuste y una quedaría con el trazo viejo sin que nadie lo note.

La cabecera en franja azul (`tc-section-head banner`) siguió ese mismo
camino. Nació dentro de «Nueva deuda», con la nota de que se quedaba ahí
hasta decidir si todas las cabeceras irían así; la copió «Cobrar» y la pidió
después la tabla de deudas, y esa tercera pantalla resolvió la duda: vive en
el parcial compartido.

La pantalla de deuda quedó en una sola cosa: la tabla. Salieron el total al
pie, la píldora de pendientes de la cabecera y la tira de cifras que la
encabezaba —deuda, vencido, deudas abiertas y vencimiento más antiguo—, que
repetía lo que las filas de abajo dicen una por una y empujaba la primera
deuda por debajo del pliegue. Cuántas hay lo sigue diciendo el pie del
paginador, que las cuenta de todos modos.

El total al pie además decía otra cosa sin avisarlo: sumaba la deuda
**completa** mientras la tabla mostraba una página, así que con el selector de
filas en 15 y treinta cargos abiertos las dos cifras no coincidían.

Comprobantes siguió después el mismo camino. Era la única de las tres
pestañas que quedaba con la cabecera blanca —deuda e historial ya llevaban la
franja—, y puesta al lado de las otras parecía de otra pantalla en vez de otra
cara del mismo abonado. Con la franja se le fue también su píldora «N
emitidos», que repetía el conteo del pie del paginador dos líneas más abajo.

Que el conteo lo dé solo el pie no es manía de limpieza: el pie cuenta el
total aunque la tabla muestre una página, así que las dos cifras estaban
condenadas a separarse en cuanto el abonado pasara de quince comprobantes —el
mismo desajuste que ya había tenido el total al pie de la deuda—.

Con eso se retiraron el parcial `_debt_summary.html` y el tag
`account_debt_summary` que lo pintaba: la pantalla de deuda era su único
consumidor. La vista **sigue** calculando la deuda —la tabla y los botones de
cobro viven de ella—, solo que ya no se pinta como resumen.

La identidad del abonado la pinta `customer_hero`, el mismo bloque de la
ficha. Si cada pantalla lo describiera por su cuenta, podrían acabar diciendo
cosas distintas sobre quién es y qué tiene activo.

«Cobrar» y «Compromiso» actúan sobre lo marcado, y sin marcas lo avisan con
un aviso flotante arriba a la derecha que se va solo a los tres segundos.
Antes era una franja bajo la tabla: con la tabla larga quedaba fuera de la
pantalla, así que el clic parecía no haber hecho nada. No es un modal porque
el operador no tiene nada que decidir, solo que enterarse, y un modal le
cobraría un clic de más por un descuido.

Lo pinta `tcAviso`, del sistema visual compartido (`.tc-toast`), no una
librería de terceros: se probó con SweetAlert2 y su caja venía a la escala
de un diálogo, no a la de esta interfaz, y achicarla por CSS habría dejado
60 KB de CDN para pintar una fila de texto.

Si por lo que sea el aviso no está disponible, el clic **no** se bloquea y
sigue al servidor, que devuelve al tablero con el mismo mensaje —el guardia
de verdad está ahí (`BoardSelectionRequiredMixin`), y el aviso del navegador
solo ahorra el viaje.

Los formularios usan el layout etiqueta/campo del sistema anterior
(`tc-form`), para que el operador reconozca la pantalla, con el trazo de la
ficha en vez del aspecto por defecto de Bootstrap.

### Una tarjeta, un margen lateral

`--tc-pad-x` es el margen lateral de las tarjetas, y lo leen las cuatro cosas
que tienen que arrancar en la misma línea: la cabecera, el cuerpo, las celdas
de los bordes de la tabla y el pie.

Las fichas de formulario —cobrar, comprobante, nueva deuda— piden más aire que
una tarjeta de consulta: los 18px compartidos están pensados para tablas de
filas cortas, y en un formulario dejan las etiquetas contra el borde. Ese aire
se gana **redefiniendo la variable sobre la tarjeta entera**, que es lo que
hace `.tc-sheet { --tc-pad-x: 26px; }` en el parcial compartido.

Antes lo ganaba cada ficha subiendo el padding de su cuerpo, y solo el del
cuerpo. La misma tarjeta acababa entonces con tres márgenes laterales
distintos —título a 18, campos a 26, botones a 18— y las tres zonas arrancaban
en líneas diferentes, que es exactamente lo que la variable existe para
evitar. `charge_create` lo había visto a medias y corregido el pie; la
cabecera se quedó descolgada en las tres.

`test_diseno.MargenLateralDeLaFichaTests` lee el CSS de las plantillas —es una
regla de hoja de estilos, el cliente de pruebas no la resuelve— y falla si
alguna vuelve a fijar en píxeles el lateral de una de las tres zonas.
## Permisos

| Permiso                  | Habilita                        |
|--------------------------|---------------------------------|
| `payments.view_charge`   | consultar la deuda              |
| `payments.view_payment`  | consultar el historial          |
| `payments.view_receipt`  | consultar y abrir comprobantes  |
| `payments.add_payment`   | registrar un cobro              |
| `payments.void_payment`  | anular un cobro registrado      |

Cobrar y anular están separados a propósito: quien atiende la ventanilla no
debería poder deshacer por su cuenta lo que ya entró en caja.

Los permisos son los estándar de Django y se conceden de forma explícita. Este
módulo **no** se apoya en la matriz de capacidades por rol de
`accounts.User`: esa matriz tiene una contradicción pendiente de decidir con
negocio, y amarrarle la cobranza extendería el problema al dinero.

## Pendiente

- Comprobante electrónico SUNAT sobre el pago ya registrado.
- Corte automático al llegar la `cut_date`, respetando los compromisos
  vigentes (`Charge.is_protected_from_cut()` ya responde esa pregunta).
- Cierre de caja y arqueo por sede, en la sección Caja.
