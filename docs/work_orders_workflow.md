# Workflow operativo del módulo de órdenes

Documentación técnica del módulo `apps/work_orders/` del nuevo SICV
(Telecable / Fiber The Andes).

Cubre el workflow operativo: estados, matriz de transiciones, asignación de
técnicos, inicio de atención, reprogramación, integración con los resultados
operativos y la liquidación técnica posterior a la atención.

La **revisión** de esa liquidación (validación única, corrección controlada,
permiso del validador y trazabilidad) está documentada aparte en
[`liquidation_review.md`](liquidation_review.md).

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
| `LIQUIDATED` | Liquidada | La atención fue liquidada técnicamente. Ver §9. |
| `REPROGRAMMED` | Reprogramada | La atención fue movida a otra fecha/hora. |
| `REJECTED` | Rechazada | La orden fue rechazada según regla operativa. |
| `NOT_FEASIBLE` | No factible | La ejecución no fue técnicamente factible. |
| `CANCELLED` | Anulada | La orden fue anulada. |

**Flujo principal de referencia:**

```
PENDING → ASSIGNED → IN_PROGRESS → ATTENDED → LIQUIDATED
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
| `ATTENDED` | `LIQUIDATED` |
| `LIQUIDATED` | — (final) |
| `REJECTED` | — (final) |
| `NOT_FEASIBLE` | — (final) |
| `CANCELLED` | — (final) |

### Estados terminales y estados finales

Son dos conceptos distintos:

- **`WorkOrder.TERMINAL_STATUSES`** (`ATTENDED`, `LIQUIDATED`, `REJECTED`,
  `NOT_FEASIBLE`, `CANCELLED`): la orden está **cerrada operativamente**. No
  admite asignación ni reasignación de técnico, ni inicio de atención, ni
  reprogramación. La propiedad `WorkOrder.is_closed` devuelve `True`.
- **`WorkOrder.FINAL_STATUSES`** (`LIQUIDATED`, `REJECTED`, `NOT_FEASIBLE`,
  `CANCELLED`): además **no admiten ninguna transición de salida**.

`ATTENDED` es terminal pero no final: su única salida es la liquidación
técnica. Ningún estado terminal puede devolver la orden a
`WorkOrder.ACTIVE_STATUSES` (`PENDING`, `ASSIGNED`, `DERIVED`, `IN_PROGRESS`,
`REPROGRAMMED`); es decir, **liquidar no reabre la atención de campo**.

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

## 9. Liquidación técnica

### Atender no es liquidar

Son dos hechos distintos y deliberadamente separados:

| | Atender | Liquidar |
|---|---|---|
| Pregunta que responde | ¿Terminó la atención en campo? | ¿Qué se ejecutó exactamente? |
| Estado resultante | `ATTENDED` | `LIQUIDATED` |
| Registro | `WorkOrder.result` + `attended_at` | `WorkOrderLiquidation` |
| Momento | Al cerrar la visita | Después, con el detalle técnico a la mano |

La cadena completa prevista es **atender → liquidar → validar → cerrar**.

La etapa de **validación** ya está implementada como un ciclo de revisión
propio de la liquidación, con validación única y una sola oportunidad de
corrección: ver [`liquidation_review.md`](liquidation_review.md). La decisión
funcional vigente descartó la doble validación NOC + almacén.

El **cierre definitivo** sigue sin implementarse: `LIQUIDATED` no equivale a
cerrada, y validar la liquidación **no** cambia el estado de la orden.

### Modelo `WorkOrderLiquidation`

Relación `OneToOne` con `WorkOrder`: **una orden tiene como máximo una
liquidación vigente**, garantizado por la base de datos y revalidado por el
servicio antes de escribir.

| Campo | Descripción |
|---|---|
| `work_order` | Orden liquidada (`OneToOneField`) |
| `liquidated_by` | Usuario responsable de la liquidación |
| `liquidated_at` | Fecha y hora real de la liquidación |
| `resolution_detail` | Detalle de la solución o trabajo ejecutado (**obligatorio**) |
| `technical_notes` | Observaciones técnicas de la atención |
| `network_element` | Elemento de red: NAP, caja o mufa |
| `network_port` | Puerto utilizado |
| `equipment_serial` | Serie del equipo instalado o retirado |
| `signal_level_dbm` | Nivel de señal medido (dBm) |
| `cable_meters_used` | Metros de cable utilizados |
| `krill_reference` | Referencia Krill, **capturada a mano** |
| `created_at` / `updated_at` | Trazabilidad del registro |

Los datos técnicos viven **cada uno en su propio campo**, no mezclados en
texto libre, para poder medirse después sin parsear. Los campos son genéricos
a propósito: el mismo modelo sirve para instalación, avería, corte, reconexión
y traslado.

**Krill:** `krill_reference` queda preparado, pero en esta fase **no se
consume ninguna API externa**. La sincronización real (traer el elemento de
red, el puerto y la potencia óptica desde Krill en lugar de digitarlos) queda
pendiente.

### Servicio `liquidate_order()`

```python
liquidate_order(
    order,
    user,
    technical_notes="",
    resolution_detail="",
    items=None,
    remarks="",
    **technical_data,
)
```

Es el **único** camino autorizado para liquidar. Valida, en este orden:

| Regla | Efecto si falla |
|---|---|
| La orden debe estar en `ATTENDED` | `ValidationError` |
| La orden no debe estar ya liquidada | `ValidationError` |
| Debe indicarse un usuario responsable | `ValidationError` |
| El usuario responsable debe estar activo | `ValidationError` |
| `resolution_detail` no puede estar vacío | `ValidationError` |
| Los datos técnicos deben pertenecer a `LIQUIDATION_TECHNICAL_FIELDS` | `ValidationError` |

Efectos, **todos dentro de una única `transaction.atomic`**:

1. Crea la `WorkOrderLiquidation` (validada con `full_clean()`).
2. Crea los `WorkOrderLiquidationItem` recibidos en `items`, validando cada uno.
3. Mueve la orden a `LIQUIDATED` mediante `change_status()`, lo que deja
   registro en `WorkOrderStatusHistory`.

`order.status` **nunca** se modifica con `save()` directo: la transición pasa
por el mecanismo oficial para conservar el historial. Si cualquier paso falla
—por ejemplo un ítem con cantidad inválida— no queda liquidación parcial: la
orden se mantiene en `ATTENDED` y no se escribe historial.

La propiedad `WorkOrder.is_liquidated` consulta la **existencia del registro**,
no el estado: liquidar es un hecho documentado por `WorkOrderLiquidation`, y
`LIQUIDATED` es su consecuencia.

### Materiales y equipos declarados

Modelo `WorkOrderLiquidationItem`, con `ForeignKey` a la liquidación
(`related_name="items"`): **múltiples ítems por liquidación**.

| Campo | Descripción |
|---|---|
| `movement_type` | `USED` (utilizado) o `REMOVED` (retirado) |
| `material_code` | Código o referencia del material |
| `material_name` | Nombre del material o equipo |
| `quantity` | Cantidad declarada (debe ser mayor que cero) |
| `unit_of_measure` | `UNIT`, `METER`, `ROLL` o `SET` |
| `remarks` | Observación del ítem |

> **La declaración es informativa y trazable.** En esta fase **no descuenta
> stock, no genera kardex y no afecta el stock por técnico ni el de almacén.**
> El ítem no referencia ninguna entidad de inventario, precisamente para que
> no pueda moverlo.

### Evidencias de la atención

Modelo `WorkOrderEvidence`.

| Campo | Descripción |
|---|---|
| `work_order` | Orden a la que pertenece (obligatorio) |
| `liquidation` | Liquidación que respalda, si corresponde (opcional) |
| `file` | Archivo o fotografía |
| `description` | Descripción de la evidencia |
| `uploaded_by` | Usuario que la adjuntó |
| `created_at` | Fecha y hora de carga |

`clean()` impide vincular una evidencia a la liquidación de **otra** orden.

**Almacenamiento:** en desarrollo se usa el storage local de Django
(`MEDIA_ROOT = BASE_DIR / 'media'`, `MEDIA_URL = 'media/'`), servido por
`config/urls.py` solo cuando `DEBUG` está activo. La ruta la resuelve
`evidence_upload_path()`, que agrupa por orden:

```
media/work_orders/<order_number>/evidences/<archivo>
```

El modelo depende únicamente de la API de storage de Django, de modo que
migrar a Azure Blob Storage en producción sea **un cambio de configuración**,
no de código. Azure **no** se configura en esta fase.

---

## 10. Administración (Django Admin)

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

### Liquidación en el admin

- El changelist de órdenes muestra tres columnas nuevas: **Liquidada** (sí/no),
  **Liquidado por** y **Fecha de liquidación**, resueltas con
  `select_related("liquidation", "liquidation__liquidated_by")` para no
  disparar una consulta por fila.
- La liquidación y sus evidencias aparecen como **inlines de solo lectura** en
  la ficha de la orden.
- `WorkOrderLiquidationAdmin` expone los datos técnicos completos, con los
  materiales declarados y las evidencias como inlines de solo lectura. No
  permite alta ni edición: liquidar pasa por `liquidate_order()`.
- **`status` sigue siendo de solo lectura en `WorkOrderAdmin`**, de modo que
  nadie pueda marcar `LIQUIDATED` a mano y saltarse el servicio (lo que
  dejaría una orden en estado liquidado sin registro de liquidación).

---

## 11. Pruebas implementadas

Paquete `apps/work_orders/tests/`, separado por módulos. Ejecutar con:

```bash
python manage.py test apps.work_orders
```

`base.py` define `WorkOrderTestCase`, que arma el escenario común (sede, zona,
cliente con dos direcciones, suscripción, usuarios por rol y catálogos con
códigos estables) y expone los helpers `create_order()`,
`create_assigned_order()`, `create_order_in_progress()` y
`create_attended_order()`.

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
| + | Los estados finales no tienen salidas |
| + | Ningún estado terminal devuelve la orden a la operación |
| + | Un estado inexistente es rechazado |
| + | Repetir el estado actual no crea historial |

> La prueba «los estados terminales no tienen salidas» se dividió en dos al
> abrirse `ATTENDED → LIQUIDATED`: `FINAL_STATUSES` conserva la regla original
> y una prueba nueva verifica que ningún estado terminal pueda volver a
> `ACTIVE_STATUSES`.

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

### `test_liquidation.py` — liquidación técnica

26 pruebas nuevas, agrupadas en cuatro clases.

**`WorkOrderLiquidationTests`** — servicio `liquidate_order()`

| # | Prueba |
|---|---|
| 1 | Se crea una liquidación válida para una orden `ATTENDED` |
| 2 | `ATTENDED → LIQUIDATED` se permite |
| 3 | Liquidar desde `PENDING` → `ValidationError` |
| 4 | Liquidar desde `ASSIGNED` → `ValidationError` |
| 5 | Liquidar desde `IN_PROGRESS` → `ValidationError` |
| 6 | Una orden ya liquidada no puede liquidarse de nuevo |
| 7 | La liquidación registra `liquidated_by` |
| 8 | La liquidación registra `liquidated_at` |
| 9 | El cambio a `LIQUIDATED` crea `WorkOrderStatusHistory` |
| 10 | Un error no deja liquidación parcial ni historial |
| 14 | Un usuario inactivo no puede liquidar |
| + | Sin usuario responsable → `ValidationError` |
| + | `resolution_detail` vacío → `ValidationError` |
| + | Los datos de red se guardan en campos separados |
| + | Un campo técnico desconocido es rechazado |
| + | `is_liquidated` depende del registro, no del estado |

**`WorkOrderLiquidationTransitionTests`** — `LIQUIDATED` como estado posterior

| # | Prueba |
|---|---|
| 15 | Toda transición desde `LIQUIDATED` queda bloqueada |
| + | Una orden liquidada no admite asignación ni inicio de atención |
| + | Liquidar no equivale a validar ni cerrar |

**`WorkOrderLiquidationItemTests`** — materiales declarados

| # | Prueba |
|---|---|
| 11 | Se pueden declarar múltiples materiales/equipos |
| 12 | Un ítem conserva tipo, cantidad y observación |
| + | La declaración no toca stock ni inventario |
| + | Una cantidad no positiva es rechazada |

**`WorkOrderEvidenceTests`** — evidencias (`MEDIA_ROOT` temporal)

| # | Prueba |
|---|---|
| 13 | La evidencia queda vinculada a su orden y liquidación |
| + | Una liquidación de otra orden es rechazada |
| + | El archivo se guarda bajo la carpeta de la orden |

---

## 12. Fuera del alcance de esta fase

No implementado todavía, por definición de la actividad:

- Doble validación NOC + almacén (descartada: la revisión es única, ver
  [`liquidation_review.md`](liquidation_review.md)).
- Cierre definitivo de la orden y `WorkOrder.Status.CLOSED`.
- Descuento o devolución real de inventario, kardex y stock por técnico.
- Integración Krill (`krill_reference` queda preparado, sin consumir la API).
- Azure Blob Storage (en desarrollo se usa `MEDIA_ROOT` local).
- Frontend / PWA de técnicos.
- Notificaciones WhatsApp.
