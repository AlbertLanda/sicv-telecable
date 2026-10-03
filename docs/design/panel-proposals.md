# Propuestas visuales del panel SICV

Estado: propuestas para seleccionar. La aplicación conserva el panel actual; el comparador se publica como archivo estático independiente en QA.

Abrir `apps/reports/static/reports/panel-proposals.html` en un navegador, o `/static/reports/panel-proposals.html` en QA. Es autocontenido, funciona sin conexión y no necesita dependencias. El selector superior permite comparar ambos diseños con el mismo alcance y los mismos datos. La selección no guarda una preferencia definitiva para la aplicación.

## Alcance y contenido

Modo Operate: administrador y Contabilidad consultan indicadores y pasan a detalles. Los datos son ficticios. Filtros por sede y mes, búsqueda, navegación por indicadores y tabla de detalles funcionan sobre un conjunto de demostración local. No existe conexión con la base, SUNAT ni ningún servicio externo. No se registran pagos ni cambian abonados.

Se preservan los cuatro indicadores actuales, su definición provisional de activo y los conceptos de fecha real de pago, cartera por antigüedad y órdenes con más de 48 horas. La variante no redefine permisos ni reglas contables. Hay acceso directo a las cuatro listas y los filtros se conservan al cambiar de variante.

## A · Ejecutiva

Una navegación lateral de tinta azul distingue el espacio administrativo. Una banda horizontal de indicadores evita repetir cuatro cajas independientes. La tendencia de recaudación ocupa la región principal; la antigüedad de cartera y las órdenes críticas acompañan la lectura. Azul corporativo para selección y acciones, verde para confirmación, ámbar para pendientes.

Primera pantalla: sede y período, cuatro indicadores y tendencia visibles. Interacción principal: pulsar un indicador para consultar inmediatamente sus filas. Ventaja: facilita la presentación a Gerencia. Riesgo: el gráfico ocupa espacio que podría destinarse a más registros.

## B · Operativa

Navegación horizontal y fondo claro para un puesto de trabajo con uso prolongado. Las cifras son una franja compacta de consulta. La tabla de sedes ocupa la región principal, con cartera y órdenes a la derecha. Azul para acciones y estados activos; verde corporativo en la identificación y los pagos confirmados.

Primera pantalla: alcance, período, cifras y comparativo de sedes. Interacción principal: entrar desde una sede o abrir Cobros, Cartera u Órdenes sin desplegar grupos. Ventaja: mayor densidad para consulta repetida. Riesgo: requiere cuidar el ancho de las tablas al extenderlo a otros módulos.

## Decisiones comunes

Logo corporativo existente; familia de sistema apropiada para una interfaz operativa; numerales tabulares; contraste legible; controles de al menos 44px; foco visible; navegación accesible por teclado; adaptación móvil con menú desplegable y tablas desplazables. Sin animaciones de entrada ni dependencias de red. Las transiciones se limitan a color y estados y respetan movimiento reducido.

No se escribe DESIGN.md: ninguna alternativa ha sido elegida como sistema visual definitivo. Las guías consultadas son Impeccable (modo Operate y craft floor) y Emil Kowalski (interacciones breves, estados y movimiento reducido). Sus cargadores no se instalaron; la revisión se realiza sobre el código y el navegador local.

Fuentes: https://github.com/pbakaus/impeccable y https://emilkowal.ski/skill.

## Validación

Chromium: navegación, filtros por sede y mes, conservación del estado al cambiar variante, detalle de cobros, búsqueda, recuperación de resultados vacíos, umbral de órdenes críticas, menú móvil y Escape. Sin errores JavaScript ni desbordamiento de página en 1440, 1280 y 390px. Capturas de escritorio y móvil en `previews/`. Revisión visual independiente: cuatro hallazgos corregidos y puntuados como resueltos; disposición ship para propuestas, no para una identidad final. No se ejecutó el detector de Impeccable ni una auditoría exhaustiva de accesibilidad.
