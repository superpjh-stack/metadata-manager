#!/bin/sh
set -eu
mkdir -p /data/media
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 90 --access-logfile - --error-logfile - --forwarded-allow-ips=''
