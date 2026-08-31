ANÁLISIS FLUJO FTTH – JOLEYDI – 31/08
#---------------------------------------------------------------
       ANALISIS PREVIA COMPARACIÓN CON SICV ACTUAL Y NUEVA      IMPLEMENTACIÓN
#---------------------------------------------------------------

1. MODELOS REVISADOS

Customer
- DNI/RUC/C.E./Pasaporte: existe (Customer.DocumentType)
- nombres/apellidos: existe (persona natural)
- razón social: existe (persona jurídica)
- teléfono: existe (principal y secundario)
- correo: existe
- sedes: existe - pendiente sede jauja y la oroya


CustomerAddress
- zona: existe (FK a Zone)
- distrito: existe (texto libre, sin catálogo)
- dirección: existe (texto libre, sin catálogo)
- referencia: existe (texto libre, sin catálogo)
- GPS (latitud/longitud/enlace): existe
- número de medidor: existe

NO EXISTE: 
- tipo de vía: NO existe
- vía: NO existe
- etapa/otros: NO existe
- Precinto: NO existe
- número de suministro eléctrico: NO existe
- tipo de vivienda: NO existe (número/manzana/lote/piso/departamento/interior)

Subscription
- servicio (service_type): existe
- plan: existe
- estado (PRESALE/INSTALLATION/ACTIVE/CUT/SUSPENDED/CANCELLED): existe
- filtrado plan↔servicio: existe (Plan.service_type + validación en el formulario)
Ciclo de Facturación: existe

Contract
- relación con cliente/suscripción: existe
- exige suscripción en PRESALE sin contrato activo previo: existe
- número de contrato correlativo: existe (sin bloqueo transaccional, a diferencia de las OT)
- fecha de inicio: existe
- fecha de fin: existe

NO EXISTE: 
- número de orden: NO existe
- servicio (service_type): NO existe por estar relacionado con la suscripción
- plan: NO existe por estar relacionado con la suscripción 
- estado: NO existe al crear la orden
- modalidad: NO existe
- cuotas: NO existe


2. PANTALLAS PROPUESTAS

1. Buscar/crear cliente
2. Identificación de abonados con datos similares
2.1. Muestra de delo abonados similares (código, abonado, dni, estado, deuda)
2. Registrar domicilio (Jalar datos con el número de suministro electrónico)
3. Seleccionar servicio y plan
4. Crear suscripción/contrato
5. Resumen breve en el apartado datos del cliente
6. Generar OT instalación directo sin pasar filtro de servicio


3. CAMPOS FALTANTES

- Número de suministro eléctrico (CustomerAddress)
- Tipo de vivienda (aparece en el flujo aprobado, sin campo ni regla definida)
- Campos no existentes indicados.


4. ARCHIVOS QUE REQUERIRÍAN CAMBIO

- apps/customers/models.py (agregar electrical_supply_number a CustomerAddress)
- apps/customers/forms.py (CustomerAddressForm)
- apps/customers/templates/customers/address_create.html
- apps/customers/templates/customers/detail.html (mostrar el nuevo campo)
- apps/customers/views.py / urls.py (futura vista "Generar OT" desde ficha/resumen comercial)
- apps/services/... : sin cambios necesarios (el filtrado servicio→plan ya cumple lo pedido)
- apps/contracts/... : sin cambios necesarios (ya vincula cliente/suscripción correctamente)
- apps/work_orders/... : NO se toca (capa oficial de Kevin, ya lista y documentada)
- apps/technicians/... : vacío; requiere contrato de API de Kevin antes de poder construirse


5. CAMBIOS QUE NO SE REALIZARON TODAVÍA

- No se crearon migraciones.
- No se modificó work_orders.
- No se alteraron reglas de negocio.


6. DUDAS / DECISIONES PENDIENTES

- Formato y unicidad del número de suministro eléctrico: ¿único por dirección? ¿validación de formato?
- Definición de "tipo de vivienda": no está detallado en el plan ni en los criterios de aceptación.
- Campos restantes: Previa evaluación si serán necesarios o no.
- Contrato de integración con Kevin para invocar create_work_order() desde el flujo comercial (vista server-side vs. endpoint).
- Contrato de API para el canal técnico: hoy no existe Django REST Framework instalado ni ninguna app "api" en el proyecto.


#---------------------------------------------------------------
                ANALISIS CLAUDE AI
#---------------------------------------------------------------
# Sprint FTTH — Día 1 (Lunes 31/08/2026)

Auditoría de arquitectura y mapa del flujo comercial, según
"Plan de trabajo — Sprint FTTH" (Colaborador: Joleydi).

Objetivo del día: auditar `Customer`, `CustomerAddress`, `Subscription`,
`Plan` y `Contract`; comparar la implementación actual contra el flujo FTTH
aprobado (Figura 1 del plan); identificar campos reutilizables y campos
faltantes. **No se crearon migraciones.**

---

## 1. Resumen ejecutivo

La base de dominio (`Customer`, `CustomerAddress`, `Subscription`, `Plan`,
`Contract`) ya cubre la mayor parte de los pasos 1 a 6 del flujo comercial
(Figura 1, bloque "Generación de la instalación en SICV"). No es necesario
duplicar ningún modelo.

Los tres huecos reales frente al flujo aprobado son:

1. **No existe el número de suministro eléctrico** en `CustomerAddress` (ni
   en ningún otro modelo). Es un campo nuevo a proponer, diferenciado de
   `meter_number`.
2. **No existe ningún mecanismo que impida crear un servicio de TV Cable
   ficticio.** Hoy no hay lógica de ese tipo en el código — no es que haya
   que "eliminarla", es que aún no existe el flujo de creación de
   Subscription/Contract que la Actividad 4.1 pide construir, así que el
   riesgo se previene por diseño desde el primer commit, no se corrige
   después.
3. **No existe ninguna capa de API** en el proyecto (no hay Django REST
   Framework instalado, no hay app `api`, no hay serializers). El paso 7→8
   del flujo ("Generar OT" → "OT disponible para técnicos") y todo el bloque
   2 ("Atención de la instalación en la App del Técnico") dependen de un
   contrato de integración que debe entregar Kevin sobre `work_orders`. Esto
   es una dependencia externa a este frente, no un pendiente de Joleydi.

Ningún modelo necesita migración para el paso 1 a 6 salvo el punto 1
(suministro eléctrico), que queda pendiente de aprobación técnica antes de
tocar `apps/customers/migrations/`.

---

## 2. Mapa del flujo aprobado vs. implementación actual

Bloque 1 del flujo (Figura 1): "Generación de la instalación en SICV (ATC /
Ventas)".

| # | Paso del flujo aprobado | Estado actual | Archivos involucrados |
|---|---|---|---|
| 1 | Buscar o crear cliente (DNI, código u otros datos) | **Implementado.** `CustomerSearchView` busca por código, documento, nombres, teléfono, dirección, distrito, referencia, medidor. Acotado a la sede activa. | `apps/customers/views.py::CustomerSearchView` |
| 2 | Obtener datos del cliente (consulta DNI/RUC) | **Implementado.** `CustomerDocumentLookupView` consulta RENIEC/SUNAT vía `apps/customers/services/sunat.py`; solo autocompleta, no persiste. | `apps/customers/views.py::CustomerDocumentLookupView`, `apps/customers/services/sunat.py` |
| 3 | Completar datos del abonado (teléfono, correo, dirección, distrito, zona) | **Implementado** para teléfono/correo/dirección (`CustomerGeneralDataView`, Pantalla 4). Distrito y zona se resuelven en el paso 4 (dirección), no en el paso 3. | `apps/customers/forms.py::CustomerRegistrationForm`, `apps/customers/views.py::CustomerGeneralDataView` |
| 4 | Registrar domicilio del servicio (referencia, tipo de vivienda, **número de suministro eléctrico**) | **Parcial.** `CustomerAddress` ya tiene `address`, `reference`, `district` (texto libre), `zone` (FK a `Zone`), `meter_number`, `latitude/longitude`, `gps_link`, `is_primary`. **Falta:** número de suministro eléctrico y tipo de vivienda — ninguno de los dos existe hoy en el modelo. | `apps/customers/models.py::CustomerAddress`, `apps/customers/forms.py::CustomerAddressForm` |
| 5 | Seleccionar servicio FTTH y plan (Internet / Dúo / TV Cable según corresponda) | **Implementado** el mecanismo de filtrado (`Plan.service_type` + validación cruzada en `SubscriptionCreateForm.clean()`). **No implementado** el catálogo específico de servicios FTTH/Dúo — depende de qué `ServiceType`/`Plan` existan cargados en la base, no del código. | `apps/services/models.py::ServiceType, Plan`, `apps/services/forms.py::SubscriptionCreateForm` |
| 6 | Crear suscripción / contrato (alta comercial) | **Implementado.** `SubscriptionCreateView` crea `Subscription` en `PRESALE`; `ContractCreateView` crea `Contract` solo sobre suscripciones en `PRESALE` sin contrato activo previo, genera `contract_number` correlativo y estado `ACTIVE`. | `apps/services/views.py::SubscriptionCreateView`, `apps/contracts/views.py::ContractCreateView` |
| 7 | Generar Orden de Instalación (OT en `PENDING`) | **Servicio de dominio listo, sin UI de consumo.** `create_work_order()` (`apps/work_orders/services.py`) es la única vía legítima, ya deja la orden en `WorkOrder.Status.PENDING` y no toca la suscripción. Documentado en `docs/work_orders_creation.md`. **Falta:** el botón/vista en el flujo comercial (ficha de cliente / resumen de contratación) que la invoque. Existe una maqueta puramente visual sin POST: `CustomerWorkOrderUIPreviewView`. | `apps/work_orders/services.py::create_work_order`, `apps/customers/views.py::CustomerWorkOrderUIPreviewView` (solo lectura) |
| 8 | OT disponible para técnicos (visible según sede) | **No implementado.** No existe capa de API ni app de consumo técnico. `apps/technicians/` está vacío (modelos y vistas sin contenido real). | `apps/technicians/models.py`, `apps/technicians/views.py` (vacíos) |

Bloque 2 del flujo ("Atención de la instalación en la App del Técnico",
pasos 1-9): **fuera de alcance de Joleydi para el hito MVP** según §4.2 del
plan, y sin base de código porque no existe todavía el contrato de API de
Kevin ni la app/PWA. Se retoma en la Actividad de Jueves 03/09 y Domingo
06/09 una vez que el contrato esté estable.

---

## 3. Auditoría por modelo

### 3.1 `Customer` (`apps/customers/models.py`)

Ya cubre DNI, RUC, C.E. y Pasaporte (`DocumentType`), con la regla de
correspondencia documento↔tipo de persona centralizada en
`Customer.person_type_for_document()`. Código único, sede (`branch`),
teléfonos, correo, activo/inactivo. **No requiere cambios** para el alcance
de este sprint.

### 3.2 `CustomerAddress` (`apps/customers/models.py`)

| Campo actual | ¿Reutilizable para FTTH? |
|---|---|
| `zone` (FK a `Zone`, protegido) | Sí — ya asocia la dirección a una zona de la sede. |
| `address`, `reference`, `district` (texto libre) | Sí. |
| `meter_number` | Sí, y debe **conservarse tal cual** — es el dato que el plan exige mantener separado del nuevo número de suministro. |
| `latitude`, `longitude`, `gps_link` | Sí, sin cambios. |
| `is_primary`, `is_active` | Sí, sin cambios. |

**Campo faltante:** número de suministro eléctrico. Propuesta para
discutir en la revisión de las 15:00 (no implementada aún, según regla del
plan de "no crear migraciones sin revisión"):

​```python
electrical_supply_number = models.CharField(
    max_length=50,
    blank=True,
    verbose_name="Número de suministro eléctrico",
)
​```

Mismo patrón que `meter_number` (opcional, texto libre, sin validación de
formato hoy) para no introducir una regla de negocio que nadie pidió. Vive
en `CustomerAddress`, no en `Customer`, porque el plan lo describe como
"dato propuesto del inmueble" — el suministro pertenece al domicilio, no al
titular.

Pendiente de confirmar con TI/negocio antes de migrar: ¿debe ser único?
¿Debe validarse contra algún proveedor externo o es dato de digitación
libre? El plan no lo especifica y `services/sunat.py` no cubre suministro
eléctrico.

**Tipo de vivienda:** mencionado en la Figura 1 ("tipo de vivienda") pero no
detallado en ningún punto del texto del plan ni en los criterios de
aceptación (§6). No se propone campo nuevo todavía — se reporta como punto
a definir con negocio en la revisión de hoy.

### 3.3 `ServiceType` / `Plan` (`apps/services/models.py`)

Reutilizables sin cambios. El filtrado servicio→plan ya existe en dos
capas: `SubscriptionCreateForm.clean()` (servidor) y en el modelo
(`Plan.service_type`, protegido). No hay nada en el código que "genere" un
servicio de TV Cable automáticamente — la eliminación de esa duplicidad
ficticia (§2 del plan) se traduce, en este sprint, en **no introducirla**
al construir la Actividad de Miércoles 02/09.

### 3.4 `Subscription` (`apps/services/models.py`)

Reutilizable sin cambios. Ya relaciona `customer`, `address`, `service_type`
y `plan`, nace en `PRESALE`, y tiene la restricción única
`(customer, service_type, service_number)`. El estado `INSTALLATION` ya
existe en `Subscription.Status` aunque hoy solo lo escribe
`start_order_attention()` en `work_orders/services.py` (fuera del alcance
de Joleydi, según §4.2).

### 3.5 `Contract` (`apps/contracts/models.py`)

Reutilizable sin cambios. Ya vincula `customer` + `subscription`, exige
suscripción en `PRESALE` sin contrato activo previo, genera
`contract_number` correlativo en la vista. **Observación técnica:**
`ContractCreateView.generate_contract_number()` calcula el correlativo con
`Contract.objects.order_by("-id").first().id + 1`, sin bloqueo
transaccional — a diferencia del correlativo de `WorkOrderSequence` en
`work_orders`, que sí usa `select_for_update()`. No es parte del alcance de
este sprint modificarlo, pero se deja registrado como riesgo latente de
colisión bajo alta concurrencia.

### 3.6 `WorkOrder` / `create_work_order()` (`apps/work_orders/`)

**No se modifica.** Es la "capa oficial" que el plan exige consumir
(§4.1: "nunca `WorkOrder.objects.create()`"). Ya está lista, documentada y
probada (`docs/work_orders_creation.md`). El trabajo de Joleydi del jueves
03/09 es exclusivamente de **consumo** desde la ficha/resumen comercial.

---

## 4. Lista exacta de archivos que requerirían cambio

| Archivo | Cambio previsto | Requiere migración |
|---|---|---|
| `apps/customers/models.py` | Agregar `electrical_supply_number` a `CustomerAddress` (pendiente de aprobación) | Sí, si se aprueba |
| `apps/customers/forms.py` | Agregar el campo a `CustomerAddressForm` | No |
| `apps/customers/templates/customers/address_create.html` | Agregar el campo al formulario visual | No |
| `apps/customers/views.py` | Nueva vista de "Generar OT de instalación" desde la ficha/resumen comercial, consumiendo `apps.work_orders.services.create_work_order` (pendiente del contrato con Kevin) | No |
| `apps/customers/urls.py` | Nueva ruta para la acción de generar OT | No |
| `apps/customers/templates/...` | Resumen previo a la generación de instalación (§4.1) — no existe todavía | No |
| — | Interfaz móvil/PWA | Bloqueada hasta contrato API de Kevin | No |

Ningún archivo de `apps/work_orders/` aparece en esta lista.

---

## 5. Bloqueos / puntos a definir con negocio o con Kevin

1. Formato y unicidad del número de suministro eléctrico.
2. "Tipo de vivienda" (Figura 1) — sin campo, sin catálogo, sin regla.
3. Contrato de integración para `Generar OT` (¿vista server-side que llama
   a `create_work_order`? ¿endpoint API?).
4. Contrato de API para el canal técnico (login, listar OT, tomar OT) — no
   existe DRF instalado ni app `api`.

---

## 6. Pendiente para la siguiente jornada (Martes 01/09)

Consolidar identificación, contacto y dirección; implementar el número de
suministro eléctrico **si fue aprobado técnicamente** en la revisión de
hoy; mantener separación suministro vs. medidor; tests + evidencia visual.

Condición de entrada: resolución de los puntos 1 y 2 de la sección 5 en la
revisión conjunta de las 15:00-17:00 de hoy.