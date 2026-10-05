# Continuidad SICV y corrección de imágenes de MEDIA — 2026-10-05

## Acceso y base

El conector GitHub se autenticó como `AlbertLanda`. El repositorio
`AlbertLanda/sicv-telecable` informó `push=true` y permiso `admin`.
La creación remota de `fix/azure-media-branding` confirmó acceso de escritura.
No se emplearon contraseñas ni tokens pegados en conversaciones.

La referencia remota `feature/azure-pilot-readiness` y el marcador HTTP
`/static/fiscal/qa-release.json` de Azure QA coincidieron con
`14927088f8beee24a4e229cb332e9c1ba23ad90e`. El marcador acredita la versión
publicada, no los flujos autenticados ni la configuración de infraestructura.
Se creó un worktree aislado desde ese commit. Los documentos sin subir de la
revisión local anterior se conservaron en su rama `fix/qa-continuity-review`.

## Evaluación y prioridades

Se revisaron las guías de producto, diseño corporativo, panel, pagos, preparación
fiscal, OSE, muestras QA y piloto Azure. Las cifras de pruebas de entregas anteriores
siguen siendo evidencia histórica, no resultados de esta continuación.

| Área | Estado acreditado y trabajo siguiente |
|---|---|
| Cobranza y documentos internos | Implementados; esta ejecución comprueba impresión, firmas y muestras QA. No acredita todos los flujos de caja ni la operación real. |
| Panel y ficha | Implementados y con validación anterior documentada. No se modificó interfaz ni se repitió su validación visual. |
| Preparación fiscal | Borradores y configuración versionada implementados. Emisión tributaria real bloqueada. |
| OSE | Transporte simulado; una aceptación sigue dejando un borrador. Pendientes proveedor, decisiones por RUC y adaptación/validación real. |
| MEDIA | Backend Azure configurable; corregida la lectura de imágenes corporativas. Activación, permisos, persistencia y restauración en Azure sin acreditar. Es bloqueante para documentos reales. |
| Caja | Cierre persistido, arqueo y egresos siguen pendientes según la documentación revisada; requieren desarrollo y validación operativa. |
| Migración y operación | Pendientes conciliación de un cliente piloto y lotes, comprobación de permisos por sede/empresa y restauración de respaldos. |

Prioridad técnica inmediata: validar MEDIA con datos ficticios en Azure y registrar
evidencias de los flujos y la recuperación. En paralelo, Contabilidad debe cerrar
las decisiones fiscales y la elección del OSE. Después se podrán completar el
adaptador real y las comprobaciones de conciliación y operación. No se asigna
porcentaje de avance ni se considera listo el reemplazo de producción.

## Cambio concreto

`organization.branding` resuelve imágenes mediante el almacenamiento MEDIA de
Django y las lee en memoria; conserva búsqueda local cuando se proporciona un
directorio explícito. Recibos y contratos dejan de depender del disco del App
Service para los logos y el sello de empresa. Los archivos originales no cambian.

Se conserva la tolerancia a logos ausentes o ilegibles al imprimir. Un error al
leer un sello de empresa encontrado sigue siendo error: no se transforma en una
firma ausente. `comprobar_logo` distingue ausencia de fallo de acceso/imagen y
no expone detalles de excepciones que podrían contener secretos.

No se cambian reglas de dinero, impuestos, modelos, migraciones, permisos, series,
asignación de técnicos ni estados fiscales. No se trasladan archivos reales ni
se activa Blob Storage mediante este cambio.

## Comprobaciones de esta ejecución

- Python 3.12.14 local, dependencias del proyecto y SQLite aislado de pruebas.
  Python 3.11 y PostgreSQL corresponden a los jobs de CI; no se atribuyen a esta ejecución.
- 144 pruebas correctas: las diez nuevas de almacenamiento privado, las de marca
  local y las existentes de comprobantes, documentos/firmas de contrato y muestras QA.
- Las nuevas pruebas reproducían la omisión de logos/sello remotos antes del cambio.
  El backend de prueba rechaza rutas locales y URLs, y comprueba cierre de lecturas,
  conservación de bytes y transparencia del sello, selección de nombres, recorte,
  incrustación en PDF y fallos de acceso o archivo.
- `manage.py check`: sin incidencias. `makemigrations --check --dry-run`: sin cambios.
  `git diff --check`: correcto.
- No se ejecutó la suite completa local, una prueba de Azure Blob real ni una
  revisión visual nueva. No se desplegó ni se alteró el legado o la base de QA.

El cambio se entrega para revisión en su rama aislada, con base de PR en QA.
La validación en nube descrita en `azure_pilot.md` sigue pendiente.
