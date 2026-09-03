# API del técnico: tomar orden (claim)

**Sprint FTTH · Frente: Dominio Work Orders / API del Técnico**
**Colaborador:** Kevin Rivera · **Fecha:** 02/09/2026 (día 5)
**Rama:** `feature/ftth-api-tecnico-mvp`

Cierra el circuito del hito: la OT que genera el alta comercial FTTH aparece en
`available/` (día 3) y aquí el técnico **la toma**, quedando como responsable
sin que despacho intervenga.

Es la **única acción de escritura** del canal técnico. Continúa
[`docs/api_technician_work_orders.md`](api_technician_work_orders.md) y cierra
el hueco de concurrencia detectado en
[`docs/api_tecnico_auditoria_dia1.md`](api_tecnico_auditoria_dia1.md) §2.3.

**No hay migraciones, ni estados nuevos, ni cambios en el dominio.**
`models.py` y `services.py` siguen idénticos: la transición la ejecuta
`WorkOrder.assign_technician()`, el mismo método que usa la bandeja de despacho
web. Lo único que este endpoint añade sobre el dominio es el **bloqueo de
fila**, que es responsabilidad del canal y no una regla nueva.

---

## 1. Contrato para el cliente

| Acción | Método y ruta | Éxito | Errores |
|---|---|---|---|
| Tomar OT | `POST /api/technicians/work-orders/<id>/claim/` | `200` ficha ya asignada | `401` · `403` · `409` no disponible |

Cabecera `Authorization: Token <key>`, igual que el resto del canal.
`GET`, `PUT`, `PATCH` y `DELETE` responden `405`: tomar es una acción, no un
recurso que se lea o se edite. En particular `GET` **no** toma la orden — una
escritura alcanzable por una navegación accidental sería una orden asignada sin
que nadie la pidiera.

### 1.1 Cuerpo de la petición

```json
{"remarks": "Voy en camino, llego en 20 minutos."}
```

`remarks` es **el único campo aceptado**, y es opcional: un POST con cuerpo
vacío es válido. Queda registrado en la asignación y en el historial de
estados.

Lo que el cuerpo **no** puede decidir: `assigned_technician`, `status`,
`assigned_at` ni ningún otro campo de la orden. No están declarados en
`WorkOrderClaimSerializer`, así que DRF los descarta al validar y el dominio
nunca los ve. El responsable sale de `request.user`, el estado destino lo
decide la matriz de transiciones y la hora la pone `timezone.now()` dentro del
dominio. Hay prueba:
`test_the_client_cannot_decide_the_technician_or_the_status`.

### 1.2 Respuesta de éxito

**La ficha completa del detalle**, no la fila de la bandeja: incluye `address`
(con referencia y coordenadas) y `detail`, que `available/` deliberadamente no
publica. Dos razones:

- El técnico que acaba de tomar la orden ya necesita la dirección para
  moverse, y así no hace una segunda petición.
- Ya tiene derecho a verla: la orden es suya. Que la respuesta traiga el
  domicilio es la otra cara de que `available/` no lo lleve.

El `status` que viaja es el de **después** de la toma (`ASSIGNED` /
«Asignada»): la ficha se relee de la base tras la transición, no se serializa
la instancia previa.

Con la ficha llega también lo que el técnico necesita para seguir:
`can_start_attention` en `true` —la siguiente acción, decidida por el dominio y
no deducida del estado por la app— y `technical_data` en `null`, porque todavía
no se ejecutó nada. Detalle de esos campos en
[`api_technician_work_orders.md`](api_technician_work_orders.md) §1.2.

**Ubicación:** la dirección textual viaja siempre; las coordenadas solo si son
válidas. Un `0 / 0.0000000` se publica como `null` y sin `gps_link`, nunca como
GPS real (§1.3 del mismo documento).

---

## 2. Qué se puede tomar: la misma definición que la bandeja

La toma resuelve su objeto contra
[`available_work_orders()`](../apps/work_orders/api/queries.py), **la misma
función** que publica `available/`.

Esa coincidencia es el invariante del canal, no un detalle de implementación:
si el listado fuera más ancho que la toma, el técnico vería órdenes que al
pulsarlas rebotan con `409` sin explicación posible; si fuera más estrecho,
habría órdenes tomables invisibles. Se verifica **en las dos direcciones**:

| Dirección | Prueba |
|---|---|
| Lo listado se puede tomar | `test_everything_available_can_actually_be_claimed` |
| Lo tomado sale de la bandeja | `test_claimed_order_leaves_the_available_pool` |

De reutilizar la definición se siguen gratis dos protecciones que **no hay que
programar aquí**: una orden de otro técnico no es tomable (tiene dueño) y una
`SYSTEM` de NOC tampoco (no es trabajo de campo).

### 2.1 La protección que sí es propia del endpoint

`assign_technician()` acepta **reasignar** una orden que ya está en `ASSIGNED`
— es una potestad legítima del despacho web, que decide a quién le toca. Por
eso, si la toma resolviera la orden por `pk` sin más, **un técnico podría
arrebatarle el trabajo a otro con una sola petición**.

Lo único que lo impide es que el universo de la toma sea el pool sin dueño.
Está fijado por `test_order_already_taken_by_another_technician_is_not_stolen`,
que además comprueba que la orden no cambió: no basta con recibir `409` si por
el camino se abrió una asignación nueva.

### 2.2 Sede: no filtra

`available/` acota a la sede del técnico por defecto y amplía con
`?scope=all`. La toma **no filtra por sede en absoluto**, y es deliberado: si
lo hiciera, el técnico vería una orden con `scope=all` y no podría tomarla —
exactamente la restricción dura que el plan (4.1) prohíbe. Un técnico sin sede
registrada también puede tomar.

---

## 3. Concurrencia: el bloqueo transaccional

Requisito del plan: dos técnicos no pueden quedar ambos como responsables de la
misma OT.

El hueco está identificado desde el día 1 (§2.3): `assign_technician()` es
atómico pero **no bloquea la fila** — valida `self.status` sobre la instancia ya
cargada en memoria, así que dos tomas simultáneas podrían leer ambas `PENDING`
y pasar las dos. Se cierra en el canal, **sin modificar el dominio**:

```python
@transaction.atomic
def claim(self, *, remarks):
    order = available_work_orders(
        WorkOrder.objects.select_for_update(of=("self",))
    ).get(pk=self.kwargs["pk"])

    order.assign_technician(
        self.request.user,
        assigned_by=self.request.user,
        remarks=remarks,
    )

    return order
```

Tres decisiones, todas necesarias:

1. **El filtro viaja DENTRO del `select_for_update()`.** Ahí está todo el peso:
   el ganador toma el lock con la orden aún disponible; el perdedor espera, y
   cuando el lock se libera la orden ya tiene dueño y no cumple el filtro, así
   que cae en `DoesNotExist` → `409`. Comprobar la disponibilidad antes o
   después del bloqueo, en lugar de dentro, dejaría la carrera abierta.

2. **`of=("self",)` limita el bloqueo a la fila de la OT.** El filtro por
   `order_type__code` obliga a un JOIN con el catálogo, y un `FOR UPDATE` sin
   `of` bloquearía también esa fila: como **todas** las instalaciones comparten
   el mismo `OrderType`, cada toma quedaría esperando a la anterior en el
   sistema completo en vez de solo en su propia orden.

3. **La consulta que bloquea no lleva `select_related`.** Añadirlo metería
   `LEFT JOIN` por las FK opcionales (`zone`, `subtype`), y PostgreSQL rechaza
   un `FOR UPDATE` sobre el lado nulable de un outer join. La ficha se relee
   después, ya fuera de la carrera, por `object_queryset()`.

**Nota de motor.** En PostgreSQL (producción) el bloqueo de fila es real. En
SQLite (desarrollo y CI) la cláusula se ignora — incluido `of`, sin error — y
las escrituras se serializan a nivel de base de datos. Es el mismo criterio ya
aplicado al correlativo de OT y a la unicidad de la instalación.

### 3.1 Cómo se prueba algo que el entorno no reproduce

El escenario de dos tomas simultáneas no es reproducible en SQLite. Se cubre
por los dos lados:

- `test_the_claim_locks_only_the_work_order_row` — caja blanca: verifica que la
  consulta **pide** el bloqueo y que está limitado a `self`. Es lo que un
  refactor podría perder en silencio sin que ninguna otra prueba se queje.
- `test_the_loser_of_the_race_gets_the_unavailable_response` — el resultado
  observable: uno gana, el otro recibe `409`, queda **una sola** asignación
  vigente y nunca hay dos técnicos convencidos de ser el responsable.
- `test_a_rejected_claim_leaves_nothing_behind` — resolución y adjudicación
  viven en la misma transacción: una toma rechazada no deja ni asignación ni
  historial a medias.

---

## 4. Por qué `409` para todo lo no tomable

Una sola respuesta —mismo código y mismo cuerpo— para orden inexistente, ya
tomada, de otro técnico, en otro estado o de otro tipo:

```json
{"detail": "La orden ya no está disponible."}
```

**Que sean indistinguibles es el punto.** Es el mismo principio de no
enumeración que el 404 uniforme del detalle: si «no existe» respondiera distinto
de «ya la tomó otro», el técnico podría descubrir qué ids de orden existen
probándolos uno por uno. Fijado por
`test_unknown_order_is_indistinguishable_from_an_unavailable_one`, que compara
código **y** cuerpo.

**Por qué `409` y no `404`:** la pregunta del cliente no es «¿existe esta
orden?» sino «¿puedo tomarla?», y para todos esos casos la respuesta es que ya
no está disponible. El mensaje dice exactamente eso y no cuenta de más.

El `400` existe solo como red de seguridad: las condiciones que
`assign_technician()` valida —técnico activo con rol técnico, orden en estado
asignable— ya las garantizan el permiso de canal y el filtro de
disponibilidad. Se captura el `ValidationError` para que una regla de dominio
futura se manifieste con su mensaje en español y no como un `500`.

---

## 5. Seguridad: cuatro capas, en este orden

1. **`IsActiveTechnician`** — ¿puedes operar en este canal? Se reevalúa en cada
   petición: el token no caduca, así que un cambio de rol posterior al login
   corta el acceso en la siguiente petición
   (`test_technician_moved_to_another_role_loses_the_claim`).
2. **`CanClaimWorkOrder`** — ¿puedes ejecutar *esta acción*? (§6.)
3. **`available_work_orders()` bajo bloqueo** — ¿está tomable *ahora*?
4. **El dominio** — ¿admite la transición?

Las dos primeras se evalúan **antes** de resolver la orden. Si el orden fuera el
inverso, quien no puede tomar recibiría `409` en un id existente y `403` en el
resto, y esa diferencia le diría qué órdenes existen. Con este orden recibe
`403` para cualquier id (`test_permission_is_evaluated_before_the_object`).

Cada prueba de rechazo comprueba además que la orden **sigue disponible**: un
`401` o un `403` que ya hubiera tocado la orden sería peor que un `200` mal
dado.

### 5.1 La toma no hereda de `TechnicianWorkOrderObjectMixin`

Corrección de lo que anticipaba
[`api_technician_work_orders.md`](api_technician_work_orders.md) §4. Ese mixin
filtra por `assigned_technician = request.user`, y **una orden tomable no tiene
técnico asignado**: heredarlo daría un universo vacío y ninguna orden podría
tomarse nunca. La toma cuelga de `TechnicianChannelMixin` —permisos y
relaciones, sin filtro de dueño— y resuelve su objeto contra
`available_work_orders()`.

Lo que sí se comparte con el detalle son las relaciones de la ficha, ahora
declaradas una sola vez en `TechnicianChannelMixin.OBJECT_RELATIONS` y
consumidas por los dos. Escritas dos veces, un campo nuevo en el detalle
costaría una consulta extra en la toma sin que nadie lo note.

### 5.2 Trazabilidad: `assigned_by` es el propio técnico

En el despacho web un supervisor elige a quién le toca; en la toma el técnico se
adjudica trabajo sin dueño. Por eso `technician` y `assigned_by` son el mismo
usuario, y así queda en `WorkOrderAssignment`: **una asignación donde ambos
coinciden es, en el historial, una orden tomada desde la app.** Se registra en
lugar de dejarse nulo, que se leería como un dato faltante.

---

## 6. Permiso de la toma — bloqueo B3, **sigue abierto**

Hoy la toma exige el permiso de canal y **ningún permiso Django adicional**
(`CLAIM_PERMISSION = None` en
[`apps/work_orders/api/permissions.py`](../apps/work_orders/api/permissions.py)).
No es un olvido: es lo único que puede afirmarse sin inventar una regla, y la
propuesta del día 1 necesita revisarse porque **tiene un efecto lateral que no
se había medido**:

- **Reutilizar `assign_workorder`** (propuesta del día 1) es reutilizar el
  permiso que gobierna la bandeja de despacho web
  (`WorkOrderAssignView.permission_required`, `views.py:148`) y que decide si
  se pinta la acción «Asignar» en las plantillas. Concederlo al grupo Técnico
  para habilitar la toma le daría además la potestad de asignar **cualquier**
  orden a **cualquier** técnico desde la web. La toma es lo contrario: el
  técnico solo toma para sí mismo y solo del pool sin dueño. Y `models.py:610`
  documenta la intención opuesta —que la app del técnico pueda recibir
  `start_workorder` «sin arrastrar `assign_workorder`»—, así que reutilizarlo
  contradice el criterio con el que se separaron los permisos.
- **Crear `claim_workorder`** exige migración de `Meta.permissions`, que por
  regla del sprint requiere aprobación, y hasta que alguien lo conceda dejaría
  la toma en `403` para todos los técnicos.

Mientras negocio decida, la autorización real no queda en el aire: la sostienen
el permiso de canal (solo un técnico activo entra), el filtro de disponibilidad
(solo se toma lo que no tiene dueño) y el hecho de que el técnico sale de
`request.user`.

**Cerrar B3 es cambiar esa línea** por el nombre del permiso: no hay que tocar
la vista, ni la ruta, ni el serializador. `test_functional_permission_gates_the_claim`
fija ese cableado — simula el permiso decidido y comprueba que sin él el
técnico recibe `403` antes de que la orden se resuelva, y que con él concedido
la toma vuelve a funcionar.

---

## 7. Bloqueos abiertos

- **B3 — Permiso funcional de la toma.** §6. Decisión pendiente con la
  evidencia nueva sobre el efecto lateral de `assign_workorder`.
- **B9 (nuevo) — ¿Debe la toma ser idempotente para el mismo técnico?** Hoy un
  segundo POST del propio dueño recibe `409`, igual que si la orden fuera de
  otro. Es correcto y seguro —no reasigna ni duplica la traza— pero en campo el
  caso frecuente no es el doble toque sino **el reintento por red
  intermitente**: la toma llegó, la respuesta se perdió, y el técnico ve un
  error sobre una orden que ya es suya.
  **Recuperación para la app, mientras B9 no se cierre:** ante un `409`,
  recargar `GET /api/technicians/work-orders/` — si la orden aparece ahí, la
  toma sí se aplicó. Devolver la ficha con `200` en ese caso es un cambio de
  contrato y no se implementa sin decisión.
- **B6 — Ficha previa a la toma.** El técnico decide con `branch`, `zone` y
  `district`. Confirmar si basta.
- **B7 — Paginación.** Sin cambios; no afecta a este endpoint.
- **B4 — Nombre del endpoint.** Cerrado: `claim/`, confirmado en la
  coordinación del 02/09.

---

## 8. Pruebas

`apps/work_orders/tests/test_api_claim.py` — 28 pruebas en 7 bloques:

| Bloque | Cubre |
|---|---|
| `ClaimSuccessTests` | Toma efectiva, asignación única con `assigned_by`, historial PENDING → ASSIGNED, `remarks`, cuerpo vacío, forma de la ficha |
| `ClaimChannelInvariantTests` | Lo listado se toma, lo tomado sale de la bandeja, el detalle se abre después de tomar |
| `ClaimUnavailableOrderTests` | Robo de orden ajena, segunda toma, no enumeración, `SYSTEM`, otros tipos, `DEMO-INSTALLATION`, estados no PENDING |
| `ClaimConcurrencyTests` | Bloqueo pedido y limitado a `self`, resultado de la carrera, nada a medias tras un rechazo |
| `ClaimBranchScopeTests` | Toma fuera de sede, técnico sin sede |
| `ClaimPermissionTests` | Sin token, sin rol, cambio de rol, permiso antes del objeto, cableado de B3 |
| `ClaimContractTests` | Solo `POST`, y el cuerpo no decide técnico ni estado |

---

## 9. Qué NO se tocó

- **`apps/work_orders/models.py` y `services.py`**: idénticos. Ni un estado
  nuevo, ni un manager, ni una migración. La toma no modifica
  `assign_technician()`; el bloqueo lo aplica el canal.
- **`api/queries.py`**: la definición de «disponible» se consume sin cambiarla.
  Ese era el objetivo de escribirla como función parametrizable el día 3.
- **La capa web**: bandeja de despacho, asignación e inicio de atención siguen
  igual. El canal API es aditivo.
- **`config/urls.py`**: sin cambios. La ruta nueva entra por
  `apps/work_orders/api/urls.py`, que ya estaba incluido.
- **El inicio de atención (`start/`)**: sigue fuera de alcance. La orden tomada
  queda en `ASSIGNED`; iniciar la atención se reintegra cuando entre en
  alcance.
