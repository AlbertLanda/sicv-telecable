# Reporte diario — Sprint FTTH · Día 6

**Formato del plan de trabajo §7.**

| | |
|---|---|
| **Fecha** | 02 / 09 / 2026 |
| **Jornada del plan** | Día 6 — «Hardening e integración backend» |
| **Colaborador** | Kevin Rivera |
| **Frente** | Dominio Work Orders / API del Técnico |
| **Rama** | `feature/ftth-api-tecnico-mvp` |
| **Base** | `0fe32e6` (día 5) |

---

## 1. Entregable del día

**Backend estable para que Joleydi trabaje el domingo**, según el trabajo
obligatorio del plan: corregir fallos, completar la documentación del contrato
API y asegurar compatibilidad con la UI que ella consumirá.

| Trabajo obligatorio (plan) | Estado |
|---|---|
| Corregir fallos | ✅ 3 corregidos (§2) |
| Completar documentación del contrato API | ✅ referencia única de consumo (§3) |
| Asegurar compatibilidad con la UI de Joleydi | ✅ contrato compartido recuperado y ampliado |
| Ejecutar suite de módulos y global | ✅ 543 pruebas OK |

---

## 2. Fallos corregidos

### 2.1 Cobertura que faltaba en la ficha de ATC — y el fallo que dejó pasar

El día 5 agregué a `customers/detail.html` un comentario con `{# … #}` de
cuatro líneas. **Django solo interpreta esa sintaxis en una línea**, así que el
bloque se pintó como texto dentro del campo Latitud y quedó visible en
pantalla. Lo detectó el colaborador al revisar la ficha, no las pruebas.

Lo relevante no es la etiqueta mal usada, sino **por qué la suite no lo
atrapó**: las 536 pruebas del día 5 pasaron con el comentario roto, porque toda
la cobertura de la regla de ubicación estaba en la capa Python y **ninguna
prueba renderizaba esa plantilla**.

Corregido con `{% comment %}` y cubierto con
`apps/customers/test_detail_render.py` (4 pruebas sobre el HTML real):

- que **ningún** marcador de comentario llegue al navegador —comprobación
  genérica, no solo el caso que falló—;
- que un `0,0` guardado en base no pinte coordenadas ni el botón de mapa;
- que un GPS válido **sí** se pinte (sanear no puede significar esconder);
- que la dirección textual siga en pantalla sin GPS.

**Verificación de la prueba de regresión:** reintroduje el comentario roto y
confirmé que la prueba falla (`'{#' unexpectedly found`), luego restauré la
plantilla. Una prueba de regresión que no falla ante el bug original no sirve
de nada.

### 2.2 Documento perdido antes del commit del día 5

`docs/orden_tecnica_contrato_compartido.md` no quedó en el commit `0fe32e6`
—Git nunca lo llegó a conocer— y dos documentos que **sí** se subieron lo
referencian, de modo que había dos enlaces muertos en GitHub. Es además el
contrato de coordinación que pidió el líder técnico.

Recuperado y ampliado con lo aparecido después: el hallazgo del JavaScript
(§4.1) y el bloqueo B10 (§2.3).

### 2.3 B10 — se podía tomar una OT de un servicio ya cancelado

**El fallo.** Las cuatro condiciones de «orden disponible» miraban solo la
orden, y `WorkOrder` guarda su propio estado. Una OT nacida sobre una
suscripción válida seguía en `PENDING` aunque la suscripción se cancelara
**después**. El camino no es teórico: un corte definitivo pone la suscripción
en `CANCELLED` y no toca las demás órdenes de esa suscripción. Resultado: un
técnico podía tomar y viajar a instalar un servicio comercialmente cancelado.

**Mitigado en el canal**, con tres propiedades que lo hacen defendible:

- **No inventa un criterio de negocio.** Importa del dominio la misma
  `SUBSCRIPTION_BLOCKED_STATUSES` desde la que `create_work_order()` se niega a
  registrar trabajo nuevo: si el dominio no aceptaría crear esa orden hoy, el
  canal no la publica. Si negocio amplía esa lista, las dos puntas se mueven
  juntas.
- **No toca el dominio.** Ni estado, ni efecto, ni migración.
- **La toma lo heredó sin escribir una línea**, por compartir definición con el
  listado: la orden deja de publicarse y deja de ser tomable en el mismo
  instante.

Es estrecha a propósito —solo cancelada—, con prueba de los dos lados: `PRESALE`
y `SUSPENDED` siguen disponibles, porque excluir de más dejaría al técnico sin
trabajo legítimo.

**Sigue pendiente de negocio** qué hacer con las OT abiertas al cancelar una
suscripción: la mitigación evita el viaje en falso, pero no limpia la cola de
despacho.

### 2.4 Suite de 34 minutos → 12 segundos

El costo no estaba en la lógica sino en el `setUp`: los escenarios crean varios
usuarios por prueba y cada `create_user()` ejecuta PBKDF2 con cientos de miles
de iteraciones.

`config/settings.py` declara ahora `MD5PasswordHasher` **solo** cuando el
comando invocado es exactamente `manage.py test`. La condición es estrecha a
propósito (`sys.argv[1:2] == ['test']`): cualquier otro arranque —runserver,
gunicorn, migrate, shell— conserva PBKDF2, así que ningún entorno real puede
quedar con hasheo débil por accidente. **Verificado**: fuera de la suite,
`settings.PASSWORD_HASHERS[0]` sigue siendo PBKDF2.

| | Antes | Ahora |
|---|---|---|
| Suite global | 536 pruebas / **2060 s** (34 min) | 543 pruebas / **12,3 s** |

Impacto directo en el plan: el día 6 exige correr la suite completa, y hasta
hoy cada verificación costaba media hora. En CI el job se había ampliado a 30
minutos por este motivo.

---

## 3. Documentación del contrato API

Nuevo: [`docs/api_tecnico_referencia.md`](api_tecnico_referencia.md) — **página
única de consumo**, para cumplir la exigencia del plan §4.1 («contrato API
claro para que Joleydi pueda consumirlo sin conocer reglas internas del
dominio»). Hasta hoy la información estaba repartida en tres documentos
organizados por jornada, útiles para entender *por qué*, no para *integrar*.

Incluye los 6 endpoints en una tabla, cabecera de autenticación, tabla de
códigos de error con **qué debe hacer el cliente** ante cada uno, el flujo
típico completo, los campos de cada respuesta con ejemplos, y las reglas que el
cliente debe respetar al pintar (choices dobles, `can_start_attention` decidido
por el servidor, `technical_data` en `null`, y que **un `0` jamás llega por
esta API**, así que no hay que compararlo).

Actualizados por el cambio de B10: `api_technician_work_orders.md` §2 (cuatro
condiciones → cinco) y `api_technician_claim.md` §2.

---

## 4. Tests ejecutados

```
manage.py check ............................ OK (0 issues)
makemigrations --check --dry-run ........... OK (No changes detected)
test_detail_render (nuevo) ................. Ran 4 tests — OK
test_api_claim + test_api_available_orders . Ran 54 tests — OK (1,7 s)
Suite GLOBAL ............................... Ran 543 tests — OK (12,3 s)
```

7 pruebas nuevas hoy (4 de renderizado, 3 de B10). Total del sprint en el
frente: 60 nuevas entre los días 5 y 6. Cero migraciones; `models.py` y
`services.py` de `work_orders` siguen intactos.

---

## 5. Prompt Claude Code de la jornada

- Ejecutar la jornada de hardening del plan: corregir los fallos abiertos,
  completar la documentación del contrato API y dejar el backend estable para
  el consumo del frente comercial.
- Cubrir con pruebas la plantilla que quedó sin cobertura el día 5, verificando
  que la prueba nueva falle ante el fallo original antes de darla por buena.
- Reducir el costo de la suite sin cambiar ninguna validación ni ninguna
  prueba, y sin que ningún entorno real pueda quedar con hasheo débil.
- Mitigar el hueco de la suscripción cancelada reutilizando la definición que
  ya existe en el dominio, sin inventar reglas ni tocar el dominio.

**Decisiones consultadas y resueltas por el colaborador** (no las tomó la
herramienta): dejar reportada —y no corregir— la entrada del `0,0` en el frente
de alta comercial; aplicar el hasher rápido en `settings.py`; y mitigar B10 en
el canal en lugar de solo reportarlo.

---

## 6. Bloqueos

| # | Bloqueo | Estado |
|---|---|---|
| **B3** | Permiso funcional de la toma | **Abierto.** Requiere decisión antes de la demo del 07. Reutilizar `assign_workorder` daría a los técnicos poder de despacho en la web |
| **B10** | ¿Anular las OT abiertas al cancelar una suscripción? | **Mitigado en canal; decisión de fondo abierta** |
| **GPS-entrada** | El `0,0` sigue entrando por la consulta de suministro | **Reportado, no corregido** — decisión del frente de alta comercial. Tres puntos de la misma causa: servicio Python, JS del formulario y lo ya guardado en base |
| **B9** | Idempotencia de la toma ante reintento | Abierto. Recuperación documentada para la app |
| **B5** | Llamador comercial de `create_installation_work_order()` | Depende de Joleydi |
| **B6** | ¿Basta `branch` + `zone` + `district` antes de tomar? | Abierto |
| **Zona** | ¿Sugerir la Zona a partir del suministro? | Abierto, para negocio |

---

## 7. Pendiente para la siguiente jornada (día 7 — demo MVP)

1. **Recorrido completo end-to-end** en cuanto exista la acción «Generar Orden
   de Instalación»: contratación → OT `PENDING` → `available` → `claim` → mis
   órdenes → detalle. Es el hito del 07/09.
2. **Cerrar B3** — es la única decisión que afecta al comportamiento del
   endpoint en la demo.
3. **Coordinación con Joleydi**: los 4 puntos del contrato compartido §4.
4. **Evidencia visual** para el reporte: respuesta del claim y ficha de ATC con
   y sin GPS válido.
5. Confirmar que CI queda en verde con la suite acelerada (el timeout de 30
   minutos pasa a ser holgura, no límite).
