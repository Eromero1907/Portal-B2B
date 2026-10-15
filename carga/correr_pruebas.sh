#!/usr/bin/env bash
# correr_pruebas.sh — pruebas de aceptación de la plataforma, desde y hacia un estado limpio.
# Deja el reporte en resultados/pruebas/aceptacion.json
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
mkdir -p resultados/pruebas
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql > /dev/null
estado=0
docker compose --profile herramientas run --rm -T -e SALIDA_PRUEBAS=resultados/pruebas/aceptacion.json carga \
    python carga/pruebas_aceptacion.py || estado=$?
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql > /dev/null
exit $estado
