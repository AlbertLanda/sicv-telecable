# Calidad de datos de abonados

Primera entrega de revisión del padrón actual. Se abre desde **Clientes →
Calidad de datos**, en `/reportes/calidad-abonados/`.

ATC y Administración pueden detectar expedientes incompletos sin depender de
decisiones sobre caja o facturación. La pantalla utiliza el permiso existente
`customers.change_customer`, también exigido al entrar por URL. No cambia
permisos de otros roles.

## Operación

1. Seleccionar la sede en la barra superior.
2. Revisar los indicadores y filtrar por estado, código, nombre o documento.
3. Seleccionar una alerta para consultar sus abonados.
4. Abrir la ficha desde el código y contrastar el dato con una fuente válida.

Las correcciones siguen el flujo existente de la ficha y sus permisos. Esta
pantalla no escribe, fusiona, elimina ni importa abonados.

## Controles

| Alerta | Criterio |
|---|---|
| Documento por revisar | Tipo desconocido, número vacío, DNI que no tiene 8 dígitos ASCII, RUC que no tiene 11, o número con espacios exteriores/minúsculas. |
| Posible documento duplicado | Dos abonados de la misma sede con tipo y número coincidentes al quitar espacios exteriores y convertir a mayúsculas. Incluye inactivos aunque el listado filtre solo activos. Los números vacíos no se agrupan. |
| Sin nombre o razón social | Persona natural sin nombres ni apellidos; persona jurídica sin razón social; tipo de persona desconocido. |
| Sin dirección completa | Ninguna dirección activa tiene dirección y distrito informados. Una dirección secundaria completa también sirve. |
| Sin medio de contacto | Teléfono principal, secundario y correo vacíos. No exige tener los tres. |

Un abonado puede presentar varias alertas. Los indicadores cuentan personas,
conservan la búsqueda y el estado elegidos, y no cambian al seleccionar una
alerta. La tabla aplica además la alerta seleccionada y pagina de 25 en 25.
Los filtros inválidos devuelven errores, no un listado vacío aparentemente
correcto. Sin sede activa no se consulta el padrón de todas las sedes.

## Límites

- Revisa datos **ya presentes en SICV**, incluidos los cargados en ensayos de
  migración. No analiza directamente exportaciones del sistema anterior.
- Las coincidencias no prueban que dos expedientes sean la misma persona ni
  autorizan su fusión. No se buscan coincidencias entre sedes.
- No valida identidad, existencia o estado fiscal en RENIEC/SUNAT, dígito
  verificador del RUC, vigencia del contacto, servicios, deuda o facturación
  agrupada. Sin alertas no equivale a expediente aprobado para migrar.
- El diagnóstico se calcula al consultar. No conserva un cierre de revisión
  ni reemplaza la validación contable.
- No requiere migraciones de base de datos ni nuevas dependencias.

## Verificación

`apps.reports.tests.test_customer_quality` cubre reglas, coincidencias con
inactivos, separación de sedes/tipos de documento, filtros, paginación,
permisos, nombres escapados, consulta sin cambios y ausencia de consultas por
cada fila. El módulo se incluye también en el job PostgreSQL de CI.

Todos los datos de las pruebas son ficticios. No incorporar expedientes,
documentos ni exportaciones reales al repositorio público.
