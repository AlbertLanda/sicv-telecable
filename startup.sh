#!/usr/bin/env bash
set -euo pipefail

echo "[SICV] Recolectando archivos estaticos..."
python manage.py collectstatic --noinput

echo "[SICV] Iniciando Gunicorn..."
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout "${GUNICORN_TIMEOUT:-600}" \
  --workers "${GUNICORN_WORKERS:-3}" \
  --access-logfile - \
  --error-logfile -
