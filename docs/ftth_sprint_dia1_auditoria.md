ANÁLISIS FLUJO FTTH -- JOLEYDI -- 31/08

#--------------------------------------------------------------
   ANALISIS PREVIA COMPARACIÓN CON SICV ACTUAL Y NUEVA IMPLEMENTACIÓN
#--------------------------------------------------------------

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
- número de suministro eléctrico: NO existe actualmente; se propone registrarlo manualmente en el domicilio
- número/manzana/lote/piso/departamento/interior: NO existe
- tipo de vivienda: NO existe y queda fuera del MVP hasta definir la regla de negocio

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

NO EXISTE EN Contract:
- servicio (service_type): no se duplica; se obtiene mediante
Subscription
- plan: no se duplica; se obtiene mediante Subscription
- modalidad: NO existe
- cuotas: NO existe


2. PANTALLAS PROPUESTAS
1. Buscar/crear cliente
2. Identificación de abonados con datos similares 2.1. Muestra de los abonados similares (código, abonado, DNI, estado, deuda)
3. Registrar domicilio
4. Registrar manualmente el número de suministro eléctrico como
dato del domicilio.
5. No se contempla por ahora una consulta automática del suministro, porque actualmente no existe una API para obtenerlo.
6. Seleccionar servicio y plan
7. Crear suscripción/contrato
8. Resumen breve en el apartado datos del cliente
9. Generar OT de instalación reutilizando/adaptando el flujo existente de creación de órdenes de trabajo.
10. Criterio para OT: no se plantea una segunda vista independiente para generar órdenes. El flujo FTTH deberá reutilizar/adaptar WorkOrderCreateView, su ruta y el botón existente "Nueva orden de trabajo", consumiendo el servicio de dominio create_work_order().


3. CAMPOS FALTANTES
- Número de suministro eléctrico (CustomerAddress): dato que se
propone registrar manualmente.
- Tipo de vivienda: queda fuera del MVP hasta definir la regla de negocio.
- Campos no existentes indicados: quedan sujetos a evaluación
posterior según necesidad funcional.
- Importante: el tipo de vivienda no se mezcla con número, manzana, lote, piso, departamento o interior. Son conceptos diferentes y no se propone incorporarlos al modelo mientras no exista una definición de negocio aprobada.


4. ARCHIVOS QUE REQUERIRÍAN CAMBIO
- apps/customers/models.py: eventualmente agregar
electrical_supply_number a CustomerAddress, previa aprobación.
- apps/customers/forms.py: agregar el campo a CustomerAddressForm cuando se implemente.
- apps/customers/templates/customers/address_create.html: mostrar el campo de suministro eléctrico para ingreso manual.
- apps/customers/templates/customers/detail.html: mostrar el número de suministro eléctrico cuando corresponda.
- Flujo existente de WorkOrderCreateView y su ruta:
reutilizar/adaptar, en lugar de crear una vista independiente
para FTTH.
- Integración del flujo comercial con create_work_order(): pendiente de implementación en la jornada correspondiente.
- apps/services/...: sin cambios necesarios (el filtrado
servicio→plan ya cumple lo pedido).
- apps/contracts/...: sin cambios necesarios (ya vincula
cliente/suscripción y Contract ya tiene estado).
- apps/work_orders/...: no se modifica hoy; el flujo FTTH deberá consumir/adaptar la creación existente y utilizar
create_work_order().
- apps/technicians/...: requiere contrato de API de Kevin antes de construir la integración del canal técnico.


5. CAMBIOS QUE NO SE REALIZARON TODAVÍA
- No se crearon migraciones.
- No se modificó work_orders.
- No se alteraron reglas de negocio.
- No se creó una segunda vista independiente para generar OT.
- No se implementó todavía el registro del número de suministro
eléctrico; en esta jornada solo se documentó la necesidad y la regla de ingreso manual.
- No se incorporó tipo de vivienda al MVP.
- No se introdujo ninguna creación automática de TV Cable ficticia.


6. DUDAS / DECISIONES PENDIENTES
- Formato y unicidad del número de suministro eléctrico: queda
pendiente definir si debe ser único por dirección y si tendrá
validación de formato.
- El número de suministro eléctrico será, por ahora, un dato ingresado manualmente; no se plantea consulta mediante API.
- Tipo de vivienda: queda fuera del MVP hasta que se defina y apruebe la regla de negocio. No debe confundirse con número, manzana, lote, piso, departamento o interior.
- Campos restantes: previa evaluación si serán necesarios o no.
- Integración del flujo comercial con la creación existente de OT: adaptar/reutilizar WorkOrderCreateView y consumir create_work_order(), sin crear una segunda vista independiente.
- Contrato de API para el canal técnico: pendiente de definición con Kevin.

#---------------------------------------------------------------

                ANALISIS CLAUDE AI

#---------------------------------------------------------------

# Sprint FTTH --- Día 1 (Lunes 31/08/2026)

Auditoría de arquitectura y mapa del flujo comercial, según "Plan de trabajo --- Sprint FTTH" (Colaborador: Joleydi).
Objetivo del día: auditar `Customer`, `CustomerAddress`, `Subscription`, `Plan` y `Contract`; comparar la implementación actual contra el flujo FTTH aprobado (Figura 1 del plan); identificar campos reutilizables y campos faltantes. **No se crearon migraciones.**

## 1. Resumen ejecutivo
La base de dominio (`Customer`, `CustomerAddress`, `Subscription`,
`Plan`, `Contract`) ya cubre la mayor parte de los pasos 1 a 6 del flujo comercial (Figura 1, bloque "Generación de la instalación en SICV"). No es necesario duplicar ningún modelo.

Los puntos principales identificados frente al flujo aprobado son:

1.  **Número de suministro eléctrico:** no existe actualmente en
    `CustomerAddress`. Se propone como un dato propio del domicilio y, por ahora, será **ingresado manualmente**. No se plantea una consulta automática porque actualmente no existe una API para obtener este dato. Debe mantenerse diferenciado de `meter_number`.

2.  **Tipo de vivienda:** no existe actualmente y queda **fuera del MVP** hasta definir la regla de negocio. No se debe mezclar con número, manzana, lote, piso, departamento o interior, porque son conceptos diferentes.

3.  **Generación de OT:** ya existe un flujo de creación de órdenes de trabajo en `develop`, mediante `WorkOrderCreateView`, su ruta y el botón **"Nueva orden de trabajo"**. Por tanto, **no se plantea una segunda vista independiente para generar OT**. El nuevo flujo FTTH deberá reutilizar o adaptar la creación existente y consumir `create_work_order()`.

4.  **Contrato:** `Contract` sí tiene estado. Servicio y plan no deben agregarse nuevamente a `Contract`, porque se obtienen mediante `Subscription`. El número de OT pertenece a `WorkOrder`, no a `Contract`.

5.  **TV Cable ficticio:** en el SICV nuevo no existe actualmente una creación automática de TV Cable ficticia. La regla para el nuevo flujo es simplemente **no introducir ese comportamiento heredado del sistema antiguo**.


## 2. Mapa del flujo aprobado vs. implementación actual

Bloque 1 del flujo (Figura 1): "Generación de la instalación en SICV (ATC / Ventas)".

  ----------------------------------------------------------------
  \#                Paso del flujo    Estado actual                         Archivos involucrados
                    aprobado                                                
  ----------------- ----------------- 
  1                 Buscar o crear    **Implementado.**                     `apps/customers/views.py::CustomerSearchView`
                    cliente (DNI,     `CustomerSearchView` busca por        
                    código u otros    código, documento, nombres, teléfono, 
                    datos)            dirección, distrito, referencia,      
                                      medidor. Acotado a la sede activa.    

  2                 Obtener datos del **Implementado.**                     `apps/customers/views.py::CustomerDocumentLookupView`,
                    cliente (consulta `CustomerDocumentLookupView` consulta `apps/customers/services/sunat.py`
                    DNI/RUC)          RENIEC/SUNAT vía                      
                                      `apps/customers/services/sunat.py`;   
                                      solo autocompleta, no persiste.       

  3                 Completar datos   **Implementado** para                 `apps/customers/forms.py::CustomerRegistrationForm`,
                    del abonado       teléfono/correo/dirección             `apps/customers/views.py::CustomerGeneralDataView`
                    (teléfono,        (`CustomerGeneralDataView`, Pantalla  
                    correo,           4). Distrito y zona se resuelven en   
                    dirección,        el paso 4 (dirección), no en el paso  
                    distrito, zona)   3.                                    

  4                 Registrar         **Parcial.** `CustomerAddress` ya     `apps/customers/models.py::CustomerAddress`,
                    domicilio del     tiene `address`, `reference`,         `apps/customers/forms.py::CustomerAddressForm`
                    servicio          `district` (texto libre), `zone` (FK  
                                      a `Zone`), `meter_number`,            
                                      `latitude/longitude`, `gps_link`,     
                                      `is_primary`. **Falta:** número de    
                                      suministro eléctrico. Este dato se    
                                      registrará manualmente cuando se      
                                      implemente. **Tipo de vivienda queda  
                                      fuera del MVP** hasta definir la      
                                      regla de negocio.                     

  5                 Seleccionar       **Implementado** el mecanismo de      `apps/services/models.py::ServiceType, Plan`,
                    servicio FTTH y   filtrado (`Plan.service_type` +       `apps/services/forms.py::SubscriptionCreateForm`
                    plan (Internet /  validación cruzada en                 
                    Dúo / TV Cable    `SubscriptionCreateForm.clean()`).    
                    según             **No implementado** el catálogo       
                    corresponda)      específico de servicios FTTH/Dúo ---  
                                      depende de qué `ServiceType`/`Plan`   
                                      existan cargados en la base, no del   
                                      código. No se debe introducir         
                                      creación automática de TV Cable       
                                      ficticia.                             

  6                 Crear suscripción **Implementado.**                     `apps/services/views.py::SubscriptionCreateView`,
                    / contrato (alta  `SubscriptionCreateView` crea         `apps/contracts/views.py::ContractCreateView`
                    comercial)        `Subscription` en `PRESALE`;          
                                      `ContractCreateView` crea `Contract`  
                                      solo sobre suscripciones en `PRESALE` 
                                      sin contrato activo previo, genera    
                                      `contract_number` correlativo y       
                                      utiliza el estado de `Contract`.      
                                      Servicio y plan se mantienen en       
                                      `Subscription`; no se duplican en     
                                      `Contract`.                           

  7                 Generar Orden de  **Flujo de creación existente         `apps/work_orders/views.py::WorkOrderCreateView`, ruta
                    Instalación (OT   disponible.** En `develop` existe     existente de OT,
                    en `PENDING`)     `WorkOrderCreateView`, su ruta y el   `apps/work_orders/services.py::create_work_order()`
                                      botón **"Nueva orden de trabajo"**.   
                                      El flujo FTTH no debe crear una       
                                      segunda vista independiente: debe     
                                      reutilizar/adaptar esta creación y    
                                      consumir `create_work_order()`, que   
                                      es la vía de dominio para crear la    
                                      OT. El número de OT pertenece a       
                                      `WorkOrder`.                          

  8                 OT disponible     **No implementado en el canal         `apps/technicians/models.py`,
                    para técnicos     técnico.** La integración con la      `apps/technicians/views.py` (pendiente de
                    (visible según    App/PWA del técnico depende del       implementación)
                    sede)             contrato de API de Kevin.             

Bloque 2 del flujo ("Atención de la instalación en la App del Técnico", pasos 1-9): **fuera de alcance de Joleydi para el hito MVP** según §4.2 del plan, y pendiente del contrato de API y de la app/PWA del canal técnico.


## 3. Auditoría por modelo
### 3.1 `Customer` (`apps/customers/models.py`)
Ya cubre DNI, RUC, C.E. y Pasaporte (`DocumentType`), con la regla de correspondencia documento↔tipo de persona centralizada en
`Customer.person_type_for_document()`. Código único, sede (`branch`), teléfonos, correo, activo/inactivo. **No requiere cambios** para el alcance de este sprint.

### 3.2 `CustomerAddress` (`apps/customers/models.py`)
  -----------------------------------------------------------------------
  Campo actual                        ¿Reutilizable para FTTH?
  ----------------------------------- -----------------------------------
  `zone` (FK a `Zone`, protegido)     Sí --- ya asocia la dirección a una
                                      zona de la sede.

  `address`, `reference`, `district`  Sí.
  (texto libre)                       

  `meter_number`                      Sí, y debe **conservarse tal cual**
                                      --- es el dato del medidor y debe
                                      mantenerse separado del nuevo
                                      número de suministro eléctrico.

  `latitude`, `longitude`, `gps_link` Sí, sin cambios.

  `is_primary`, `is_active`           Sí, sin cambios.
  -----------------------------------------------------------------------

**Campo faltante:** número de suministro eléctrico. Se propone
incorporar en `CustomerAddress` como dato ingresado manualmente. **No existe actualmente una API para consultarlo**, por lo que no se debe plantear un flujo de "jalar datos" mediante el suministro.
Propuesta para una futura implementación, sujeta a aprobación:
``` python
electrical_supply_number = models.CharField(
    max_length=50,
    blank=True,
    verbose_name="Número de suministro eléctrico",
)
```

El campo pertenece a `CustomerAddress`, no a `Customer`, porque
representa un dato del domicilio. Por ahora no se define unicidad ni validación de formato.

**Tipo de vivienda:** queda fuera del MVP hasta definir la regla de negocio. No se propone campo nuevo. No debe mezclarse con número, manzana, lote, piso, departamento o interior.

### 3.3 `ServiceType` / `Plan` (`apps/services/models.py`)
Reutilizables sin cambios. El filtrado servicio→plan ya existe en dos capas: `SubscriptionCreateForm.clean()` (servidor) y en el modelo (`Plan.service_type`, protegido).

No se debe introducir ninguna creación automática de TV Cable ficticia. En el SICV nuevo esa creación automática no existe actualmente; la regla es no incorporar el comportamiento heredado del sistema antiguo.

### 3.4 `Subscription` (`apps/services/models.py`)
Reutilizable sin cambios. Ya relaciona `customer`, `address`,
`service_type` y `plan`, nace en `PRESALE`, y tiene la restricción única `(customer, service_type, service_number)`. El estado `INSTALLATION` ya existe en `Subscription.Status`.

Servicio y plan permanecen en `Subscription`; no deben agregarse
nuevamente a `Contract`.

### 3.5 `Contract` (`apps/contracts/models.py`)
Reutilizable sin cambios. Ya vincula `customer` + `subscription`, exige suscripción en `PRESALE` sin contrato activo previo y genera
`contract_number` correlativo en la vista.

**Estado:** `Contract` **sí tiene estado**, con estados `DRAFT`,
`ACTIVE`, `SUSPENDED`, `CANCELLED` y `FINISHED`.

**Separación de responsabilidades:** - El servicio y el plan se obtienen mediante `Subscription`; no se duplican en `Contract`. - El número de OT pertenece a `WorkOrder`; no pertenece a `Contract`.

**Observación técnica:** `ContractCreateView.generate_contract_number()` calcula el correlativo con
`Contract.objects.order_by("-id").first().id + 1`, sin bloqueo
transaccional --- a diferencia del correlativo de `WorkOrderSequence` en `work_orders`, que sí usa `select_for_update()`. No es parte del alcance de este sprint modificarlo, pero se deja registrado como riesgo latente
de colisión bajo alta concurrencia.

### 3.6 `WorkOrder` / `WorkOrderCreateView` / `create_work_order()`(`apps/work_orders/`)

**No se modifica en esta jornada.** El proyecto ya cuenta en `develop` con `WorkOrderCreateView`, su ruta y el botón **"Nueva orden de trabajo"**.

Para el flujo FTTH **no se creará una segunda vista independiente para generar OT**. Se deberá reutilizar/adaptar la creación existente y consumir `create_work_order()`, que constituye la vía de dominio para la creación de la orden.

El número de OT pertenece a `WorkOrder`, no a `Contract`.


## 4. Lista exacta de archivos que requerirían cambio

  ---------------------------------------------------------------------------------------------------------------
  Archivo / componente                                       Cambio previsto              Requiere migración
  ---------------------------------------------------------- ---------------------------- -----------------------
  `apps/customers/models.py`                                 Agregar                      Sí, si se aprueba
                                                             `electrical_supply_number` a 
                                                             `CustomerAddress` (pendiente 
                                                             de aprobación)               

  `apps/customers/forms.py`                                  Agregar el campo a           No
                                                             `CustomerAddressForm` para   
                                                             ingreso manual               

  `apps/customers/templates/customers/address_create.html`   Agregar el campo al          No
                                                             formulario visual            

  `apps/customers/templates/customers/detail.html`           Mostrar el número de         No
                                                             suministro eléctrico         

  `WorkOrderCreateView` y ruta existente                     Reutilizar/adaptar la        No
                                                             creación existente para el   
                                                             flujo FTTH; **no crear una   
                                                             segunda vista                
                                                             independiente**              

  `apps/work_orders/services.py::create_work_order`          Consumir el servicio de      No
                                                             dominio existente desde el   
                                                             flujo FTTH                   

  `apps/services/...`                                        Sin cambios necesarios       No

  `apps/contracts/...`                                       Sin cambios necesarios       No

  `apps/technicians/...`                                     Integración futura,          No
                                                             bloqueada por el contrato de 
                                                             API de Kevin                 
  ---------------------------------------------------------------------------------------------------------------

**Nota:** Ningún archivo de `apps/work_orders/` se modifica en la
jornada de hoy. La referencia a `WorkOrderCreateView` corresponde al
flujo existente que deberá reutilizarse/adaptarse cuando se implemente
la integración FTTH.

------------------------------------------------------------------------

## 5. Bloqueos / puntos a definir con negocio o con Kevin

1.  Formato y unicidad del número de suministro eléctrico.
2.  Regla de negocio para "tipo de vivienda". **Queda fuera del MVP**
    hasta que exista una definición aprobada.
3.  Integración del flujo comercial con la creación existente de OT:
    reutilizar/adaptar `WorkOrderCreateView` y consumir
    `create_work_order()`.
4.  Contrato de API para el canal técnico (login, listar OT, tomar OT),
    pendiente de definición con Kevin.
5.  Confirmar el catálogo de `ServiceType`/`Plan` que estará disponible
    para FTTH. No se debe introducir creación automática de TV Cable
    ficticia.

------------------------------------------------------------------------

## 6. Validaciones y evidencia de la auditoría

La observación de la revisión exige registrar **el resultado real** de
las validaciones ejecutadas y no únicamente los comandos.

En la evidencia disponible para esta corrección documental **no se
conserva la salida de ejecución ni el conteo real de tests del
repositorio**, por lo que no se inventan cantidades ni resultados.

  -----------------------------------------------------------------------
  Validación                          Resultado real disponible en la
                                      evidencia
  ----------------------------------- -----------------------------------
  `python manage.py check`            No consta la salida de ejecución en
                                      la evidencia disponible

  Suite de tests (`pytest` /          No consta el número real de tests
  `python manage.py test`, según      ejecutados/aprobados en la
  corresponda al proyecto)            evidencia disponible

  Revisión de `WorkOrderCreateView`,  **Identificado como existente en
  ruta y botón "Nueva orden de        `develop`**, según la revisión de
  trabajo"                            arquitectura

  Revisión de `create_work_order()`   **Identificado como servicio de
                                      dominio existente** para la
                                      creación de OT

  Revisión de `Contract`              **Confirmado que tiene estado**;
                                      servicio/plan permanecen en
                                      `Subscription` y el número de OT
                                      corresponde a `WorkOrder`
  -----------------------------------------------------------------------

**Importante:** esta jornada corresponde únicamente a la corrección de
la documentación. No se modificaron modelos, migraciones ni
`work_orders`.

------------------------------------------------------------------------

## 7. Pendiente para la siguiente jornada (Martes 01/09)

Consolidar identificación, contacto y dirección; implementar el registro
manual del número de suministro eléctrico si fue aprobado técnicamente;
mantener la separación suministro vs. medidor; mantener fuera del MVP el
tipo de vivienda hasta definir la regla de negocio; y continuar con la
adaptación del flujo comercial para reutilizar `WorkOrderCreateView` y
consumir `create_work_order()`.

Condición de entrada: definición del número de suministro eléctrico y de
la regla de negocio de tipo de vivienda, además de los acuerdos
necesarios para la integración de la OT.