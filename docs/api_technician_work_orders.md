# API del técnico: órdenes disponibles, mis órdenes y detalle

**Sprint FTTH · Frente: Dominio Work Orders / API del Técnico**
**Colaborador:** Kevin Rivera · **Fecha:** 02/09/2026 (día 3)
**Rama:** `feature/ftth-api-tecnico-mvp`

Endpoints de **lectura** del canal técnico. Continúan el canal autenticado del
día 2 (`docs/api_technician_auth.md`) y son los que consume la app antes de que
exista la toma de la orden, que llega el viernes.

**No hay migraciones, ni estados nuevos, ni cambios en el dominio.** Todo lo
que este documento describe es exposición de lo que `apps/work_orders` ya
resuelve.

---

## 1. Contrato para el cliente

Prefijo `/api/technicians/work-orders/`. Todos exigen la cabecera
`Authorization: Token <key>` que devuelve el login, y el permiso de canal
`IsActiveTechnician`.

| Acción | Método y ruta | Éxito | Errores |
|---|---|---|---|
| Disponibles | `GET /api/technicians/work-orders/available/` | `200` lista | `400` scope inválido · `401` · `403` |
| Mis órdenes | `GET /api/technicians/work-orders/` | `200` lista | `401` · `403` |
| Detalle | `GET /api/technicians/work-orders/<id>/` | `200` ficha | `401` · `403` · `404` |

Los tres son de solo lectura: `POST`, `PATCH`, `PUT` y `DELETE` responden
`405`.

Todos los errores tienen la misma forma, en español y con `detail` siempre
cadena — nunca lista — para que el cliente no distinga formatos según el
código:

```json
{"detail": "No encontrado."}
```

### 1.1 Parámetros

Solo `available/` acepta uno:

| Parámetro | Valores | Defecto | Significado |
|---|---|---|---|
| `scope` | `branch` \| `all` | `branch` | Acota a la sede del técnico o amplía a todas |

Cualquier otro valor responde `400`. Cualquier otro parámetro se ignora: **no
existe un parámetro de sede**. El técnico puede ampliar su universo, nunca
apuntarlo a una sede concreta.

### 1.2 Forma de las respuestas

Los campos con `choices` viajan dos veces: el **código estable**, que es con lo
que la app decide, y la **etiqueta legible**, que es lo que pinta. El cliente no
mantiene su propia tabla de traducciones ni se rompe si cambia una etiqueta.

**Fila base** (`available/` y mis órdenes):

```json
{
  "id": 12,
  "order_number": "OT-2026-00012",
  "customer": {
    "code": "CLI001",
    "document_type": "DNI",
    "document_number": "45678912",
    "display_name": "Juan Pérez Ramos"
  },
  "service_type": "Internet",
  "plan": "Fibra 100 Mbps",
  "order_type": "Instalación",
  "subtype": null,
  "status": "PENDING",
  "status_display": "Pendiente",
  "priority": "NORMAL",
  "priority_display": "Normal",
  "scheduled_at": null,
  "created_at": "2026-09-02T09:14:33.512Z"
}
```

**`available/` añade** `branch`, `zone` y `district` — lo justo para decidir si
tomar la orden.

**El detalle añade** `address` (objeto con `address`, `reference`, `district`,
`latitude`, `longitude`, `gps_link`), `detail`, `branch` y `zone`.

> **Sin paginación.** Las listas son arreglos planos, no `{count, next,
> previous, results}`. Decisión consciente del MVP: activar la paginación
> después cambiaría la forma de la respuesta y rompería al cliente. Anotado
> como punto a revisar cuando el volumen lo pida (bloqueo B7).

---

## 2. Qué es una «orden disponible» — bloqueo B1, cerrado

Definido en [`apps/work_orders/api/queries.py`](../apps/work_orders/api/queries.py).
Cuatro condiciones, decididas por negocio el 02/09:

| Condición | Por qué |
|---|---|
| `status = PENDING` | Sin ejecución todavía. Es además la condición exacta del claim |
| `assigned_technician IS NULL` | Sin responsable |
| `attention_type = FIELD` | **Regla permanente.** NOC atiende por sistema, el técnico en campo |
| `order_type.code = "INSTALLATION"` | **Recorte de alcance del MVP**, no regla de negocio |

Las dos últimas no tienen la misma vida útil y el código lo dice
explícitamente:

- Una OT marcada `SYSTEM` que se colara podría ser tomada por un técnico de
  campo, pasaría a `ASSIGNED` con él como responsable y **quedaría bloqueada
  para quien debe resolverla en remoto**. Ese filtro se queda.
- El filtro por `INSTALLATION` existe porque el hito del 07/09 es el circuito
  de instalaciones FTTH. Abrirlo a averías u otros trabajos de campo es cambiar
  una línea en `queries.py`; el resto del diseño no se entera.

La comparación por código es exacta, así que el `DEMO-INSTALLATION` de datos de
prueba queda fuera sin necesitar exclusión aparte.

**Quedan fuera `DERIVED` y `REPROGRAMMED`** aunque el dominio los admita en
`ASSIGNABLE_STATUSES`: en ambos ya hubo una decisión operativa previa —derivar a
otra área, pactar una fecha con el cliente— que una toma desde la app desharía
sin que nadie se entere.

### 2.1 Por qué la regla vive en una función y no repetida en dos vistas

`available_work_orders()` la consumen **dos endpoints escritos en jornadas
distintas**: el listado de hoy y el claim del viernes. Si cada uno declarara su
filtro, bastaría con que uno cambiara para que la app mostrara órdenes que la
toma rechaza — el técnico vería un botón que le rebota con `409` sin
explicación posible.

El parámetro `queryset` permite aplicar la misma regla sobre consultas
distintas sin que la función conozca ninguna de las dos:

```python
# Listado (hoy)
available_work_orders(WorkOrder.objects.select_related(...))

# Claim (viernes)
available_work_orders(WorkOrder.objects.select_for_update()).get(pk=pk)
```

Hay una prueba que fija el invariante:
`test_everything_listed_satisfies_the_claim_condition`.

**No se añadió un manager al modelo.** «Disponible» no es un concepto de
`WorkOrder` —la bandeja de despacho web publica otro conjunto y sigue siendo
válida—: es una regla del canal técnico y se declara en la capa del canal.

---

## 3. Sede: organización y filtro, no restricción dura

Exigencia explícita del plan (4.1). Se cumple así:

- Por defecto `available/` acota a la sede del técnico, que resuelve la
  operación normal.
- `?scope=all` amplía a todas las sedes, de modo que **una asignación legítima
  fuera de sede nunca queda bloqueada**.
- No hay parámetro de sede, así que nadie puede apuntar la bandeja a una sede
  ajena para espiar su carga.
- Un técnico **sin sede registrada ve todo**. Filtrar por `branch_id=None`
  devolvería siempre lista vacía: dejaría al técnico sin trabajo por un dato
  administrativo faltante.

**«Mis órdenes» no filtra por sede en absoluto.** Son órdenes que el técnico ya
tiene; ocultarle una porque quedó fuera de su sede sería exactamente la
restricción dura que el plan prohíbe.

---

## 4. Arquitectura de las vistas: quién entra vs. qué ve

`available/` y «mis órdenes» son **universos opuestos**: lo que no tiene dueño
frente a lo que ya lo tiene. Por eso el filtro por técnico no puede vivir en la
base compartida — la bandeja de disponibles tendría que deshacerlo, y un filtro
de visibilidad que se aplica en un sitio y se revierte en otro es donde se
cuela un hueco.

La jerarquía separa las dos preguntas:

```
TechnicianChannelMixin          ← permisos + select_related. NO filtra.
├── AvailableWorkOrderListView  ← filtro: available_work_orders() + sede
└── MyWorkOrdersMixin           ← filtro: assigned_technician = request.user
    ├── MyWorkOrderListView
    └── TechnicianWorkOrderObjectMixin   ← + relaciones del detalle, 404 uniforme
        └── MyWorkOrderDetailView
```

El filtro por técnico está escrito **una sola vez**, en `MyWorkOrdersMixin`. El
claim del viernes colgará de `TechnicianWorkOrderObjectMixin` y heredará el 404
uniforme sin implementarlo.

---

## 5. El 404 uniforme: por qué no hay 403 ni comprobación de propiedad

`RetrieveAPIView` resuelve el objeto con `get_object_or_404` sobre un queryset
**ya filtrado por técnico**. Por eso «no existe» y «es de otro técnico»
recorren el mismo camino de código y producen la misma respuesta: para la vista
la orden ajena sencillamente no está en el universo consultado.

Deliberadamente **no** hay `has_object_permission`. Un chequeo sobre el objeto
ya resuelto devolvería `403`, que confirmaría al que pregunta que la orden
existe y es de otro — justo lo que el principio de no enumerar evita. La
seguridad vive en el queryset, no en un permiso que llega tarde.

Lo único ajustado a mano es el **texto**: Django responde «No WorkOrder matches
the given query.» (en inglés y nombrando el modelo interno) y se sustituye por
el `NotFound()` de DRF, que el proyecto ya sirve en español. Mismo `raise` para
los dos casos; solo deja de contar de más.

Hay dos pruebas que lo fijan: `test_foreign_order_and_unknown_id_are_indistinguishable`
compara código **y cuerpo** de ambas respuestas, y
`test_permission_is_evaluated_before_the_object` confirma que un no-técnico
recibe `403` incluso apuntando a un id inexistente.

### 5.1 Una orden disponible todavía no responde en el detalle

Es intencional, no un hueco. El flujo aprobado pone *ver detalle* **después** de
*tomar orden*, y el detalle solo responde sobre órdenes propias. Lo que el
técnico necesita para decidir si la toma viaja en la fila de `available/`.

De ahí que esa fila lleve `branch`, `zone` y `district` — y que **no** lleve la
dirección exacta: `available/` es visible para todos los técnicos del canal, y
quien no ha tomado la orden no necesita el domicilio del cliente. El distrito
ubica lo suficiente para decidir; la calle y las coordenadas aparecen en el
detalle. Registrado como bloqueo B6 por si negocio quiere una ficha previa.

---

## 6. Criterio de orden

Las dos listas ordenan distinto **a propósito**, porque responden preguntas
distintas:

| Listado | Orden | Razón |
|---|---|---|
| `available/` | `scheduled_at` asc (nulls last), `created_at` asc, `pk` | Cola de reparto: primero lo comprometido con el cliente, después lo más antiguo |
| Mis órdenes | `scheduled_at` asc (nulls last), `-created_at`, `pk` | La jornada del técnico: lo más próximo primero |

Ninguna usa `Meta.ordering` del modelo (`-created_at`), que sirve a la bandeja
de despacho web —esa mira lo recién ingresado—. Las órdenes sin fecha
programada van al final en lugar de encabezar la lista.

**No se ordena por `priority`:** es un `CharField` con choices y
alfabéticamente daría HIGH, LOW, NORMAL, URGENT, un orden sin sentido
operativo. Hacerlo bien exigiría anotar un peso; queda documentado como opción
futura, no como olvido.

El desempate por `pk` mantiene el orden estable entre peticiones.

---

## 7. Rendimiento

Las relaciones se precargan por capas, sin que ninguna vista repita las de otra:

```python
# TechnicianChannelMixin — lo que pinta cualquier fila.
.select_related(
    "subscription", "subscription__customer",
    "subscription__service_type", "subscription__plan",
    "order_type", "subtype",
)

# available/ encadena lo suyo:
.select_related("branch", "zone", "subscription__address")

# El detalle encadena lo suyo:
.select_related("subscription__address", "branch", "zone")
```

Sin esto, listar N órdenes dispara una consulta por cliente, servicio, plan,
tipo y subtipo de cada fila.

Ambos listados tienen prueba de N+1
(`test_query_count_does_not_grow_with_the_number_of_orders`), que compara
contra la línea base medida con una sola orden en lugar de fijar un número
absoluto: lo que importa es que el costo **no dependa del tamaño del listado**.

---

## 8. Pruebas

| Archivo | Cubre |
|---|---|
| `test_api_available_orders.py` | Las 4 condiciones de B1 una por una, sede blanda, `scope` inválido, forma de la fila, no exposición del domicilio, orden, permisos, solo lectura, N+1 |
| `test_api_my_orders.py` | Aislamiento entre técnicos, lista vacía, campos, orden, permisos, N+1 |
| `test_api_work_order_detail.py` | Contenido de la ficha, 404 uniforme e indistinguible, orden de evaluación de permisos, solo lectura |

Los dos últimos se **rescataron con revisión** de `feature/api-tecnico-base`
—sin merge ni cherry-pick, según la estrategia del día 1— y pasan sin cambios
sobre el `base.py` actual.

---

## 9. Qué NO se tocó

- **`apps/work_orders/models.py` y `services.py`**: idénticos. Ni un estado
  nuevo, ni un manager, ni una migración.
- **La capa web**: bandeja de despacho, asignación e inicio de atención siguen
  igual. El canal API es aditivo.
- **`config/urls.py`**: una sola adición, el `include` de las rutas de órdenes
  antes del de identidad. Nada existente se movió.
- **El inicio de atención (`start/`) de la rama histórica**: existe y es
  rescatable, pero no está en el contrato mínimo del sprint y hoy es jornada de
  solo lectura. Se reintegra cuando la atención entre en alcance.

---

## 10. Bloqueos abiertos

- **B6 — Ficha previa al claim.** El técnico decide con `branch`, `zone` y
  `district`. Confirmar si basta o si negocio quiere un detalle antes de tomar.
- **B7 — Paginación.** Hoy lista plana. Revisar cuando el volumen lo pida;
  activarla cambia la forma de la respuesta.
- **B3, B4 — Permiso y nombre del claim.** Siguen abiertos del día 1; se
  resuelven el viernes.
- **B5 — Punto de creación comercial.** Coordinación con Joleydi, jueves.
