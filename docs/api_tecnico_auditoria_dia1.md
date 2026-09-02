# Día 1 — Auditoría WorkOrder → API del técnico

**Sprint FTTH · Frente: Dominio Work Orders / API del Técnico**
**Colaborador:** Kevin Rivera · **Fecha:** 31/08/2026
**Rama:** `feature/ftth-api-tecnico-mvp` (partida de `develop` @ `d1e4fd8`)

Nota técnica del lunes. **No introduce cambios de dominio ni migraciones.** Su
objetivo es dejar auditado el dominio existente, definir el contrato de la API,
fijar la estrategia de seguridad y concurrencia, y decidir cómo reintegrar la
rama histórica `feature/api-tecnico-base` sin fusionarla. El código empieza a
escribirse el martes.

---

## 1. Baseline de validación

Antes de auditar se verificó que la rama parte de un estado limpio y coherente
con el dominio.

| Verificación | Resultado |
|---|---|
| Rama vs `origin/develop` | 0 commits detrás / 0 adelante · diff vacío (código idéntico) |
| `manage.py check` | System check identified no issues (0 silenced) |
| `makemigrations --check --dry-run` | No changes detected (modelos sin drift) |
| Suite `apps.work_orders` + `apps.accounts` | **280 tests OK** (exit 0) — ver sección 9 |

El `makemigrations --check` en verde confirma que los modelos del dominio
(`WorkOrder`, sus catálogos, `User`) están alineados con sus migraciones: no hay
campos declarados sin migrar ni migraciones huérfanas. Punto de partida válido
para auditar la lógica sin arrastrar deuda de esquema.

---

## 2. Auditoría del dominio existente

El dominio de órdenes **ya está construido y es sólido**. La API no debe crear
lógica de negocio nueva: debe **exponer** lo que ya existe. Nada de lo revisado
requiere modificación para el MVP.

### 2.1 Creación de la OT — `create_work_order()`

`apps/work_orders/services.py:190`. Punto de entrada único para registrar una
OT (documentado así en el propio módulo). Cumple ya todo el alcance 4.1 del
plan:

- Emite el correlativo oficial vía `generate_order_number()`
  (`services.py:40`), que reserva el número dentro de transacción con
  `select_for_update()` sobre `WorkOrderSequence`. Ya contempla el matiz
  PostgreSQL (bloqueo real de fila) vs SQLite (serialización de escrituras +
  `unique` en `order_number` como última barrera).
- Deja la orden en `Status.PENDING`.
- `created_by` sale **siempre** del usuario ejecutor; **rechaza**
  explícitamente `order_number` y `assigned_technician` enviados por el cliente.
- No toca la `Subscription`: una OT de instalación sobre una suscripción en
  `PRESALE` la deja en `PRESALE`.
- Todo dentro de una única transacción: si algo falla, no queda ni la orden ni
  el consumo del correlativo.

**Ya se invoca desde la web** en `apps/work_orders/views.py:96`
(`WorkOrderCreateView`). El flujo comercial FTTH de Joleydi debe terminar
llamando a **este mismo servicio** con `order_type` = `INSTALLATION`, no crear
la OT por otra vía. → coordinación del jueves.

`OrderType.code = "INSTALLATION"` existe en catálogo (también hay un
`DEMO-INSTALLATION` de datos de prueba que no debe usarse en el flujo real).

### 2.2 Modelo `WorkOrder` — estados y transiciones

`apps/work_orders/models.py:342`. Máquina de estados formal y centralizada:

- `Status`: PENDING, ASSIGNED, DERIVED, IN_PROGRESS, ATTENDED, LIQUIDATED,
  REPROGRAMMED, REJECTED, NOT_FEASIBLE, CANCELLED.
- `ALLOWED_TRANSITIONS` (matriz oficial), más los conjuntos derivados
  `ASSIGNABLE_STATUSES`, `STARTABLE_STATUSES`, `TERMINAL_STATUSES`,
  `ACTIVE_STATUSES`, `FINAL_STATUSES`.
- Transición **PENDING → ASSIGNED** habilitada. Es la que ejecuta el claim.
- `change_status()` es el único mutador de estado y registra
  `WorkOrderStatusHistory`. **Regla del plan:** nadie cambia estados a mano;
  todo pasa por el dominio.

### 2.3 Asignación — `WorkOrder.assign_technician()`

`apps/work_orders/models.py:780`. Método oficial de asignación/reasignación,
`@transaction.atomic`:

- Valida que el técnico exista, tenga rol `TECHNICIAN` y esté activo.
- Valida que la orden esté en `ASSIGNABLE_STATUSES`.
- Cierra la asignación vigente en `WorkOrderAssignment` (traza al técnico
  anterior, no lo sobrescribe) y abre una nueva.
- Si la orden no estaba en `ASSIGNED`, transiciona vía `change_status()`.

**Este es el método que el `claim` debe invocar.** No se implementa transición
nueva.

> **Hueco detectado (relevante para el claim):** `assign_technician()` es
> atómico pero **no bloquea la fila** de la orden — valida `self.status` sobre
> la instancia ya cargada en memoria. Dos claims concurrentes sobre la misma OT
> pueden leer ambos `PENDING` y pasar los dos. El cierre de este hueco es
> responsabilidad de la vista de claim (sección 6), no del método: se
> resuelve envolviendo la lectura en `select_for_update()`. No se propone
> modificar `assign_technician()`.

### 2.4 Inicio de atención — `start_order_attention()`

`apps/work_orders/services.py:295`. Envuelve `WorkOrder.start_attention()`
(`models.py:846`) y, además, si la orden es `INSTALLATION` y la suscripción
está en `PRESALE`, la promueve a `INSTALLATION`. Este segundo efecto es la
razón por la que la API **debe llamar al servicio y no al método del modelo
directamente**.

### 2.5 Identidad y permisos

- **No existe un modelo de "técnico" propio.** `apps/technicians/models.py`
  está vacío. La identidad técnica es `accounts.User` con `role = TECHNICIAN` +
  `branch`/`office`. No se crea modelo nuevo (alcance 4.3 lo confirma:
  `assigned_technician` como responsable único para el MVP).
- Permisos funcionales ya declarados en `WorkOrder.Meta`
  (`models.py:615`, migraciones 0010/0011): `assign_workorder` y
  `start_workorder`. La web ya los usa (`views.py:148`, `views.py:284`). El
  claim reutilizará `assign_workorder` (ver bloqueo B3).

---

## 3. Revisión de `feature/api-tecnico-base` y código rescatable

La rama histórica trae 4 commits / 23 archivos / ~3.000 líneas de buena
calidad. **Respetó el dominio:** `work_orders/models.py` y
`work_orders/services.py` son **idénticos** a develop (no inventó reglas).

### 3.1 Código rescatable (se reintegra con revisión)

| Archivo | Qué aporta | Veredicto |
|---|---|---|
| `config/settings.py` (bloque `REST_FRAMEWORK`) | DRF con `TokenAuthentication` + `IsAuthenticated` global | Rescatar (edición aditiva) |
| `requirements.txt` | `djangorestframework==3.18.0` | Rescatar (ya instalado en el venv) |
| `apps/accounts/services.py` | `is_active_technician()`, `authenticate_technician()`, excepciones de auth | Rescatar íntegro |
| `apps/accounts/api/` (`serializers`, `permissions`, `views`, `urls`) | Login, `me/`, permiso `IsActiveTechnician` reevaluado en cada request | Rescatar íntegro |
| `apps/work_orders/api/` (`serializers`, `permissions`, `views`, `urls`) | Mis órdenes, detalle con **404 uniforme** (anti-enumeración), `select_related`, inicio de atención | Rescatar íntegro |
| Tests: `test_api_auth`, `test_api_my_orders`, `test_api_work_order_detail`, `test_api_start_attention` | Cobertura de auth, listados, detalle e inicio | Rescatar íntegro |
| `docs/api_technician_*.md` (3 archivos) | Documentación del contrato | Rescatar |

### 3.2 Código NO rescatable / que NO se reintegra

- **`config/urls.py` de la rama histórica está ATRASADO.** Se ramificó antes de
  varios commits de develop: **elimina** los `include` de `apps.accounts.urls`
  (mi perfil) y `apps.organization.urls` (sede activa) y quita
  `redirect_authenticated_user` del login. Su diff a develop es en parte una
  **regresión**. → no se copia el archivo; se aplican a mano solo las **dos
  adiciones** de rutas API sobre el `config/urls.py` actual.
- **`apps/accounts/models.py` de la rama histórica tiene 9 líneas menos** que
  develop: **le falta el campo `phone`** (predata la migración 0003). Merge o
  cherry-pick lo **borraría**.
- La rama convierte `apps/accounts/tests.py` (archivo) en paquete
  `apps/accounts/tests/`. Hay que **replicar la conversión a mano** en develop
  actual, preservando el contenido de tests que develop ya tenga.

### 3.3 Faltante — es el trabajo nuevo del sprint

`available/` y `claim/` **no existen** en la rama histórica. La rama llega hasta
"mis órdenes / detalle / inicio de atención". Los dos endpoints centrales del
hito (órdenes disponibles y toma) son desarrollo nuevo (jueves/viernes).

---

## 4. Contrato API (mínimo del sprint)

Prefijo base: `/api/technicians/`. Autenticación por **token DRF** (cabecera
`Authorization: Token <key>`), salvo el login.

| Acción | Método y ruta | Auth | Permiso | Éxito | Errores |
|---|---|---|---|---|---|
| Login | `POST /api/technicians/login/` | Abierto | — | `200` `{token, technician}` | `400` datos faltantes · `401` credenciales inválidas · `403` no es técnico |
| Identidad | `GET /api/technicians/me/` | Token | `IsActiveTechnician` | `200` identidad | `401` sin token · `403` no técnico activo |
| Disponibles | `GET /api/technicians/work-orders/available/` | Token | `IsActiveTechnician` | `200` lista | `401` · `403` |
| Mis órdenes | `GET /api/technicians/work-orders/` | Token | `IsActiveTechnician` | `200` lista | `401` · `403` |
| Detalle | `GET /api/technicians/work-orders/<id>/` | Token | `IsActiveTechnician` | `200` ficha | `401` · `403` · `404` uniforme (inexistente = ajena) |
| Tomar OT | `POST /api/technicians/work-orders/<id>/claim/` | Token | `IsActiveTechnician` + `assign_workorder` | `200` ficha ya asignada | `401` · `403` · `404` · `409` ya tomada / no PENDING |

**Nombres finales (a confirmar en revisión):** la rama histórica ya expone el
inicio de atención como `.../<id>/start/`. El plan lista el nombre `claim` para
la toma; se adopta `claim/` salvo indicación distinta (bloqueo B4).

Forma de las respuestas (heredada de la rama histórica, se conserva):
- **Lista** (`WorkOrderListSerializer`): `id`, `order_number`, `customer`
  (código, tipo/nº doc, nombre), `service_type`, `plan`, `order_type`,
  `subtype`, `status` + `status_display`, `priority` + `priority_display`,
  `scheduled_at`, `created_at`. Cada choice viaja como código estable + etiqueta
  legible.
- **Detalle** (`WorkOrderDetailSerializer`, extiende la lista): añade `address`
  (dirección de atención + GPS), `detail`, `branch`, `zone`.
- Errores: siempre `{"detail": "<mensaje en español>"}`.

---

## 5. Estrategia de seguridad

Tres capas independientes, evaluadas por separado y en este orden. Ninguna
suple a otra:

1. **Autenticación (token) — "¿sé quién eres?"** `TokenAuthentication` global.
   El único endpoint abierto es el login (`authentication_classes = []`,
   `AllowAny` declarado localmente, nunca aflojando el default global).
2. **Permiso de canal `IsActiveTechnician` — "¿puedes operar en este canal?"**
   Delega en `is_active_technician()` y se reevalúa **en cada petición**. El
   token DRF no caduca; esto cierra el hueco de un token vigente cuyo dueño fue
   desactivado o cambiado de rol después de autenticarse.
3. **Queryset filtrado por `request.user` — "¿es tuya esta orden?"** El técnico
   sale **siempre** de `request.user`, jamás de un parámetro del cliente. No hay
   parámetro que manipular.

**Anti-enumeración (404 uniforme).** En "mis órdenes"/detalle, una orden ajena y
una inexistente recorren el mismo camino y devuelven el **mismo 404**. La
seguridad vive en el queryset, no en un `has_object_permission` que devolvería
403 y confirmaría que la orden existe. Para acciones con permiso funcional
(claim), el permiso se evalúa **antes** de resolver la orden: quien no lo tiene
recibe `403` para cualquier id y no puede sondear cuáles existen.

**El cliente nunca decide reglas.** Ni el técnico (sale de `request.user`), ni el
estado destino (lo decide la matriz de transiciones), ni la hora (la pone
`timezone.now()` en el dominio). Los serializers de escritura declaran solo los
campos admitidos (p. ej. `remarks`); cualquier `status`/`assigned_technician`
que llegue en el POST es descartado por DRF antes de tocar el dominio.

---

## 6. Estrategia de concurrencia — claim atómico

Requisito del plan: dos técnicos no pueden quedar ambos como responsables de la
misma OT. Como `assign_technician()` no bloquea la fila (sección 2.3), el
bloqueo lo aplica la vista de claim:

```python
from django.db import transaction
from apps.accounts.models import User

with transaction.atomic():
    try:
        order = (
            WorkOrder.objects
            .select_for_update()
            .get(pk=pk, status=WorkOrder.Status.PENDING)
        )
    except WorkOrder.DoesNotExist:
        # No existe, ya no está PENDING, o la ganó otro técnico en la carrera.
        # Respuesta 409, indistinguible entre "no disponible" y "ya tomada".
        return Response({"detail": "La orden ya no está disponible."}, status=409)

    order.assign_technician(request.user, assigned_by=request.user)

return Response(WorkOrderDetailSerializer(order).data)
```

Puntos clave:
- El filtro `status=PENDING` va **dentro** del `select_for_update().get()`: el
  ganador toma el lock con la orden aún PENDING; el perdedor, al liberarse el
  lock, ya no encuentra una fila PENDING y cae en `DoesNotExist` → `409`.
- El técnico se toma de `request.user`, no del cuerpo.
- La transición real la ejecuta `assign_technician()` (dominio oficial):
  PENDING → ASSIGNED, con historial y `WorkOrderAssignment`.

**Nota de motor:** en PostgreSQL (producción) `select_for_update()` es un
bloqueo de fila real y la prueba de concurrencia es determinista. En SQLite
(desarrollo) la cláusula se ignora pero las escrituras se serializan; el test
concurrente debe escribirse teniendo esto en cuenta (patrón ya presente en el
proyecto para el correlativo). Detalle a cerrar el viernes.

---

## 7. Estrategia de reintegración (sin merge)

El plan prohíbe fusionar `api-tecnico-base` o hacer merge a develop/main. Por lo
visto en 3.2, un merge además **regresaría** develop (perdería `phone` y las
rutas de perfil/organización). Plan de reintegración **archivo por archivo**
(previsto para el martes):

1. **Copiar archivos nuevos** (conflicto cero, no existen en develop): paquetes
   `apps/accounts/api/`, `apps/work_orders/api/`, `apps/accounts/services.py`,
   los tests de API y las docs `api_technician_*.md`.
2. **Ediciones aditivas manuales** sobre develop actual:
   - `config/settings.py`: agregar el bloque `REST_FRAMEWORK` y `rest_framework`
     en `INSTALLED_APPS` (+ `rest_framework.authtoken`, requerido por el token).
   - `config/urls.py`: agregar **solo** los dos `path` de la API
     (`api/technicians/work-orders/` y `api/technicians/`) **sin** tocar las
     rutas existentes de perfil/organización/login.
   - `requirements.txt`: agregar `djangorestframework==3.18.0`.
3. **Migración de authtoken:** `rest_framework.authtoken` aporta su propia
   migración (crea `authtoken_token`; la tabla ya existe en la BD local de
   prueba). Aplicar con `migrate authtoken`. No es una migración propia del
   dominio.
4. **Convertir `apps/accounts/tests.py` → paquete** preservando el contenido
   que develop ya tenga.
5. Tras cada bloque: `manage.py check`, `makemigrations --check` y la suite de
   los módulos tocados en verde antes de seguir.

---

## 8. Bloqueos — reglas de negocio no definidas (para revisión 15:00–17:00)

Por regla del sprint, lo no definido por negocio **se reporta, no se inventa**.
Cinco puntos requieren decisión antes de codificar los endpoints nuevos:

- **B1 — Definición de "disponible".** ¿Qué devuelve `available/`? Propuesta:
  `status = PENDING` **y** `assigned_technician IS NULL`. ¿Entran DERIVED /
  REPROGRAMMED? ¿Solo `order_type = INSTALLATION` o todos los tipos?
- **B2 — Sede en `available/`.** El plan exige que sede/zona sea organización y
  filtro, **no** restricción dura. Propuesta: filtrar por defecto a la sede del
  técnico con parámetro para ampliar, sin bloquear asignaciones válidas fuera de
  sede. Confirmar.
- **B3 — Permiso del claim.** Propuesta: **reutilizar** `assign_workorder` (ya
  existe, sin migración; se concede al grupo Técnico). Crear `claim_workorder`
  exigiría migración → requiere aprobación. Confirmar cuál.
- **B4 — Nombre final del endpoint de toma.** Plan dice `claim/`; la rama
  histórica ya usa `start/` para inicio de atención (acción distinta).
  Confirmar `claim/`.
- **B5 — Punto de creación comercial (dep. Joleydi, jueves).** Dónde
  exactamente el flujo de contratación FTTH invocará `create_work_order()` con
  `INSTALLATION`, para que la OT quede PENDING y visible en `available/` sin
  copia ni sincronización manual.

---

## 9. Evidencia de pruebas (baseline del día)

```
manage.py check ............................ OK (0 issues)
makemigrations --check --dry-run ........... OK (No changes detected)
Suite apps.accounts ........................ Ran 9 tests — OK (exit 0)
Suite apps.work_orders + apps.accounts ..... Ran 280 tests — OK (exit 0)
```

Baseline verde confirmado sobre los módulos del frente: la lógica de dominio
existente (creación, estados, asignación, inicio de atención) está cubierta y
pasa antes de introducir la capa API.

---

## 10. Pendiente para el martes (Día 2 — Base API y autenticación técnica)

Reintegrar de forma segura, según el plan de la sección 7:
DRF + `authtoken`, `accounts/services.py`, paquete `accounts/api/`
(login + `me/`) y el permiso `IsActiveTechnician`, más las adiciones de
`settings.py`/`urls.py`/`requirements.txt`. Dejar el canal API autenticado con
usuario técnico identificable y los tests de `accounts` + `check` en verde.
