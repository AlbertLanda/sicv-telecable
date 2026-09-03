# API del técnico — referencia rápida

**Sprint FTTH · Canal técnico · Actualizado: día 6 (hardening)**
**Base:** `https://<host>/api/technicians/`

Página única para **consumir** la API sin conocer reglas internas del dominio
(exigencia del plan §4.1). Cada endpoint enlaza al documento que explica *por
qué* está diseñado así; aquí solo está *cómo* se usa.

| Documento | Cubre |
|---|---|
| [`api_technician_auth.md`](api_technician_auth.md) | Login e identidad |
| [`api_technician_work_orders.md`](api_technician_work_orders.md) | Disponibles, mis órdenes, detalle |
| [`api_technician_claim.md`](api_technician_claim.md) | Toma de la orden |
| [`orden_tecnica_contrato_compartido.md`](orden_tecnica_contrato_compartido.md) | Quién escribe qué sobre la misma OT |

---

## 1. Todos los endpoints

| # | Acción | Método y ruta | Auth | Éxito | Errores |
|---|---|---|---|---|---|
| 1 | Login | `POST /login/` | — | `200` `{token, technician}` | `400` · `401` · `403` |
| 2 | Identidad | `GET /me/` | Token | `200` identidad | `401` · `403` |
| 3 | Disponibles | `GET /work-orders/available/` | Token | `200` lista | `400` scope inválido · `401` · `403` |
| 4 | Mis órdenes | `GET /work-orders/` | Token | `200` lista | `401` · `403` |
| 5 | Detalle | `GET /work-orders/<id>/` | Token | `200` ficha | `401` · `403` · `404` |
| 6 | **Tomar OT** | `POST /work-orders/<id>/claim/` | Token | `200` ficha asignada | `401` · `403` · `409` |

Cualquier método no listado responde `405`. Los endpoints 3, 4 y 5 son de solo
lectura; el 6 es la **única** escritura del canal.

## 2. Autenticación

```http
POST /api/technicians/login/
{"username": "tecnico1", "password": "..."}

200 → {"token": "9944b09...", "technician": {...}}
```

Después, en **toda** petición:

```http
Authorization: Token 9944b09...
```

El token **no caduca**, pero el permiso se reevalúa en cada petición: si al
técnico se le desactiva la cuenta o se le cambia el rol, la siguiente petición
falla sin esperar a que el token expire.

## 3. Forma de los errores

Siempre igual, en español, y `detail` **siempre cadena** — nunca lista — para
que el cliente no distinga formatos según el código:

```json
{"detail": "No encontrado."}
```

| Código | Significa | Qué debe hacer el cliente |
|---|---|---|
| `400` | Entrada inválida (p. ej. `scope` desconocido) | Corregir el parámetro |
| `401` | Sin token o token inválido | Volver al login |
| `403` | Autenticado pero sin permiso de canal | No reintentar; no es un técnico activo |
| `404` | Orden inexistente **o de otro técnico** (indistinguible a propósito) | Refrescar la lista |
| `405` | Método no permitido | Error de integración |
| `409` | La orden ya no está disponible para tomar | Refrescar `available/` |

## 4. Flujo típico del cliente

```
POST /login/                       → token
GET  /work-orders/available/       → el técnico elige una
POST /work-orders/<id>/claim/      → 200: ya es suya (o 409: otro la tomó)
GET  /work-orders/                 → su jornada
GET  /work-orders/<id>/            → ficha completa con dirección y GPS
```

El detalle **solo responde sobre órdenes propias**: antes de tomarla devuelve
`404`. Para decidir si la toma, el técnico usa lo que ya viaja en la fila de
`available/` (sede, zona y distrito).

## 5. Campos de la respuesta

### 5.1 Fila de `available/`

```json
{
  "id": 12,
  "order_number": "OT-2026-000012",
  "customer": {"code": "CLI001", "display_name": "Juan Pérez Ramos"},
  "service_type": "Internet",
  "plan": "Fibra 100 Mbps",
  "order_type": "Instalación",
  "subtype": null,
  "status": "PENDING",
  "status_display": "Pendiente",
  "priority": "NORMAL",
  "priority_display": "Normal",
  "scheduled_at": null,
  "created_at": "2026-09-02T09:14:33.512Z",
  "branch": "Sede Chachapoyas",
  "zone": "Zona Norte",
  "district": "Chachapoyas"
}
```

**Sin documento del cliente y sin domicilio**: esta bandeja la ven todos los
técnicos del canal.

### 5.2 Ficha (detalle y respuesta del claim)

Todo lo anterior —con `customer` ampliado a `document_type` y
`document_number`— más:

```json
{
  "address": {
    "address": "Av. Los Álamos 123",
    "reference": "Frente al parque",
    "district": "Chachapoyas",
    "latitude": "-6.2290000",
    "longitude": "-77.8730000",
    "gps_link": "https://www.google.com/maps/search/?api=1&query=..."
  },
  "detail": "",
  "branch": "Sede Chachapoyas",
  "zone": "Zona Norte",
  "reason": "Cliente nuevo",
  "started_at": null,
  "attended_at": null,
  "can_start_attention": true,
  "technical_data": null
}
```

**Reglas que el cliente debe respetar al pintar esto:**

- **Choices dobles.** Decida con el código (`status`), muestre la etiqueta
  (`status_display`). No mantenga su propia tabla de traducciones.
- **`can_start_attention`** dice si ofrecer «Iniciar atención». Lo decide el
  servidor; no lo deduzca del estado ni replique la matriz de transiciones.
- **`technical_data`** es `null` mientras no haya liquidación. `null` y un
  bloque con campos vacíos **no** son lo mismo.
- **Ubicación:** `address`, `reference` y `district` siempre vienen.
  `latitude`, `longitude` y `gps_link` pueden ser `null` / `""` y **eso
  significa que no hay GPS**. Nunca compare contra `0`: un cero jamás llega por
  esta API. Si no hay coordenadas, guíe por la dirección textual.
- **Coordenadas como cadena**, para no perder precisión al pasar por float.

### 5.3 `technical_data` cuando existe

```json
{
  "liquidated_at": "2026-09-06T18:20:11Z",
  "resolution_detail": "Se instaló la ONU y se dejó el servicio operativo.",
  "technical_notes": "",
  "network_element": "NAP-014",
  "network_port": "5",
  "equipment_serial": "ABC123",
  "signal_level_dbm": "-18.50",
  "cable_meters_used": "45.00",
  "krill_reference": "",
  "review_status": "LIQUIDATED",
  "review_status_display": "Liquidada"
}
```

Hoy **solo lectura**. Estos son los nombres y tipos con los que llegará la
escritura cuando atención y liquidación entren en alcance, para que la pantalla
se escriba una sola vez.

## 6. Parámetros

Solo `available/` acepta uno:

| Parámetro | Valores | Defecto | Significado |
|---|---|---|---|
| `scope` | `branch` \| `all` | `branch` | Acota a la sede del técnico o amplía a todas |

Cualquier otro valor → `400`. **No existe un parámetro de sede**: el técnico
puede ampliar su universo, nunca apuntarlo a una sede concreta.

> Un técnico **sin sede** registrada ve todo, en lugar de recibir una lista
> vacía por un dato administrativo faltante.

## 7. Tomar una orden

```http
POST /api/technicians/work-orders/12/claim/
Authorization: Token ...

{"remarks": "Voy en camino"}      ← opcional; cuerpo vacío también es válido
```

- **`200`** → la ficha completa, ya en `ASSIGNED`. No hace falta una segunda
  petición para pintar la pantalla.
- **`409`** → `{"detail": "La orden ya no está disponible."}` Misma respuesta
  para: la tomó otro, no existe, cambió de estado, no es de campo, no es
  instalación, o su suscripción se canceló. **Es indistinguible a propósito**,
  para que no se puedan sondear órdenes ajenas. Acción del cliente: refrescar
  `available/`.

**El cuerpo no decide nada más.** `remarks` es el único campo aceptado; enviar
`status`, `assigned_technician` u `order_number` no tiene efecto: se descartan
antes de llegar al dominio. El técnico sale siempre del token.

> **Reintento por red intermitente (bloqueo B9, abierto).** Si la petición
> llegó pero la respuesta se perdió, el reintento responde `409` aunque la
> orden ya sea suya. Recuperación: recargar `GET /work-orders/` — si la orden
> aparece ahí, la toma **sí** se aplicó.

## 8. Qué NO expone la API todavía

Fuera de alcance del hito del 07/09, en el orden en que llegarán:

| Acción | Estado |
|---|---|
| Iniciar atención | Existe en el dominio (`start_order_attention()`); no expuesta |
| Registrar resultado / atender | Existe en el dominio (`attend_order()`); no expuesta |
| Liquidar y registrar datos técnicos | Existe en el dominio (`liquidate_order()`); solo lectura en la API |
| Materiales, evidencias y firma | No implementado |
| Paginación de listas | Listas planas (bloqueo B7) |

Cuando lleguen, **la OT seguirá siendo la misma `WorkOrder`**: no habrá un
recurso nuevo ni una copia.

## 9. Qué se puede tomar — definición vigente

Cinco condiciones, en [`api/queries.py`](../apps/work_orders/api/queries.py).
`available/` y `claim/` consumen **la misma función**, así que lo que la
bandeja publica es exactamente lo que la toma acepta:

| Condición | Naturaleza |
|---|---|
| `status = PENDING` | Regla |
| Sin técnico asignado | Regla |
| `attention_type = FIELD` | **Permanente** — NOC atiende por sistema |
| `order_type.code = INSTALLATION` | **Recorte del MVP**, no regla de negocio |
| Suscripción no cancelada | Mitigación (B10) |

Ampliar el alcance a averías u otros trabajos de campo es cambiar **una línea**
de ese archivo; el resto del canal no se entera.
