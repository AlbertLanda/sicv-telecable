# Bandeja operativa de despacho de órdenes de trabajo

Documentación técnica de la bandeja que permite al personal autorizado
consultar las OT registradas por ATC, organizarlas y llevarlas al flujo de
asignación existente (SICV — Telecable / Fiber The Andes).

Cubre la vista de listado, el formulario de filtros, el permiso de
visualización y la plantilla. La asignación en sí no se toca aquí: está
documentada en [`work_orders_web_assignment.md`](work_orders_web_assignment.md),
y el dominio de la orden, en [`work_orders_workflow.md`](work_orders_workflow.md).

---

## 1. Principio: la bandeja solo lee

```
ATC registra la OT
      ↓
OT en PENDING
      ↓
Bandeja de despacho          ← busca, filtra, pagina
      ↓
Acción Asignar / Reasignar   ← enlace, no formulario propio
      ↓
work_orders:assign           ← flujo ya existente
      ↓
order.assign_technician(...) ← única transición
```

La bandeja **no** crea órdenes, **no** cambia estados, **no** escribe
`assigned_technician` y **no** inicia atención. Su acción es un enlace a
`work_orders:assign`, que es quien ejecuta la transición contra el dominio.

Consecuencia práctica: esta actividad no añade ninguna regla de negocio. Todo
lo que decide qué se puede despachar sigue viviendo donde ya vivía
(`ASSIGNABLE_STATUSES`, `can_be_assigned`, `assign_technician()`).

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `apps/work_orders/forms.py` | `WorkOrderDispatchFilterForm` (nuevo) |
| `apps/work_orders/views.py` | `WorkOrderDispatchListView` (nueva) |
| `apps/work_orders/urls.py` | Ruta `work_orders:dispatch` |
| `apps/work_orders/templates/work_orders/work_order_dispatch.html` | Pantalla |
| `apps/work_orders/templatetags/work_order_tags.py` | Filtros `status_css` / `priority_css` |
| `templates/base.html` | Enlace «Bandeja de Despacho» en el navbar |
| `apps/work_orders/tests/test_web_dispatch.py` | Pruebas de la bandeja |

Ruta: `/work-orders/dispatch/`, bajo el prefijo `work-orders/` que
`config/urls.py` ya incluía.

**Sin cambios en modelos, migraciones ni settings.** `makemigrations --check`
sale limpio. El único archivo fuera de `apps/work_orders` es
`templates/base.html`, y solo para añadir el enlace de navegación
(ver §8).

---

## 3. Autorización

| Acción | Permiso |
|---|---|
| Abrir la bandeja | `work_orders.view_workorder` |
| Asignar / reasignar | `work_orders.assign_workorder` |

`view_workorder` es el permiso por defecto que Django ya crea para el modelo:
no hace falta declararlo ni migrar nada. Se eligió frente a inventar un
permiso nuevo porque lo que la bandeja hace es exactamente *ver órdenes*.

Son dos atribuciones distintas y deliberadamente separadas: un usuario puede
consultar la bandeja sin poder despachar. La vista no menciona ningún rol —
quien concede el permiso decide a quién le corresponde.

Comportamiento de `PermissionRequiredMixin` sobre `AccessMixin`:

- **Anónimo** → redirección al login.
- **Autenticado sin `view_workorder`** → `403`.

Ocultar la acción en la plantilla es comodidad de interfaz, no seguridad: la
barrera real sigue siendo `WorkOrderAssignView`, que responde `403` aunque se
escriba la URL a mano. Hay una prueba explícita de que tener acceso a la
bandeja **no** abre ningún atajo hacia la asignación, ni por GET ni por POST.

---

## 4. Filtros: un formulario, no parámetros crudos

`WorkOrderDispatchFilterForm` es un `forms.Form` (no un `ModelForm`): no
describe una orden, describe la consulta. Se enlaza a `request.GET` y todos
sus campos son opcionales, de modo que abrir la bandeja sin parámetros es un
formulario válido y vacío.

| Campo | Tipo | Efecto |
|---|---|---|
| `q` | texto | Búsqueda (§5) |
| `status` | choice | `status=` |
| `branch` | FK | `branch=` |
| `zone` | FK | `zone=` |
| `order_type` | FK | `order_type=` |
| `priority` | choice | `priority=` |
| `technician` | choice | pk, o `unassigned` → `assigned_technician__isnull=True` |

### Por qué el saneamiento vive en el formulario

Los `ModelChoiceField` y `ChoiceField` validan la entrada antes de que llegue
al ORM. Un `?branch=999999` o un `?status=BASURA` se quedan en `form.errors`
y su filtro simplemente no se aplica. La vista nunca interpreta parámetros
crudos ni construye condiciones a mano: **no hay `raw()`, `extra()` ni
cadenas SQL con datos del operador.**

`selected_filters()` llama a `is_valid()` y lee `cleaned_data`, que solo
contiene los campos que pasaron. Es una decisión concreta: un parámetro
corrupto anula **su propio** filtro sin arrastrar a los demás, de modo que
`?branch=999999&status=PENDING` sigue filtrando por estado.

### Catálogos del filtro sin `is_active`

A diferencia del formulario de creación, los selectores de la bandeja no se
acotan a registros activos. Un filtro sirve para encontrar lo que *ya existe*:
si una sede, una zona, un tipo o un técnico se desactivan más tarde, sus
órdenes deben seguir siendo consultables. El formulario de creación sí acota a
activos, porque ahí se decide qué se puede registrar de nuevo.

### Regla crítica: sede y zona no restringen al técnico

Los filtros de sede y zona se aplican **únicamente al queryset del listado**.
`WorkOrderAssignForm` no se modificó en esta actividad y sigue ofreciendo todo
técnico activo con rol `TECHNICIAN`, sea cual sea su sede.

Hay una prueba dedicada a esto
(`test_branch_filter_does_not_restrict_eligible_technicians`): con el filtro de
sede aplicado, un técnico de otra sede sigue apareciendo como elegible en el
flujo de asignación de una orden listada.

---

## 5. Búsqueda

Un único campo `q` que cubre los criterios pedidos:

- número de orden (`order_number`)
- código de cliente (`customer.code`)
- documento de identidad (`customer.document_number`)
- razón social (`customer.business_name`)
- nombres y apellidos (`first_name`, `paternal_surname`, `maternal_surname`)

Se filtra **palabra por palabra en AND**, con cada palabra buscada en OR sobre
todos esos campos. Es el mismo criterio que ya usa la búsqueda de clientes, y
hace que `"Juan Pérez"` exija ambas coincidencias en lugar de devolver todo lo
que contenga cualquiera de las dos. Todo se expresa con `Q()` del ORM.

---

## 6. Rendimiento

```python
WorkOrder.objects.select_related(
    "subscription", "subscription__customer",
    "subscription__address", "subscription__address__zone",
    "branch", "zone", "order_type", "subtype",
    "assigned_technician", "assigned_technician__branch",
).order_by("-created_at", "-pk")
```

Todo lo que la tabla pinta por fila viaja en la misma consulta. Sin esto,
listar 20 órdenes dispara una consulta por cliente, sede, zona, tipo y técnico
de cada fila.

**No se usa `distinct()`.** Todos los joins de la bandeja son FK hacia-uno, así
que no multiplican filas: no hay duplicados que eliminar, y `distinct()` sobre
este `select_related` solo costaría. Hay una prueba de que el listado no
repite órdenes.

**Ordenamiento.** `Meta.ordering` ya es `-created_at`; se repite en la vista
con un desempate explícito por `-pk`. No es redundancia: la paginación lo
necesita. Con dos órdenes creadas en el mismo instante, un orden no
determinista puede repetir o saltar filas entre páginas.

**Paginación** de 20 órdenes por página. Nunca se carga el sistema entero en
una respuesta.

**No se añadió ningún índice ni migración.** Los índices que ya existían
(`status`, `subscription`, `created_at`) cubren el uso previsto; añadir más sin
una necesidad medida quedaba fuera del alcance autorizado.

La prueba de N+1 compara el número de consultas con una orden y con varias, en
lugar de fijar una cifra exacta: lo que se quiere probar es la ausencia de
N+1, no congelar cuántas consultas hace Django para autenticar.

---

## 7. Pantalla

- Tabla Bootstrap coherente con el resto del SICV, dentro de `card-custom`.
- **Estados y prioridades como badges con texto propio.** El texto siempre
  sale de `get_status_display` / `get_priority_display`; el color es solo
  apoyo. La pantalla se lee igual sin distinguir colores.
- Las clases de color se resuelven en `work_order_tags.py` en vez de en una
  cadena de `{% if %}`: el mapeo estado → clase queda en un solo sitio y no
  ensucia la plantilla.
- **Filtros por GET**, de modo que cada combinación es una URL compartible y
  la paginación puede arrastrarla. La vista expone `querystring` (la query
  string sin `page`) y cada enlace de página añade el suyo.
- **Dos estados vacíos distintos**: «no hay coincidencias» cuando hay filtros
  aplicados (con botón para limpiarlos) y «todavía no hay órdenes» cuando la
  bandeja está vacía de verdad.
- Si la OT tiene técnico se muestra con su sede; si no, un badge **Sin
  asignar**.
- El cliente enlaza a su ficha (`customers:detail`), la navegación segura ya
  existente.
- La acción es **Asignar** o **Reasignar** según haya técnico, y apunta a
  `work_orders:assign`. No hay formulario duplicado.

Condición de la acción:

```django
{% if perms.work_orders.assign_workorder and order.can_be_assigned %}
```

`can_be_assigned` se consulta al modelo en lugar de repetir la lista de
estados en la plantilla: si mañana cambia `ASSIGNABLE_STATUSES`, la bandeja lo
sigue sin tocarse.

---

## 8. Cambio fuera del módulo

`templates/base.html` recibe un enlace «Bandeja de Despacho» en el navbar,
envuelto en `{% if perms.work_orders.view_workorder %}`. Es el único archivo
modificado fuera de `apps/work_orders`.

Se incluyó porque una bandeja operativa alcanzable solo escribiendo la URL no
es utilizable por el personal de despacho. No toca ningún otro módulo, no
altera comportamiento existente y es reversible en una línea si el responsable
del Área de TI prefiere otro punto de entrada.

---

## 9. Pruebas

`apps/work_orders/tests/test_web_dispatch.py` cubre los 18 escenarios mínimos:

| # | Escenario | Prueba |
|---|---|---|
| 1 | Acceso autorizado | `test_authorized_user_opens_the_board` |
| 2 | Usuario anónimo | `test_anonymous_user_is_redirected_to_login` |
| 3 | Sin permiso | `test_user_without_view_permission_gets_403`, `test_board_does_not_open_a_shortcut_to_assignment` |
| 4 | Listado sin duplicados | `test_board_lists_every_order_once` |
| 5 | Búsqueda por OT | `test_search_by_order_number_returns_the_exact_order` |
| 6 | Búsqueda por cliente | `test_search_by_customer_code...`, `..._document_number...`, `..._business_name...` |
| 7 | Filtro estado | `test_filter_by_status` |
| 8 | Filtro sede | `test_filter_by_branch`, `test_branch_filter_does_not_restrict_eligible_technicians` |
| 9 | Filtro zona | `test_filter_by_zone` |
| 10 | Filtro tipo | `test_filter_by_order_type` |
| 11 | Filtro prioridad | `test_filter_by_priority` |
| 12 | Sin resultados | `test_incompatible_filters_show_a_clear_empty_state` |
| 13 | Paginación | `test_board_paginates_long_listings`, `test_filters_survive_pagination` |
| 14 | Asignar visible | `test_assign_action_is_offered_for_assignable_orders` |
| 15 | Asignar oculto | `test_assign_action_is_hidden_without_permission` |
| 16 | OT cerrada | `test_closed_orders_do_not_offer_assignment` |
| 17 | Reasignación | `test_assigned_orders_offer_reassignment` |
| 18 | Consultas | `test_listing_does_not_issue_queries_per_order` |

Extras: ordenamiento descendente, filtro por técnico y por «sin asignar»,
filtros combinables, parámetros corruptos, búsqueda multi-palabra y resolución
de la ruta.

---

## 10. Fuera de alcance (deliberado)

No se implementó, por corresponder a etapas posteriores:

- Inicio de atención / paso a `IN_PROGRESS`.
- Atención en campo, causa, resultado, cierre.
- Liquidación, validación y correcciones.
- Materiales, inventario, kardex.
- Evidencias, GPS, PWA, notificaciones.

Tampoco se modificó `create_work_order()`, el correlativo, la máquina de
estados ni la lógica de asignación. El siguiente bloque recomendado es el
inicio web de atención reutilizando `WorkOrder.start_attention(...)`.
