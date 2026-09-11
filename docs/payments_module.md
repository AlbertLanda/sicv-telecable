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

La pantalla sigue el formato del sistema anterior: Código, Fecha y Hora del
sistema, Fecha de pago, **Autoriza** y la tabla de deudas a elegir.
`granted_by` es quien lo teclea y `authorized_by` quien lo autoriza —se
ofrecen supervisión, retenciones y administración—: guardar solo al usuario
dejaría sin responsable una decisión comercial.

El estado se reevalúa al leerlo, porque un compromiso se rompe por el paso del
tiempo y no por una acción de nadie:

    ACTIVE      la fecha no llegó y queda saldo
    FULFILLED   los cargos incluidos quedaron cancelados
    BROKEN      pasó la fecha prometida con saldo pendiente
    CANCELLED   se dejó sin efecto a mano

Conceder exige motivo: aplazar el corte de alguien que ya debe es una decisión
que hay que poder explicar después.

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
    python manage.py generar_datos_cobranza_prueba --dry-run

Siembra deudas, cobros con comprobante y un compromiso sobre un abonado real,
para ver las cuatro pantallas con contenido creíble.

Deja la suscripción facturable antes de emitir —`ACTIVE`, con fecha de
instalación y con mensualidad del plan—: una recién registrada está en
instalación y con tarifa en cero, no genera nada, y la pantalla se vería vacía
sin explicar por qué.

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

`apps/payments/tests/test_diseno.py` fija que ninguna pantalla traiga su
propio CSS ni su propia versión del abonado, y que ninguna vuelva a encabezar
la cuenta con la tira de cifras.

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
