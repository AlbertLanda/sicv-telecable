# Piloto SICV en Azure — preparación previa a Blob Storage

Estado: preparado para la fase de infraestructura. **No cargar todavía firmas,
evidencias ni documentos reales** hasta completar Azure Blob Storage.

## Estado del código y comprobación de MEDIA (2026-10-05)

La base QA `14927088f8beee24a4e229cb332e9c1ba23ad90e` ya incluye el backend
Azure y sus dependencias. Eso acredita preparación del código; no confirma
que el App Service lo tenga activado ni que sus permisos estén validados.
El marcador público de versión tampoco informa ese estado.

Variables disponibles en `config/settings.py`:

- `DJANGO_AZURE_MEDIA_ENABLED=True`.
- `DJANGO_AZURE_STORAGE_ACCOUNT`: nombre de cuenta.
- `DJANGO_AZURE_MEDIA_CONTAINER`: contenedor de MEDIA.
- `DJANGO_AZURE_MEDIA_URL_EXPIRATION_SECS`: vigencia de URL, 3600 por defecto.

El backend utiliza `DefaultAzureCredential`. En App Service deben comprobarse
la identidad administrada y sus permisos. No incluir secretos en documentos.

La corrección `fix/azure-media-branding` hace que recibos y contratos busquen
logos y sello de la empresa en el almacenamiento configurado de Django.
Antes se buscaban directamente en `MEDIA_ROOT`, aunque Blob estuviera activo.
Se conservan los nombres `telecable-logo*`, `Logo-telecable-2*` y `firma_<código>*`,
su selección por extensión/nombre y la alternativa empaquetada de muestras QA.
Los archivos deben estar en la raíz de MEDIA, local o del contenedor configurado.
La lectura se realiza en memoria mediante `listdir` y `open`; no requiere rutas
locales ni acceso público a los blobs. No migra archivos existentes al contenedor.

`python manage.py comprobar_logo` comprueba lectura del isotipo con el backend
activo. Informa si falta, y termina con error si falla el acceso o el archivo
no es una imagen legible. No imprime URLs, credenciales ni el listado de MEDIA.
Que el logo funcione no acredita subida, firma del abonado ni respaldo.

Antes de admitir archivos reales, registrar evidencia en QA con archivos
ficticios: escritura/lectura mediante Django, descarga por el flujo autorizado,
ausencia de acceso público anónimo, vencimiento de URLs, conservación tras
reinicio/despliegue y recuperación desde el respaldo elegido. Validar también
logos, firma de empresa, firma del abonado y evidencias por sus respectivos flujos.
La restricción inicial sigue vigente hasta completar estas comprobaciones.

## Arquitectura objetivo del piloto

- Azure App Service (Linux / Python 3.11) para Django.
- Azure Database for PostgreSQL Flexible Server para datos relacionales.
- WhiteNoise + `collectstatic` para archivos static.
- Azure Blob Storage para `MEDIA` en la siguiente etapa.
- Un único cliente real de Huancayo como migración piloto y conciliada.

## Variables mínimas de App Service

```text
DJANGO_DEBUG=False
DJANGO_PRODUCTION=True
DJANGO_SECRET_KEY=<secreto distinto a local/CI>
DJANGO_ALLOWED_HOSTS=<app>.azurewebsites.net
DJANGO_CSRF_TRUSTED_ORIGINS=https://<app>.azurewebsites.net

DJANGO_DB_ENGINE=postgresql
DJANGO_DB_NAME=<base>
DJANGO_DB_USER=<usuario>
DJANGO_DB_PASSWORD=<secreto>
DJANGO_DB_HOST=<servidor>.postgres.database.azure.com
DJANGO_DB_PORT=5432
DJANGO_DB_SSLMODE=require
DJANGO_DB_CONN_MAX_AGE=60
```

Para dominio propio se agregan ambos hosts/orígenes a las listas separadas por
coma.

## Startup Command de App Service

Configurar:

```text
bash startup.sh
```

`startup.sh` ejecuta `collectstatic` y levanta Gunicorn. En el recurso de pruebas
existente `sicv-telecable-qa`, aplica primero las migraciones pendientes y habilita
las simulaciones OSE. La excepción no se aplica a otros recursos, donde las
migraciones se aplican de forma controlada durante el despliegue:

```bash
python manage.py migrate --noinput
```

## Validaciones antes de cargar el primer cliente

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Luego ejecutar la suite de pruebas del commit desplegado.

## Datos del primer cliente

La extracción del sistema legado se hará por respuestas de red observadas en
las herramientas de desarrollador del navegador, siempre usando una sesión
corporativa autorizada. Se guardará una exportación estructurada por cliente y
se transformará mediante un importador del SICV; no se copiarán campos a mano.

La importación deberá conciliar como mínimo:

- identidad y contacto;
- sede, dirección y sector;
- servicios/suscripciones, plan y estado;
- deuda/cargos;
- pagos y comprobantes disponibles;
- contratos/documentos disponibles;
- equipos;
- órdenes históricas y estados disponibles.

La ausencia de un dato en las respuestas del sistema antiguo se registrará como
"no disponible en origen"; no se inventará.

## Pendiente bloqueante

Azure Blob Storage para MEDIA. Hasta terminarlo, App Service no debe recibir
firmas, fotos, PDFs firmados ni evidencias reales, porque el filesystem de la
aplicación no se considera el repositorio definitivo de esos archivos.
