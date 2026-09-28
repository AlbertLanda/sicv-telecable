# Piloto SICV en Azure — preparación previa a Blob Storage

Estado: preparado para la fase de infraestructura. **No cargar todavía firmas,
evidencias ni documentos reales** hasta completar Azure Blob Storage.

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

`startup.sh` ejecuta `collectstatic` y levanta Gunicorn. Las migraciones **no
se ejecutan automáticamente al reiniciar la aplicación**. Se aplican de forma
controlada durante el despliegue:

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
