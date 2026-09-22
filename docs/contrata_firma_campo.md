# La contrata firmada en campo

El abonado firma su contrato en el móvil del técnico, en su domicilio, el día
de la instalación. Es el mismo contrato que ATC registró en oficina: no hay
un documento del portal y otro de SICV.

Pantalla: apartado **Contrata** de la Orden Técnica, en el portal del técnico
(`/technician/`).

## Por qué en la orden de instalación

Porque es el único momento en que el abonado y el sistema están en el mismo
sitio. Antes, el contrato se imprimía, viajaba en la mochila del técnico,
volvía firmado y alguien lo archivaba; el SICV nunca se enteraba de si estaba
firmado.

El apartado aparece **solo en las instalaciones**, que es donde hay un alta
que firmar: una avería o un corte no firman nada. Y quién lo decide es el
servidor —el catálogo de tipos de orden—, no una lista de códigos en el
navegador que pueda decir otra cosa.

## Lo que se guarda es el trazo, no el PDF

`ContractSignature` guarda el dibujo que hizo el abonado, con quién lo recogió,
en qué orden y cuándo. No guarda un PDF firmado.

El contrato se dibuja siempre desde sus datos —`document.py` decide qué dice,
`pdf.py` cómo se ve—, así que archivar además el PDF dejaría dos versiones del
mismo documento que pueden separarse: corregido mañana un dato del abonado, el
archivo guardado seguiría contando lo de ayer. Con el trazo guardado, el
contrato firmado es el de siempre con un dato más, y sale igual por el portal
del técnico que por SICV.

El nombre del firmante sí se copia al firmar y no se vuelve a leer del
cliente: el papel dice quién firmó ese día.

## Firmar son tres pasos

```
dibujar  →  colocar  →  aceptar
```

**Dibujar** ocurre en un recuadro aparte, no sobre el contrato: firmar con el
dedo encima de un documento reducido a pantalla de móvil no sale legible. El
lienzo deja elegir tinta —negra o azul— y grosor, porque una firma fina en una
pantalla pequeña se pierde y una gruesa emborrona a quien firma con trazo
apretado. El grosor va en proporción al lienzo, así que pesa igual en un móvil
de cinco pulgadas que en una tablet.

**Colocar** pone el trazo sobre la hoja, ya a su tamaño de papel. Nace centrado
sobre la línea de EL ABONADO, así que aceptar sin tocar nada lo deja donde el
contrato lo espera; moverlo y estirarlo desde la esquina es para ajustar, no
para buscar sitio. Puede salirse del hueco —hay quien firma largo— pero no de
la hoja: una firma fuera del papel no se imprime.

**Aceptar** guarda el trazo y dónde quedó. Lo que se guarda es eso, no un PDF:
el contrato se vuelve a dibujar en el servidor con esos datos, y el navegador
nunca fabrica un documento firmado.

### El hueco lo declara el papel

El bloque de firmas reserva una fila encima de cada línea, haya firma o no: en
un contrato sin firmar es el espacio para el bolígrafo, y en uno firmado en
campo es donde se apoya el trazo. Así el documento ocupa lo mismo en los dos
casos.

Ese hueco —página, posición y medidas— lo anota el propio PDF **al dibujarse**
(`_HuecoDeLaFirma`) y viaja con el archivo en la cabecera `X-Contrata-Ancla`.
El visor lo lee de ahí y no lo calcula por su cuenta: dos fórmulas distintas de
«dónde se firma» acabarían discrepando, y la que manda es la del papel.

La colocación se guarda **relativa a ese hueco**, nunca a la página. Si mañana
el contrato gana un párrafo y el bloque de firmas baja media hoja, la firma baja
con él en lugar de quedarse flotando donde estaba.

### La empresa firma impresa

El lado de **LA EMPRESA** ya no va en blanco: lleva el sello de la razón
social que contrata, apoyado en su línea igual que el trazo del abonado en la
suya. La empresa no firma en el móvil porque su firma es siempre la misma,
como en los contratos que se entregaban en papel con el sello puesto.

Las firmas viven en `MEDIA_ROOT`, una por código de empresa emisora
—`firma_INV.png`—, y las resuelve `apps/organization/branding.py`, el mismo
módulo que encuentra el logotipo. Van ahí y no con el código porque las deja
administración y las cambia sin pasar por un despliegue.

El archivo tiene que ser un **PNG recortado y con fondo transparente**: el
sello se apoya sobre la línea de firma, y un JPEG con su fondo blanco la
taparía dejando el recuadro del recorte a la vista. El de INVERSIONES se
preparó a partir del escaneo que entregó administración, pasando a
transparencia todo lo que estaba por encima del umbral de papel y recortando
después a la caja del dibujo.

El sello queda justo encima de su línea, rozándola —ese milímetro decide
además su tamaño, porque el alto es el del hueco menos ese aire—, y debajo se
siguen escribiendo «LA EMPRESA» y la razón social: el sello es un escaneo y el
pie de firma es el dato, que tiene que leerse igual de bien en una fotocopia.

Una razón social sin sello cargado imprime su espacio en blanco, para firmarlo
a mano.

El trazo se recorta a lo que realmente se dibujó y se escala por proporción.
Sin recortar, una firma pequeña hecha en una esquina del lienzo llegaría al
papel como un sello diminuto perdido en el aire; sin proporción, una firma
ancha y otra apretada saldrían deformadas al mismo rectángulo.

## Volver a coger la firma

Una firma ya registrada no queda congelada en la hoja: **se toca y se despega**.
Al tocarla aparece con su recuadro y su asa, y desde ahí se puede mover, cambiar
de tamaño, sustituir por otro trazo o **eliminar**.

Tocar no es arrastrar. El primer toque solo la despega, para que nadie mueva por
accidente una firma dada por buena mientras lee el contrato en el móvil.

Mientras se recoloca, el contrato se pide **sin la firma** (`?sin_firma=1`): con
el trazo dibujado debajo se verían dos firmas y solo una sería la que se va a
guardar.

Mover una firma **no es volver a firmarla**. El trazo que se arrastra es el que
hizo el abonado —se pide al servidor, no se repinta—, y al guardar solo cambian
las medidas: ni la fecha de firma ni el nombre del firmante se tocan. El abonado
no tiene que estar delante otra vez porque su firma quedara torcida en la hoja.

## Cuándo se puede firmar

Con la orden **En atención**, el mismo límite que ya gobierna la ficha técnica,
los materiales y las evidencias: el técnico no tiene que aprender una regla
nueva por pantalla.

Mientras la orden siga abierta, la firma se puede rehacer —reemplaza a la
anterior, y el trazo descartado se borra— o rechazar, que devuelve el contrato
a sin firmar. Al cerrar la orden queda la que el abonado aceptó.

El documento, en cambio, se puede consultar siempre, también con la orden ya
cerrada: a ese domicilio no se vuelve, y lo que se firmó tiene que poder
mirarse.

## El canal

El técnico no tiene sesión web, así que la pantalla de contratos de SICV —que
sí la exige— no le sirve. El canal del técnico publica lo suyo por token, como
el resto de sus endpoints:

| Endpoint | Qué hace |
|---|---|
| `GET /api/technicians/work-orders/<id>/contract/` | Estado de la contrata: contrato, si está firmada y si se puede firmar ahora. Responde 200 aunque la orden no tenga contrata: que una avería no traiga contrato no es un error. |
| `GET …/contract/document/` | El contrato en PDF, el mismo que imprime SICV, con la firma dentro si ya se firmó. Lleva su hueco de firma —y dónde quedó el trazo— en la cabecera `X-Contrata-Ancla`. Con `?sin_firma=1`, la hoja como estaba antes de firmarla. |
| `GET …/contract/signature/` | El trazo guardado, en PNG. Lo pide el visor para volver a ponerlo en pantalla cuando el técnico lo coge. |
| `POST …/contract/signature/` | El abonado acepta: llega el PNG del trazo y, si se movió, dónde quedó dentro del hueco. |
| `PATCH …/contract/signature/` | Solo las medidas: mueve o redimensiona la firma registrada, sin imagen y sin tocar la fecha de firma. |
| `DELETE …/contract/signature/` | El abonado rechaza: el contrato vuelve a sin firmar. |

Las vistas son **canal, no dominio**: resuelven de qué contrato habla la orden
y quién puede tocarlo ahora. Qué es una firma y cómo se guarda lo decide
`apps/contracts/signatures.py`.

El contrato se llega por la **suscripción**, que es lo que la orden y el
contrato comparten. No hay una clave nueva entre los dos módulos.

## El visor

`contract_signer.js` abre el PDF a pantalla completa con
[pdf.js](../apps/work_orders/static/work_orders/technician/vendor/README.md):
zoom con botones y con dos dedos, desplazamiento con uno, el lienzo de firma
en una hoja inferior con **Borrar**, **Rechazar** y **Colocar firma**, y la
firma sobre la hoja con **Volver a dibujar**, **Cancelar**, **Eliminar firma**
y **Aceptar y guardar** —los dos últimos solo cuando ya estaba registrada—.

El trazo se dibuja encadenando los puntos medios de cada tramo y curvándolo
sobre el punto real que los separa. Dibujar de punto a punto medio y arrancar
el tramo siguiente en el punto entero deja media curva sin pintar, y la firma
sale a rayas.

Aceptada la firma, el visor vuelve a pedir el documento: lo que el abonado
tiene que ver entonces es su contrato con la firma dentro, no el que el técnico
trajo en blanco.

Rehacer una firma olvida la colocación anterior: el trazo nuevo vuelve a nacer
centrado sobre la línea, como el primero.

Es la única librería de terceros del portal, y está copiada en el repositorio
en vez de pedirse a un CDN: el portal se usa en el domicilio del abonado, con
la conexión que haya, y un contrato que no abre porque un CDN tarda es un
contrato que no se firma.

El PNG llega con **fondo transparente**, y por eso el canal rechaza cualquier
otro formato: un JPG traería un recuadro blanco que taparía la línea del
contrato sobre la que se apoya.

## Lo que ve SICV

- La **vista del contrato** dice «Firmada el … en OT-…» o «Pendiente de
  firma». ATC no tiene que abrir el PDF para comprobarlo.
- La **ficha del abonado** marca los contratos firmados en su tabla.
- El **contrato impreso** sale firmado desde el mismo botón de siempre. No hay
  un «imprimir contrato firmado» aparte, porque no hay dos documentos.

## Lo que queda abierto

- **Solo INVERSIONES tiene firma cargada.** Si otra razón social del grupo
  empieza a firmar contratos, hay que dejar su `firma_<CÓDIGO>.png` en
  `MEDIA_ROOT`; hasta entonces su lado del bloque sale en blanco.
- **Nadie avisa al técnico de que falta firmar.** El cierre de la orden no
  exige la firma ni la cuenta entre sus requisitos. Se dejó fuera a propósito:
  convertirla en obligatoria bloquearía instalaciones donde el abonado no está
  presente, que hoy existen. Si negocio decide que no debe haberlas, el sitio
  donde exigirlo es el resumen de cierre.
- **La firma no se puede corregir desde oficina.** Cerrada la orden, rehacerla
  exige volver al domicilio. No hay pantalla en SICV para reemplazarla, por la
  misma razón por la que no hay edición de contrato.
