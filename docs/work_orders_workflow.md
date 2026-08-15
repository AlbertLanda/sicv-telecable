# Workflow operativo del módulo de órdenes

Documentación técnica del módulo `apps/work_orders/` del nuevo SICV
(Telecable / Fiber The Andes).

Cubre el workflow operativo: estados, matriz de transiciones, asignación de
técnicos, inicio de atención, reprogramación e integración con los resultados
operativos.

---

## 1. Estados del workflow

El estado del workflow (`WorkOrder.status`) responde a **dónde está la orden
en su ciclo de atención**. Es una dimensión distinta del **resultado operativo**
(`WorkOrder.result`), que responde a **cómo terminó la atención**. Ver §8.

| Código | Nombre visible | Uso esperado |
|---|---|---|
| `PENDING` | Pendiente | Orden creada y aún sin ejecución. |
| `ASSIGNED` | Asignada | Orden asignada a un técnico responsable. |
| `DERIVED` | Derivada | Orden derivada a otro nivel o área de atención. |
| `IN_PROGRESS` | En atención | La atención fue iniciada. |
| `ATTENDED` | Atendida | La atención operativa terminó. |
| `REPROGRAMMED` | Reprogramada | La atención fue movida a otra fecha/hora. |
| `REJECTED` | Rechazada | La orden fue rechazada según regla operativa. |
| `NOT_FEASIBLE` | No factible | La ejecución no fue técnicamente factible. |
| `CANCELLED` | Anulada | La orden fue anulada. |

**Flujo principal de referencia:**

```
PENDING → ASSIGNED → IN_PROGRESS → ATTENDED
```

**Rutas alternativas:** `DERIVED`, `REPROGRAMMED`, `REJECTED`, `NOT_FEASIBLE`
y `CANCELLED`, según la matriz de la sección siguiente.

---

## 2. Matriz de transiciones permitidas

Definida en `WorkOrder.ALLOWED_TRANSITIONS`. Es la **única** fuente de verdad
sobre qué movimientos son válidos.

| Estado actual | Estados permitidos |
|---|---|
| `PENDING` | `ASSIGNED`, `DERIVED`, `CANCELLED` |
| `ASSIGNED` | `IN_PROGRESS`, `REPROGRAMMED`, `REJECTED`, `NOT_FEASIBLE`, `CANCELLED` |
| `DERIVED` | `ASSIGNED`, `IN_PROGRESS`, `CANCELLED` |
| `IN_PROGRESS` | `ATTENDED`, `REPROGRAMMED`, `NOT_FEASIBLE` |
| `REPROGRAMMED` | `ASSIGNED`, `CANCELLED` |
| `ATTENDED` | — (terminal) |
| `REJECTED` | — (terminal) |
| `NOT_FEASIBLE` | — (terminal) |
| `CANCELLED` | — (terminal) |

### Estados terminales

`ATTENDED`, `REJECTED`, `NOT_FEASIBLE` y `CANCELLED` están listados en
`WorkOrder.TERMINAL_STATUSES`. Una orden en cualquiera de ellos:

- no admite ninguna transición de salida,
- no admite asignación ni reasignación de técnico,
- no admite inicio de atención,
- no admite reprogramación.

La propiedad `WorkOrder.is_closed` devuelve `True` en estos estados.

### Mecanismo oficial de cambio de estado

```python
order.change_status(new_status, user=None, remarks="")
```

Es el **único** camino autorizado para modificar `status`. Ninguna otra parte
del código debe asignar `order.status` directamente.

Comportamiento:

1. Valida que `new_status` exista en `WorkOrder.Status`.
2. Si el estado nuevo es igual al actual, devuelve `False` sin escribir nada
   (operación nula, no ensucia el historial).
3. Valida la transición contra `ALLOWED_TRANSITIONS`. Si no está permitida,
   lanza `ValidationError` **sin modificar la orden ni el historial**.
4. Persiste el nuevo estado y crea un registro en `WorkOrderStatusHistory`.
5. Al entrar a `ATTENDED`, sella `attended_at` automáticamente.

Todo el método corre dentro de `transaction.atomic`, de modo que un fallo
intermedio no deja la orden y su historial desincronizados.

### Trazabilidad de estados

Cada transición válida genera un `WorkOrderStatusHistory` con:

| Campo | Contenido |
|---|---|
| `work_order` | Orden afectada |
| `previous_status` | Estado de origen |
| `new_status` | Estado de destino |
| `changed_by` | Usuario responsable del cambio |
| `remarks` | Observación libre |
| `changed_at` | Fecha y hora automática |

El historial es de **solo lectura**: no es editable desde el admin y solo se
escribe a través de `change_status()`.

---

## 3. Asignación y reasignación de técnicos

```python
order.assign_technician(technician=usuario, assigned_by=responsable, remarks="...")
```

### Validaciones

| Regla | Efecto si falla |
|---|---|
| El técnico debe existir (no `None`) | `ValidationError` |
| El usuario debe tener `role == TECHNICIAN` | `ValidationError` |
| El usuario debe estar activo (`is_active`) | `ValidationError` |
| La orden no debe estar anulada ni cerrada operativamente | `ValidationError` |

Los estados que admiten asignación están en `WorkOrder.ASSIGNABLE_STATUSES`:
`PENDING`, `ASSIGNED`, `DERIVED` y `REPROGRAMMED`.

### Efectos

1. Cierra la asignación vigente poniéndole `unassigned_at = now()`. **El
   registro anterior nunca se borra ni se sobrescribe.**
2. Crea un nuevo `WorkOrderAssignment` para el técnico entrante.
3. Actualiza `WorkOrder.assigned_technician`.
4. Si la orden no estaba ya en `ASSIGNED`, la mueve a ese estado usando
   `change_status()`, lo que además deja traza en el historial de estados.

En todo momento existe **como máximo una asignación vigente** (aquella con
`unassigned_at IS NULL`). La propiedad `WorkOrderAssignment.is_active` lo
expone directamente.

### Modelo `WorkOrderAssignment`

| Campo | Descripción |
|---|---|
| `work_order` | Orden asignada |
| `technician` | Técnico responsable |
| `assigned_by` | Usuario que ejecutó la asignación |
| `assigned_at` | Momento de la asignación |
| `unassigned_at` | Momento del cierre (nulo si está vigente) |
| `remarks` | Observación de la asignación |

---

## 4. Inicio de atención

```python
order.start_attention(user=tecnico, remarks="...")
```

### Validaciones

- La orden debe estar en `ASSIGNED` o `DERIVED`
  (`WorkOrder.STARTABLE_STATUSES`).
- La orden debe tener un técnico asignado.

### Efectos

1. Registra `started_at = timezone.now()`.
2. Cambia el estado a `IN_PROGRESS` mediante `change_status()`, dejando
   trazabilidad del usuario responsable y la observación.

`started_at` (inicio real) es distinto de `scheduled_at` (fecha programada) y
de `attended_at` (cierre de la atención). Los tres coexisten para permitir
medir puntualidad y duración de la atención.

---

## 5. Reprogramación

```python
order.reprogram(new_schedule=nueva_fecha, user=responsable, reason="...")
```

### Validaciones

- Debe indicarse una nueva fecha.
- La orden debe poder transicionar a `REPROGRAMMED` (es decir, estar en
  `ASSIGNED` o `IN_PROGRESS`).
- La nueva fecha debe ser posterior a la fecha programada vigente.

### Efectos

1. Crea un `WorkOrderReprogramming` guardando la fecha anterior.
2. Actualiza `WorkOrder.scheduled_at` con la nueva fecha.
3. Cambia el estado a `REPROGRAMMED` mediante `change_status()`.

**La fecha anterior nunca se pierde**: queda en `previous_schedule`. Las
reprogramaciones sucesivas encadenan su histórico completo.

Para retomar la atención, la orden debe volver a `ASSIGNED` (por ejemplo con
una nueva llamada a `assign_technician()`).

### Modelo `WorkOrderReprogramming`

| Campo | Descripción |
|---|---|
| `work_order` | Orden reprogramada |
| `previous_schedule` | Fecha programada anterior |
| `new_schedule` | Nueva fecha programada |
| `reason` | Motivo de la reprogramación |
| `created_by` | Usuario que la registró |
| `created_at` | Fecha de registro automática |

---

## 6. Integración con `apply_order_result()`

Las reglas de negocio sobre la suscripción viven **exclusivamente** en
`apps/work_orders/services.py`. Ni los modelos, ni el admin, ni las pruebas
replican esas reglas: solo las consumen.

### `apply_order_result(order)`

Aplica los efectos del resultado de la orden sobre la `Subscription`.

Valida que la orden tenga resultado y que el resultado pertenezca al tipo de
orden. Luego enruta por el **código estable** del tipo de orden hacia la regla
correspondiente. Corre dentro de `transaction.atomic`.

### `attend_order(order, result, user=None, remarks="")`

Punto de integración entre el workflow y los resultados operativos. En una
sola operación atómica:

1. Valida que el resultado corresponda al tipo de orden.
2. Registra `order.result`.
3. Mueve la orden a `ATTENDED` mediante `change_status()` (lo que exige que
   la orden venga de `IN_PROGRESS` y sella `attended_at`).
4. Delega en `apply_order_result(order)`.

Esta función **no contiene reglas de negocio propias**: solo orquesta.

---

## 7. Reglas especiales por tipo de orden

Las reglas se identifican mediante **códigos estables de catálogo**
(`INSTALLATION`, `CUT`, `RECONNECTION`, `TRANSFER`, `TEMPORARY`, `DEFINITIVE`,
`INTERNAL`, `EXTERNAL`, `SUCCESSFUL`), nunca por nombres visibles. Renombrar
un catálogo desde el admin no debe alterar el comportamiento del sistema.

| Caso | Resultado | Efecto sobre `Subscription` |
|---|---|---|
| Instalación exitosa | `SUCCESSFUL` | `PRESALE → ACTIVE`, registra `installation_date` |
| Corte temporal exitoso | `SUCCESSFUL` | `→ SUSPENDED`, registra `cut_date` |
| Corte definitivo exitoso | `SUCCESSFUL` | `→ CANCELLED`, registra `cut_date` |
| Reconexión exitosa | `SUCCESSFUL` | `→ ACTIVE`, registra `reconnection_date` |
| Traslado interno exitoso | `SUCCESSFUL` | No modifica la dirección |
| Traslado externo exitoso | `SUCCESSFUL` | Actualiza `Subscription.address` con la nueva dirección |

### Corte

Requiere subtipo (`TEMPORARY` o `DEFINITIVE`) y un `CutDetail` asociado, que
se revalida con `full_clean()` antes de aplicar el efecto:

- **Temporal:** exige `expected_return_date` y prohíbe `competitor`.
- **Definitivo:** prohíbe `expected_return_date`.

### Traslado

Requiere subtipo (`INTERNAL` o `EXTERNAL`) y un `TransferDetail` asociado,
también revalidado antes de aplicar:

- **Interno:** exige `previous_location` y `new_location`, y prohíbe
  `new_address`. La dirección del servicio **no cambia**.
- **Externo:** exige `previous_address` (que debe coincidir con la dirección
  actual de la suscripción) y `new_address` distinta. Ambas deben pertenecer
  al cliente de la suscripción.

### Resultados no exitosos

Un resultado distinto de `SUCCESSFUL` **no produce ningún efecto** sobre la
suscripción. La orden queda `ATTENDED` de todos modos: fue atendida, pero no
debe contabilizarse como ejecución efectiva.

---

## 8. Separación entre estado y resultado

La orden mantiene seis dimensiones analíticas independientes:

| Dimensión | Campo | Catálogo |
|---|---|---|
| Tipo de orden | `order_type` | `OrderType` |
| Subtipo | `subtype` | `OrderSubtype` |
| Motivo | `reason` | `OrderReason` |
| Causa | `cause` | `OrderCause` |
| Resultado | `result` | `OrderResult` |
| Estado del workflow | `status` | `WorkOrder.Status` |

Los cinco catálogos cuelgan de `OrderType`, y `WorkOrder.clean()` valida que
subtipo, motivo, causa y resultado pertenezcan al tipo de la orden.

**Ejemplo:** una orden de instalación puede estar `ATTENDED` con resultado
`NOT_FEASIBLE`. Fue atendida (dimensión de workflow), pero no cuenta como
instalación efectiva (dimensión de resultado). Confundir ambas dimensiones
distorsionaría los indicadores operativos.

---

## 9. Administración (Django Admin)

`WorkOrderAdmin` expone número de orden, cliente, suscripción, tipo, subtipo,
motivo, causa, resultado, sede, zona, técnico, estado, prioridad, tipo de
atención y fechas.

- **Filtros:** estado, sede, zona, técnico, tipo, subtipo, prioridad y tipo de
  atención.
- **Búsqueda:** número de orden, detalle, y DNI, código y nombre del cliente
  a través de `subscription__customer__…`.
- **Historiales:** estados, asignaciones y reprogramaciones se muestran como
  inlines de **solo lectura**, sin permiso de alta, edición ni borrado.

El historial de estados también está bloqueado en su propio `ModelAdmin`
(`has_add_permission`, `has_change_permission` y `has_delete_permission`
devuelven `False`): solo `change_status()` puede escribirlo.

---

## 10. Pruebas implementadas

Paquete `apps/work_orders/tests/`, separado por módulos. Ejecutar con:

```bash
python manage.py test apps.work_orders
```

`base.py` define `WorkOrderTestCase`, que arma el escenario común (sede, zona,
cliente con dos direcciones, suscripción, usuarios por rol y catálogos con
códigos estables) y expone los helpers `create_order()`,
`create_assigned_order()` y `create_order_in_progress()`.

### `test_catalogs.py` — catálogos y validación cruzada

| # | Prueba |
|---|---|
| 1 | Creación de `OrderType` |
| 2 | Creación de `OrderReason` |
| 3 | Creación de `WorkOrder` con sus valores por defecto |
| 4 | Motivo de otro tipo → `ValidationError` |
| 5 | Causa de otro tipo → `ValidationError` |
| 6 | Resultado de otro tipo → `ValidationError` |
| + | Subtipo de otro tipo → `ValidationError` |

### `test_assignment.py` — asignación y reasignación

| # | Prueba |
|---|---|
| 7 | Asignación de usuario `TECHNICIAN` → permitida |
| 8 | Asignación de usuario `ATC` → `ValidationError`, sin historial |
| 15 | La asignación crea `WorkOrderAssignment` con todos sus datos |
| 16 | La reasignación conserva el técnico anterior con su `unassigned_at` |
| + | Técnico inactivo → `ValidationError` |
| + | Asignar a una orden anulada → `ValidationError` |
| + | Tras varias reasignaciones solo queda una asignación vigente |

### `test_transitions.py` — matriz de transiciones

| # | Prueba |
|---|---|
| 9 | `PENDING → ASSIGNED` permitido |
| 10 | `ASSIGNED → IN_PROGRESS` permitido |
| 11 | `IN_PROGRESS → ATTENDED` permitido, sella `attended_at` |
| 12 | `PENDING → ATTENDED` prohibido, sin tocar orden ni historial |
| 13 | `CANCELLED → IN_PROGRESS` prohibido, sin tocar orden ni historial |
| 14 | `change_status()` crea `WorkOrderStatusHistory` completo |
| + | El flujo principal deja las tres transiciones en orden |
| + | Los estados terminales no tienen salidas |
| + | Un estado inexistente es rechazado |
| + | Repetir el estado actual no crea historial |

### `test_workflow.py` — reprogramación e inicio de atención

| # | Prueba |
|---|---|
| 17 | La reprogramación conserva la fecha anterior |
| 18 | `start_attention()` registra `started_at` |
| + | Varias reprogramaciones encadenan el histórico |
| + | Reprogramar una orden cerrada → `ValidationError` |
| + | Reprogramar hacia atrás → `ValidationError` |
| + | El inicio de atención deja traza del usuario |
| + | Iniciar atención sin asignar → `ValidationError` |
| + | Iniciar atención en orden cerrada → `ValidationError` |

### `test_results.py` — resultados operativos

| # | Prueba |
|---|---|
| 19 | Instalación exitosa activa la suscripción |
| 20 | Corte temporal exitoso la suspende |
| 21 | Corte definitivo exitoso la cancela |
| 22 | Reconexión exitosa la activa |
| 23 | Traslado interno exitoso no cambia la dirección |
| 24 | Traslado externo exitoso cambia la dirección |
| + | Aplicar resultado sin resultado → `ValidationError` |
| + | Resultado de otro tipo de orden → `ValidationError` |
| + | Orden `ATTENDED` con resultado no factible no activa la suscripción |

---

## 11. Fuera del alcance de esta fase

No implementado todavía, por definición de la actividad:

- Liquidación digital del técnico.
- Materiales utilizados o retirados, y stock por técnico.
- Integración Krill.
- Galería / evidencias fotográficas.
- Validación NOC y validación de almacén.
- Cierre definitivo de la orden.
- Frontend / PWA de técnicos.
