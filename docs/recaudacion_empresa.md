# Recaudación por empresa/RUC

Entrada: **Reportes → Recaudación por empresa**, `/contabilidad/recaudacion/`.
Tablero local de cobros confirmados en PEN, independiente de la emisión fiscal,
los archivos importados del legado/SIRE y la caja física. No realiza llamadas
a SUNAT, bancos ni otros servicios al consultar.

## Recorrido de uso

1. Seleccionar una empresa o todas las empresas autorizadas, periodo y una
   fecha dentro del periodo. Diario = un día; quincenal = 1–15 o 16–fin de mes;
   mensual/anual = mes/año calendario. Se usa America/Lima.
2. Consultar recaudación y cantidad de cobros; opcionalmente filtrar por sede y
   oficina receptoras. El alcance pertenece a la empresa y no a la sede activa
   de la barra superior. Se conservan sedes/oficinas históricas inactivas que
   tienen cobros, así como registros sin oficina.
3. Revisar cada empresa, el desglose por sede/oficina/medio, los importes diarios
   y el detalle paginado. Los indicadores incluyen todas las páginas.
4. Descargar Excel: Control, Cobros, Por empresa, Por oficina y medio y Por día.
   Se exporta todo el filtro (hasta 50000 cobros), no solo la página visible.
   Para volúmenes superiores se debe reducir periodo, empresa o sede.
5. Administración abre **Ver umbral e historial**, selecciona periodo, importe
   y porcentaje de aviso y guarda con motivo. No se siembran importes reales
   ni se deducen umbrales tributarios. Una alerta no cambia el RUC/talonario ni
   bloquea cobros, genera asientos o envía mensajes.

## Qué se suma

- Un `Payment` registrado se suma exactamente una vez por su importe recibido,
  aunque cubra varios cargos o tenga conciliación bancaria.
- Fecha real `paid_at`, desde medianoche del inicio hasta antes de medianoche
  del día posterior al final del periodo. Fechas posteriores al momento de la
  consulta se excluyen. No se usa fecha de emisión ni de creación como sustituto.
- Se incluyen todos los medios de pago vigentes y el dinero no aplicado que
  forme parte de un cobro registrado. Los descuentos no son dinero recibido.
- Pendientes/anulados, depósitos de caja al banco, garantías, otros ingresos,
  gastos y ajustes de deuda no incrementan la recaudación de abonados.
- Una anulación posterior retira el cobro del periodo original al volver a
  consultar. No es un libro inmutable, un reporte de devoluciones ni cierre de
  caja. Las pantallas pueden cambiar si hay operaciones entre consultas.

## Atribución y calidad de datos

La empresa se toma del movimiento original `CashEntry.PAYMENT`, cuando existe.
Un cambio posterior de emisor del talonario no mueve esos cobros a otra empresa.
Si ese movimiento carece de empresa no se rellena por inferencia. Si su RUC
conservado difiere del configurado para la empresa, el cobro se excluye y se
cuenta como incidencia dentro del periodo.

Sin movimiento original de caja, se usa la empresa actual del talonario. Estos
cobros se identifican como **Talonario actual**: su atribución histórica puede
cambiar si cambia la configuración. No se escribe un historial ficticio ni se
presenta el informe como histórico definitivo. La referencia original de caja
se conserva junto al número actual del comprobante en el detalle/Excel.

Sin empresa atribuible no hay inclusión ni asignación automática. Empresas
inactivas no se ofrecen, conforme al acceso contable existente. La consulta
por empresas autorizadas no acredita la totalidad de todos los cobros del ERP.
Un RUC incompleto o repetido entre empresas activas se señala y bloquea la
configuración/evaluación normal de la alerta hasta revisar el catálogo. No se
fusionan empresas ni se amplían accesos por coincidir el RUC. Los desgloses
conservan la identidad de sedes y oficinas aunque compartan el mismo nombre.

Las incidencias se consultan para todas las sedes de las empresas seleccionadas:
sin fecha real (sin poder asignar periodo), fechas futuras del periodo y RUC
inconsistente del periodo. No exponen registros de otras empresas.

## Alertas e historial

Un umbral por empresa y tipo de periodo, sin alertas activas por defecto.
Menor al porcentaje: «Por debajo del aviso»; desde el porcentaje y antes del
importe: «Cerca del umbral»; igual o superior al importe: «Umbral alcanzado».

Se evalúa el **total de toda la empresa**, incluso cuando la tabla está filtrada
por oficina. Ambos importes se muestran por separado. Los resultados dependen
de los cobros atribuibles y registrados, no del universo del sistema antiguo.
La configuración vigente se utiliza también al consultar periodos pasados; no
se simula cuál fue la alerta histórica ni se registran notificaciones automáticas.

Cada cambio/desactivación crea una revisión con RUC, importe, porcentaje, autor,
fecha y motivo. Cambiar el RUC invalida la interpretación de la regla anterior;
se muestra «Reconfigurar». Dos editores no pueden sobrescribir una revisión no
vista. Reenviar el mismo formulario devuelve la misma revisión. El historial
solo se consulta desde la interfaz administrativa.

## Accesos y validación

Administración y Contabilidad reciben `accounting.view_revenue`. Contabilidad
necesita además `CompanyAccess` activo por empresa. Configurar exige
`accounting.manage_revenue_rules`, concedido por defecto solo a Administración;
una concesión explícita también respeta el acceso por empresa. La revocación
se comprueba en pantalla, configuración y descarga. ATC no recibe el tablero.

El Excel trata texto como texto literal y calcula todos sus subtotales a partir
del mismo conjunto de filas que exporta. No incorpora información de otros RUC
ni depende de los filtros de página. Los resultados HTTP no se almacenan en caché.
Las agregaciones usan SQL y no consultan aplicaciones/cargos por cada cobro. Un
índice de estado/fecha de pago apoya los filtros del reporte.

`apps.accounting.test_revenue` verifica periodos, medianoche en Lima, atribución,
duplicaciones, exclusiones, permisos, filtros, totales, exportación, cambios de
RUC, versiones y dos carreras PostgreSQL. Se incluye automáticamente en el job
PostgreSQL de CI que ejecuta `apps.accounting`. Solo usa datos sintéticos.

Ejemplo: dos oficinas cobran 70 y 30; umbral mensual 100, aviso 80 %. Filtrar
la primera muestra 70 en el filtro, 100 en toda la empresa y «Umbral alcanzado».
Un depósito posterior al banco de 50 no aumenta ninguno de esos totales.

Migraciones aditivas: tabla de versiones e índice para pagos. No crean alertas,
empresas, cobros, accesos por RUC ni importaciones reales.
