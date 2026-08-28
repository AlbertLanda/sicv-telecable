# API del técnico: inicio de atención

Documentación técnica del primer endpoint de **escritura** del canal de API del
técnico en SICV (SICV — Telecable / Fiber The Andes).

Continúa los cimientos de los días anteriores:
[`api_technician_auth.md`](api_technician_auth.md) (autenticación) y
[`api_technician_work_orders.md`](api_technician_work_orders.md) (listado y
detalle). El dominio de la transición —estados, matriz e historial— está en
[`work_orders_workflow.md`](work_orders_workflow.md); la pantalla web
equivalente, en
[`work_orders_start_attention.md`](work_orders_start_attention.md).

---

## 1. Principio: la API es un canal, no una segunda implementación

```
POST /api/technicians/work-orders/<id>/start/
      ↓
IsActiveTechnician        ← ¿puedes operar en este canal?
      ↓
CanStartWorkOrder         ← ¿puedes ejecutar ESTA acción?
      ↓
queryset filtrado         ← ¿es tuya esta orden?   (404 uniforme)
      ↓
start_order_attention()   ← MISMA función que ejecuta la web
      ↓
WorkOrder.start_attention() → matriz de transiciones + historial
```

Las cuatro primeras capas son del canal; la quinta es el dominio. **Ninguna
regla de negocio vive en la vista**: no comprueba si la orden es iniciable, no
conoce `STARTABLE_STATUSES` y no redacta el mensaje de rechazo. Lo intenta y
traduce a HTTP lo que el dominio conteste, exactamente como hace
`WorkOrderStartAttentionView` en la web.

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `apps/work_orders/api/permissions.py` | `CanStartWorkOrder` — envuelve el permiso Django ya existente |
| `apps/work_orders/api/serializers.py` | `WorkOrderStartAttentionSerializer` |
| `apps/work_orders/api/views.py` | `TechnicianWorkOrderObjectMixin`, `StartWorkOrderAttentionView` |
| `apps/work_orders/api/urls.py` | Ruta `work_orders_api:start_attention` |
| `apps/work_orders/tests/test_api_start_attention.py` | Pruebas del endpoint |

No hay migraciones: el permiso `work_orders.start_workorder` ya existe desde la
migración 0011 y no se creó ninguno nuevo. Tampoco se tocó el modelo.

---

## 3. Endpoint `POST /api/technicians/work-orders/<id>/start/`

**Petición** — el body es opcional y solo admite un campo:

```json
{ "remarks": "Cliente confirmó acceso al domicilio." }
```

**Respuesta 200** — la ficha del día 3 ya actualizada:

```json
{
  "id": 17,
  "order_number": "OT-API-0001",
  "status": "IN_PROGRESS",
  "status_display": "En atención",
  "...": "resto de WorkOrderDetailSerializer"
}
```

| Situación | Código |
|---|---|
| OT propia y elegible, con permiso | 200, pasa a `IN_PROGRESS` |
| Estado no iniciable | 400 con el mensaje del dominio |
| Sin `work_orders.start_workorder` | 403 |
| OT de otro técnico o id inexistente | 404 idéntico |
| Sin token | 401 |
| `GET`, `PUT`, `PATCH`, `DELETE` | 405 |

### 3.1 Decisión: verbo en la ruta, no `PATCH` sobre el detalle

Iniciar la atención es una **transición del proceso con su propio permiso**, no
la edición de un campo. Un `PATCH {"status": "IN_PROGRESS"}` invitaría
justamente a lo contrario: que el cliente nombre el estado destino. Aquí el
cliente pide la *acción* y el dominio decide el estado.

### 3.2 La respuesta reutiliza `WorkOrderDetailSerializer`

No se inventó una respuesta nueva. El técnico que acaba de iniciar necesita ver
la orden actualizada, y esa forma ya está definida y probada desde el día 3;
devolver algo distinto obligaría al cliente a mantener dos parsers para la
misma entidad.

**Pendiente explícito:** el detalle no expone `started_at`. La hora real de
inicio queda registrada en el modelo y en el historial, pero no viaja en la
respuesta. No se agregó porque el alcance del día pedía reutilizar el
serializador tal cual, y ampliarlo es una decisión del día 3, no de hoy.

---

## 4. Autorización: tres capas y un orden que importa

```python
permission_classes = [IsAuthenticated, IsActiveTechnician, CanStartWorkOrder]
```

Ninguna suple a otra. `IsActiveTechnician` responde «¿puedes operar en este
canal?» y `CanStartWorkOrder` responde «¿puedes ejecutar esta acción?». Un
técnico activo puede ver su OT en el detalle y aun así no poder iniciarla: son
preguntas distintas, y por eso se declaran por separado en vez de fusionarse en
un único permiso «técnico que puede iniciar».

`CanStartWorkOrder` envuelve el permiso Django que **ya usa la web**
(`WorkOrderStartAttentionView.permission_required`). No se creó uno propio para
la API: si operaciones se lo retira a alguien, se lo retira en los dos canales
a la vez. No se usó `DjangoModelPermissions` porque mapea permisos a métodos
HTTP sobre un modelo (`add`/`change`/`delete`), y traducir «iniciar atención» a
`change_workorder` diluiría la distinción que el módulo mantiene a propósito.

### 4.1 El permiso se evalúa antes de resolver la orden

Es deliberado y es la misma decisión ya documentada en la vista web. Si la
orden se resolviera primero, un técnico **sin** el permiso recibiría 404 en una
OT ajena y 403 en la propia — y esa diferencia le diría cuáles existen. Con
este orden recibe **403 para cualquier id** y no aprende nada.

Fijado por `test_missing_permission_never_reveals_which_orders_exist`, que
recorre los tres casos —propia, ajena e inexistente— y exige 403 en los tres.

El 404 uniforme para quien **sí** tiene el permiso se hereda del queryset, sin
código propio: `StartWorkOrderAttentionView` extiende
`TechnicianWorkOrderObjectMixin`, el mismo que usa el detalle. Eso convirtió el
«no enumerar» en una propiedad del canal en lugar de una decisión que cada
vista nueva deba recordar implementar.

---

## 5. El dominio decide; la vista traduce

```python
try:
    start_order_attention(order, user=request.user, remarks=...)
except ValidationError as exc:
    order.refresh_from_db()
    return Response({"detail": " ".join(exc.messages)}, status=400)
```

- **Se llama al servicio, no al modelo.** `start_order_attention()` invoca
  `WorkOrder.start_attention()` *y además* mueve la suscripción de preventa a
  «En instalación» cuando la orden es una instalación. Llamar al modelo
  directamente compilaría igual y dejaría ese efecto fuera —un error silencioso
  que solo aparecería en facturación—. La prueba
  `test_the_service_is_used_not_just_the_model` verifica ese efecto colateral
  precisamente porque es lo único que distingue una llamada de la otra.
- **La vista no pregunta si la orden es iniciable.** Lo intenta y deja que el
  dominio acepte o rechace. Una comprobación previa sería una segunda matriz de
  estados con fecha de caducidad.
- **El mensaje es del dominio.** Ya está redactado para el operador y no expone
  trazas internas. Se unen los mensajes en una cadena para que `detail` tenga el
  mismo tipo que en el resto de errores del canal (401, 403, 404) y el cliente
  no tenga que distinguir entre texto y lista según el código.
- **`refresh_from_db()` antes de responder el 400.** El servicio es atómico, así
  que no quedó nada a medias; se relee para no serializar un objeto en memoria
  que no refleje la base de datos.

---

## 6. Entrada: un solo campo, y lo que no es campo

```python
class WorkOrderStartAttentionSerializer(serializers.Serializer):
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
```

Mismo contrato que `WorkOrderStartAttentionForm`, que ya lo documenta como el
que «deberá aceptar la futura API del técnico».

**Lo que no declara es tan importante como lo que declara.** `status`,
`started_at` y `assigned_technician` no son campos, de modo que un POST que los
incluya no los cuela: DRF los descarta al validar y el servicio nunca los ve. No
hace falta una lista negra ni un filtrado explícito — la protección es
estructural. `test_client_cannot_influence_the_outcome` envía los tres
manipulados y comprueba que el estado lo decidió la matriz, la hora la puso
`timezone.now()` y el técnico asignado no se movió.

---

## 7. Pruebas

`apps/work_orders/tests/test_api_start_attention.py`, sobre el escenario base
de `apps/work_orders/tests/base.py`.

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | OT propia `ASSIGNED` con permiso | 200, pasa a `IN_PROGRESS` |
| 2 | Técnico sin `start_workorder` | 403, orden sin cambios |
| 3 | OT de otro técnico | 404 idéntico al id inexistente |
| 4 | Estado no iniciable | 400 con mensaje de dominio, orden intacta |
| 5 | Body con `remarks` | Queda en el historial, con el técnico como responsable |
| 6 | Body con `status`/`assigned_technician` | Ignorado; no cambia el resultado |
| — | Sin permiso, sobre cualquier id | 403 en los tres casos (no enumera) |
| — | ATC con el permiso concedido | 403 por canal: las capas no están fusionadas |
| — | Sin token | 401 |
| — | Rechazo del dominio | No agrega entradas al historial |
| — | Instalación en preventa | La suscripción pasa a «En instalación» |
| — | `remarks` ausente | 200, observación vacía |
| — | `GET`/`PUT`/`PATCH`/`DELETE` | 405 |

El escenario 7 de la actividad —suite completa sin regresión— se cubre con
`python manage.py test`.

---

## 8. Pendiente explícito: PENDING no produce 400

La actividad cita `PENDING` como ejemplo de estado no iniciable. En este
proyecto **una orden en `PENDING` todavía no tiene técnico asignado**, así que
el filtro por técnico la excluye antes de llegar al dominio y la respuesta
correcta es el 404 uniforme, no el 400.

El escenario 4 se cubre entonces con una orden ya iniciada (`IN_PROGRESS`) y
con una atendida (`ATTENDED`), que sí son propias del técnico y sí llegan al
rechazo del dominio. `test_pending_order_is_not_reachable` deja documentado el
caso `PENDING` y su 404, para que la diferencia sea una decisión registrada y
no un hueco.

---

## 9. Qué NO se tocó

- `WorkOrder.start_attention()`, `STARTABLE_STATUSES` y `ALLOWED_TRANSITIONS`.
- `start_order_attention()`: se consume, no se modifica.
- `WorkOrderStartAttentionView` ni ningún template web.
- `WorkOrderListSerializer` ni `WorkOrderDetailSerializer`: el endpoint reutiliza
  el segundo para responder.
- Ninguna migración nueva; ningún permiso nuevo.

Lo único que cambió del día 3 es que el `select_related` de ficha y el 404 en
español se subieron de `MyWorkOrderDetailView` a
`TechnicianWorkOrderObjectMixin`, para que el endpoint de hoy los herede en vez
de copiarlos. El detalle no cambió de comportamiento y sus pruebas siguen
pasando sin modificación.

---

## 10. Siguiente paso

Día 5: endpoint para **atender/cerrar** una OT (causa y resultado) envolviendo
`attend_order()`, con el mismo criterio de reutilización de dominio.
