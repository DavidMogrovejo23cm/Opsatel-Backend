#!/bin/sh
set -e

DB_HOST=${DB_HOST:-db}
DB_PORT=${DB_PORT:-3306}
USER=${MYSQL_USER:-root}
PASSWORD=${MYSQL_ROOT_PASSWORD:-}
DATABASE=${MYSQL_DATABASE:-opsatel}

printf 'Esperando a MySQL en %s:%s...\n' "$DB_HOST" "$DB_PORT"

until mysqladmin ping -h "$DB_HOST" --silent; do
  printf 'MySQL no está listo, reintentando en 2 segundos...\n'
  sleep 2
done

printf 'MySQL listo. Iniciando backend...\n'
exec uvicorn main:app --host 0.0.0.0 --port 8000
