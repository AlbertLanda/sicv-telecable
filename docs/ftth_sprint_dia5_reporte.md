# Reporte diario — Sprint FTTH · Día 5

**Formato del plan de trabajo §7.**

| | |
|---|---|
| **Fecha** | 02 / 09 / 2026 |
| **Jornada del plan** | Día 5 — «Claim, seguridad y concurrencia» |
| **Colaborador** | Kevin Rivera |
| **Frente** | Dominio Work Orders / API del Técnico |
| **Rama** | `feature/ftth-api-tecnico-mvp` |
| **Commit** | `0fe32e6` — `feat: claim atomico de ordenes del canal tecnico dia 5 sprint ftth` |
| **Base** | `035533f` (= `origin/develop` al inicio de la jornada, tras `git fetch` + fast-forward) |

---

## 1. Entregable del día

**Toma (claim) de la OT disponible, atómica y segura**, más el hardening de
ubicación y la preparación del contrato de datos técnicos que pidió el líder
técnico en la misma jornada.

| Entregable comprometido (plan) | Estado |
|---|---|
| Claim funcional | ✅ `POST /api/technicians/work-orders/<id>/claim/` |
| Tests concurrentes / atómicos | ✅ 3 pruebas dedicadas (bloqueo pedido, carrera, nada a medias) |
| Permisos | ✅ 4 capas evaluadas por separado; permiso de acción cableado y probado |

**Alcance añadido en la jornada** (instrucción del líder técnico, adelanta
parte del hardening del día 6):

- Detalle de OT preparado para datos técnicos (`technical_data`, solo lectura).
- Ubicación saneada: dirección textual siempre, `0 / 0.0000000` nunca como GPS.
- Confirmación explícita de que la OT es **una sola** `WorkOrder`, sin modelo
  espejo, y de que el técnico solo puede escribir su parte.
- Contrato compartido documentado para consumo de Joleydi.

---

## 2. Endpoints y dominio afectados

**Endpoint nuevo**

| Método y ruta | Éxito | Errores |
|---|---|---|
| `POST /api/technicians/work-orders/<id>/claim/` | `200` ficha ya asignada | `401` · `403` · `409` no disponible · `405` otros métodos |

**Dominio: sin cambios.** `apps/work_orders/models.py` y
`apps/work_orders/services.py` quedan **idénticos** a develop. La transición la
ejecuta `WorkOrder.assign_technician()`, el mismo método que usa la bandeja de
despacho web. **Cero migraciones**, cero estados nuevos, cero modelos nuevos.

Lo único que la vista añade sobre el dominio es el **bloqueo de fila**, que
cierra el hueco documentado en la auditoría del día 1 §2.3
(`assign_technician()` es atómico pero no bloquea la fila).

**Archivos**

| Archivo | Cambio |
|---|---|
| `apps/work_orders/api/views.py` | `ClaimWorkOrderView` + `OBJECT_RELATIONS` compartido |
| `apps/work_orders/api/permissions.py` | **nuevo** — `CanClaimWorkOrder` + `CLAIM_PERMISSION` (B3) |
| `apps/work_orders/api/serializers.py` | `WorkOrderClaimSerializer`, `WorkOrderTechnicalDataSerializer`, ubicación saneada, campos de trabajo en el detalle |
| `apps/work_orders/api/urls.py` | ruta `<int:pk>/claim/` |
| `apps/customers/coordinates.py` | **nuevo** — definición única de coordenada válida |
| `apps/customers/models.py` | propiedades `map_latitude` / `map_longitude` / `map_link` (sin migración) |
| `apps/customers/templates/customers/detail.html` | la ficha de ATC usa las propiedades saneadas |
| `apps/work_orders/tests/test_api_claim.py` | **nuevo** — 28 pruebas |
| `apps/customers/test_coordinates.py` | **nuevo** — 13 pruebas |
| `apps/work_orders/tests/test_api_work_order_detail.py` | +12 pruebas |
| `docs/api_technician_claim.md` | **nuevo** — contrato y decisiones de la toma |
| `docs/orden_tecnica_contrato_compartido.md` | **nuevo** — coordinación con Joleydi |
| `docs/api_technician_work_orders.md` | actualizado + 2 correcciones de lo previsto el día 3 |

---

## 3. Decisiones técnicas de la jornada

1. **El filtro de disponibilidad viaja DENTRO del `select_for_update()`.** Ahí
   está toda la garantía: el ganador toma el lock con la orden aún disponible;
   el perdedor espera y, al liberarse, ya no encuentra una fila que cumpla el
   filtro → `409`. Comprobarlo antes o después del bloqueo dejaría la carrera
   abierta.

2. **`of=("self",)`** — no previsto el día 3. El filtro por `order_type__code`
   obliga a un JOIN con el catálogo, y un `FOR UPDATE` sin `of` bloquearía
   también esa fila: como todas las instalaciones comparten el mismo
   `OrderType`, cada toma esperaría a la anterior **en todo el sistema**.

3. **La toma no puede heredar de `TechnicianWorkOrderObjectMixin`** —
   corrección de lo que anticipaba el documento del día 3. Ese mixin filtra por
   `assigned_technician = request.user` y una orden tomable no tiene técnico
   asignado: heredarlo daría universo vacío y **ninguna orden podría tomarse
   nunca**. Resuelve contra `available_work_orders()`, el mismo universo que
   publica `available/`.

4. **`409` uniforme para todo lo no tomable** (inexistente, ajena, ya tomada,
   otro estado, otro tipo): mismo código y mismo cuerpo, por el mismo principio
   de no enumeración que el `404` del detalle.

5. **Una sola definición de «disponible», reutilizada.** El listado y la toma
   consumen `available_work_orders()`. De ahí salen gratis dos protecciones que
   no hay que programar: una orden con dueño no es tomable y una `SYSTEM` de
   NOC tampoco.

6. **La regla de coordenadas vive en un solo módulo** y la consumen la API del
   técnico y la ficha de ATC. `gps_link` se **deriva** de las coordenadas en
   lugar de leerse de la base de datos, porque el enlace almacenado pudo
   construirse sobre un `0,0`.

---

## 4. Tests ejecutados

```
manage.py check ............................ OK (0 issues)
makemigrations --check --dry-run ........... OK (No changes detected)
test_api_claim (nuevo) ..................... Ran 28 tests — OK
test_coordinates (nuevo) ................... Ran 13 tests — OK
test_api_work_order_detail (+12) ........... Ran 28 tests — OK
Suite GLOBAL ............................... Ran 536 tests — OK (exit 0)
```

53 pruebas nuevas. Suite global en verde, que es la exigencia del plan antes de
la entrega final.

> **Nota de tiempos:** la suite global tarda ~34 min porque `WorkOrderTestCase`
> crea ~8 usuarios por prueba y Django hashea cada contraseña con PBKDF2. No es
> la lógica: es el `setUp`. Se reduciría a ~3 min declarando un hasher rápido
> solo para la suite. **No lo apliqué** porque `config/settings.py` es
> compartido y CI ya se ajustó esta madrugada — queda como propuesta.

### 4.1 Escenarios de prueba mínimos del plan (§6)

| Criterio de control | Resultado | Evidencia / observación |
|---|---|---|
| Una `Subscription` válida genera una OT `INSTALLATION` con correlativo oficial y estado `PENDING` | **CUMPLE** | `test_ftth_installation_publication.py`, `test_ftth_installation_uniqueness.py`. **Obs:** el servicio está listo y blindado; el llamador desde la UI comercial es la tarea de Joleydi — hoy `git grep create_installation_work_order` solo encuentra pruebas |
| La OT aparece en `available` inmediatamente después de su creación | **CUMPLE** | `test_pending_unassigned_field_installation_is_available` |
| Un técnico autenticado puede listar disponibles y sus propias órdenes | **CUMPLE** | `test_api_available_orders.py`, `test_api_my_orders.py` |
| Un técnico no puede enumerar ni leer una OT privada de otro | **CUMPLE** | `test_foreign_order_and_unknown_id_are_indistinguishable`, `test_unknown_order_is_indistinguishable_from_an_unavailable_one`, `test_another_technicians_technical_data_is_unreachable` |
| El claim ignora cualquier técnico enviado por el cliente y usa `request.user` | **CUMPLE** | `test_the_client_cannot_decide_the_technician_or_the_status` |
| Claim cambia `PENDING → ASSIGNED` mediante el dominio oficial | **CUMPLE** | `test_claim_records_the_transition_in_the_history` — el registro de historial solo existe si pasó por `change_status()` |
| Dos técnicos tomando la misma OT no pueden quedar ambos como responsables | **CUMPLE** | `test_the_loser_of_the_race_gets_the_unavailable_response` + `test_the_claim_locks_only_the_work_order_row`. **Obs:** SQLite ignora `FOR UPDATE`, así que el paralelismo real no es reproducible en el entorno de pruebas; se verifica que el bloqueo **se pide** (y limitado a la OT) y el resultado observable de la carrera |
| Una OT ya asignada no puede ser reclamada nuevamente como si estuviera disponible | **CUMPLE** | `test_order_already_taken_by_another_technician_is_not_stolen`, `test_second_claim_of_the_same_order_is_rejected` |
| Filtros de sede/zona no se convierten en restricciones duras | **CUMPLE** | `test_order_from_another_branch_can_be_claimed`, `test_technician_without_branch_can_claim`, `test_scope_all_shows_every_branch` |
| Tests específicos, módulo, `check`, `makemigrations --check` y suite | **CUMPLE** | §4 |

---

## 5. Prompt Claude Code de la jornada

Registro exigido por el plan («registrar diariamente el prompt o instrucción
principal utilizado»). Hoy hubo **dos** instrucciones, ambas recibidas por
mensajería y trasladadas literalmente a Claude Code:

**Prompt 1 — Albert Landa (05:10):**

> «Antes de continuar el sprint, hagan `git fetch origin` y actualicen sus ramas
> desde `origin/develop`. No continúen sobre la base de ayer. Esta madrugada se
> integraron las revisiones de alta comercial FTTH, suministro/GPS y API del
> técnico. […] Kevin: continuar con el flujo claim/tomar orden, usando la
> definición común de `available_work_orders()` y bloqueo transaccional. No
> hacer merge directo a develop.»

**Prompt 2 — líder técnico (misma jornada):**

> «Continúa desde el develop actualizado. Necesitamos avanzar el backend de la
> misma Orden Técnica que verá ATC y trabajará el técnico. Prioridad: claim
> atómico, detalle de OT para el técnico, aislamiento por usuario y preparar la
> API para los datos técnicos. La OT debe ser una sola `WorkOrder`. En
> ubicación, mantener siempre la dirección textual y tratar coordenadas vacías o
> `0 / 0.0000000` como inválidas, nunca como GPS válido. Coordina con Joleydi
> los campos que necesita su ficha. No hagas merge directo a develop.»

**Decisiones que produjeron** (detalle en §3): el `of=("self",)` del bloqueo, la
corrección de la herencia prevista para la vista de la toma, el `409` uniforme,
el aislamiento del permiso de acción en `CLAIM_PERMISSION` para no cerrar B3
por mi cuenta, y el módulo único de coordenadas en lugar de repetir la
validación en cada capa.

**Revisión humana:** el código fue leído y comprendido antes de entregarlo; las
dos correcciones al diseño previsto del día 3 (§3.2 y §3.3) salieron de esa
revisión y no del generador.

---

## 6. Bloqueos

| # | Bloqueo | Estado | Qué se necesita |
|---|---|---|---|
| **B3** | Permiso funcional de la toma | **Abierto — evidencia nueva** | Reutilizar `assign_workorder` (propuesta del día 1) daría a los técnicos la potestad de **despachar cualquier orden desde la web**: es el permiso de `WorkOrderAssignView` y el que pinta la acción «Asignar». Y `models.py:610` documenta la intención contraria. Crear `claim_workorder` exige migración → aprobación. Hoy autoriza el permiso de canal; cerrarlo es **una línea** en `api/permissions.py`, con prueba que fija el cableado |
| **B9** | ¿Idempotencia de la toma ante reintento del mismo técnico? | **Nuevo** | Hoy un segundo POST del propio dueño responde `409`. En campo el caso real no es el doble toque sino el **reintento por red intermitente**: la toma llegó, la respuesta se perdió. Recuperación documentada para la app: ante `409`, recargar «mis órdenes» |
| **GPS-entrada** | El `0,0` sigue **entrando** por la consulta de suministro | **Reportado, no corregido** | `distriluz_gps.py:164` decide con `if latitude and longitude`, y `"0"` es cadena no vacía. Las dos fichas ya lo filtran al publicar, pero la BD sigue acumulando ceros. El arreglo está escrito en `orden_tecnica_contrato_compartido.md` §3.1; cambia el contrato de esa función y arrastra `test_supply_lookup.py` y el formulario → **decisión de Joleydi o del líder**, no unilateral |
| **B5** | Punto de creación comercial | **Depende de Joleydi** | La fachada está lista; falta el llamador desde el resumen del contrato |
| **B6** | ¿Basta `branch` + `zone` + `district` para decidir antes de tomar? | Abierto | Confirmación de negocio |
| **Zona** | ¿Debe el sistema **sugerir** la Zona a partir del suministro? | **Nuevo, para negocio** | Distriluz devuelve distrito y GPS, no Zona: hoy ATC la elige a mano y de ella dependen la bandeja y el filtro de sede del técnico. Deducirla exigiría definir qué manda si distrito y GPS discrepan, y qué pasa sin GPS. **Se reporta, no se inventa** |

---

## 7. Pendiente para la siguiente jornada (día 6 — hardening e integración)

1. **Coordinación efectiva con Joleydi** sobre el contrato compartido: los 4
   puntos del §4 de `orden_tecnica_contrato_compartido.md`.
2. **Prueba integrada end-to-end** en cuanto exista su acción «Generar Orden de
   Instalación»: contratación → OT `PENDING` → `available` → `claim` → mis
   órdenes → detalle.
3. **Decisión sobre B3** para dejar el permiso cerrado antes de la demo del 07.
4. **Decisión sobre la entrada del GPS** (`distriluz_gps.py`).
5. **Evidencia visual**: capturas de la ficha de ATC con y sin GPS válido, y de
   la respuesta del claim. El backend es API; la única interfaz tocada es la
   ficha del cliente.
6. **Propuesta de hasher rápido para la suite** (§4), si el líder lo aprueba.
