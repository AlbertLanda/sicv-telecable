# Dirección corporativa del SICV

## Encargo y alcance

El usuario delega la selección de una referencia empresarial de Figma y solicita una interfaz propia para Telecable, rápida para ATC, Contabilidad y Administración. El trabajo integra el diseño en el panel real, sus cuatro listados, búsqueda de abonados y cabecera de las seis pestañas de la ficha. Conserva Django, Bootstrap, datos, URLs y permisos existentes. El marco visual también se comparte con otras páginas autenticadas; sus composiciones específicas no se reconstruyen en esta entrega.

## Referencia y procedencia

Kit público `(v11) Carbon Design System`, enlazado desde la documentación oficial de IBM: https://www.figma.com/community/file/1157761560874207208. Fuente accesible: https://www.carbondesignsystem.com/getting-started/designing/design-resources y https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines.

Figma fue instalado, pero sus herramientas de lectura no aparecieron en el registro disponible durante esta ejecución. El enlace público bloqueó al rastreador. Por tanto, se adaptan las pautas oficiales documentadas de Carbon; no se declara extracción de nodos, inspección de un archivo privado ni fidelidad píxel a píxel a una pantalla de Figma.

Guías adicionales proporcionadas por el usuario: Impeccable (Operate y craft floor), Emil Kowalski y Taste Redesign. Se usan como criterios de diseño, sin introducir React ni dependencias visuales nuevas. No existe un comp aprobado para esta implementación; es una composición desde código.

## Primera pantalla

Una barra blanca identifica Telecable y la sede. El menú de tinta oscura distingue la navegación global; el cuerpo neutro favorece lectura continua. El panel presenta alcance y período, una banda de cuatro indicadores con separadores y las dos consultas de recaudación y cartera. Los importes se alinean con numerales tabulares. Ámbar señala órdenes críticas; no se inventan cifras ni tendencias.

La búsqueda pone el campo principal antes de la tabla. El nombre y el código abren la ficha real. En la ficha, una identidad estable y seis pestañas con estado activo conservan el contexto del abonado al consultar información, órdenes, deuda, historial de pagos, comprobantes y actividad. Las acciones mutables siguen condicionadas por permisos.

## Interacción característica

Panel → listado del indicador → nombre del abonado → ficha → pestaña. Cada paso usa una URL real y conserva los filtros de los indicadores existentes. El usuario puede abrir enlaces en otra pestaña; no se convierten filas enteras en controles ambiguos.

## Calidad y restricciones

- Encabezado principal único, jerarquía corta, etiquetas visibles o accesibles, foco visible y enlace al contenido.
- Textos primarios oscuros, secundarios legibles; azul para acciones y selección, verde para marca y confirmación.
- Esquinas de 4px, sin sombras decorativas ni animaciones de entrada. El marco no anima al alternar menú. Movimiento reducido respetado.
- Tabla desplazable y enfocable en móvil; ningún desbordamiento del documento en 390, 1280 y 1440px.
- Menú móvil con fondo de cierre, Escape, foco contenido y contenido principal inerte mientras está abierto. Menú cerrado inerte; preferencia de escritorio separada del estado móvil.
- Datos locales sintéticos etiquetados como MUESTRA QA en las capturas. Las capturas no representan la operación real ni emisión tributaria.

## Implementación

`apps/reports/static/reports/corporate.css` define la capa visual autenticada después de estilos específicos. `corporate-shell.js` centraliza navegación y búsqueda de opciones. La tipografía Inter y las versiones Bootstrap ya existentes se conservan, ahora servidas desde el SICV junto con sus licencias; véase `apps/reports/static/reports/vendor/README.md`. No se cargan componentes de Carbon ni nuevas bibliotecas JavaScript. WhiteNoise versiona y comprime los recursos en nube.

La preparación fiscal continúa siendo preparación. Este trabajo no conecta OSE/SUNAT, no modifica reglas de facturación y no toca el sistema legado activo.
