# Integración: del alta comercial FTTH a la OT publicada

**Sprint FTTH · Frente: Dominio Work Orders / API del Técnico**
**Colaborador:** Kevin Rivera · **Fecha:** día 4 (jueves 03/09/2026)
**Rama:** `feature/ftth-api-tecnico-mvp`
**Interlocutora:** Joleydi (frente de alta comercial FTTH)

Documento de traspaso. Define **exactamente** qué debe invocar el flujo
comercial para que la OT de instalación quede publicada en el canal técnico,
y qué no debe hacer. Cierra el bloqueo B5 desde el lado del dominio de
órdenes.

**No contiene código del flujo comercial.** El paso 7 del flujo aprobado
—«Generar Orden de Instalación»— es del frente de Joleydi, que ya lo declara
como su bloqueo nº 3 y planea reutilizar `WorkOrderCreateView`. Aquí se
especifica el contrato de ese punto de unión, no su implementación.

---

## 1. Estado real del circuito

| Paso | Estado |
|---|---|
| Cliente, dirección, suscripción, contrato | Implementado (frente comercial) |
| **Creación de la OT de instalación desde el flujo comercial** | **No existe** |
| OT publicada en el canal técnico | Implementado (día 3) |

`create_work_order()` se invoca hoy desde **un solo sitio**:
`apps/work_orders/views.py:96` (`WorkOrderCreateView`, el formulario web
«Nueva orden de trabajo»). El flujo comercial termina en `Contract` y ahí se
corta: el operador debe navegar a otra pantalla y volver a elegir la
suscripción a mano.

Ese salto manual es exactamente la duplicidad que el sprint elimina. La pieza
que falta es una sola llamada.

---

## 2. Contrato del punto de creación

```python
from apps.work_orders.services import create_installation_work_order

order = create_installation_work_order(
    subscription=subscription,   # la recién dada de alta
    created_by=request.user,     # NUNCA de datos del POST

    # Opcionales, si el alta comercial los captura:
    reason=...,                  # motivo del catálogo (p. ej. "Cliente nuevo")
    priority=...,
    detail=...,
    scheduled_at=...,
)
```

**Dos argumentos obligatorios y ya está.** La OT queda **PENDING, con
correlativo oficial, sin técnico, de campo y visible en `available/`** en la
misma petición. No hay un segundo paso, ni un job, ni un flag que marcar.

### 2.0 Por qué un servicio propio y no `create_work_order()` directo

`create_installation_work_order()` es una **fachada del dominio, no una regla
nueva**: resuelve el tipo de orden y delega en `create_work_order()`, que
sigue siendo el único camino que emite el correlativo, valida la suscripción y
persiste. No duplica ninguna validación, así que no puede desalinearse de
ella.

Existe porque el paso «Generar Orden de Instalación» tiene dos formas de
producir una OT válida e **invisible** para el técnico (sección 3), y las dos
se evitan mejor con una firma que con una advertencia en un manual:

- El tipo de orden **no es un parámetro**: se resuelve por código exacto.
- `attention_type` **no es un parámetro**: aplica el valor por defecto `FIELD`.
  No es que se valide y se rechace — es que no hay valor que pasar mal.

Llamar a `create_work_order()` directamente sigue siendo válido y es lo que
hace la web para el resto de tipos de orden. Para la instalación FTTH, la
fachada quita dos decisiones que no aportan nada al flujo comercial y sí
pueden romperlo.

### 2.1 Argumentos que NO se deben enviar

El servicio ni siquiera los acepta, y es deliberado:

| Argumento | Por qué no |
|---|---|
| `order_number` | Lo emite el correlativo transaccional. Aceptarlo reabre la puerta a duplicados |
| `status` | Toda OT nace `PENDING`. El estado lo decide la matriz de transiciones |
| `assigned_technician` | La asignación es un flujo aparte. Si el alta asignara técnico, la OT saldría del pool sin que nadie la tomara |

`created_by` sí es parámetro —el servicio no conoce el `request`— pero **debe
salir de `request.user`**, nunca de un id enviado por el navegador.

### 2.2 Comportamiento garantizado

- **Atómico.** Si algo falla no queda ni la orden ni el correlativo consumido.
  Un `ValidationError` se puede mostrar al operador tal cual: los mensajes ya
  están redactados en español para él.
- **No toca la suscripción.** Una instalación sobre una suscripción en
  `PRESALE` la deja en `PRESALE`. La promoción a `INSTALLATION` ocurre cuando
  el técnico inicia la atención, no al crear la orden.
- **La sede sale del cliente.** No de la sede activa de la sesión del
  operador. Importa porque `available/` acota por defecto a la sede del
  técnico.

---

## 3. Las dos trampas: OT válida pero invisible

Ninguna es un fallo del código. Son argumentos que, si llegan mal, producen
una orden perfectamente correcta que **el técnico no verá nunca**.

**Si usas `create_installation_work_order()` las dos quedan cerradas** y esta
sección es solo contexto. Siguen documentadas porque el formulario web general
de OT sí las expone, y porque conviene saber qué se está evitando.

Ambos modos de fallo están cubiertos por pruebas reproducibles en
`test_ftth_installation_publication.py::InstallationPublicationTrapTests`, y
su cierre en `::InstallationServiceTests`.

### Trampa 1 — `attention_type = SYSTEM`

`WorkOrder.attention_type` decide a qué canal pertenece la orden: `FIELD`
(técnico en campo) o `SYSTEM` (NOC en remoto). El canal técnico solo publica
`FIELD`.

El formulario web actual **expone ese campo** (`WorkOrderCreateForm`, campo
`attention_type`). Si el flujo FTTH lo hereda tal cual y alguien marca
«Sistema / NOC», la instalación se crea, queda PENDING y no aparece jamás en
la app.

> **Recomendación:** en el flujo de instalación FTTH **no exponer el campo**.
> El valor por defecto del modelo ya es `FIELD`, así que basta con no
> enviarlo. Una instalación siempre es trabajo de campo.

### Trampa 2 — el tipo de orden equivocado

El catálogo tiene `INSTALLATION` y también un `DEMO-INSTALLATION` de datos de
prueba. Resolver el tipo por nombre, por coincidencia parcial o tomando el
primer resultado del catálogo puede devolver el de demo.

> **Recomendación:** resolver siempre por **código exacto**:
> `OrderType.objects.get(code="INSTALLATION")`. El filtro del canal técnico
> también compara por código exacto, así que cualquier otro tipo queda fuera.

---

## 4. Evidencia: el circuito probado extremo a extremo

`apps/work_orders/tests/test_ftth_installation_publication.py` recorre el
camino completo llamando al servicio real, no a un atajo de pruebas:

```
Subscription (PRESALE)
  -> create_work_order(order_type=INSTALLATION)
  -> WorkOrder PENDING, correlativo OT-2026-NNNNNN, sin técnico, FIELD
  -> GET /api/technicians/work-orders/available/  ->  la devuelve
```

| Grupo | Qué demuestra |
|---|---|
| `InstallationOrderCreationTests` | Criterio §6.1 del plan: PENDING, correlativo oficial, sin técnico, sede del cliente, suscripción intacta, correlativos consecutivos |
| `InstallationBecomesAvailableTests` | Criterio §6.2: aparece de inmediato, **es la misma fila y no una copia**, con los datos que el técnico necesita, y la sede filtra sin bloquear |
| `InstallationPublicationTrapTests` | Los dos modos de fallo de la sección 3, reproducibles |
| `InstallationServiceTests` | Que `create_installation_work_order()` cierra ambos por firma, delega las validaciones del dominio y transmite los datos comerciales opcionales |
| `InstallationCreationRejectionTests` | Lo que el dominio rechaza antes de crear nada (suscripción cancelada, usuario inactivo) |

«No es una copia» se comprueba por identidad —el `id` que publica la API es el
`pk` de la orden creada— y verificando que en la base existe **exactamente
una** fila con ese número.

---

## 5. Guion de la prueba integrada (15:00–17:00)

Cuando el punto de creación exista, este es el recorrido a demostrar:

1. Alta comercial completa de un cliente FTTH hasta el contrato.
2. La acción comercial genera la OT — **sin navegar a otra pantalla**.
3. Verificar en base: `status = PENDING`, `order_number` con formato
   `OT-2026-NNNNNN`, `assigned_technician` vacío, `attention_type = FIELD`,
   `order_type.code = "INSTALLATION"`.
4. `POST /api/technicians/login/` con un técnico de la sede del cliente.
5. `GET /api/technicians/work-orders/available/` → la OT aparece, con el
   mismo `order_number`.
6. Confirmar que no se creó ninguna fila adicional ni se ejecutó ningún paso
   de sincronización.

Comando de verificación rápida desde la terminal:

```bash
curl -H "Authorization: Token <key>" \
     http://localhost:8000/api/technicians/work-orders/available/
```

---

## 6. Bloqueo nuevo — B8: nada impide dos OT de instalación

**Reportado, no resuelto.** El objetivo del sprint dice «generar **una sola**
OT de instalación». Hoy `create_work_order()` no comprueba si la suscripción
ya tiene una instalación abierta: dos envíos del formulario, un doble clic o
un reintento tras un error de red producen **dos OT PENDING** para el mismo
cliente, y las dos aparecen en `available/`. Dos técnicos podrían tomar una
cada uno.

No lo he corregido por decisión deliberada: añadir esa validación es **cambiar
una regla del dominio**, y el plan exige aprobación previa para eso. Además
la regla exacta no está definida y no debe inventarse:

- ¿Se prohíbe una segunda instalación mientras exista otra en estado activo,
  o para siempre sobre la misma suscripción?
- ¿Qué pasa con una instalación previa `NOT_FEASIBLE` o `CANCELLED`? Lo
  normal sería permitir reintentar, pero eso hay que decidirlo.
- ¿El bloqueo es duro (rechazo) o blando (aviso al operador)?

Mientras no haya decisión, la mitigación es del lado comercial: que la acción
que genera la OT no sea reejecutable —deshabilitar el botón tras el envío,
redirigir en `POST/redirect/GET`—. Es una contención de interfaz, no una
garantía del dominio.

---

## 7. Qué NO se tocó

- **`create_work_order()` y el modelo `WorkOrder`**: idénticos. La jornada no
  añade validaciones, estados ni migraciones. Lo único que se suma a
  `services.py` es la fachada de la sección 2.0, que delega en el servicio
  existente sin reimplementar ni una sola de sus reglas.
- **El código del tipo de instalación** pasa a estar declarado una vez en
  `services.INSTALLATION_ORDER_TYPE_CODE`, y el filtro del canal técnico lo
  importa de ahí. Antes estaba escrito en los dos sitios: si uno cambiara sin
  el otro, el canal publicaría un tipo distinto del que el alta comercial
  crea — instalaciones reales que no aparecen en la app.
- **`WorkOrderCreateView` y su formulario**: intactos. Son el punto que el
  frente comercial va a reutilizar y no deben moverse por debajo.
- **La capa API del día 3**: sin cambios. El circuito se probó contra los
  endpoints tal como quedaron publicados.
