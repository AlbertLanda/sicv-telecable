# Dashboard operativo del abonado

## Objetivo

La ficha del cliente prioriza ahora la información que ATC necesita para operar
sin recorrer bloques extensos: identidad, contacto, servicio, dirección, contrato
y órdenes abiertas.

## Jerarquía visual

1. Encabezado ejecutivo del abonado.
2. Orden de trabajo abierta destacada, cuando existe.
3. Accesos rápidos a resumen, direcciones, suscripciones, contratos, OT y actividad.
4. Resumen compacto de los datos principales.
5. Secciones completas para consulta histórica.

## Orden inicial vs. ejecución técnica

La ruta `work_orders:<pk>/initial/` presenta la orden administrativa emitida por
ATC y excluye deliberadamente la ficha técnica, evidencias y liquidación. Puede
abrirse para consulta o con `?print=1` para lanzar la impresión del navegador.

La ruta habitual `work_orders:<pk>/` continúa siendo la ficha técnica viva: allí
se visualiza lo registrado posteriormente por el técnico (NAP, borne, equipo,
evidencias, liquidación, etc.).

Esta separación evita mezclar lo solicitado originalmente con lo ejecutado en
campo y conserva el flujo de claim del técnico sin reintroducir asignación manual.
