# Catálogo de servicios y motivos de orden

Documentación del encadenado que el ATC usa al emitir una OT
(SICV — Telecable / Fiber The Andes).

Cubre el catálogo (`OrderType` / `OrderReason`), su ámbito por tipo de
servicio y el comportamiento del formulario. La creación en sí está en
[`work_orders_web_creation.md`](work_orders_web_creation.md); el servicio de
dominio, en [`work_orders_creation.md`](work_orders_creation.md).

---

## 1. Los tres selectores encadenados

El SICV operativo pide al ATC tres decisiones en orden, cada una acotada
por la anterior:

```
Suscripción   →  qué contrató el abonado        (INTERNET / CABLE / DUO)
      ↓
Servicio      →  qué se va a emitir              (OrderType)
      ↓
Motivo        →  por qué se emite                (OrderReason)
      ↓
Detalle       →  la situación en una línea       (texto libre)
```

**El alta no pide sede, zona ni subtipo.** Sede y zona las deriva el
dominio —`_resolve_branch()` toma la del cliente y rechaza cualquier
otra; `_resolve_zone()` cae en la de la dirección de la suscripción— y se
guardan igual en la orden. Ofrecerlas solo daba al operador una elección
que no existía. El subtipo tampoco: los únicos que hay en el catálogo son
`ADD`/`REMOVE` de anexos de TV, que fija `services/annexes.py`, nunca el
ATC. Un valor enviado a mano para cualquiera de los tres se descarta: no
están entre los campos del formulario.

«Servicio» es la etiqueta que el operador conoce; en el modelo es
`WorkOrder.order_type`. Se conserva el nombre del SICV que se está
reemplazando porque renombrarlo obligaría a reaprender un listado que ya
se usa a diario.

El **detalle** es texto libre y corto —"internet lento", "no sintoniza
canales"—. No es un catálogo: describe el caso concreto, no su
clasificación.

---

## 2. Ámbito por servicio

Un tipo de orden declara sobre qué servicios puede emitirse mediante
`OrderType.service_types`.

**Sin servicios declarados, el tipo es transversal**: se ofrece sobre
cualquier suscripción. Restringir exige declararlo de forma explícita, de
modo que un catálogo a medio configurar nunca esconde opciones que el
operador esperaba ver.

| Bloque | Servicios | Tipos de orden |
|---|---|---|
| Transversales | INTERNET, CABLE, DUO | INSTALACIÓN, CAMBIO DE PLAN, CORTE, RECONEXIÓN, REQUERIMIENTO, RETIRO, RETIRO LÓGICO |
| Señal de internet | INTERNET, DUO | AVERÍA INTERNET, INCIDENCIA NOC |
| Señal de cable | CABLE, DUO | AVERÍA CABLE, SERVICIOS, ANEXOS DE TV |

DUO lleva ambas señales, así que hereda los dos bloques: son 12 servicios
frente a los 9 de INTERNET y los 10 de CABLE.

La consulta vive en el catálogo, no en la vista:

```python
OrderType.objects.for_service_type(subscription.service_type)
order_type.applies_to_service_type(subscription.service_type_id)
```

---

## 3. Dónde se aplica la regla

**En el queryset del formulario.** `WorkOrderCreateForm` acota
`order_type` a lo emitible sobre los servicios que el cliente realmente
tiene. Ofrecer «AVERÍA CABLE» a un abonado solo-internet no es una
opción de más: es una orden imposible que alguien acabaría creando.

**En el navegador.** La página publica un mapa JSON (`#wo-cascade`) con
la relación suscripción → servicio → motivo, y un script repinta los
selectores al cambiar la suscripción o el servicio. El encadenado se
resuelve en el servidor y viaja como datos: pedir el catálogo por AJAX en
cada cambio añadiría latencia y un endpoint más que autorizar, para algo
que ya está cargado.

Al repintar, una selección que deja de ser válida se descarta en vez de
conservarse: mantenerla enviaría al servidor algo que el formulario va a
rechazar.

**En `clean()`.** El navegador no es la última palabra: un POST armado a
mano llegaría igual. `WorkOrderCreateForm.clean()` vuelve a comprobar que
el servicio elegido corresponde al de la suscripción, y ahí sí es
vinculante. La coherencia servicio ↔ motivo ↔ subtipo ya la validaban
`WorkOrder.clean()` y `services._validate_creation_catalogs()`.

---

## 4. Carga del catálogo

```bash
python manage.py cargar_catalogo_ordenes            # idempotente
python manage.py cargar_catalogo_ordenes --dry-run  # valida y revierte
```

El comando exige que INTERNET, CABLE y DUO existan y falla si no; no los
crea. Inventarlos aquí duplicaría la fuente de verdad del catálogo
comercial y dejaría dos definiciones que podrían divergir. El orden es
`cargar_catalogo_comercial` primero, `cargar_catalogo_ordenes` después.

Los nombres se guardan en mayúsculas para que el selector no mezcle
grafías. Por eso el comando también normaliza dos tipos que ya existían:
`INSTALLATION` («Instalacion» → «INSTALACIÓN», junto con su motivo
«Cliente nuevo» → «CLIENTE NUEVO») y `TV_ANNEX` («Anexos de TV» →
«ANEXOS DE TV», acotado a CABLE/DUO). Los códigos no cambian: son los que
consumen `contracts`, `services/annexes.py` y `work_orders/services.py`.

`INSTALACIÓN` conserva el motivo `NEW_CLIENT` además de `REQUERIDO`,
porque es el que emite el alta comercial automática.

`RETIRED_ORDER_TYPES` recoge lo que el comando llegó a sembrar y ya no es
operativo —hoy, `TAC_INCIDENT`—. Quitarlo de la tabla no basta: en un
entorno donde el comando ya se ejecutó el tipo seguiría ofreciéndose. Se
intenta borrar y, si alguna OT lo referencia, se desactiva en su lugar:
dejar de ofrecer un tipo no puede costar el historial de las órdenes que
se emitieron con él.

---

## 5. El corte lee su motivo, no un subtipo

Cerrar un CORTE con éxito exige saber si suspende o cancela la
suscripción. Esa decisión se lee del **motivo**, porque el catálogo ya la
modela ahí: CORTE VOLUNTARIO y CORTE MOROSIDAD suspenden; los
DEFINITIVO - … cancelan.

`TEMPORARY_CUT_REASONS` y `DEFINITIVE_CUT_REASONS` viven en `models.py`,
compartidos por `CutDetail.clean()` y `_apply_cut_result()`: dos copias
del mismo criterio acabarían contradiciéndose.

Un motivo de corte que no esté en ninguno de los dos conjuntos **no cierra
la orden**, y el error lo nombra. Decidir si una suscripción se suspende o
se cancela es una regla explícita, no un valor por defecto que herede un
motivo nuevo del catálogo.

Antes esto se leía de `WorkOrder.subtype` con códigos `TEMPORARY` /
`DEFINITIVE` que nunca llegaron a sembrarse, así que ningún corte podía
cerrarse.

---

## 6. Lo que este catálogo no cubre

`TRASLADO` figura como motivo de `REQUERIMIENTO`, siguiendo el listado
operativo. El tipo de orden `TRANSFER` que espera `TransferDetail` no
forma parte de este catálogo y queda sin sembrar: si el traslado necesita
su propio expediente, hace falta decidir antes si es un servicio propio o
un motivo. `_apply_transfer_result()` sigue leyendo subtipos
`INTERNAL`/`EXTERNAL` que tampoco existen, con el mismo efecto que tenía
el corte antes de este cambio.
