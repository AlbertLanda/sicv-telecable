# Conciliación contable por empresa

Primera entrega de revisión de evidencia importada. Ruta `/contabilidad/` y
menú **Reportes → Conciliación contable**. El rol Contabilidad entra aquí al
iniciar sesión; Administración conserva su panel operativo.

## Alcance disponible

- Importación transaccional de Excel OSIPTEL del sistema anterior: una versión
  por archivo, empresa, periodo y fuente. Conserva nombre, SHA256, fecha y autor.
- Comprobantes identificados por empresa + tipo + serie + número; líneas
  idénticas se conservan y señalan, nunca se eliminan automáticamente.
- Detección de base cero/IGV igual al total, clasificación desconocida,
  pendiente local, estado SUNAT vacío y metadatos distintos dentro del documento.
- Revisión del total del resumen y de totales auxiliares reconocidos en H/I;
  las fórmulas no se ejecutan. Los valores auxiliares requieren caché de Excel.
- Importación directa de ZIP/CSV RVIE nativo de 40 columnas y conservación de
  todos sus campos, referencias, descuentos e importes adicionales. `Est. Comp`
  tiene su propio campo: no se traduce a aceptación ni se compara con el código
  SUNAT del sistema antiguo como si fueran el mismo catálogo.
- Comparación con RVIE nativo o CSV `SICV-RVIE-1`: presencia, fecha, moneda, base, IGV, total
  y códigos SUNAT de origen cuando ambos archivos los incluyen. Código de
  origen no equivale a aceptación certificada. Ausencia en archivo no equivale
  a rechazo SUNAT. Sin la otra fuente, el resultado es «Falta cargar la otra fuente».
- Observaciones y reclasificación por línea con motivo y autor; cada envío
  agrega una revisión. La fuente, importes y estados no se sobrescriben.
- Vínculo consultado por empresa + tipo + serie + número con constancias
  internas del ERP. Muestra código/nombre/documento del abonado, sede de servicio,
  conceptos y estado del cobro. Claves ambiguas o identidades distintas no se
  asignan automáticamente. No se busca un abonado por parecido de nombre o DNI.
- Excel con Control, Conciliación, Detalle SIRE, Detalle OSIPTEL, Resumen OSIPTEL e Historial.
  Fija versiones y corte de revisiones en URL/nombre/control; ignora el filtro
  visual para incluir el periodo completo de las versiones elegidas.
- Ejemplo ficticio accesible sin asignación de empresa y sin crear operaciones.

## Permisos y puesta en marcha

La migración `accounting.0001_initial` solo agrega tablas. No modifica cobros,
abonados, borradores fiscales, talonarios, equipos ni autorizaciones existentes.

Administración entra en **Accesos por empresa**, elige al usuario de
Contabilidad y habilita cada empresa que necesita. El rol de Contabilidad
conserva el reporte de caja y recibe capacidades específicas de conciliación,
sin permisos para cobrar, anular pagos, emitir o administrar personal.
Sin asignación explícita no puede consultar datos, importar ni exportar esa
empresa. Revocar el acceso se aplica en cada petición. Las sedes no sustituyen
el alcance por empresa: un RUC puede operar en varias sedes.

1. Habilitar empresas para el usuario existente.
2. Cargar OSIPTEL de un mes completo, conservando el nombre original
   `OSIPTEL_RUC_AAAAMMDD_AAAAMMDD…xlsx`. El operador confirma soles y alcance.
3. Revisar comprobantes y alertas; abrir un documento para anotar o reclasificar.
4. Seleccionar fuente SIRE y cargar el ZIP original o su CSV nativo. Revisar
   fechas presentes, cantidades, importes y códigos de estado. Un archivo
   parcial no demuestra ausencia en SUNAT de comprobantes de días posteriores.
5. Descargar el Excel con las versiones y revisiones elegidas.

Una carga posterior no borra las anteriores. Una anotación pertenece a la
versión revisada y no se aplica automáticamente a otro archivo. Dos cargas
concurrentes del mismo archivo se serializan por empresa y producen una versión.

## Formatos y límites

- OSIPTEL: `.xlsx`, hoja `Detalle Ventas`, 18 columnas del export conocido
  (serie en D, correlativo en E aunque E no tenga título). Fechas Excel o texto
  DD/MM/AAAA / AAAA-MM-DD. El nombre y las fechas de emisión deben corresponder
  al RUC/mes elegido. No se verifica criptográficamente la identidad del emisor.
- RVIE nativo: `.zip` con un único CSV en la raíz, UTF-8 con BOM opcional y
  esquema reconocido de 40 columnas. Rechaza rangos agrupados, columnas
  desconocidas, archivos adicionales, rutas anidadas, cifrado y enlaces. Los
  signos, descuentos y referencias se conservan; no se recalculan impuestos.
  CSV y ZIP que contengan los mismos bytes se reconocen como la misma evidencia.
- RVIE alternativo: `.csv` UTF-8, delimitador `;` o `,`, encabezado exacto descargable en
  `/contabilidad/plantilla-rvie/`. Es un formato de intercambio SICV, **no una
  estructura oficial para presentar a SUNAT ni un lector nativo certificado**.
  RUC y periodo AAAAMM son obligatorios en cada fila. Se permiten emisiones de
  otro mes porque periodo tributario y fecha de emisión son campos diferentes.
- Límites: 5 MB de subida, 50 MB descomprimidos; XLSX hasta 250 entradas ZIP,
  RVIE exactamente un CSV;
  15.000 líneas/comprobantes. XML con entidades/DOCTYPE, macros, fórmulas en
  campos numéricos, importes no finitos o precisión excesiva se rechazan.
- Si `Notas Credito` contiene datos, se rechaza el archivo hasta validar esa
  estructura. No se afirma que una hoja vacía implique ausencia de notas reales.
- Monedas: OSIPTEL en PEN confirmado por operador; RVIE en PEN o USD. Nunca se
  suman ni comparan importes de distintas monedas como si fueran equivalentes.
- Se mantienen signo e importes recibidos; no se infieren afectación tributaria,
  base/IGV mediante división entre 1.18 ni aceptación a partir de códigos externos.
- No se guarda el archivo original en MEDIA: se guardan valores normalizados,
  filas de origen, resumen y huella en PostgreSQL. Conservar el original en el
  archivo documental del área para contrastar su huella. No subir originales,
  datos personales, claves ni XML reales al repositorio público.

La vista lee la base local, sin llamadas a servicios externos al abrir el panel.
Las importaciones están acotadas y son síncronas en esta entrega. No se anuncia
sincronización automática ni una fecha de actualización SUNAT no recibida.

## Pendientes y siguiente integración

Se necesitan evidencias de recepción (CDR, especialmente tipo 14), confirmar
el facturador actual y habilitar las credenciales de consulta. Después:

1. Contrastar con Contabilidad los resultados del lector y el catálogo de estados.
2. Configurar credenciales fuera del código y un adaptador de consulta SIRE.
3. Ejecutar descarga/tickets en un trabajador con reintentos acotados, exclusión
   de trabajos simultáneos, idempotencia y fecha de última consulta satisfactoria.
4. Mantener separado el envío/aceptación fiscal y la presencia/generación SIRE.

No hay aceptación/reemplazo de propuestas ni generación de registros desde este
módulo. La API fiscal real, XML firmado y CDR no se habilitan con esta entrega.
La consulta integrada genérica documenta varios tipos pero no el tipo 14;
no utilizarla como supuesto adaptador universal de recibos de servicios públicos.

Referencias oficiales revisadas el 09/10/2026:
- https://cpe.sunat.gob.pe/node/158 (acceso API y tickets RVIE/RCE).
- https://cpe.sunat.gob.pe/node/159 (actualización de propuesta RVIE).
- https://cpe.sunat.gob.pe/node/131 (generación final en portal).
- https://cpe.sunat.gob.pe/guias-y-manuales (consulta integrada y recibos públicos).

## Validación

`python manage.py test apps.accounting` cubre permisos/revocación/IDOR/CSRF,
atomicidad, importación repetida y concurrente en PostgreSQL, límites del lector,
fechas e importes inválidos, notas de crédito, identidad tipo/serie/correlativo,
comparación, ausencia de fuente, monedas, historial y exportación sin fórmulas
inyectadas. Las pruebas usan exclusivamente datos ficticios y forman parte de CI
y del job PostgreSQL. El despliegue QA aplica la migración con el arranque
existente, sin cargar archivos reales ni asignar empresas de forma automática.

## Límites del vínculo con abonados

El vínculo usa la configuración actual de la emisora y tipo del talonario. Una
constancia interna no constituye un CPE ni un CDR; el estado fiscal se presenta
como «No acreditado por este cruce». Se contrasta la identidad aportada por SIRE
si está disponible. El acceso contable por empresa permite esta vista resumida,
sin otorgar acceso general a las fichas de abonados. El Excel indica cuándo se
consultó el ERP; estos datos operativos pueden cambiar después de una exportación.
Los datos antiguos aún no migrados aparecen como «Sin vínculo en el ERP».

La migración `payments.0024_seed_econet` agrega ECONET si no existe, sin modificar
su configuración manual ni crear talonarios, correlativos o permisos contables.
