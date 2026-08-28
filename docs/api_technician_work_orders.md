# API del técnico: permiso funcional, «Mis órdenes» y detalle de una OT

Documentación técnica del permiso `IsActiveTechnician` y de los dos endpoints
de lectura del canal de API del técnico en SICV (SICV — Telecable / Fiber The
Andes): el listado de órdenes asignadas y la ficha de una orden concreta.

Continúa el cimiento del día anterior, documentado en
[`api_technician_auth.md`](api_technician_auth.md). La primera acción de
escritura del canal —el inicio de atención, que reutiliza el queryset y el
serializador de aquí— está en
[`api_technician_start_attention.md`](api_technician_start_attention.md). El dominio de las órdenes
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
List / DetailSerializer       ← solo lectura, sin acciones
```

Las tres primeras capas son **compartidas** por el listado y el detalle
(`TechnicianWorkOrdersMixin`), y esa es justamente la razón de que el detalle
no necesite ninguna comprobación de propiedad propia: lo que no es tuyo no
llega a existir para la vista.

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
| `apps/work_orders/api/serializers.py` | `WorkOrderListSerializer`, `WorkOrderDetailSerializer`, `WorkOrderCustomerSerializer`, `WorkOrderAddressSerializer` |
| `apps/work_orders/api/views.py` | `TechnicianWorkOrdersMixin`, `TechnicianWorkOrderObjectMixin`, `MyWorkOrderListView`, `MyWorkOrderDetailView` |
| `apps/work_orders/api/urls.py` | Rutas `work_orders_api:my_orders` y `work_orders_api:my_order_detail` |
| `config/urls.py` | Prefijo `api/technicians/work-orders/` |
| `apps/work_orders/tests/test_api_my_orders.py` | Pruebas del listado |
| `apps/work_orders/tests/test_api_work_order_detail.py` | Pruebas del detalle |

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

## 5. Endpoint `GET /api/technicians/work-orders/<id>/`

Ficha de una OT propia. Un `RetrieveAPIView` sobre el mismo queryset filtrado
del listado.

**Respuesta 200**

```json
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
  "created_at": "2026-08-27T09:12:44-05:00",
  "address": {
    "address": "Av. Los Álamos 123",
    "reference": "Frente al parque",
    "district": "Chachapoyas",
    "latitude": "-6.2290000",
    "longitude": "-77.8690000",
    "gps_link": ""
  },
  "detail": "El cliente reporta intermitencia desde el lunes.",
  "branch": "Sede Central",
  "zone": "Zona Norte"
}
```

| Situación | Código |
|---|---|
| OT propia | 200 |
| OT de otro técnico | 404 |
| Id inexistente | 404, idéntico al anterior |
| Usuario autenticado sin rol técnico | 403 |
| Sin token | 401 |
| `POST`, `PUT`, `PATCH`, `DELETE` | 405 |

### 5.1 El detalle **extiende** al listado, no lo reescribe

```python
class WorkOrderDetailSerializer(WorkOrderListSerializer):
    class Meta(WorkOrderListSerializer.Meta):
        fields = WorkOrderListSerializer.Meta.fields + [
            "address", "detail", "branch", "zone",
        ]
```

Hereda campos, `Meta` y el criterio de choices. Dos consecuencias buscadas: el
listado del día 2 no puede romperse desde el detalle, y un campo que mañana se
agregue a la fila aparece en la ficha sin tocar dos sitios. `created_at` ya
venía en el listado, así que la ficha lo tiene por herencia y no se declara
dos veces.

Ninguno de los campos nuevos tiene choices, de modo que el criterio «código
estable + etiqueta legible» sigue aplicando exactamente donde aplicaba:
`status` y `priority`.

`zone` se declara con `allow_null=True` porque `WorkOrder.zone` es opcional en
el modelo; sin eso, una orden sin zona respondería 500 en lugar de `null`.

### 5.2 Decisión: qué dirección es «la dirección de atención»

Sale de `subscription.address`, la dirección vigente del servicio, y viaja en
un bloque propio con lo necesario para llegar y confirmar el punto —calle,
referencia, distrito y coordenadas—. No se exponen `is_primary`, `is_active`
ni el resto de la ficha: son datos de administración del cliente, no de
atención en campo.

Se usa un `Serializer` plano y no un `ModelSerializer` de `CustomerAddress`,
por la misma razón que en `WorkOrderCustomerSerializer`: `apps/customers` está
fuera de alcance y la forma de la respuesta se decide en el canal técnico.

**Pendiente explícito.** En un **traslado externo** el técnico debe
presentarse en `TransferDetail.new_address`, no en la dirección vigente de la
suscripción. El alcance de hoy no lo cubre y se deja anotado en el código y
aquí como pendiente funcional, no como olvido.

---

## 6. El 404 uniforme: por qué no hay 403 ni comprobación de propiedad

`RetrieveAPIView` resuelve el objeto con `get_object_or_404` **sobre el
queryset ya filtrado por técnico**. Por eso «no existe» y «es de otro técnico»
recorren el mismo camino de código y devuelven la misma respuesta: para esta
vista una orden ajena sencillamente no está en el universo consultado. El 404
uniforme no se programa, se hereda del filtro.

Deliberadamente **no** existe `has_object_permission` ni ninguna comprobación
posterior sobre el objeto ya resuelto. Un chequeo así devolvería 403, y un 403
confirma que la orden existe y es de otro: es exactamente la enumeración que
el login del día 1 evita al no distinguir usuario inexistente de contraseña
incorrecta. La seguridad vive en el queryset, no en un permiso que llega tarde.

El orden de evaluación refuerza la separación: el permiso de canal decide
antes de que se intente resolver la orden, así que un usuario no técnico
recibe 403 aun apuntando a un id inexistente. Ese 403 informa sobre el
usuario, no sobre la existencia de la OT
(`test_permission_is_evaluated_before_the_object`).

La prueba que fija el criterio de aceptación no compara solo códigos:
`test_foreign_order_and_unknown_id_are_indistinguishable` exige **mismo código
y mismo cuerpo**. Si mañana alguien agregara un mensaje del tipo «no tienes
acceso a esta orden», la prueba lo detiene.

Desde el día 4, el `select_related` de ficha y este 404 viven en
`TechnicianWorkOrderObjectMixin`, un mixin intermedio entre el base y las
vistas que operan sobre **una** orden. Así el endpoint de inicio de atención
hereda el mismo 404 en lugar de copiarlo, y el «no enumerar» pasa a ser una
propiedad del canal en vez de una decisión que cada vista nueva deba recordar.

### 6.1 Lo único que se ajusta a mano: el texto del 404

```python
def get_object(self):
    try:
        return super().get_object()
    except Http404:
        raise NotFound()          # -> {"detail": "No encontrado."}
```

Django emite `Http404` con el mensaje «No WorkOrder matches the given query.»
y DRF 3.18 lo propaga tal cual al cliente. Dos problemas: va en inglés,
mientras el resto del canal responde en español (`"Credenciales inválidas."`,
`"Se requiere un usuario con rol técnico activo."`), y **nombra el modelo
interno**, un detalle de implementación que el cliente no necesita.

No cambia la lógica de autorización: sigue siendo un único `raise` para los
dos casos, así que las respuestas continúan siendo indistinguibles. Se corrige
qué cuenta el mensaje, no cuándo se emite. Fijado por
`test_not_found_message_is_the_project_standard`, que comprueba el mismo
cuerpo para la orden ajena y para la inexistente.

---

## 7. Seguridad: el filtro es del servidor

```python
class TechnicianWorkOrdersMixin:
    permission_classes = [IsAuthenticated, IsActiveTechnician]

    def get_queryset(self):
        return WorkOrder.objects.filter(
            assigned_technician=self.request.user
        ).select_related(...)
```

Las vistas **no leen ningún parámetro de la petición** para decidir de quién
son las órdenes. No existe un `?technician=` que validar, ni un id que
comparar contra el usuario, porque el técnico sale de `request.user` y de
ningún otro sitio. En el detalle el id **sí** viaja en la URL, pero solo
selecciona dentro de lo que ya es del técnico: no hay nada que manipular para
alcanzar una orden ajena.

**El filtro vive en un solo sitio a propósito.** Es la única línea que impide
que un técnico vea las órdenes de otro; copiarla en el detalle significaría
que un cambio futuro del criterio —filtrar también por sede, excluir órdenes
liquidadas— podría aplicarse en un endpoint y olvidarse en el otro, que es
exactamente la clase de desalineación que abre un hueco de visibilidad. Por la
misma razón el mixin trae también `permission_classes`.

Consecuencia directa: la respuesta tampoco puede filtrar datos de clientes
ajenos, porque los datos del cliente se serializan **a través** de la orden
ya filtrada. No hay una consulta de clientes separada que pudiera devolver
más de lo debido.

Del cliente solo viaja identificación básica —código de abonado, tipo y
número de documento, y nombre para mostrar—. Teléfonos, correo y el resto de
la ficha no son necesarios para reconocer una orden en un listado y no se
envían.

---

## 8. Decisión: criterio de orden

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

## 9. Rendimiento

El `select_related()` replica el criterio de la bandeja web: todo lo que el
serializador pinta se trae en la misma consulta.

```python
# En el mixin: lo que necesita WorkOrderListSerializer, base de ambos.
.select_related(
    "subscription",
    "subscription__customer",
    "subscription__service_type",
    "subscription__plan",
    "order_type",
    "subtype",
)

# El detalle encadena encima solo lo suyo:
.select_related("subscription__address", "branch", "zone")
```

La base es compartida porque el serializador de detalle **extiende** al de la
lista: todo lo que pinta la fila lo pinta también la ficha, así que las mismas
relaciones hacen falta en los dos. Lo que solo usa la ficha se encadena en su
propia vista y **no se le cobra al listado**: `branch`, `zone` y la dirección
no se exponen por fila, y `assigned_technician` no se expone en ninguno de los
dos (el técnico es siempre el usuario autenticado).

La prueba `test_query_count_does_not_grow_with_the_number_of_orders` mide la
línea base con una orden y exige el **mismo** número de consultas con siete,
en lugar de fijar un número absoluto: lo que importa es que el costo no
dependa del tamaño del listado. Si alguien quita un `select_related`, la
segunda medición se dispara y la prueba falla.

---

## 10. Pruebas

Sobre el escenario base de `apps/work_orders/tests/base.py`.

### 10.1 Listado — `test_api_my_orders.py`

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

### 10.2 Detalle — `test_api_work_order_detail.py`

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | OT propia | 200 con los campos de detalle |
| 2 | OT de otro técnico | 404, nunca 403 |
| 3 | Id inexistente | 404 |
| — | Ajena vs. inexistente | **Mismo código y mismo cuerpo** |
| — | Mensaje del 404 | `{"detail": "No encontrado."}`, no el de Django |
| — | OT sin técnico asignado | 404 |
| 4 | Sin token | 401 |
| 5 | Usuario autenticado no técnico | 403 |
| — | No técnico sobre id inexistente | 403 (el permiso decide primero) |
| — | Técnico movido a otro rol | 403 |
| — | Campos de la respuesta | Los de la lista más `address`, `detail`, `branch`, `zone` |
| — | Dirección de atención | Solo los campos útiles en campo |
| — | Choices heredados | Código + etiqueta |
| — | OT sin zona | `zone: null`, sin error |
| — | `POST`/`PUT`/`PATCH`/`DELETE` | 405 |

El escenario 6 de la actividad —suite completa sin regresión— se cubre con
`python manage.py test`.

---

## 11. Pendiente explícito: filtro por sede y zona

**No se filtra por sede ni zona, y es una decisión, no un olvido.** La sede
del técnico es referencia operativa y no una restricción de elegibilidad
—ya decidido en el bloque de asignación, donde un técnico activo de otra sede
sigue siendo elegible para una orden de cualquier sede—. Por coherencia, «Mis
órdenes» lista todo lo asignado al técnico sin importar la sede.

El filtro por sede/zona es alcance del **bloque 2 del roadmap (App del
técnico)**, no de este bloque de cimientos.

## 12. Qué NO se tocó

- `WorkOrderDispatchListView` y las plantillas de la bandeja de despacho web.
- `apps/customers`.
- El modelo `WorkOrder`, `ALLOWED_TRANSITIONS` y `STARTABLE_STATUSES`.
- `IsActiveTechnician`: el detalle **reutiliza** el permiso del día 2, no se
  creó uno nuevo.
- Ninguna migración nueva.

El único cambio sobre código del día 1 es la extracción de
`is_active_technician()` en `apps/accounts/services.py` —exigida por el
alcance para no duplicar la condición— y el permiso añadido a
`TechnicianMeView`, documentado en §3.1.

`WorkOrderListSerializer` no cambió: el detalle lo extiende. Lo único que se
movió del día 2 es el queryset base y `permission_classes`, que pasaron de
`MyWorkOrderListView` al mixin compartido —sin alterar el comportamiento del
listado, que sus pruebas siguen fijando—.
