# API del técnico: permiso funcional y «Mis órdenes»

Documentación técnica del permiso `IsActiveTechnician` y del primer endpoint
operativo del canal de API del técnico en SICV (SICV — Telecable / Fiber The
Andes).

Continúa el cimiento del día anterior, documentado en
[`api_technician_auth.md`](api_technician_auth.md). El dominio de las órdenes
—estados, transiciones e historial— está en
[`work_orders_workflow.md`](work_orders_workflow.md); la bandeja web
equivalente, en
[`work_orders_dispatch_board.md`](work_orders_dispatch_board.md).

---

## 1. Principio: identificar y autorizar son preguntas distintas

```
Token válido
      ↓
IsAuthenticated (global)      ← ¿sé quién eres?
      ↓
IsActiveTechnician            ← ¿puedes operar en este canal?
      ↓
queryset filtrado por request.user   ← ¿qué es tuyo?
      ↓
WorkOrderListSerializer       ← solo lectura, sin acciones
```

Las tres capas son independientes y ninguna suple a la anterior. El token del
día 1 solo identifica; el permiso decide si ese usuario puede usar los
endpoints operativos; y el queryset decide qué filas le pertenecen. Un fallo
en cualquiera de las tres no se compensa con las otras dos, por lo que las
tres tienen prueba propia.

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `apps/accounts/services.py` | `is_active_technician()` — única definición de «técnico activo» |
| `apps/accounts/api/permissions.py` | `IsActiveTechnician` |
| `apps/accounts/api/views.py` | `TechnicianMeView` pasa a exigir el permiso |
| `apps/work_orders/api/serializers.py` | `WorkOrderListSerializer`, `WorkOrderCustomerSerializer` |
| `apps/work_orders/api/views.py` | `MyWorkOrderListView` |
| `apps/work_orders/api/urls.py` | Ruta `work_orders_api:my_orders` |
| `config/urls.py` | Prefijo `api/technicians/work-orders/` |
| `apps/work_orders/tests/test_api_my_orders.py` | Pruebas del endpoint |

No hay migraciones: el endpoint solo lee y no se tocó ningún modelo.

---

## 3. El permiso `IsActiveTechnician`

La regla no se reimplementó. Se extrajo el predicado `is_active_technician()`
a `apps/accounts/services.py` y ahora lo consumen **los dos** caminos: el
login del día 1 (`authenticate_technician()`) y la permission class. La
condición «rol técnico + cuenta activa» existe en un solo lugar del código,
de modo que si mañana cambia —por ejemplo, exigir sede asignada— cambia una
vez y ambos caminos quedan alineados.

```python
def is_active_technician(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and user.role == User.Role.TECHNICIAN
    )
```

El predicado acepta `AnonymousUser` y devuelve `False`: no asume que quien lo
llama ya validó la autenticación.

En `authenticate_technician()` se conserva la comprobación previa de cuenta
activa porque **los dos rechazos no son el mismo rechazo**: el estado de la
cuenta pertenece a la validez de la credencial (401) y el rol es una cuestión
de autorización (403). Confundirlos cambiaría el código de respuesta del
login y permitiría distinguir usuarios existentes de inexistentes.

El permiso se declara junto a `IsAuthenticated`, no en su lugar:

```python
permission_classes = [IsAuthenticated, IsActiveTechnician]
```

Es explícito a propósito. Declarar `permission_classes` **reemplaza** el valor
global del día 1, así que omitir `IsAuthenticated` dejaría el endpoint
apoyado únicamente en el permiso de rol.

### 3.1 Decisión: `TechnicianMeView` sí lleva el permiso

`GET /api/technicians/me/` pasa a exigir `IsActiveTechnician`. Es un cambio
deliberado sobre el día 1, y la razón es concreta: **el token del canal
técnico no caduca**. Sin el permiso, un usuario desactivado o movido a otro
rol *después* de haber iniciado sesión seguiría obteniendo respuesta con su
token viejo, porque el rol solo se verificaba al emitirlo.

Con el permiso aplicado, rol y estado se reevalúan en cada petición:

| Situación | Antes | Ahora |
|---|---|---|
| Técnico activo con su token | 200 | 200 |
| Su cuenta se desactiva después del login | 200 | 401 |
| Pasa de técnico a ATC después del login | 200 | 403 |

Se consideró dejarlo abierto a cualquier usuario autenticado con el argumento
de que solo devuelve identidad y no datos operativos. Se descartó: el hueco
del token vigente es real, y `me/` pertenece al canal técnico, no a un canal
genérico. Dos pruebas fijan el comportamiento nuevo
(`test_deactivated_technician_with_live_token_is_rejected` y
`test_technician_moved_to_another_role_loses_access`).

---

## 4. Endpoint `GET /api/technicians/work-orders/`

Devuelve las OT cuyo `assigned_technician` es el usuario autenticado.

**Respuesta 200**

```json
[
  {
    "id": 12,
    "order_number": "OT-00012",
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
    "status": "ASSIGNED",
    "status_display": "Asignada",
    "priority": "NORMAL",
    "priority_display": "Normal",
    "scheduled_at": "2026-08-28T14:00:00-05:00",
    "created_at": "2026-08-27T09:12:44-05:00"
  }
]
```

| Situación | Código |
|---|---|
| Técnico activo con OT asignadas | 200, solo las suyas |
| Técnico activo sin OT asignadas | 200, lista vacía |
| Usuario autenticado sin rol técnico | 403 |
| Sin token | 401 |

Cada campo con choices viaja dos veces: el **código estable** con el que la
app decide y la **etiqueta legible** que pinta en pantalla. Así el cliente no
mantiene su propia tabla de traducciones y no se rompe si cambia una etiqueta.

El cliente se serializa con `str(customer)`, que ya resuelve persona natural
(nombres y apellidos) y jurídica (razón social). No se agregó ninguna
propiedad al modelo de `apps/customers`, que está fuera de alcance.

Solo lectura: no se expone ninguna acción de transición. Iniciar atención,
atender y liquidar llegan en los días 4 a 6 y pasarán por los servicios de
dominio, no por un serializador.

---

## 5. Seguridad: el filtro es del servidor

```python
def get_queryset(self):
    return WorkOrder.objects.filter(assigned_technician=self.request.user)
```

La vista **no lee ningún parámetro de la petición**. No existe un `?technician=`
que validar, ni un id que comparar contra el usuario, porque el técnico sale
de `request.user` y de ningún otro sitio. Un técnico no puede ver órdenes de
otro manipulando la URL: no hay nada que manipular.

Consecuencia directa: la respuesta tampoco puede filtrar datos de clientes
ajenos, porque los datos del cliente se serializan **a través** de la orden
ya filtrada. No hay una consulta de clientes separada que pudiera devolver
más de lo debido.

Del cliente solo viaja identificación básica —código de abonado, tipo y
número de documento, y nombre para mostrar—. Teléfonos, correo y el resto de
la ficha no son necesarios para reconocer una orden en un listado y no se
envían.

---

## 6. Decisión: criterio de orden

```python
.order_by(F("scheduled_at").asc(nulls_last=True), "-created_at", "pk")
```

**Por fecha programada ascendente, lo más próximo primero.** Es el orden útil
para un técnico en campo, que mira su jornada. `Meta.ordering` del modelo
(`-created_at`) responde a otra necesidad: la bandeja de despacho mira lo
recién ingresado, y por eso el endpoint no lo hereda.

- **Nulos al final.** Una OT sin fecha programada no debe encabezar la lista
  por delante de las que tienen hora fijada.
- **Desempate explícito por `pk`.** Con dos órdenes de la misma fecha, un
  orden no determinista puede repetir o saltar filas cuando se pagine.
- **No se ordena por prioridad.** `priority` es un `CharField` con choices:
  alfabéticamente daría `HIGH, LOW, NORMAL, URGENT`, un orden sin sentido
  operativo. Hacerlo correctamente exige anotar un peso numérico con
  `Case/When`, y queda registrado como **opción futura** —no como olvido— por
  si el área operativa pide que la urgencia mande sobre el horario.

---

## 7. Rendimiento

El `select_related()` replica el criterio de la bandeja web: todo lo que el
serializador pinta por fila se trae en la misma consulta.

```python
.select_related(
    "subscription",
    "subscription__customer",
    "subscription__service_type",
    "subscription__plan",
    "order_type",
    "subtype",
)
```

Se recorta a lo que este endpoint realmente serializa: no arrastra `branch`,
`zone` ni `assigned_technician` —que la bandeja sí necesita— porque aquí no
se exponen (el técnico es siempre el usuario autenticado).

La prueba `test_query_count_does_not_grow_with_the_number_of_orders` mide la
línea base con una orden y exige el **mismo** número de consultas con siete,
en lugar de fijar un número absoluto: lo que importa es que el costo no
dependa del tamaño del listado. Si alguien quita un `select_related`, la
segunda medición se dispara y la prueba falla.

---

## 8. Pruebas

`apps/work_orders/tests/test_api_my_orders.py`, sobre el escenario base de
`apps/work_orders/tests/base.py`.

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | Técnico con OT asignadas | 200, solo las suyas |
| 2 | Técnico sin OT asignadas | 200, lista vacía |
| 3 | OT de otro técnico (y OT sin asignar) | No aparecen |
| 4 | Usuario autenticado no técnico | 403 |
| 5 | Sin token | 401 |
| 6 | Varias OT | Mismo número de consultas, sin N+1 |
| — | Campos de la respuesta | Los acordados, sin datos operativos |
| — | Criterio de orden | Fecha programada asc., nulos al final |
| — | Técnico desactivado con token vivo | 401 |
| — | Técnico movido a otro rol | 403 |

---

## 9. Pendiente explícito: filtro por sede y zona

**No se filtra por sede ni zona, y es una decisión, no un olvido.** La sede
del técnico es referencia operativa y no una restricción de elegibilidad
—ya decidido en el bloque de asignación, donde un técnico activo de otra sede
sigue siendo elegible para una orden de cualquier sede—. Por coherencia, «Mis
órdenes» lista todo lo asignado al técnico sin importar la sede.

El filtro por sede/zona es alcance del **bloque 2 del roadmap (App del
técnico)**, no de este bloque de cimientos.

## 10. Qué NO se tocó

- `WorkOrderDispatchListView` y las plantillas de la bandeja de despacho web.
- `apps/customers`.
- El modelo `WorkOrder`, `ALLOWED_TRANSITIONS` y `STARTABLE_STATUSES`.
- Ninguna migración nueva.

El único cambio sobre código del día 1 es la extracción de
`is_active_technician()` en `apps/accounts/services.py` —exigida por el
alcance para no duplicar la condición— y el permiso añadido a
`TechnicianMeView`, documentado en §3.1.
