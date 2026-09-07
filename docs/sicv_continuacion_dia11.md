# SICV Telecable — continuidad día 11

Esta rama continúa desde los avances de Kevin (`feature/actividades-sicv-dia9`) y Joleydi (`feature/ot-validacion-programacion-dia10`) sin modificar sus ramas históricas.

## Cerrado en esta continuación

- La programación por día sin hora usa `scheduled_date`; no se inventa una hora 09:00.
- El tablero muestra `Sin hora` cuando corresponde.
- Una OT `PENDING` puede moverse más de una vez y continúa `PENDING`, sin técnico y sin registros de asignación.
- Una OT que realmente pasa a `REPROGRAMMED` continúa sujeta al workflow existente.
- La API del canal técnico expone `scheduled_at`, `scheduled_date` y `agenda_date`, de forma que el cliente móvil pueda distinguir hora pactada, día-sin-hora y ausencia de programación.
- Programar y tomar/asignar una OT siguen siendo operaciones independientes.

## Siguiente bloque inmediato

1. Adaptar el portal técnico existente para pintar:
   - fecha + hora cuando exista `scheduled_at`;
   - fecha + `Sin hora` cuando exista `scheduled_date`;
   - `Sin programación` cuando ambos sean nulos.
2. Revisar el orden de las bandejas técnicas para que una OT con `scheduled_date` no sea tratada como si no estuviera programada.
3. Añadir restricción de base de datos que impida que `scheduled_at` y `scheduled_date` tengan valor simultáneamente.
4. Alinear la documentación FTTH: una instalación del canal comercial nace como atención `FIELD`.
5. Ejecutar la suite completa y corregir cualquier contrato de API afectado por los nuevos campos.

## Después del cierre técnico

- ampliar el canal técnico a los trabajos de campo que negocio confirme;
- flujo NOC para órdenes `SYSTEM` sin publicarlas en el pool de técnicos de campo;
- dashboard operativo por sede, estado, tipo y motivo;
- matriz de permisos definitiva;
- auditoría de acciones e históricos;
- catálogo de OT para validación formal con ATC.

Inventario, cobranza y despliegue PostgreSQL/Azure se mantienen como bloques posteriores que requieren validación de proceso antes de ampliar el modelo.
