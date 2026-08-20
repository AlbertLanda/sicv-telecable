# Creación de órdenes de trabajo

Documentación técnica del registro de órdenes en `apps/work_orders/`
(SICV — Telecable / Fiber The Andes).

Cubre el servicio único de creación, las validaciones previas a persistir, el
correlativo transaccional del número de OT y el comportamiento esperado bajo
concurrencia.

El ciclo posterior (asignación, atención, resultados y liquidación) está en
[`work_orders_workflow.md`](work_orders_workflow.md); la revisión de la
liquidación, en [`liquidation_review.md`](liquidation_review.md).

---

## 1. Punto de entrada único

```python
from apps.work_orders.services import create_work_order

order = create_work_order(
    subscription=subscription,
    order_type=installation_type,
    created_by=request.user,
    reason=installation_reason,
    detail="Instalación de cliente nuevo.",
)
```

`create_work_order()` es el **único** camino legítimo para registrar una OT.
Vistas, API e interfaz deben consumirlo; ninguna capa fuera del servicio debe
llamar a `WorkOrder.objects.create(...)`.

Motivo: la creación no es un `INSERT`. Implica validar reglas de negocio
cruzadas entre suscripción, cliente, sede, zona y catálogos, y reservar un
correlativo compartido por todos los usuarios de ATC. Repartir esa lógica
entre vistas garantiza que una de ellas se salte una regla.

### Firma

Todos los argumentos son **keyword-only**, para que ninguna llamada dependa
del orden posicional:

| Argumento | Obligatorio | Descripción |
|---|---|---|
| `subscription` | Sí | Suscripción sobre la que se registra el trabajo |
| `order_type` | Sí | `OrderType` activo |
| `created_by` | Sí | Usuario ejecutor, activo |
| `customer` | No | Si se envía, debe coincidir con el titular de la suscripción |
| `branch` | No | Por defecto, la sede del cliente |
| `zone` | No | Por defecto, la zona de la dirección del servicio |
| `subtype` | No | Debe pertenecer al `order_type` |
| `reason` | No | Debe pertenecer al `order_type` |
| `cause` | No | Debe pertenecer al `order_type` |
| `attention_type` | No | Por defecto `FIELD` |
| `priority` | No | Por defecto `NORMAL` |
| `detail` | No | Detalle de la solicitud |
| `scheduled_at` | No | Fecha programada de atención |

### Argumentos deliberadamente NO aceptados

- **`order_number`** — lo emite el correlativo (§3). Aceptarlo desde fuera
  reabriría la puerta a números duplicados.
- **`created_by` desde datos del formulario** — se toma del usuario ejecutor.
  El parámetro existe porque el servicio no conoce el `request`, pero la capa
  que lo invoque debe pasar `request.user`, nunca un id enviado por el cliente.
- **`assigned_technician`** — la asignación es un flujo aparte
  (`order.assign_technician()`), fuera del alcance de esta actividad.
- **`status`** — toda OT nueva nace en `PENDING`.
- **`result`**, **`started_at`**, **`attended_at`** — pertenecen a la atención,
  no al registro.

---

## 2. Regla crítica: crear una OT no ejecuta el trabajo

| Momento | Estado de la suscripción | Interpretación |
|---|---|---|
| Venta / creación de OT | `PRESALE` | Existe la intención de venta; todavía no hay instalación física |
| Técnico inicia atención | `INSTALLATION` | La instalación se está ejecutando en campo |
| Instalación exitosa | `ACTIVE` | El servicio quedó instalado y operativo |

`create_work_order()` **no toca la suscripción**. Una OT de instalación creada
sobre una suscripción en `PRESALE` la deja en `PRESALE`; tampoco escribe
`installation_date`, `cut_date` ni `reconnection_date`.

Los movimientos de estado siguen ocurriendo donde ya estaban:

- `PRESALE → INSTALLATION` en `start_order_attention()`.
- `INSTALLATION → ACTIVE` en `apply_order_result()` con resultado
  `SUCCESSFUL`.

Esta actividad **no modificó** esa semántica: ni `start_order_attention()`,
ni `attend_order()`, ni `apply_order_result()`, ni la liquidación, corrección,
validación o evidencias fueron alterados.

---

## 3. Numeración de la OT

### 3.1 Formato

```
OT-2026-000001
```

`OT` + año de creación + correlativo de 6 dígitos con relleno de ceros.
Definido en `services.py` por `ORDER_NUMBER_PREFIX`, `ORDER_NUMBER_PADDING` y
`format_order_number()`.

### 3.2 Correlativo general de empresa, no por sede

Se evaluó un correlativo por sede (`HYO-2026-000001`, `JAU-2026-000001`,
`ORO-2026-000001`) y **se descartó**:

- La sede ya viaja como dato propio de la orden en `WorkOrder.branch`.
  Codificarla también en el número duplica el dato y abre la posibilidad de
  que ambos se contradigan.
- Un correlativo por sede exige una secuencia independiente y un bloqueo por
  cada sede, multiplicando los puntos donde puede fallar la unicidad.
- Un número único de empresa se comunica y se busca sin ambigüedad entre
  áreas.

Si en el futuro se decide numerar por sede, `WorkOrderSequence` admite la
extensión añadiendo `branch` a su clave única; el resto del mecanismo de
bloqueo no cambia.

### 3.3 Modelo `WorkOrderSequence`

Migración `0009_work_order_sequence`.

| Campo | Tipo | Descripción |
|---|---|---|
| `year` | `PositiveIntegerField` (único) | Año del correlativo |
| `last_number` | `PositiveIntegerField` | Último número emitido |
| `created_at` / `updated_at` | `DateTimeField` | Auditoría |

Una fila por año. El correlativo **vive en esta tabla, no en la tabla de
órdenes**: borrar la última OT no hace retroceder la numeración, y no existe
ninguna lectura del tipo `last_order.id + 1`.

### 3.4 `generate_order_number(year=None)`

```python
sequence = WorkOrderSequence.objects.select_for_update().get(year=year)
sequence.last_number += 1
sequence.save(update_fields=["last_number", "updated_at"])
return format_order_number(year, sequence.last_number)
```

Debe ejecutarse dentro de una transacción. `create_work_order()` está decorado
con `@transaction.atomic`, así que la reserva del número y el `INSERT` de la
orden comparten la misma transacción: **o quedan ambos, o no queda ninguno**.

La primera OT del año crea la fila del correlativo dentro de un
`transaction.atomic()` anidado (savepoint). Si otro proceso gana la carrera y
la crea primero, el `IntegrityError` se absorbe en el savepoint y se vuelve a
leer la fila con bloqueo, sin invalidar la transacción de la orden.

---

## 4. Concurrencia

Varios colaboradores de ATC registran órdenes en paralelo. El riesgo real es
que dos de ellos lean el mismo último número antes de que alguno confirme su
transacción y ambos intenten crear la misma OT.

### 4.1 Comportamiento en PostgreSQL (motor de producción)

`select_for_update()` emite `SELECT ... FOR UPDATE` y aplica un **bloqueo real
de fila**:

1. El usuario A abre la transacción y bloquea la fila del año 2026.
2. El usuario B pide el mismo año y **queda esperando** en el bloqueo.
3. A incrementa a `N`, inserta su orden y confirma. El bloqueo se libera.
4. B despierta, lee el valor ya actualizado, incrementa a `N + 1` y continúa.

Ningún número se reparte dos veces. La espera es la del incremento, no la de
toda la operación de negocio, porque las validaciones ocurren **antes** de
pedir el número.

### 4.2 Comportamiento en SQLite (desarrollo local)

SQLite ignora la cláusula `FOR UPDATE`: el bloqueo de fila no existe. En su
lugar serializa las escrituras a nivel de base de datos completa, lo que en la
práctica evita el solapamiento en desarrollo, pero **no es equivalente** al
bloqueo de PostgreSQL.

Por eso el diseño mantiene una segunda barrera independiente del motor:

### 4.3 Última barrera: unicidad de `order_number`

`WorkOrder.order_number` es `unique=True`. Si por cualquier causa —corrupción
del correlativo, intervención manual, un motor sin bloqueo real— se intentara
crear una OT con un número ya usado, la restricción lo impide y la transacción
completa se revierte. Nunca queda una segunda orden con número repetido.

### 4.4 Limitación conocida de las pruebas

Las pruebas corren sobre SQLite, que no permite simular bloqueos de fila
reales entre conexiones concurrentes. Lo que sí se verifica localmente:

- El correlativo nunca reutiliza un número dentro de una misma transacción.
- Borrar órdenes no hace retroceder la numeración.
- Un número duplicado no produce una segunda orden.
- Un fallo revierte la orden **y** el consumo del correlativo.

La verificación de bloqueo real de fila queda pendiente para el entorno
PostgreSQL.

---

## 5. Validaciones previas a persistir

Todas se ejecutan **antes** de reservar el número y de escribir la orden.
Todas levantan `ValidationError`.

### Usuario ejecutor

- Debe existir (`created_by` no nulo y con `pk`).
- Debe estar activo (`is_active`).

### Suscripción

- Debe existir y estar registrada.
- Debe estar habilitada (`is_active`).
- No puede estar en `CANCELLED` (`SUBSCRIPTION_BLOCKED_STATUSES`).
- Si se envía `customer`, debe ser el titular de la suscripción.

### Catálogos

- `OrderType` debe existir y estar activo.
- `OrderSubtype`, si se envía, debe pertenecer al `OrderType`.
- `OrderReason`, si se envía, debe pertenecer al `OrderType`.
- `OrderCause`, si se envía, debe pertenecer al `OrderType`.

### Sede y zona

- `branch` por defecto es la sede del cliente de la suscripción. Si se envía
  explícitamente, debe coincidir: no se registra trabajo de un cliente bajo la
  sede de otro.
- `zone` por defecto es la zona de la dirección del servicio
  (`subscription.address.zone`). Si se envía explícitamente, debe pertenecer a
  la sede de la orden.

### Persistencia

- `status = PENDING`, siempre.
- `created_by` = usuario ejecutor.
- `order.full_clean()` antes de `save()`: las reglas cruzadas de
  `WorkOrder.clean()` y la unicidad de `order_number` se aplican también aquí,
  de modo que el servicio no depende de que la validación viva en un solo
  lugar.

---

## 6. Atomicidad

`create_work_order()` está decorado con `@transaction.atomic`. Ante cualquier
excepción —de validación o de escritura— se revierte:

- la orden,
- el incremento del correlativo,
- cualquier escritura intermedia.

No puede quedar una OT parcialmente creada ni un número «quemado». Tras un
fallo, la siguiente creación exitosa recibe el número que le correspondía.

---

## 7. Pruebas

Archivo `apps/work_orders/tests/test_creation.py`, sobre `WorkOrderTestCase`.

```bash
python manage.py test apps.work_orders.tests.test_creation
```

### `CreateWorkOrderTests` — camino feliz

| Prueba |
|---|
| Se crea una OT válida con sus datos |
| La OT nace en `PENDING`, sin técnico, resultado ni marcas de atención |
| `created_by` queda trazado al usuario ejecutor |
| Sede y zona se derivan de la suscripción |
| El número usa el formato oficial `OT-AAAA-NNNNNN` |

### `CreateWorkOrderValidationTests` — rechazos

| Prueba |
|---|
| Sin usuario → `ValidationError` |
| Usuario inactivo → `ValidationError` |
| Sin suscripción → `ValidationError` |
| Suscripción deshabilitada → `ValidationError` |
| Suscripción cancelada → `ValidationError` |
| Suscripción que no corresponde al cliente → `ValidationError` |
| Cliente correcto → se acepta |
| `OrderType` inactivo → `ValidationError` |
| `OrderSubtype` de otro tipo → `ValidationError` |
| `OrderReason` de otro tipo → `ValidationError` |
| `OrderCause` de otro tipo → `ValidationError` |
| Sede de otro cliente → `ValidationError` |
| Zona de otra sede → `ValidationError` |
| Zona de la misma sede → se acepta |

En todos los rechazos se comprueba además que **no quedó ninguna orden**.

### `CreateWorkOrderSubscriptionStateTests` — estados de suscripción

| Prueba |
|---|
| Una OT de instalación mantiene la suscripción en `PRESALE` |
| Corte, reconexión y traslado no alteran el estado de la suscripción |

### `OrderNumberSequenceTests` — correlativo

| Prueba |
|---|
| La secuencia arranca en `OT-AAAA-000001` |
| 25 llamadas consecutivas no reutilizan ningún número |
| Cada año lleva su propia secuencia |
| Cinco órdenes seguidas reciben números distintos |
| Borrar la última orden no hace retroceder el correlativo |

### `CreateWorkOrderAtomicityTests` — transaccionalidad

| Prueba |
|---|
| Un fallo al guardar revierte la orden y el correlativo |
| Un número duplicado no crea una segunda orden |
| Una creación fallida no quema el siguiente número |

---

## 8. Fuera del alcance de esta actividad

- Vistas, formularios, plantillas o API de creación (el servicio queda listo
  para que los consuman). La capa web que lo consume se documentó después en
  [`work_orders_web_creation.md`](work_orders_web_creation.md).
- Asignación de técnico en el momento de la creación.
- Cierre automático de órdenes.
- Movimientos de inventario.
- Cualquier cambio en atención, liquidación, corrección, validación o
  evidencias.
- Integraciones externas (Krill, WhatsApp, Azure).
- Correlativo por sede (evaluado y descartado, §3.2).
- Verificación de bloqueo real de fila bajo PostgreSQL (§4.4).
