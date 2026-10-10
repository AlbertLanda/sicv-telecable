# Revisión contable guiada en Azure QA

Entrada: **Reportes > Revisión contable · QA**, `/reportes/revision-contable/`.

La guía presenta 16 casos sintéticos con datos, resultado esperado, preguntas y
estado de cobertura. Complementa las ocho muestras de facturación y la muestra
de anulación existentes; no crea abonados, cargos, pagos ni documentos fiscales.
Los importes ilustrativos no definen nuevas tarifas ni reglas tributarias.

## Uso para Contabilidad

1. Entrar con un usuario propio con rol Contabilidad, Administración o permiso
   `payments.view_cash_closing`. No es necesario compartir el superusuario.
2. Recorrer los casos y guardar **Pendiente de revisar**, **Revisado sin
   observaciones**, **Falta dato o ajuste** o **No aplica**. Los dos últimos
   requieren una explicación. Se puede continuar otro día.
3. Descargar la revisión completa en CSV (UTF-8 con BOM, separador `;`, compatible
   con Excel). Incluye los 16 casos, datos, preguntas, pendientes y comentarios.
4. Administración puede seleccionar un revisor para consultar y exportar sus
   observaciones. No puede enviar revisiones en nombre de esa persona.

El rol Contabilidad mantiene sus permisos operativos actuales: esta pantalla no
concede acceso a registros de abonados, cobros, anulaciones o emisión fiscal.
El catálogo completo está disponible con su rol. Los enlaces opcionales a las
muestras operativas exigen permisos de ficha y comprobantes, y se resuelven solo
desde la sede activa y un manifiesto QA existente.

## Cobertura y límites

Casos: abonado; receptor/emisor; pronto pago 2026; precio normal; política 2025;
primer mes; reconexión; pago pendiente; anulación; agrupación; parciales/adelantos;
caja; migración; emisión/conexión fiscal; correcciones/reportes; otros faltantes.

Los ejemplos de la guía son referencias fijas, no una lectura de saldos vigentes.
La pantalla distingue muestras operativas, preguntas de negocio y funciones
pendientes. El consolidado de caja sigue siendo parcial; la emisión real, las
reglas tributarias y la migración conciliada siguen pendientes. No se cargan
firmas, evidencias ni documentos reales mientras MEDIA no esté habilitado.

## Acceso y persistencia

`ACCOUNTING_REVIEW_ENABLED` se activa exclusivamente cuando `WEBSITE_SITE_NAME`
es `sicv-telecable-qa`. Fuera de ese recurso, GET/POST/export devuelven 404 y el
menú se oculta. Las pruebas usan `override_settings`; no hay activación global
por DEBUG ni por el rol del usuario.

Cada guardado agrega una fila de `AccountingReviewNote`, con autor, versión del
catálogo, caso y fecha. La pantalla y el CSV muestran el último envío por caso;
se conservan revisiones anteriores y se muestran las cinco últimas del caso.
La migración inicial de Reportes solo crea esta tabla: no altera datos contables.
Cambiar sustancialmente los casos requiere una nueva versión del catálogo para
no arrastrar revisiones a escenarios diferentes.

El autor solo ve su revisión. La supervisión exige superusuario o los permisos
conjuntos `accounts.view_user` y `audit.view_auditevent`, además del acceso a la
guía. Se mantiene CSRF, escape HTML y `private, no-store`; el CSV neutraliza
fórmulas aportadas en comentarios. No se registran cuerpos POST en auditoría.

Verificación: `python manage.py test apps.reports.tests.test_accounting_review`
(también incluida en el job PostgreSQL de CI).
