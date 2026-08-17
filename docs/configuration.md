# Configuracion del proyecto SICV

Documento tecnico de la Fase 5: configuracion segura por variables de entorno y
pipeline de integracion continua en GitHub Actions.

Archivos involucrados: `config/settings.py`, `.env.example`, `.gitignore`,
`.github/workflows/ci.yml`, `requirements.txt`.

---

## 1. Variables de entorno disponibles

Toda la configuracion sensible o dependiente del entorno se lee desde variables
de entorno. No se agregaron dependencias: se usa `os.environ` de la libreria
estandar mas dos helpers en `config/settings.py` (`env_bool` y `env_list`).

| Variable | Obligatoria | Valor por defecto | Descripcion |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | Si (cuando `DJANGO_DEBUG=False`) | clave insegura solo si `DEBUG=True` | Clave de firma de Django. Distinta en cada entorno. |
| `DJANGO_DEBUG` | No | `False` | Modo debug. Solo `True` en desarrollo local. |
| `DJANGO_ALLOWED_HOSTS` | No | `localhost,127.0.0.1` si `DEBUG=True`; vacio si no | Hosts permitidos, separados por comas. |

Valores aceptados como verdadero en `DJANGO_DEBUG`: `1`, `true`, `yes`, `on`,
`si` (sin distinguir mayusculas). Cualquier otro valor, o la ausencia de la
variable, se interpreta como `False`.

### Carga de `.env`

Si existe un archivo `.env` en la raiz del proyecto, `settings.py` lo carga con
la funcion `load_dotenv` (implementacion propia, ~10 lineas, sin dependencias).
Las variables ya definidas en el entorno del sistema tienen prioridad sobre el
archivo, por lo que CI y produccion no se ven afectados por su ausencia.

## 2. `.env` y `.env.example`

- **`.env.example`** esta versionado. Es la plantilla: contiene solo nombres de
  variables y valores de ejemplo seguros. **Nunca** debe contener secretos
  reales.
- **`.env`** es el archivo local de cada desarrollador. Esta ignorado por Git
  (`.gitignore` incluye `.env` y `.env.*`, con la excepcion `!.env.example`) y
  no debe subirse nunca al repositorio.

Verificacion rapida de que Git lo ignora:

```bash
git check-ignore -v .env
```

## 3. Regla de manejo de SECRET_KEY

La clave que estaba escrita directamente en `settings.py` (prefijo
`django-insecure-`) **se considera expuesta** por haber sido versionada. Fue
retirada del codigo y **no debe reutilizarse en ningun entorno real**.

Reglas vigentes:

1. `SECRET_KEY` se lee exclusivamente de `DJANGO_SECRET_KEY`.
2. Cada entorno (local, pruebas, CI, QA, produccion) usa una clave **distinta e
   independiente**.
3. `.env.example` no contiene ninguna clave real, solo el marcador
   `change-me-in-local-env`.
4. Si la variable falta y `DEBUG=False`, el proyecto **falla al arrancar** con un
   `ImproperlyConfigured` explicito en lugar de continuar de forma insegura.
5. Solo con `DEBUG=True` se usa una clave de desarrollo interna
   (`dev-only-insecure-key-not-for-production`), marcada como no apta para
   produccion.

Generar una clave local:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

y pegar el resultado en `DJANGO_SECRET_KEY` dentro de `.env`.

La clave de produccion sera generada y almacenada aparte por el Area de TI (no
en el repositorio) cuando se configure el entorno productivo.

## 4. DEBUG y ALLOWED_HOSTS

```python
DEBUG = env_bool('DJANGO_DEBUG', default=False)

ALLOWED_HOSTS = env_list(
    'DJANGO_ALLOWED_HOSTS',
    default=('localhost', '127.0.0.1') if DEBUG else (),
)
```

- El valor por defecto de `DEBUG` es `False`: si la variable no se define, el
  proyecto queda en el modo mas seguro.
- `ALLOWED_HOSTS` acepta una lista separada por comas y limpia los espacios:
  `localhost, sicv.ejemplo.pe ,127.0.0.1` produce
  `['localhost', 'sicv.ejemplo.pe', '127.0.0.1']`.
- **No se usa `['*']` como valor predeterminado** en ningun caso.

Ejemplos:

```bash
# Desarrollo local
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Futuro entorno productivo (dominio aun no definido)
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=sicv.example.com,www.sicv.example.com
```

## 5. Configuracion regional (Peru)

```python
LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Lima'
USE_I18N = True
USE_TZ = True
```

Con `USE_TZ = True` los timestamps se siguen almacenando en UTC y se convierten
a `America/Lima` solo en la presentacion, por lo que la logica de ordenes
(atencion, reprogramacion, resultados) no cambia de comportamiento. La suite
completa se ejecuto despues del cambio: **49 pruebas, todas en verde**.

## 6. Static y media

```python
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
```

- `STATIC_ROOT` queda definido para una futura ejecucion de `collectstatic`; no
  se usa en desarrollo.
- `MEDIA_ROOT` apunta a la carpeta local `media/`, destino de las evidencias de
  ordenes de trabajo. Ambas carpetas (`media/`, `staticfiles/`) estan ignoradas
  por Git.
- En esta actividad **no** se integro Azure Blob Storage.

## 7. Ejecutar el proyecto localmente

```bash
git clone <repo>
cd sicv-telecable

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

pip install -r requirements.txt

copy .env.example .env         # Windows
# cp .env.example .env         # Linux / macOS
# editar .env y colocar una DJANGO_SECRET_KEY generada localmente

python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver
```

Base de datos de desarrollo: SQLite (`db.sqlite3`), sin configuracion adicional.

## 8. Workflow de GitHub Actions

Archivo: `.github/workflows/ci.yml`. Job unico: `validaciones`.

**Se ejecuta en:**

- `push` hacia `develop`.
- `pull_request` cuyo destino sea `develop`.

**Que hace:**

1. Descarga el repositorio (`actions/checkout@v4`).
2. Prepara Python 3.11 con cache de pip (`actions/setup-python@v5`).
3. Instala dependencias desde `requirements.txt`.
4. Define variables de entorno de prueba seguras a nivel de job.
5. Ejecuta las validaciones de Django.

Tiene `timeout-minutes: 15` para evitar jobs colgados.

### Comandos ejecutados en CI

| Paso | Comando | Bloquea el pipeline |
|---|---|---|
| Validar configuracion | `python manage.py check` | Si |
| Verificar migraciones | `python manage.py makemigrations --check --dry-run` | Si |
| Suite de pruebas | `python manage.py test --verbosity 2` | Si |
| Reporte de hardening | `python manage.py check --deploy` | No (`continue-on-error`) |

Cualquier fallo en los tres primeros pasos deja el workflow en rojo. El paso
`check --deploy` es **solo informativo**: reporta advertencias de HTTPS/cookies
que corresponden a una actividad posterior de despliegue y todavia no deben
bloquear la integracion.

### Variables de entorno del CI

```yaml
DJANGO_SECRET_KEY: ci-only-insecure-key-for-automated-tests
DJANGO_DEBUG: "False"
DJANGO_ALLOWED_HOSTS: localhost,127.0.0.1
```

- No es la clave expuesta del antiguo `settings.py` ni una clave real de ningun
  entorno; sirve unicamente para que Django arranque durante las pruebas.
- No se usan credenciales de Azure, contraseñas productivas ni bases de datos
  corporativas.
- Las pruebas corren contra la base de datos de test aislada que Django crea y
  destruye en cada ejecucion.

Al no ser un secreto, se define en claro dentro del workflow; no se requieren
GitHub Secrets en esta fase.

## 9. Validaciones ejecutadas localmente

```
python manage.py check                              -> sin problemas
python manage.py makemigrations --check --dry-run   -> No changes detected
python manage.py test                               -> Ran 49 tests ... OK
git diff --check                                    -> sin errores
```

Escenarios de configuracion verificados manualmente:

| Escenario | Resultado |
|---|---|
| `.env` valido presente | Arranca; `DEBUG=True`, hosts `['localhost', '127.0.0.1']` |
| `DJANGO_DEBUG=True` | Interpretado como `True` |
| `DJANGO_DEBUG=False` / `0` | Interpretado como `False` |
| `DJANGO_ALLOWED_HOSTS` con varios valores y espacios | Convertido a lista limpia |
| `DJANGO_SECRET_KEY` ausente con `DEBUG=False` | `ImproperlyConfigured` con mensaje explicito |

## 10. Pendiente para produccion / Azure

Nada de lo siguiente forma parte de esta actividad; queda documentado como
trabajo futuro:

- **PostgreSQL**: reemplazar SQLite mediante variables de entorno. Nombres
  previstos (comentados en `.env.example`, sin valores reales):
  `DJANGO_DB_ENGINE`, `DJANGO_DB_NAME`, `DJANGO_DB_USER`,
  `DJANGO_DB_PASSWORD`, `DJANGO_DB_HOST`, `DJANGO_DB_PORT`.
- **Azure App Service**: variables de entorno cargadas desde la configuracion
  de la App Service, no desde `.env`.
- **Azure Blob Storage**: mover `MEDIA_ROOT` a almacenamiento externo para las
  evidencias.
- **Hardening HTTPS**: `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` (las advertencias que hoy
  reporta `check --deploy`).
- **Despliegue automatico**: este workflow solo valida; no despliega.
- **Separacion de `settings.py`** en modulos por entorno, si la complejidad lo
  justifica. Hoy la distincion se hace por variables de entorno.

## 11. Troubleshooting

**`ImproperlyConfigured: Falta la variable de entorno DJANGO_SECRET_KEY`**
No hay `.env` o no define la variable, y `DJANGO_DEBUG` no es `True`. Copiar
`.env.example` a `.env` y generar una clave local (seccion 3).

**`DisallowedHost: Invalid HTTP_HOST header`**
El host usado no esta en `DJANGO_ALLOWED_HOSTS`. Agregarlo a la lista separada
por comas. No usar `*`.

**Los cambios en `.env` no tienen efecto**
Una variable ya exportada en el entorno del sistema tiene prioridad sobre el
archivo (`os.environ.setdefault`). Revisar el entorno de la terminal, o
reiniciar `runserver`, que no recarga `.env` en caliente.

**`makemigrations --check` falla en CI**
Alguien modifico modelos sin generar la migracion. Ejecutar
`python manage.py makemigrations`, revisar el archivo generado y subirlo.

**Horas mostradas con 5 horas de diferencia**
Comportamiento esperado de `USE_TZ = True`: se guarda en UTC y se muestra en
`America/Lima` (UTC-5). Usar `django.utils.timezone.localtime` al formatear.

## 12. Limitaciones detectadas

- `check --deploy` reporta 5 advertencias de seguridad (HSTS, redireccion SSL,
  cookies seguras, `DEBUG`). Es esperado: corresponden a la configuracion
  productiva, aun no abordada. Por eso el paso no bloquea el CI.
- El cargador de `.env` es minimo: soporta `CLAVE=VALOR`, comentarios y lineas
  vacias, pero no valores multilinea ni interpolacion de variables. Suficiente
  para el uso actual; si se necesita mas, evaluar `django-environ` y
  documentarlo.
- CI usa SQLite, igual que desarrollo. Diferencias de comportamiento propias de
  PostgreSQL no quedan cubiertas hasta que se configure esa base.
