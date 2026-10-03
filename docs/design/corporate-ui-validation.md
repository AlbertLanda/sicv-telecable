# Validación de la interfaz corporativa

Fecha: 2026-10-03. Rama de trabajo: `feature/corporate-client-ui`, basada en QA `61d1808cc0db5af17f2ee211dc62cff8af58e4b7`.

Las comprobaciones de navegación se ajustaron en `fix/corporate-navigation-checks` para esperar `aria-hidden="true"` en iconos decorativos. Conservan la verificación de URL, texto, ubicación única del cobro y pestaña activa; no se eliminan aserciones ni se modifica la interfaz revisada.

## Código y datos

La interfaz integra el panel existente, sus detalles, búsqueda y ficha del abonado. No cambian modelos, migraciones, reglas económicas, permisos ni emisión fiscal. Los enlaces de nombre y código conducen a la ruta real de la ficha. La búsqueda conserva y codifica su término al paginar.

## Pruebas

- Suite Django local final: 1.962 pruebas, resultado OK, 7 omitidas por configuración. Después de las correcciones de revisión se repitieron las 40 pruebas existentes de panel, rediseño de ficha, ubicación, consulta NOC y cifras compartidas; resultado OK. Las 22 pruebas de navegación de cuentas también pasaron tras actualizar las expectativas de los iconos decorativos.
- `manage.py check`: sin incidencias. `makemigrations --check --dry-run`: sin cambios. `node --check` y `git diff --check`: correctos.
- `collectstatic` con `CompressedManifestStaticFilesStorage`: recursos copiados y procesados correctamente, incluidas referencias relativas a las fuentes locales.
- Chromium: ocho vistas autenticadas en cada ancho 390, 1280 y 1440px (24 vistas), sin desbordamiento horizontal del documento, errores JavaScript ni solicitudes fallidas. Inter local cargado.
- Navegación panel → listado → nombre del abonado → ficha; búsqueda → ficha; seis pestañas y estado activo; menú Más opciones; búsqueda sin resultados y recuperación; preferencia de colapso de escritorio; menú móvil, 35 pasos Tab, Escape, cierre por fondo y cambio de tamaño.
- Las tres tablas de Información se enfocaron en móvil y desplazaron con ArrowRight; se verificó `scrollLeft > 0`. Las ayudas de desplazamiento se esconden si la tabla cabe.

Las verificaciones de navegador usan exclusivamente una base SQLite local aislada y datos ficticios. No modifican datos del SICV legado ni registros de la nube. Las capturas `previews/corporate/` corresponden a panel, búsqueda e Información en escritorio/móvil. Sus nombres, documentos e importes son ejemplos de QA, no datos operativos.

## Revisión visual

Revisión independiente con Impeccable: primera disposición FIX. Se corrigieron los tres hallazgos materiales en un lote: eliminación de etiquetas decorativas sobre títulos; regiones de tabla con nombre/foco y ayuda de desplazamiento; selección, cursor de texto y barras de desplazamiento acordes a la interfaz. Se recapturaron los seis archivos y el revisor puntuó los tres hallazgos como resueltos, con disposición SHIP en el alcance revisado.

No se ejecutó el detector de Impeccable ni una auditoría exhaustiva de contraste. La revisión visual cubre panel, búsqueda, Información y marco compartido. El navegador también ejercita las seis pestañas, pero no acredita todos los roles, estados, volúmenes o textos extensos. Otras composiciones y los bordes de los avisos de alta siguen pendientes de su revisión específica. No implica autorización tributaria ni conexión OSE/SUNAT.

## Procedencia de capturas

Capturas propias del render real de Django con Chromium. No son imágenes generadas, referencias extraídas de Figma ni representaciones de la producción. El kit público Carbon fue identificado; se consultó su documentación oficial porque las herramientas nativas de Figma no estaban expuestas. Véase `corporate-ui-direction.md`.
