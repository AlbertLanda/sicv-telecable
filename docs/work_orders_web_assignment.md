# Flujo web de asignación de órdenes de trabajo

Documentación técnica de la capa web que despacha OT a un técnico desde SICV
(SICV — Telecable / Fiber The Andes).

Cubre el formulario, la vista, el permiso funcional y la ruta que conectan la
ficha del cliente con `WorkOrder.assign_technician()`. La lógica de dominio de
la asignación (validaciones, historial y transición) está en
[`work_orders_workflow.md`](work_orders_workflow.md); el registro de la orden,
en [`work_orders_web_creation.md`](work_orders_web_creation.md).

---

## 1. Principio: la capa web es delgada

```
Usuario con work_orders.assign_workorder
      ↓
OT en estado PENDING
      ↓
Pantalla de asignación
      ↓
WorkOrderAssignForm          ← acota qué técnicos son elegibles
      ↓
WorkOrderAssignView          ← resuelve orden y usuario
      ↓
order.assign_technician(...) ← valida y ejecuta la transición
      ↓
OT en ASSIGNED + técnico asociado
```

Mismo reparto que en la creación:

- **El formulario filtra y presenta.** Decide *qué técnicos se ofrecen* y, por
  tanto, cuáles se aceptan.
- **La vista orquesta.** Resuelve la orden desde la ruta, aporta
  `assigned_by=request.user` y traduce el resultado a pantalla.
- **El modelo decide.** `assign_technician()` valida rol, actividad y estado,
  cierra la asignación vigente, abre la nueva y mueve el estado por el
  mecanismo oficial.

La vista **nunca** hace `order.status = "ASSIGNED"` ni `order.save()`.

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `apps/work_orders/models.py` | Permiso `assign_workorder`, propiedad `can_be_assigned` |
| `apps/work_orders/migrations/0010_alter_workorder_options.py` | Alta del permiso |
| `apps/work_orders/forms.py` | `WorkOrderAssignForm` |
| `apps/work_orders/views.py` | `WorkOrderAssignView` |
| `apps/work_orders/urls.py` | Ruta `work_orders:assign` |
| `apps/work_orders/templates/work_orders/work_order_assign.html` | Pantalla |
| `apps/customers/templates/customers/detail.html` | Acción «Asignar» en la ficha |
| `apps/work_orders/tests/test_web_assignment.py` | Pruebas del flujo web |

Ruta: `/work-orders/<pk>/assign/`, incluida en `config/urls.py` bajo el
prefijo `work-orders/`.

---

## 3. Autorización: permiso funcional propio

Se declara en `WorkOrder.Meta`:

```python
permissions = [
    ("assign_workorder", "Puede asignar órdenes de trabajo a un técnico"),
]
```

**Por qué un permiso propio y no `change_workorder`:** despachar es una
atribución operativa distinta de editar una orden. Conceder
`change_workorder` a un coordinador para que pueda asignar le habilitaría
además a modificar cualquier campo de cualquier OT. El permiso específico
mantiene el privilegio en lo estrictamente necesario y sigue el precedente de
`validate_liquidation`, que ya autoriza por permiso y no por rol.

La migración `0010` es un `AlterModelOptions`: **no toca el esquema**, solo
registra el permiso en `auth_permission`.

| Situación | Resultado |
|---|---|
| Usuario no autenticado | Redirección a `/accounts/login/` |
| Autenticado sin el permiso | 403, la OT no cambia |
| Autenticado con `add_workorder` únicamente | 403 — crear no habilita despachar |
| Autenticado con `assign_workorder` | Abre el formulario y puede asignar |

La ficha del cliente oculta la acción con
`{% if perms.work_orders.assign_workorder and order.can_be_assigned %}`, pero
eso es comodidad de interfaz: la seguridad real es el `PermissionRequiredMixin`
de la vista.

---

## 4. `WorkOrderAssignForm`

`forms.Form` con dos campos: `assigned_technician` y `remarks` (opcional).

**Por qué `Form` y no `ModelForm`:** la asignación no es «guardar campos», es
una transición de dominio. Sin `form.save()` no existe siquiera un camino de
persistencia paralelo a `assign_technician()`.

### 4.1 Técnicos elegibles

```python
User.objects.filter(
    role=User.Role.TECHNICIAN,
    is_active=True,
    branch=order.branch_id,
)
```

Un `ModelChoiceField` valida contra su queryset. Un técnico inactivo, un
usuario administrativo o un técnico de otra sede **no son opciones válidas**:
el POST manipulado se agota en la capa web y ni siquiera llega al modelo.

La restricción de sede vive aquí a propósito. `assign_technician()` valida rol,
actividad y estado —reglas invariantes del dominio—, mientras que «el técnico
debe ser de la sede de la OT» es una regla de **alcance operativo**: si mañana
se autoriza el apoyo entre sedes, se amplía el queryset sin tocar el dominio.

Sin orden resuelta el selector queda vacío: antes eso que exponer personal de
sedes ajenas.

### 4.2 `remarks`

Opcional. Es el mismo parámetro que ya acepta `assign_technician()` y queda
registrado en `WorkOrderAssignment.remarks`, de modo que el historial de
despacho conserva la indicación con la que se envió al técnico.

---

## 5. `WorkOrderAssignView`

`LoginRequiredMixin` + `PermissionRequiredMixin` + `FormView`.

### 5.1 La orden se resuelve después del permiso

```python
def get_work_order(self):
    if not hasattr(self, "_work_order"):
        self._work_order = get_object_or_404(WorkOrder.objects...)
    return self._work_order
```

No se resuelve en `dispatch()`: así el control de permiso corre **antes** que
la búsqueda y un usuario sin autorización recibe siempre 403, sin poder usar la
diferencia 403/404 para sondear qué órdenes existen.

### 5.2 La transición la ejecuta el dominio

```python
order.assign_technician(
    technician=form.cleaned_data["assigned_technician"],
    assigned_by=self.request.user,
    remarks=form.cleaned_data.get("remarks", ""),
)
```

`assigned_by` sale de `request.user`; no es un campo del formulario, así que no
hay POST capaz de suplantarlo.

### 5.3 Errores del dominio

```python
except ValidationError as exc:
    order.refresh_from_db()
    form.add_error(None, exc.messages)
    return self.form_invalid(form)
```

Los mensajes de `assign_technician()` ya están redactados para el operador. Como
el método es `@transaction.atomic`, un rechazo no deja asignaciones a medio
abrir; el `refresh_from_db()` evita además repintar en pantalla datos que nunca
llegaron a persistirse.

### 5.4 Estado no asignable

`can_be_assigned` (propiedad del modelo, `status in ASSIGNABLE_STATUSES`) se
publica al contexto para que la pantalla no ofrezca el envío en una OT cerrada.
La comprobación real sigue estando en el dominio en cada POST: la interfaz
informa, no autoriza.

---

## 6. Reglas de negocio conservadas

- Solo se asigna desde `PENDING`, `ASSIGNED`, `DERIVED` o `REPROGRAMMED`.
- Una OT `CANCELLED`, `ATTENDED`, `LIQUIDATED`, `REJECTED` o `NOT_FEASIBLE` no
  puede forzarse a `ASSIGNED`.
- Asignar **no** inicia la atención: la OT queda en `ASSIGNED`, `started_at`
  sigue en `None` y no pasa a `IN_PROGRESS`.
- La suscripción no se toca: ni estado, ni fechas.
- No se registra causa, resultado ni ningún hecho operativo.
- No se crean movimientos de inventario ni se modifica stock.
- Ninguna capa fuera del modelo escribe `status` ni `assigned_technician`.

---

## 7. Pruebas — `test_web_assignment.py`

### `WorkOrderAssignViewAccessTests`

| Prueba |
|---|
| Un usuario autorizado ve el formulario |
| Un anónimo no puede abrir el formulario |
| Un anónimo no puede asignar |
| Un autenticado sin permiso recibe 403 al abrir |
| Un autenticado sin permiso recibe 403 al asignar y la OT no cambia |
| `add_workorder` por sí solo no autoriza la asignación |
| Una orden inexistente devuelve 404 |
| Sin permiso se responde 403 incluso ante una orden inexistente |

### `WorkOrderAssignViewSuccessTests`

| Prueba |
|---|
| Una solicitud correcta deja la OT en `ASSIGNED` y redirige a la ficha |
| El técnico persistido es exactamente el seleccionado |
| El historial de asignaciones registra quién despachó |
| La transición pasa por el mecanismo oficial (hay `WorkOrderStatusHistory`) |
| La asignación no inicia la atención |
| La asignación no toca la suscripción |
| La asignación no registra causa ni resultado |
| La observación es opcional |
| Se muestra el mensaje de confirmación |

### `WorkOrderAssignEligibilityTests`

| Prueba |
|---|
| Solo se ofrecen técnicos elegibles |
| Se rechaza un técnico inactivo |
| Se rechaza un usuario que no es técnico |
| Un técnico activo de otra sede puede ser asignado |
| El técnico es obligatorio |
| Una asignación rechazada no deja historial |
| Una reasignación fallida conserva al técnico anterior |

### `WorkOrderAssignManipulatedPostTests`

| Prueba |
|---|
| Un `status` enviado por POST se ignora |
| Un `started_at` enviado por POST se ignora |
| `order_number` y `created_by` enviados por POST se ignoran |
| `priority` y `scheduled_at` enviados por POST se ignoran |
| `assigned_by` no puede imponerse desde el POST |

### `WorkOrderAssignInvalidStatusTests`

| Prueba |
|---|
| Una OT `CANCELLED` no puede asignarse |
| Una OT `ATTENDED` no puede asignarse |
| Una OT `LIQUIDATED` no puede asignarse |
| Una OT `REJECTED` no puede asignarse |
| Una OT `IN_PROGRESS` no puede reasignarse desde esta pantalla |
| Una OT cerrada no ofrece el formulario |

### `WorkOrderAssignUITests`

| Prueba |
|---|
| Quien tiene el permiso ve la acción en la ficha del cliente |
| Quien no lo tiene no la ve |
| Una OT cerrada no ofrece la acción |

---

## 8. Deuda pendiente

- La reasignación de una OT ya `ASSIGNED` funciona por reutilizar la misma
  pantalla (el dominio cierra la asignación vigente y abre otra), pero la
  reprogramación y la derivación siguen sin interfaz propia.
- No hay bandeja de despacho: la asignación se inicia desde la ficha del
  cliente. Un listado de OT pendientes por sede es el siguiente paso natural.
- La carga de trabajo del técnico no se considera al ofrecer candidatos. Si el
  Área de TI define un criterio (OT abiertas por técnico, zona habitual), es un
  filtro más del queryset del formulario.

---

## 9. Fuera del alcance de esta actividad

- Inicio de atención y atención en campo.
- Liquidación y validación de liquidación.
- Evidencias, galería, GPS, PWA y WhatsApp.
- Inventario, kardex y movimientos de stock.
- Reprogramación, derivación y cierre de OT.
- Cambios en `create_work_order()`, en el correlativo y en la máquina de
  estados.
