# Ficha ejecutiva del cliente y shell visual global

## Objetivo

La ficha del abonado se convierte en una vista operativa priorizada y el mismo
lenguaje visual se aplica como shell global del SICV.

El sistema usa una barra superior azul, navegación lateral blanca por dominios,
contenido sobre fondo gris azulado y tarjetas blancas con jerarquía consistente.

## Navegación global

La barra superior concentra identidad, módulos principales, sede/oficina activa
y cuenta del usuario. La navegación lateral agrupa opciones por dominio:

- Clientes.
- Operaciones.
- Comercial.
- Reportes.

Solo las funcionalidades ya construidas son enlaces. Los módulos pendientes se
muestran como referencia, pero no como rutas falsas. Esta decisión evita que la
interfaz prometa funciones inexistentes y permite ir activando cada opción sin
rediseñar nuevamente la navegación.

El menú lateral puede colapsarse en escritorio y funciona como panel deslizable
en pantallas pequeñas.

## Ficha del abonado

La cabecera resume identidad, contacto, sede, servicios activos y OT abiertas.
La OT abierta más reciente se destaca antes del resto del contenido.

La vista inicial de una OT y la ficha técnica permanecen separadas:

- orden inicial: qué solicitó/emite ATC;
- ficha técnica: qué registró el técnico durante la atención.

## Mapa

Cuando la dirección principal dispone de coordenadas válidas, se construye un
Google Maps embebido y un enlace externo usando esas coordenadas reales. No se
inventa ubicación si el cliente no tiene GPS registrado.

## Alcance

Este rediseño no modifica modelos ni reglas de negocio. El retiro de asignación
manual permanece vigente y la programación sigue siendo independiente de la
toma de la OT por el técnico.
