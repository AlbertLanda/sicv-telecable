# Orden Técnica: contrato compartido ATC ↔ técnico

**Sprint FTTH · Frentes: Alta comercial (Joleydi) + API del técnico (Kevin)**
**Fecha:** 02/09/2026 (día 5) · revisado el día 6
**Estado:** propuesta de Kevin, **pendiente de confirmación de campos por
Joleydi**

Documento de coordinación pedido en la jornada del 02/09: *«la OT debe ser una
sola `WorkOrder`; ATC la consulta en modo lectura y el técnico modifica
únicamente lo que le corresponda»* y *«coordina con Joleydi los campos que
necesita su ficha para que ambos trabajen sobre el mismo contrato API»*.

No introduce modelos, campos ni migraciones: **describe lo que ya existe** y
fija los nombres para que las dos fichas se escriban una sola vez.

---

## 1. Una sola OT, dos lecturas

```
                        ┌──────────────────────────────┐
   ATC (web, lectura) ──▶│      WorkOrder (única)       │◀── Técnico (API)
                        │  + WorkOrderLiquidation      │
                        │  + WorkOrderStatusHistory    │
                        │  + WorkOrderAssignment       │
                        └──────────────────────────────┘
```

**No hay copia, ni espejo, ni tabla «datos del técnico».** Las tres tablas
satélite son historial del dominio, no duplicados: cada una responde una
pregunta distinta (qué se ejecutó, cómo se movió el estado, quién la tuvo).

Por qué importa: un segundo modelo obligaría a sincronizar dos verdades y a
decidir cuál gana cuando difieran. Con una sola fila, ATC y el técnico ven el
mismo dato en el mismo instante y no hay nada que sincronizar.

### 1.1 Quién escribe qué

| Dato | Lo escribe | Cómo | ATC |
|---|---|---|---|
| Alta de la OT (`subscription`, tipo, sede, zona, motivo, programación) | Alta comercial | `create_installation_work_order()` | lectura |
| Responsable (`assigned_technician`, `status → ASSIGNED`) | El técnico, al tomarla | `POST .../claim/` → `assign_technician()` | lectura |
| Inicio real (`started_at`, `status → IN_PROGRESS`) | El técnico | `start_order_attention()` — *fuera de alcance hoy* | lectura |
| Resultado (`result`, `status → ATTENDED`) | El técnico | `attend_order()` — *fuera de alcance hoy* | lectura |
| Datos técnicos (red, puerto, serie, señal, cable, Krill) | El técnico | `liquidate_order()` — *fuera de alcance hoy* | lectura |
| Revisión de la liquidación | Quien tenga `validate_liquidation` | servicios de revisión | según permiso |

**El técnico no puede escribir nada más que su parte, y no por convención sino
por construcción:** los serializadores de entrada del canal declaran
únicamente los campos admitidos (hoy, `remarks`), así que un POST con
`status`, `assigned_technician` u `order_number` es descartado por DRF antes de
llegar al dominio. Y el técnico sale siempre de `request.user`, nunca del
cuerpo.

**Aislamiento por usuario:** todo endpoint de OT propia resuelve sobre un
queryset filtrado por `request.user` (`MyWorkOrdersMixin`, una sola línea en
todo el canal). Una OT ajena responde `404`, idéntico a un id inexistente, para
no permitir enumerar. La toma es la única excepción y opera sobre el pool sin
dueño, donde por definición no hay nada ajeno que proteger.

---

## 2. Campos publicados hoy por la API del técnico

Contrato completo en [`api_technician_work_orders.md`](api_technician_work_orders.md)
y [`api_technician_claim.md`](api_technician_claim.md). Resumen para comparar
con la ficha de ATC:

| Bloque | Campos | Bandeja | Ficha |
|---|---|---|---|
| Identificación | `id`, `order_number` | ✅ | ✅ |
| Cliente | `code`, `display_name` | ✅ | ✅ |
| Cliente (documento) | `document_type`, `document_number` | ❌ | ✅ |
| Servicio | `service_type`, `plan` | ✅ | ✅ |
| Clasificación | `order_type`, `subtype`, `reason` | parcial | ✅ |
| Estado | `status` + `status_display`, `priority` + `priority_display` | ✅ | ✅ |
| Ubicación aproximada | `branch`, `zone`, `district` | ✅ | ✅ |
| Ubicación exacta | `address` (calle, referencia, distrito, GPS) | ❌ | ✅ |
| Tiempos | `created_at`, `scheduled_at`, `started_at`, `attended_at` | parcial | ✅ |
| Acción disponible | `can_start_attention` | ❌ | ✅ |
| Datos técnicos | `technical_data` (bloque, `null` si no hay) | ❌ | ✅ |

Dos criterios que conviene replicar en la ficha de ATC:

- **Cada campo con `choices` viaja dos veces**: el código estable, con el que
  el cliente decide, y la etiqueta legible, que es lo que pinta. Así nadie
  mantiene su propia tabla de traducciones ni se rompe si cambia una etiqueta.
- **La bandeja compartida no lleva datos personales ni el domicilio.**
  `available/` la ven todos los técnicos del canal; el documento del cliente y
  la dirección exacta aparecen solo cuando la OT ya tiene dueño.

`technical_data` es **`null`** mientras no haya liquidación —no un bloque de
campos vacíos—: son estados distintos y el cliente debe poder distinguir «aún
no se liquidó» de «se liquidó dejando los opcionales en blanco». Sus campos:
`liquidated_at`, `resolution_detail`, `technical_notes`, `network_element`,
`network_port`, `equipment_serial`, `signal_level_dbm`, `cable_meters_used`,
`krill_reference`, `review_status` + `review_status_display`. Hoy solo lectura;
esos son los nombres con los que llegará la escritura.

---

## 3. Ubicación: la regla es única y ya está escrita

Definición en [`apps/customers/coordinates.py`](../apps/customers/coordinates.py).
**Una sola función que los tres frentes pueden consumir**, para que ATC, el
resumen del contrato y la app del técnico no discrepen sobre si hay GPS.

1. **La dirección textual viaja siempre y nunca se sustituye por
   coordenadas.** `address`, `reference` y `district` son el dato que permite
   llegar; el GPS es un extra que se acompaña.
2. **`0`, `0.0000000`, vacío, no numérico o fuera del planeta ⇒ `null`.**
   Nunca `0`, para que ninguna capa posterior pueda confundirlo con una
   ubicación.
3. **El par es indivisible.** Si una coordenada falla, la otra tampoco se
   publica: media coordenada no ubica nada e invita a componer un mapa con el
   valor que falta puesto a cero.
4. **`gps_link` se deriva de las coordenadas, no se lee de la base de datos.**
   El enlace almacenado pudo construirse sobre un `0,0` antes de esta regla, y
   servirlo tal cual sería la puerta de atrás por la que el dato falso vuelve.

```python
from apps.customers.coordinates import location_payload

location_payload(address)
# {"address": ..., "reference": ..., "district": ...,
#  "latitude": Decimal | None, "longitude": Decimal | None, "gps_link": str}
```

Para plantillas —que no pueden llamar funciones con argumentos— la misma regla
se expone como propiedades de `CustomerAddress`: **`map_latitude`,
`map_longitude` y `map_link`**. Los campos almacenados (`latitude`,
`longitude`, `gps_link`) no cambian: siguen guardando lo que llegó. Lo que
cambia es qué se publica. No hay migración.

Aplicado en dos sitios:

| Consumidor | Cómo |
|---|---|
| Ficha de la Orden Técnica (API) | `WorkOrderAddressSerializer.to_representation` → `location_payload()` |
| Ficha del cliente que lee ATC (`customers/detail.html`) | `addr.map_latitude` · `addr.map_longitude` · `addr.map_link` |

**Nota de lane:** el cambio en la plantilla de ATC toca el frente de clientes.
Lo hice porque ahí es donde el enlace falso se estaba pintando y la
instrucción de la jornada es que un `0,0` nunca se publique como GPS válido;
es aditivo —tres propiedades y tres referencias en la plantilla, sin migración
ni cambio de datos— y se puede revertir sin tocar nada más si prefieren que lo
lleve el frente de clientes.

Pruebas: `apps/customers/test_coordinates.py` (unitarias, incluidas las
propiedades del modelo), `WorkOrderDetailLocationTests` (sobre la respuesta
real de la API) y `CustomerDetailLocationRenderTests` (sobre el HTML que ve
ATC).

### 3.1 ⚠️ El dato falso todavía **entra** por la consulta de suministro

Lo anterior sanea lo que se **publica**. La puerta de **entrada** sigue
abierta, y no la he cerrado porque cambiar ese contrato afecta a las pruebas y
al formulario del frente de alta comercial. Lo reporto con el arreglo listo.

Son **tres puntos de la misma causa**:

**(a) El servicio Python** — `apps/customers/services/distriluz_gps.py:160`
decide si hay GPS por presencia de la cadena:

```python
latitude = data.get("gpsy") or data.get("latitud") or ""
longitude = data.get("gpsx") or data.get("longitud") or ""

gps_link = ""
if latitude and longitude:          # ← "0" es una cadena no vacía: pasa
    gps_link = (...)
```

**(b) El JavaScript del formulario** —
`apps/customers/templates/customers/address_create.html:322`, mismo patrón y
mismo efecto, porque `"0"` también es *truthy* en JavaScript:

```javascript
if (data.latitude && data.longitude) {
    previewCoordinates.textContent = data.latitude + ", " + data.longitude;
}
```

Con un `0` de Distriluz, el preview muestra **«0, 0»**, el mensaje dice
*«Suministro encontrado con coordenadas GPS»*, habilita el enlace al mapa y al
confirmar escribe `0` en los campos del formulario (línea 358). **ATC ve un GPS
que parece válido y lo aprueba de buena fe.**

**(c) Lo ya almacenado** — cada alta de un suministro sin georreferencia deja
un `0.0000000` en `CustomerAddress`.

Arreglo para (a) y (b), consumiendo la misma regla —no duplica nada—:

```python
from apps.customers.coordinates import normalize_coordinate_pair, build_gps_link

latitude, longitude = normalize_coordinate_pair(
    data.get("gpsy") or data.get("latitud"),
    data.get("gpsx") or data.get("longitud"),
)

gps_link = build_gps_link(latitude, longitude)
```

Con eso el JSON ya llega con `null` y el `if` del JavaScript se comporta
correctamente sin tocarlo.

Cambia el contrato de `consultar_suministro_gps()` en un punto —las
coordenadas pasan de cadena a `Decimal | None`—, así que toca
`test_supply_lookup.py` y la plantilla que las recibe. **Decisión de Joleydi o
del líder**, no unilateral mía.

**Situación actual:** ni el técnico ni ATC ven el enlace falso, porque las dos
fichas aplican la regla al publicar. Lo que queda es que la base sigue
acumulando ceros, y que cualquier pantalla nueva que lea `addr.gps_link`
directamente —en lugar de `addr.map_link`— volverá a mostrar el golfo de
Guinea sin que nadie lo note.

---

## 4. Lo que necesito de Joleydi

1. **Los campos de su ficha** que salgan de la OT o de la dirección, para
   confirmar que los nombres coinciden con la tabla del §2 y que ninguno de los
   dos publica un dato que el otro llama distinto.
2. **Si el resumen del contrato o de la suscripción llega a mostrar GPS**, usar
   `addr.map_latitude` / `addr.map_longitude` / `addr.map_link` —o
   `location_payload()` si es JSON— en lugar de los campos almacenados. Hoy
   esas dos plantillas no muestran coordenadas, así que no hay nada que
   cambiar; queda dicho para cuando las muestren.
3. **Dónde queda el llamador de `create_installation_work_order()`.** Hoy nadie
   en producción lo llama (`git grep` solo encuentra pruebas), así que el
   circuito completo *alta → bandeja → toma* solo se puede recorrer creando la
   OT desde la web o el Admin. En cuanto su acción exista, la OT nace
   `PENDING`/`FIELD`/`INSTALLATION` y aparece tomable sin ningún paso
   adicional: la fachada ya lo garantiza.
4. **Confirmar que su ficha no escribe** `status` ni `assigned_technician`
   directamente. Si alguna pantalla comercial necesita mover el estado, que
   pase por los servicios del dominio.

---

## 5. Decisiones pendientes de negocio

- **B3 — Permiso funcional de la toma.** Ver
  [`api_technician_claim.md`](api_technician_claim.md) §6. Reutilizar
  `assign_workorder` daría a los técnicos la potestad de despachar cualquier
  orden desde la web.
- **B9 — Idempotencia de la toma** ante reintento del mismo técnico (red
  intermitente en campo). Hoy responde `409`.
- **B6 — Ficha previa a la toma.** ¿Basta `branch` + `zone` + `district` para
  decidir?
- **B10 — Suscripción cancelada con instalación abierta.** Ver §6.
- **Sugerencia de Zona a partir del suministro.** Distriluz devuelve distrito y
  GPS, no Zona: hoy la elige ATC a mano y de ella dependen la bandeja y el
  filtro de sede del técnico. Deducirla exigiría definir qué manda si distrito
  y GPS discrepan, y qué pasa cuando no hay GPS.
- **Traslado externo.** En un traslado el técnico se presenta en
  `TransferDetail.new_address`, no en la dirección vigente del servicio. Fuera
  del alcance FTTH de hoy; anotado para cuando el tipo entre al canal.

---

## 6. B10 — Suscripción cancelada con instalación abierta

Detectado en el hardening del día 6. **Mitigado en el canal; la decisión de
fondo sigue siendo de negocio.**

`create_installation_work_order()` impide crear una instalación sobre una
suscripción cancelada. Pero **nada revisa el orden inverso**: si la
suscripción se cancela *después*, la OT ya creada sigue en `PENDING` y por
tanto sigue publicándose en `available/` y sigue siendo tomable.

El camino no es hipotético: un corte definitivo (`_apply_cut_result` con
subtipo `DEFINITIVE`) pone la suscripción en `CANCELLED` y **no toca las demás
órdenes de esa suscripción**. Tampoco hay filtro que lo tape después:
`available_work_orders()` mira la OT y nunca el estado de la suscripción.

**Sin casos vivos hoy:** en la base de desarrollo hay 0 órdenes abiertas con
suscripción cancelada, así que esto es prevención y no un incidente en curso.

Consecuencia operativa: un técnico puede tomar y viajar a instalar un servicio
que comercialmente ya no existe.

### 6.1 Lo aplicado (mitigación de canal)

`available_work_orders()` dejó de publicar órdenes cuya suscripción esté en
`SUBSCRIPTION_BLOCKED_STATUSES`. Tres propiedades que la hacen defendible:

- **No inventa un criterio.** Importa del dominio la **misma lista** desde la
  que `create_work_order()` se niega a registrar trabajo nuevo: si el dominio
  no aceptaría crear esa orden hoy, el canal no la publica. Y si negocio añade
  un estado a esa lista, las dos puntas se mueven juntas.
- **No toca el dominio.** Ni un estado, ni un efecto, ni una migración. La OT
  sigue viva y visible para despacho, que es quien decide si se anula.
- **La toma la hereda sin escribir una línea**, porque comparte definición con
  el listado. Deja de publicarse y deja de ser tomable en el mismo instante.

Es estrecha a propósito: **solo cancelada**. `PRESALE` es donde vive una
instalación normal y `SUSPENDED` admite trabajo legítimo. Hay prueba de ambos
lados (`test_order_of_a_cancelled_subscription_is_not_available` y
`test_other_subscription_statuses_stay_available`).

### 6.2 Lo que sigue pendiente de negocio

**¿Al cancelar una suscripción deben anularse sus OT abiertas?** Si la
respuesta es sí, es un efecto nuevo en el dominio —hay que decidir el
mecanismo y la traza— y requiere aprobación explícita. La mitigación de arriba
evita el viaje en falso, pero **no limpia** la cola: esas OT siguen abiertas
en la bandeja de despacho web, que es donde alguien debe decidir qué hacer con
ellas.
