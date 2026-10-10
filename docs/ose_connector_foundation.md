# Estructura de conexión OSE y pruebas recuperables

Entrega del 2026-10-02, rama `feature/ose-connector-foundation`, sobre
`fix/full-monthly-collection` (PR #25). Es una estructura para integrar un
proveedor por contratar. No se ha elegido, dado de alta ni contratado un OSE.

## Qué está implementado

- Configuración por empresa/RUC: modo deshabilitado, simulador local o proveedor
  pendiente de integrar. Permite anotar proveedor y URL HTTPS previstas.
- Referencias a nombres de variables `SICV_OSE_…` para usuario, clave, certificado
  y clave del certificado. Son nombres de variables; no valores secretos. Esta
  entrega no los lee ni consume. Tampoco prueba las URL guardadas.
- Cada cambio de configuración registra una revisión con usuario y fecha.
- Un contrato **interno de SICV** para enviar y consultar: `OseEnvelope`,
  `OseResponse` y `OseTransport` en `ose_transport.py`. No pretende representar
  el contrato HTTP/SOAP de un OSE concreto. Un adaptador futuro deberá traducirlo
  a la documentación del proveedor elegido.
- Un simulador persistente que admite solamente JSON marcado como prueba. Su
  buzón conserva referencia, huella y resultado; no produce un CDR.
- Solicitudes congeladas por prueba, claves de reenvío, intentos consecutivos,
  registro del responsable y recuperación de ejecuciones interrumpidas.
- Pantallas para configurar, preparar, ejecutar y consultar pruebas desde la
  sección Preparación de facturación y el detalle de cada borrador.

Los resultados se guardan en `OseSimulation`; no se agregan estados fiscales
aceptados a `FiscalDocument`. Incluso una aceptación simulada deja el documento
como **borrador**. No modifica deuda, pagos, caja ni talonarios internos. Las
pantallas indican que se trata de pruebas sin validez tributaria.

## Cómo validarlo localmente

Usar una base de prueba. La rama contiene las entregas anteriores; aplicar todas
las migraciones, incluidas las nuevas `fiscal.0003` y `fiscal.0004`.

En el `.env` local del proyecto:

```dotenv
DJANGO_FISCAL_SIMULATION_ENABLED=True
DJANGO_PRODUCTION=False
```

No cambiar el perfil productivo para activar pruebas. El servicio las rechaza
cuando `PRODUCTION=True`, aunque la variable de simulación esté activada, salvo
la excepción explícita del App Service `sicv-telecable-qa` descrita abajo.

### Entorno Azure QA

El despliegue sigue usando la rama `feature/azure-pilot-readiness` y el App
Service existente. En ese recurso, `startup.sh` aplica las migraciones pendientes
antes de iniciar Gunicorn y habilita el simulador OSE. Conserva
`DJANGO_PRODUCTION=True`, HTTPS y cookies seguras. La excepción requiere ambos:
`DJANGO_FISCAL_QA_SIMULATION=True` y `WEBSITE_SITE_NAME=sicv-telecable-qa`.
Otros recursos conservan el bloqueo y el arranque sin migración automática.

Acceso de pruebas:
https://sicv-telecable-qa-f8fnfrhug3cwajc6.centralus-01.azurewebsites.net/

Usar una cuenta con permisos fiscales (el administrador tiene acceso). Para
ejecutar una prueba, configurar primero la empresa en modo **Simulador local**.
Los resultados siguen siendo simulados y sin validez tributaria.

```bash
python manage.py migrate
python manage.py check
python manage.py test apps.fiscal
python manage.py runserver
```

Un superusuario puede revisar el circuito. Para los demás usuarios, asignar
explícitamente los permisos según la responsabilidad:

| Acción | Permisos |
|---|---|
| Consultar borradores y resultados | `fiscal.view_fiscaldocument` |
| Configurar conexión prevista | `fiscal.configure_ose` |
| Preparar/ejecutar/recuperar pruebas | consulta y `fiscal.simulate_ose` |
| Preparar el borrador base | consulta y `fiscal.add_fiscaldocument` |

No se modifican permisos base de ATC, Contabilidad o Administración.

1. Ir a **Comercial → Preparación de facturación** (`/facturacion/`).
2. En **Conexión OSE prevista**, elegir la empresa y guardar **Simulador local
   de pruebas**. Para validar el simulador no hacen falta URL ni referencias de
   credenciales. Dejar los otros campos vacíos es válido.
3. Preparar un borrador con cargos ficticios de un abonado de la sede activa.
4. Abrir su detalle y seleccionar **Preparar prueba simulada**.
5. Elegir un escenario y preparar. Ese paso no ejecuta el envío.
6. Abrir la prueba y utilizar **Ejecutar prueba simulada** o **Consultar o
   recuperar prueba**, según el estado mostrado.
7. Revisar intentos, responsables e historial; comprobar que el borrador y la
   deuda no cambiaron.

## Escenarios y resultados

| Escenario | Primer intento | Continuación |
|---|---|---|
| Aceptación | Aceptación simulada | Repetir devuelve el resultado sin otro intento |
| Observación | Observación simulada | Terminal; consultar el historial |
| Rechazo | Rechazo simulado | Terminal; preparar otra prueba si se desea otro escenario |
| Respuesta pendiente | Ticket de prueba y pendiente de consulta | Primera consulta sigue pendiente; segunda consulta acepta |
| Respuesta perdida | El buzón ficticio recibe, pero la prueba queda con resultado desconocido | Se consulta y recupera la aceptación sin otro envío |
| Falla antes de recepción | El buzón no recibe y permite reintentar | El siguiente envío usa la misma referencia y acepta |

El resultado esperado de cada escenario lo define el simulador. No valida el
contenido tributario, los importes ni la habilitación del RUC. Los borradores
pueden conservar decisiones contables pendientes mientras se prueba el circuito.

## Recuperación y concurrencia

Preparar una misma clave y los mismos datos devuelve una sola prueba. Cambiar
escenario, usuario o borrador con esa clave se rechaza. Una nueva clave permite
una nueva prueba del mismo borrador y queda claramente separada en el historial.

Antes de ejecutar, se bloquea el borrador y la prueba, se reserva un intento y
se guarda un token con vigencia de tres minutos. Una segunda ejecución durante
esa vigencia se rechaza. La llamada al adaptador sucede después de salir de la
transacción de reserva; el resultado se confirma en otra transacción. Un futuro
worker no debe envolver `run_simulation` en una transacción externa.

Si el proceso se interrumpe, la reserva vencida se marca como interrumpida y el
siguiente intento **consulta** antes de reenviar. El reenvío se permite cuando
el simulador confirma que no existe recepción. Una respuesta de un intento
antiguo no puede reemplazar el resultado del intento que lo recuperó.

Una respuesta con referencia o huella ajenas, sin marca de simulación, con
estado desconocido o sin ticket cuando corresponde deja un resultado
**desconocido**, que exige consulta. Una excepción inesperada también sigue
ese camino y no se conserva su texto, porque puede contener credenciales.

Deshabilitar el simulador por empresa detiene nuevos intentos. Descartar el
borrador impide preparar o ejecutar nuevas pruebas. El historial sigue siendo
consultable. Configuración, revisiones, pruebas, intentos, eventos y buzón
ficticio tienen administrador de solo lectura; la configuración se modifica
por su pantalla para registrar revisiones.

Los controles de modelo y servicios no autorizan manipular evidencia mediante
SQL o `QuerySet.update`. Las URL y nombres de variables previstos nunca habilitan
un transporte real por sí mismos. `submit_document` conserva su bloqueo.

## Lo pendiente para el OSE contratado

1. Cotizar validación OSE para los volúmenes y empresas reales; confirmar soporte
   del tipo de comprobante, en especial recibos de servicios públicos si aplica.
2. Confirmar con Contabilidad modalidad por RUC, receptor fiscal, impuestos,
   descuentos, anticipos, emisión a crédito y momento de emisión.
3. Implementar y verificar XML/UBL y firma, artefactos persistidos, numeración
   fiscal única, notas, bajas y resúmenes que correspondan.
4. Implementar el adaptador del proveedor elegido, su autenticación, timeouts,
   consulta de tickets/documentos, clasificación de errores y lectura de CDR.
   Una falta de respuesta nunca debe producir automáticamente otro comprobante.
5. Incorporar los secretos y certificados mediante la configuración segura del
   servidor; configurar las referencias no sustituye el acceso al secreto.
6. Probar en el entorno del proveedor y validar CDR/documentos, conciliación,
   conservación y entrega al cliente antes de habilitar producción.

No hay emisión real, XML firmado, series oficiales, PDF/QR fiscal, CDR real,
conexión de red, worker de producción ni habilitación tributaria en esta entrega.
No se afirma que colocar credenciales sea suficiente para completar esos pasos.

La estructura sigue el circuito de envío y constancia de recepción descrito
por [SUNAT para SEE-OSE](https://cpe.sunat.gob.pe/informacion_general/operador_servicios_electronicos).
La separación de transacciones sigue la [documentación de Django](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).

## Verificación

La suite fiscal comprueba permisos, sedes, aislamiento de caja, estados,
idempotencia, errores, correlación y recuperación. El job **Cobranza y pruebas
OSE (PostgreSQL)** ejecuta la suite fiscal y las pruebas de cobranza con
PostgreSQL 16. Incluye tres carreras OSE mediante conexiones independientes:
preparación repetida, doble reserva y doble recuperación de una reserva vencida.
SQLite omite esas carreras; su suite no acredita bloqueo concurrente de filas.
