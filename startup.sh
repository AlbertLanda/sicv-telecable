#!/usr/bin/env bash
set -euo pipefail

# El App Service de pruebas conserva el perfil de seguridad de producción.
# Esta excepción se limita al recurso QA existente; otros despliegues no migran
# automáticamente ni habilitan las simulaciones.
if [[ "${WEBSITE_SITE_NAME:-}" == "sicv-telecable-qa" ]]; then
  export DJANGO_FISCAL_SIMULATION_ENABLED=True
  export DJANGO_FISCAL_QA_SIMULATION=True
  echo "[SICV QA] Aplicando migraciones pendientes..."
  python manage.py migrate --noinput
fi

echo "[SICV] Recolectando archivos estaticos..."
python manage.py collectstatic --noinput

echo "[SICV] Iniciando Gunicorn..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout "${GUNICORN_TIMEOUT:-600}" \
  --workers "${GUNICORN_WORKERS:-3}" \
  --access-logfile - \
  --error-logfile -
