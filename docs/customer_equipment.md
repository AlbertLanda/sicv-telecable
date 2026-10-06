# Equipos por abonado — primera entrega

Base: Azure QA `060ca58d2f024a6948f325387938b92dec98a1a3`.
Rama: `feature/customer-equipment`.

## Flujo operativo

1. Administración abre **Clientes → Equipos de abonados → Registrar equipo**.
   Registra tipo, marca, modelo y al menos serie o MAC, leyendo la etiqueta.
   La sede proviene de la barra superior. Serie y MAC no pueden repetirse,
   incluso en otra sede; la serie se guarda en mayúsculas y la MAC con dos
   caracteres por segmento.
2. ATC o Administración abre la ficha del abonado, pestaña **Equipos**,
   selecciona **Asignar equipo**, elige el equipo y el servicio. Puede
   relacionar una OT del mismo servicio y escribir una observación.
3. Al retirarlo, registra un motivo y el estado posterior: disponible para
   asignar, retirado/por revisar o dañado. El movimiento permanece visible.
4. Administración puede revisar un equipo sin asignación vigente, registrar
   el resultado y cambiar su estado; por ejemplo, devolverlo a disponible.
5. Un reemplazo consta de retirar el anterior y asignar el nuevo. Son dos
   movimientos explícitos, no una sustitución que borra el pasado.

La lista permite búsqueda por serie, MAC, marca/modelo y estado. Los
historiales se paginan. La ficha del equipo conserva sus asignaciones a
distintos servicios, revisiones, fechas y usuarios. La ficha del abonado
reúne los equipos de sus servicios. Las fechas corresponden al registro de
la operación en SICV; no se presentan como fechas históricas de instalación.

## Permisos y alcance

| Acción | Permiso | Rol incluido |
|---|---|---|
| Consultar | `equipment.view_equipment` | ATC y Administración |
| Registrar equipo | `equipment.add_equipment` + consulta | Administración |
| Asignar y retirar | `equipment.assign_equipment` + consulta | ATC y Administración |
| Revisar estado | `equipment.change_equipment` + consulta | Administración |

Las URLs y consultas exigen la sede activa; cambiar parámetros no abre otras
sedes. Los servicios de dominio vuelven a validar permiso, sede, disponibilidad
y estado del servicio. Las capacidades pueden concederse explícitamente con
los permisos habituales de Django. No se incorporan a Contabilidad ni al
canal de técnicos automáticamente.

## Integridad

- Una restricción de base de datos admite una sola asignación vigente por
  equipo; las operaciones bloquean el equipo dentro de una transacción.
- No se asigna a un abonado inactivo ni a un servicio inactivo o cancelado.
- Un servicio cancelado puede conservar un equipo físicamente pendiente de
  retiro. Su retiro no exige reactivar el servicio.
- Una clave de operación evita duplicar asignaciones o revisiones al
  reenviar formularios. Reenviar una asignación ya retirada no la reactiva.
  Repetir el retiro antiguo no afecta una asignación posterior.
- Los retiros exigen motivo, usuario, fecha y estado posterior. Una revisión
  no puede cambiar el estado de un equipo que continúa asignado.
- El historial protege equipos, suscripciones y órdenes referenciadas frente
  a borrado. Descartar altas o desistir de instalaciones detecta este historial
  y rechaza la eliminación provisional con un mensaje explicativo.
- El admin Django expone estas entidades como consulta. No ofrece edición
  libre ni borrado del historial o de los identificadores.

## Alcance de esta entrega

Es seguimiento del equipo físico ligado al servicio. La venta del producto
existente, los materiales declarados en campo y el stock de Logística siguen
siendo flujos separados. No descuenta existencias, no genera deuda ni cambia
automáticamente estados de órdenes.

No convierte los campos libres de serie/MAC de OTs antiguas en equipos: esa
vinculación necesita revisión para no inventar asignaciones. Tampoco importa
historial del legado, transfiere equipos entre sedes ni sincroniza todavía
este registro desde el portal técnico. El técnico que ejecutó la orden puede
consultarse en la OT de referencia; `assigned_by` identifica a quien registró
la asignación en SICV, no necesariamente al instalador.

## Despliegue y pruebas

La migración `equipment.0001_initial` crea tres tablas y restricciones. No
modifica ni borra datos existentes. El arranque de `sicv-telecable-qa` aplica
las migraciones según el procedimiento ya configurado. Otros entornos siguen
requiriendo su proceso habitual de migración.

Pruebas: `python manage.py test apps.equipment`.
La prueba de dos asignaciones simultáneas requiere PostgreSQL y se incorpora
al job PostgreSQL de CI. Las demás cubren normalización, duplicados, ciclo de
uso, reenvíos, permisos, sede, integridad, protección de historial, formularios,
CSRF, escape de textos y paginación. Datos exclusivamente ficticios.

Para validar visualmente en QA: registrar un equipo ficticio, asignarlo a un
servicio de prueba, retirarlo por revisión, devolverlo a disponible y asignarlo
de nuevo. Confirmar ambas asignaciones y la revisión en su historial.
