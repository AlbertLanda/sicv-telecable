@"
# Módulo de Consulta de Clientes (SICV)

## 1. Objetivo

Proporcionar una primera interfaz visual funcional de consulta de clientes del SICV.

El módulo permite que un colaborador autenticado busque un abonado y consulte en una ficha consolidada su información principal, direcciones, suscripciones, contratos y órdenes de trabajo relacionadas.

La interfaz es exclusivamente de consulta y no modifica las reglas de negocio de suscripciones ni del motor de órdenes de trabajo.

## 2. Flujo funcional

El flujo implementado es:

LOGIN → BÚSQUEDA DE CLIENTE → RESULTADOS → FICHA DEL CLIENTE

Desde la ficha del cliente se puede consultar:

- Datos generales.
- Direcciones registradas.
- Suscripciones y servicios.
- Contratos relacionados.
- Órdenes de trabajo relacionadas.

## 3. Rutas implementadas

### Búsqueda

- Nombre: `customers:search`
- Ruta: `/customers/search/`
- Vista: `CustomerSearchView`

Permite realizar búsquedas de clientes y visualizar los resultados con paginación.

### Ficha del cliente

- Nombre: `customers:detail`
- Ruta: `/customers/<id>/`
- Vista: `CustomerDetailView`

Utiliza el identificador interno del cliente para acceder a su ficha consolidada.

## 4. Criterios de búsqueda

La búsqueda utiliza un único campo principal denominado `q`.

Actualmente contempla:

- DNI.
- RUC.
- Código de cliente.
- Nombres.
- Apellido paterno.
- Apellido materno.
- Razón social.
- Teléfono principal.
- Teléfono secundario.

La búsqueda:

- Ignora espacios al inicio y final.
- Permite coincidencias parciales.
- No distingue entre mayúsculas y minúsculas.
- Normaliza las tildes.
- Permite ingresar varias palabras.
- Evita duplicar clientes.
- No realiza una consulta masiva cuando el criterio está vacío.
- Conserva el criterio ingresado después de realizar la búsqueda.

## 5. Listado de resultados

Los resultados se muestran mediante una vista paginada.

La paginación está configurada en:

- 20 clientes por página.

Cada resultado permite identificar al cliente y acceder a su ficha.

La consulta utiliza `select_related("branch")` para obtener la sede asociada sin realizar consultas adicionales por cada resultado.

## 6. Ficha consolidada

La ficha del cliente se divide en los siguientes bloques.

### 6.1 Datos del cliente

Se muestran:

- Código de abonado.
- Tipo y número de documento.
- Tipo de persona.
- Nombres y apellidos.
- Razón social.
- Teléfono principal.
- Teléfono secundario.
- Correo electrónico.
- Sede.
- Fecha de registro.
- Estado.

### 6.2 Direcciones

Se muestran las direcciones relacionadas con el cliente:

- Dirección.
- Referencia.
- Distrito.
- Zona.
- Número de medidor.
- Latitud.
- Longitud.
- Enlace GPS.
- Identificación de dirección principal.

Las direcciones principales se identifican visualmente.

### 6.3 Suscripciones y servicios

Se muestran:

- Identificador de suscripción.
- Número de servicio.
- Tipo de servicio.
- Plan.
- Dirección del servicio.
- Estado.
- Velocidad.
- Tecnología.
- Fecha de instalación.
- Fecha de corte.
- Fecha de reconexión.
- Ciclo de facturación.

Los estados existentes se representan sin modificar la lógica de negocio:

- `PRESALE`: Preventa.
- `INSTALLATION`: En instalación.
- `ACTIVE`: Activo.
- `SUSPENDED`: Suspendido.
- `CUT`: Corte.
- `CANCELLED`: Cancelado.

La interfaz solamente consulta estos estados.

### 6.4 Contratos

Se muestran los contratos relacionados con el cliente:

- Número de contrato.
- Suscripción relacionada.
- Fecha de inicio.
- Fecha de finalización.
- Estado.

No se implementa edición de contratos en esta fase.

### 6.5 Órdenes de trabajo

Las órdenes se consultan exclusivamente en modo lectura.

Se muestran:

- Número de orden.
- Servicio.
- Tipo.
- Subtipo.
- Motivo.
- Causa.
- Estado.
- Prioridad.
- Técnico asignado.
- Resultado.
- Fecha programada.
- Fecha de creación.
- Fecha de atención cuando corresponda.

Las órdenes pertenecientes a otros clientes no se muestran en la ficha.

## 7. Optimización de consultas

La ficha relaciona diferentes entidades del dominio, por lo que se utilizan mecanismos del ORM de Django para reducir consultas innecesarias.

Se utiliza:

- `select_related()` para relaciones ForeignKey.
- `prefetch_related()` para colecciones relacionadas.
- `Prefetch()` para controlar los querysets relacionados.

Se optimizan relaciones entre:

- Cliente y sede.
- Cliente y direcciones.
- Cliente y suscripciones.
- Cliente y contratos.
- Suscripción y tipo de servicio.
- Suscripción y plan.
- Suscripción y dirección.
- Suscripción y órdenes de trabajo.
- Orden y tipo.
- Orden y subtipo.
- Orden y motivo.
- Orden y causa.
- Orden y resultado.
- Orden y técnico asignado.
- Orden y sede.
- Orden y zona.

La lógica de consulta permanece en las vistas y no se realizan consultas individuales desde los templates.

## 8. Seguridad y permisos

Las vistas de consulta utilizan `LoginRequiredMixin`.

Por lo tanto:

- Un usuario autenticado puede acceder al buscador.
- Un usuario anónimo es redirigido al login.
- La información no se expone mediante endpoints públicos.
- Las vistas no implementan operaciones de modificación.
- No se modifican clientes.
- No se modifican direcciones.
- No se modifican suscripciones.
- No se modifican contratos.
- No se modifican órdenes de trabajo.

Los permisos finos por rol quedan fuera del alcance de esta primera fase.

## 9. Pruebas automatizadas

Las pruebas se encuentran en:

`apps/customers/tests.py`

Actualmente el módulo cuenta con 39 pruebas automatizadas.

Las pruebas cubren, entre otros aspectos:

- Acceso autenticado.
- Restricción para usuarios anónimos.
- Búsqueda por DNI.
- Búsqueda por RUC.
- Búsqueda por código.
- Búsqueda por nombre.
- Búsqueda por apellidos.
- Búsqueda por razón social.
- Búsqueda por teléfono.
- Búsquedas parciales.
- Normalización de espacios y tildes.
- Búsqueda con múltiples palabras.
- Ausencia de resultados.
- Búsqueda vacía.
- Eliminación de duplicados.
- Paginación.
- Visualización de datos del cliente.
- Visualización de direcciones.
- Dirección principal.
- Visualización de suscripciones.
- Visualización de planes y servicios.
- Estados de suscripción.
- Contratos relacionados.
- Órdenes relacionadas.
- Aislamiento de órdenes de otros clientes.
- Clientes sin suscripciones.
- Cliente inexistente.
- Comportamiento de solo lectura.
- Relaciones entre las entidades consultadas.

## 10. Validaciones realizadas

El módulo ha sido validado mediante:

```text
python manage.py test apps.customers
→ 39 tests OK

python manage.py check
→ System check identified no issues

python manage.py makemigrations --check
→ No changes detected

git diff --check
→ Sin errores