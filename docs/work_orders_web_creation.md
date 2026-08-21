# Flujo web de creación de órdenes de trabajo

Documentación técnica de la capa web que registra OT desde SICV
(SICV — Telecable / Fiber The Andes).

Cubre el formulario, la vista y la ruta que conectan la ficha del cliente con
el servicio `create_work_order()`. El servicio en sí, sus validaciones y el
correlativo transaccional están en
[`work_orders_creation.md`](work_orders_creation.md); el ciclo posterior de
asignación, atención y liquidación, en
[`work_orders_workflow.md`](work_orders_workflow.md), y la pantalla que
despacha la OT a un técnico, en
[`work_orders_web_assignment.md`](work_orders_web_assignment.md).

---

## 1. Principio: la capa web es delgada

```
ATC autenticado
      ↓
Ficha del cliente
      ↓
WorkOrderCreateView        ← resuelve cliente y usuario
      ↓
WorkOrderCreateForm        ← acota qué se puede elegir
      ↓
create_work_order(...)     ← decide si la orden puede registrarse
      ↓
OT en PENDING + OT-AAAA-XXXXXX
```

El reparto de responsabilidades es deliberado:

- **El formulario filtra y presenta.** Decide *qué opciones se ofrecen* y, por
  tanto, cuáles se aceptan. No reimplementa reglas de negocio.
- **La vista orquesta.** Resuelve el contexto de servidor (cliente, usuario),
  entrega el formulario y traduce el resultado del servicio a pantalla.
- **El servicio decide.** Valida las reglas cruzadas, reserva el correlativo y
  persiste. Es el único que escribe.

Esta separación es lo que permite que una futura PWA o API consuman el mismo
servicio sin duplicar la lógica de SICV.

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `apps/work_orders/forms.py` | `WorkOrderCreateForm` |
| `apps/work_orders/views.py` | `WorkOrderCreateView` |
| `apps/work_orders/urls.py` | Ruta `work_orders:create` |
| `apps/work_orders/templates/work_orders/work_order_create.html` | Pantalla |
| `apps/work_orders/tests/test_web_creation.py` | Pruebas del flujo web |

Ruta: `/work-orders/customers/<customer_pk>/create/`, incluida en
`config/urls.py` bajo el prefijo `work-orders/`.

---

## 3. `WorkOrderCreateForm`

`ModelForm` de `WorkOrder` con estos campos y **solo** estos:

```
subscription, order_type, subtype, reason, branch, zone,
attention_type, priority, scheduled_at, detail
```

### 3.1 Lo que no está es tan importante como lo que está

`order_number`, `created_by`, `status`, `assigned_technician`, `cause` y
`result` **no** se declaran en `Meta.fields`. Django solo lee del POST los
campos declarados: un navegador que envíe `order_number=OT-9999-000999` o
`created_by=<otro usuario>` no consigue nada, porque esos datos nunca llegan a
`cleaned_data`. No hace falta una lista negra ni un `clean()` defensivo — basta
con no abrir la puerta.

### 3.2 Ámbito del cliente

El formulario recibe `customer=` desde la vista (mismo patrón que
`SubscriptionCreateForm`) y acota sus querysets:

| Campo | Queryset |
|---|---|
| `subscription` | Suscripciones activas **de ese cliente** |
| `branch` | Únicamente la sede del cliente |
| `zone` | Zonas activas de esa sede |
| `order_type` / `subtype` / `reason` | Solo registros con `is_active=True` |

Un `ModelChoiceField` valida contra su queryset. Una suscripción de otro
cliente, una zona de otra sede o un catálogo desactivado no son opciones
válidas, así que el POST manipulado se rechaza con «opción no válida» sin
llegar a la base de datos.

Sin cliente resuelto los querysets quedan vacíos: se prefiere un formulario
inútil antes que uno que muestre datos de terceros.

### 3.3 `service_arguments()`

Traduce `cleaned_data` a los argumentos con nombre de `create_work_order()`.
Existe para que la vista no arme ese diccionario a mano y para que un cambio
de firma del servicio se resuelva en un solo lugar. `created_by` no aparece
aquí a propósito: lo aporta la vista.

---

## 4. `WorkOrderCreateView`

`LoginRequiredMixin` + `FormView`.

**Por qué `FormView` y no `CreateView`:** un `CreateView` expone
`form.save()`, es decir, un camino de persistencia paralelo al servicio. Al
usar `FormView` no existe ningún `save()` que alguien pueda invocar por
descuido en un futuro refactor.

### 4.1 Contexto de servidor

```python
def dispatch(self, request, *args, **kwargs):
    self.customer = get_object_or_404(
        Customer.objects.select_related("branch"),
        pk=self.kwargs["customer_pk"],
        is_active=True,
    )
```

El cliente viaja en la **ruta**, no en el cuerpo del POST. El navegador nunca
declara a qué cliente pertenece la orden: solo elige entre las opciones que el
formulario ya limitó a ese cliente.

`created_by=self.request.user` se pasa directamente al servicio.

### 4.2 Errores del servicio

```python
except ValidationError as exc:
    form.add_error(None, exc.messages)
    return self.form_invalid(form)
```

Los mensajes de `create_work_order()` ya están redactados para el operador, así
que se muestran tal cual. Como el servicio es `@transaction.atomic`, un rechazo
no deja orden a medias **ni consume correlativo**: el siguiente registro válido
sigue tomando el número que le tocaba.

---

## 5. Reglas de negocio conservadas

- La OT nace en `PENDING`, sin técnico asignado.
- Crear una OT de instalación **no** activa la suscripción: una suscripción en
  `PRESALE` sigue en `PRESALE` y sin `installation_date`.
- La máquina de estados no se toca: asignación, atención y liquidación son
  etapas posteriores.
- El correlativo lo emite `generate_order_number()` con `select_for_update()`.
  La vista no calcula, no consulta `max(id)` y no formatea números.
- Ninguna capa fuera del servicio llama a `WorkOrder.objects.create()`.

---

## 6. Pruebas — `test_web_creation.py`

### `WorkOrderCreateViewAccessTests`

| Prueba |
|---|
| Un usuario autenticado ve el formulario |
| Un anónimo no puede abrir el formulario |
| Un anónimo no puede crear una OT |
| Un cliente inexistente devuelve 404 |

### `WorkOrderCreateViewSuccessTests`

| Prueba |
|---|
| Una solicitud correcta crea exactamente una OT y redirige a la ficha |
| El número de OT lo emite el correlativo del backend |
| El navegador no puede imponer `order_number` |
| `created_by` es el usuario autenticado, no el enviado por POST |
| `status` y `assigned_technician` no son manipulables por POST |
| Una OT de instalación deja la suscripción en `PRESALE` |
| Los campos opcionales pueden omitirse |

### `WorkOrderCreateViewScopeTests`

| Prueba |
|---|
| Se rechaza una suscripción de otro cliente |
| El formulario solo ofrece suscripciones del cliente mostrado |
| Se rechaza una zona de otra sede |
| Se rechaza una sede distinta a la del cliente |

### `WorkOrderCreateViewCatalogTests`

| Prueba |
|---|
| Se rechaza un tipo de orden inactivo |
| Se rechaza un subtipo inactivo |
| Se rechaza un motivo inactivo |
| Los catálogos inactivos no se ofrecen |
| Se rechaza un subtipo de otro tipo de orden |
| Se rechaza un motivo de otro tipo de orden |

### `WorkOrderCreateViewAtomicityTests`

| Prueba |
|---|
| Un rechazo del servicio vuelve al formulario sin registros parciales |
| Una creación fallida no consume correlativo |

La atomicidad se prueba con una **suscripción cancelada**: pasa el filtro del
formulario (sigue `is_active`) pero el servicio la rechaza. Es el caso que
demuestra el reparto de responsabilidades — el formulario no lo ve, el dominio
sí.

---

## 7. Deuda pendiente

- `CustomerWorkOrderUIPreviewView` (`customers:work_order_ui_preview`) sigue en
  pie con sus pruebas. La maqueta quedó superada por esta pantalla; el botón de
  la ficha del cliente ya apunta a `work_orders:create`. Su retiro toca
  `apps/customers` y se deja a criterio del responsable de TI.
- El encadenado dinámico de subtipo/motivo según el tipo de orden se resuelve
  hoy en servidor. Un filtrado en el navegador mejoraría la experiencia, pero
  sería solo comodidad: la validación seguiría siendo la del servicio.

---

## 8. Fuera del alcance de esta actividad

- Asignación de técnicos, inicio de atención y atención en campo.
- Liquidación y validación de liquidación.
- Inventario, kardex, movimientos de stock y evidencias.
- PWA, geolocalización, WhatsApp e integración Krill.
- Cambios en modelos, migraciones o settings.
- Edición y anulación de órdenes desde la web.
- Listado y búsqueda de órdenes fuera de la ficha del cliente.
