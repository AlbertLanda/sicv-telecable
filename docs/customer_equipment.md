# Equipos: registro desde la liquidación técnica

## Decisión funcional vigente — 2026-10-06

Telecable confirmó que el registro independiente de equipos por abonado no
corresponde al nuevo sistema: genera una carga manual que ya se descartó.
El técnico registra los **últimos cuatro dígitos** del equipo durante su
atención/liquidación y ese dato sirve para completar el registro operativo.
Esta decisión reemplaza la propuesta y entrega del PR #39.

## Flujo que se conserva

1. El técnico asignado completa la ficha técnica de la misma OT. El campo
   de equipo indica «Equipo — últimos 4 dígitos» y admite valores como `0123`.
2. Al liquidar, `liquidation_technical_data_from_field()` copia
   `WorkOrderFieldSheet.equipment_code` a
   `WorkOrderLiquidation.equipment_serial`.
3. El dato continúa disponible en el contexto técnico de la OT y en los
   flujos existentes de revisión. No se requiere que ATC o Administración
   creen un equipo ni que lo asignen en un catálogo adicional.

El valor se mantiene como texto, conservando ceros iniciales. Se conservan los
valores completos anteriores y el contrato de la API; no se truncan datos ni
se añade una validación que obligue a reescribirlos. Cuatro dígitos son una
referencia parcial: no se inventa una serie/MAC completa ni se usa ese sufijo
como identificador único global o para resolver automáticamente un equipo.

## Retiro del apartado independiente

Se retiran el menú «Equipos de abonados», la pestaña «Equipos», sus formularios,
rutas y servicios de alta/asignación/retiro/revisión. Las antiguas URLs
`/equipos/…` dejan de estar disponibles, también para superusuarios. Se
eliminan las capacidades automáticas de ese módulo en los roles ATC/Admin.

Los modelos y la migración ya aplicada se conservan únicamente como archivo
para no destruir posibles registros anteriores. El admin mantiene consulta
sin alta, edición ni borrado. Se mantienen las protecciones de históricos
frente al borrado de altas provisionales. Este archivo no participa en la
liquidación técnica ni requiere trabajo operativo.

No hay migración destructiva, conversión de registros a partir de coincidencias
de cuatro dígitos ni integración nueva con almacén. Los movimientos de
materiales y su API de Logística mantienen su flujo actual.

## Verificación

Las pruebas comprueban que las URLs retiradas no permiten lectura ni escritura,
que no quedan enlaces del registro manual y que el archivo no permite editar
por admin. Una prueba de integración del canal técnico registra `0123`, termina
la atención y liquida la OT conservando ese valor sin crear un registro de
equipo independiente. Se ejecuta también en PostgreSQL.
