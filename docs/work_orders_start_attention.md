# Flujo web de inicio de atención de órdenes de trabajo

> Referencia histórica de la entrada web. La bandeja de despacho fue retirada;
> el inicio web existente vuelve a la ficha del cliente. El flujo operativo
> actual usa la toma y el inicio desde el aplicativo del técnico. Ver
> [Programación y toma de órdenes](work_orders_schedule_board.md).

Documentación técnica de la capa web que inicia la atención de una OT ya
despachada en SICV (SICV — Telecable / Fiber The Andes).

Cubre el formulario, la vista, el permiso funcional y la ruta que conectan la
bandeja de despacho con `start_order_attention()`. La lógica de dominio del
inicio (estados iniciables, `started_at` e historial) está en
[`work_orders_workflow.md`](work_orders_workflow.md); el despacho previo, en
[`work_orders_web_assignment.md`](work_orders_web_assignment.md) y
[`work_orders_dispatch_board.md`](work_orders_dispatch_board.md).

---

## 1. Principio: la capa web es delgada

```
Usuario con work_orders.start_workorder
      ↓
OT en estado ASSIGNED (o DERIVED / REPROGRAMMED) con técnico
      ↓
Pantalla de confirmación
      ↓
WorkOrderStartAttentionForm      ← solo transporta la observación
      ↓
WorkOrderStartAttentionView      ← resuelve orden y usuario
      ↓
start_order_attention(...)       ← servicio del módulo
      ↓
WorkOrder.start_attention(...)   ← valida, estampa la hora y transiciona
      ↓
OT en IN_PROGRESS + started_at + WorkOrderStatusHistory
```

Mismo reparto que en la creación y la asignación:

- **El formulario transporta.** Un único campo opcional. No describe la orden
  ni puede influir en la transición.
- **La vista orquesta.** Resuelve la orden desde la ruta, aporta
  `user=request.user` y traduce el resultado a pantalla.
- **El dominio decide.** `start_attention()` valida estado y técnico, estampa
  `started_at` con `timezone.now()` y mueve el estado por el mecanismo oficial.

La vista **nunca** hace `order.status = "IN_PROGRESS"` ni escribe `started_at`.

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `apps/work_orders/models.py` | Permiso `start_workorder`, propiedad `can_start_attention` |
| `apps/work_orders/migrations/0011_alter_workorder_options.py` | Alta del permiso |
| `apps/work_orders/forms.py` | `WorkOrderStartAttentionForm` |
| `apps/work_orders/views.py` | `WorkOrderStartAttentionView` |
| `apps/work_orders/urls.py` | Ruta `work_orders:start` |
| `apps/work_orders/templates/work_orders/work_order_start_attention.html` | Pantalla de confirmación |
| `apps/work_orders/templates/work_orders/work_order_dispatch.html` | Acción «Iniciar atención» en la bandeja |
| `apps/work_orders/tests/test_web_start_attention.py` | Pruebas del flujo web |

Ruta: `/work-orders/<pk>/start/`, incluida en `config/urls.py` bajo el prefijo
`work-orders/`.

`apps/customers/templates/customers/detail.html` **no se tocó**, para no
interferir con el frente de Joleydi. La acción se ofrece desde la bandeja de
despacho, que es la pantalla operativa del módulo.

---

## 3. Autorización: un tercer permiso funcional

Se declara en `WorkOrder.Meta`, junto al que ya existía:

```python
permissions = [
    ("assign_workorder", "Puede asignar órdenes de trabajo a un técnico"),
    ("start_workorder", "Puede iniciar la atención de órdenes de trabajo"),
]
```

**Por qué un permiso propio.** Ningún permiso existente encajaba:

- `change_workorder` habilita modificar cualquier campo de cualquier OT.
- `assign_workorder` es la atribución de *despacho*: decide a quién le toca la
  orden. Iniciar es otra cosa: declara que la atención empezó de verdad y
  estampa la hora real.
- `view_workorder` es de solo lectura.

Separarlos importa hacia adelante: cuando exista la app/PWA, el técnico
necesitará `start_workorder` y **no** debe recibir `assign_workorder` de
regalo. Sigue el precedente de `validate_liquidation` y `assign_workorder`,
que ya autorizan por permiso y no por rol.

La migración `0011` es un `AlterModelOptions`: **no toca el esquema**, solo
registra el permiso en `auth_permission`. `makemigrations --check` no detecta
cambios pendientes tras aplicarla.

| Situación | Resultado |
|---|---|
| Usuario no autenticado | Redirección a `/accounts/login/` |
| Autenticado sin el permiso | 403, la OT no cambia |
| Autenticado con `assign_workorder` únicamente | 403 — despachar no habilita iniciar |
| Autenticado con `change_workorder` únicamente | 403 |
| Autenticado con `start_workorder` | Abre la confirmación y puede iniciar |

La bandeja oculta la acción con
`{% if perms.work_orders.start_workorder and order.can_start_attention %}`,
pero eso es comodidad de interfaz: la seguridad real es el
`PermissionRequiredMixin` de la vista, que responde 403 aunque se escriba la
URL a mano o se envíe un POST manual.

---

## 4. `WorkOrderStartAttentionForm`

`forms.Form` con **un solo campo**: `remarks`, opcional.

Lo relevante es lo que **no** tiene. El estado destino, `started_at` y el
técnico responsable no son campos, así que no existe ningún nombre que un POST
manipulado pueda enviar para influir en la transición: sencillamente no hay
dónde aterrizar. La hora la pone `timezone.now()` dentro del dominio y el
responsable sale de `request.user`.

`remarks` es el mismo parámetro que ya acepta `start_attention()` y queda
registrado en `WorkOrderStatusHistory.remarks`.

Este contrato mínimo —una observación y nada más— es el que deberá aceptar la
futura API del técnico. Se define aquí una sola vez.

---

## 5. `WorkOrderStartAttentionView`

`LoginRequiredMixin` + `PermissionRequiredMixin` + `FormView`.

### 5.1 La orden se resuelve después del permiso

Mismo patrón que la asignación: `get_work_order()` con caché por petición, no
`dispatch()`. El control de permiso corre **antes** que la búsqueda, así que un
usuario sin autorización recibe siempre 403 y no puede usar la diferencia
403/404 para sondear qué órdenes existen.

### 5.2 La operación la ejecuta el servicio, no el modelo

```python
start_order_attention(
    order,
    user=self.request.user,
    remarks=form.cleaned_data.get("remarks", ""),
)
```

**Por qué el servicio y no `order.start_attention()` directo.** La actividad
pedía invocar `start_attention(...)` «o la firma vigente equivalente».
`start_order_attention()` es esa firma: llama internamente a
`WorkOrder.start_attention()` —la fuente de verdad sigue siendo la misma— y
además aplica el efecto ya aprobado sobre la suscripción (una instalación en
`PRESALE` pasa a `INSTALLATION`). Llamar al modelo por su cuenta dejaría a la
suscripción sin ese efecto y crearía un camino paralelo al que ya usa el resto
del módulo. Es también `@transaction.atomic`.

Hay una prueba dedicada a esto: si alguien sustituyera la llamada por el método
del modelo, `test_subscription_effect_of_the_service_is_applied` fallaría.

### 5.3 La vista no conoce la matriz de estados

No comprueba si la orden es iniciable antes de operar: lo intenta y deja que el
dominio acepte o rechace. `can_start_attention` solo decide si se pinta el
botón. No hay ninguna lista de estados escrita en la vista, el formulario o el
template.

### 5.4 Errores del dominio

```python
except ValidationError as exc:
    order.refresh_from_db()
    form.add_error(None, exc.messages)
    return self.form_invalid(form)
```

Los mensajes de `start_attention()` ya están redactados para el operador («No
se puede iniciar la atención de una orden en estado Pendiente.»). Se muestran
tal cual, sin traza interna y sin 500. Como el servicio es atómico, un rechazo
no deja `started_at` ni historial a medias; el `refresh_from_db()` evita además
repintar datos que nunca llegaron a persistirse.

### 5.5 `can_start_attention`

Propiedad del modelo, espejo de solo lectura de las dos condiciones que
`start_attention()` verifica:

```python
return (
    self.status in self.STARTABLE_STATUSES
    and self.assigned_technician_id is not None
)
```

No es una segunda matriz de estados: lee `STARTABLE_STATUSES`, de modo que si
mañana cambia la lista, la propiedad cambia con ella. `STARTABLE_STATUSES` y
`ALLOWED_TRANSITIONS` no se modificaron.

La vista publica además `is_startable_status` —la misma lista, consultada una
vez— para que la pantalla explique **cuál** de las dos condiciones falló. Sin
eso, una OT `PENDING` (que tampoco tiene técnico) mostraría «falta el técnico»
y el operador intentaría despacharla cuando el rechazo es por estado.

El mensaje de error del dominio se pinta **antes** de decidir si se ofrece el
formulario. Si una orden deja de ser iniciable entre el GET y el POST, el
rechazo cae en la rama sin formulario y su mensaje tiene que llegar a pantalla
igual, en lugar de perderse.

### 5.6 Redirección tras el éxito

Se vuelve a la bandeja de despacho, que es de donde se lanza la acción. Quien
puede iniciar no necesariamente puede ver la bandeja —son permisos distintos—,
así que sin `view_workorder` se redirige a la ficha del cliente, que solo exige
estar autenticado. Redirigir a una pantalla prohibida convertiría un éxito en
un 403.

El mensaje de éxito indica número de orden, estado resultante y hora de inicio
registrada.

---

## 6. Reglas de negocio conservadas

- Solo se inicia desde `ASSIGNED`, `DERIVED` o `REPROGRAMMED`, y siempre con
  técnico asignado.
- Una OT `PENDING`, `IN_PROGRESS`, `ATTENDED`, `LIQUIDATED`, `CANCELLED`,
  `REJECTED` o `NOT_FEASIBLE` no puede forzarse a `IN_PROGRESS`.
- `DERIVED` inicia **si y solo si** el dominio lo permite. No hay regla propia.
- Un GET nunca cambia estado: la transición vive en `form_valid()`.
- Iniciar **no** atiende ni liquida: no se registra causa, resultado ni
  liquidación, y `attended_at` sigue en `None`.
- No se crean movimientos de inventario ni se modifica stock.
- Ninguna capa fuera del dominio escribe `status` ni `started_at`.

---

## 7. Pruebas — `test_web_start_attention.py`

### `WorkOrderStartAttentionAccessTests`

| Prueba | Escenario |
|---|---|
| Un usuario autorizado ve la confirmación con el contexto correcto | 1 |
| Un anónimo no puede abrir la confirmación | 2 |
| Un anónimo no puede iniciar | 2 |
| Un autenticado sin permiso recibe 403 al abrir | 3 |
| Un autenticado sin permiso recibe 403 al enviar y la OT no cambia | 3 |
| `assign_workorder` por sí solo no autoriza el inicio | 3 |
| `change_workorder` por sí solo no autoriza el inicio | 3 |
| Sin permiso se responde 403 incluso ante una orden inexistente | 3 |
| Una orden inexistente devuelve 404 al autorizado | — |

### `WorkOrderStartAttentionSuccessTests`

| Prueba | Escenario |
|---|---|
| Una OT `ASSIGNED` pasa a `IN_PROGRESS` | 4 |
| `started_at` se registra dentro de la ventana de la petición | 5 |
| Se crea exactamente un `WorkOrderStatusHistory` con el estado anterior | 6 |
| `changed_by` queda a nombre del usuario autenticado | 7 |
| La observación viaja al historial tal cual | — |
| La observación es opcional | — |
| Mensaje de éxito visible y redirección a la bandeja | 16 |
| Sin `view_workorder` la redirección cae en la ficha del cliente | 16 |
| El efecto sobre la suscripción demuestra que se pasó por el servicio | — |

### `WorkOrderStartAttentionRejectionTests`

| Prueba | Escenario |
|---|---|
| Una OT `PENDING` se rechaza sin cambios ni historial | 8 |
| Una OT `IN_PROGRESS` se rechaza y no duplica historial | 9 |
| Una OT `ATTENDED` se rechaza | 10 |
| Una OT `LIQUIDATED` se rechaza | 11 |
| Una OT `CANCELLED` se rechaza | 12 |
| Una OT `REJECTED` se rechaza | 12 |
| Una OT `NOT_FEASIBLE` se rechaza | 12 |
| Una OT `DERIVED` sin técnico la rechaza el dominio y la pantalla lo explica | 13 |
| El rechazo por estado se explica antes que la falta de técnico | 13 |
| Una OT `DERIVED` con técnico sí inicia, porque el dominio lo permite | — |
| El `ValidationError` se informa sin 500 y sin traza interna | 17 |
| Una OT no iniciable no ofrece el formulario | — |

### `WorkOrderStartAttentionSafetyTests`

| Prueba | Escenario |
|---|---|
| Un GET no ejecuta ninguna transición | 14 |
| Un `status` / `new_status` enviado por POST se ignora | 15 |
| Un `started_at` enviado por POST se ignora | 15 |
| Un `assigned_technician` enviado por POST se ignora | 15 |
| Un `user` / `changed_by` enviado por POST no suplanta al operador | 15 |
| El formulario solo acepta `remarks` | 15 |

### `WorkOrderStartAttentionUITests`

| Prueba | Escenario |
|---|---|
| Quien tiene el permiso ve la acción en la bandeja | 18 |
| Quien no lo tiene no la ve | 18 |
| Una OT sin despachar no ofrece la acción | 18 |

Los escenarios 19 y 20 (no regresión de asignación y suite completa) se
verifican ejecutando `python manage.py test`.

---

## 8. Nota de compatibilidad con la futura app/PWA del técnico

```
        start_order_attention() / WorkOrder.start_attention()
                          ↑
        ┌─────────────────┴─────────────────┐
   Web actual                          API futura
        ↑                                   ↑
  Operador web                        App/PWA técnico
```

Qué queda preparado y por qué:

- **La regla no está en el template ni en JavaScript.** El template solo pinta
  contexto y un botón; no hay lógica de transición fuera del dominio.
- **El contrato de entrada ya está aislado** en
  `WorkOrderStartAttentionForm`: una observación opcional. Un serializer de la
  API futura acepta exactamente lo mismo y llama al mismo servicio.
- **La autorización es un permiso funcional, no un rol.** Conceder
  `start_workorder` al grupo de técnicos habilita la operación desde cualquier
  capa sin tocar código.
- **El responsable sale siempre del usuario autenticado**, no del cuerpo de la
  petición. La API heredará esa garantía tal cual.

No se implementó ningún endpoint de API: queda pendiente de aprobación expresa.

---

## 9. Fuera del alcance de esta actividad

- Causa, resultado y cierre de la atención.
- Liquidación técnica y validación de liquidación (seguirán consumiéndose desde
  la app/PWA del técnico, no desde un flujo administrativo paralelo).
- Materiales, kardex, inventario y movimientos de stock.
- Evidencias, fotografías, GPS y geolocalización.
- PWA, offline, service workers, sincronización y WhatsApp.
- Endpoints de API.
- Cambios en `create_work_order()`, en el correlativo, en la bandeja de
  despacho o en `assign_technician()`.
- Cambios en `ALLOWED_TRANSITIONS`, `STARTABLE_STATUSES` o la máquina de
  estados.
