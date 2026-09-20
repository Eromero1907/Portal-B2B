#!/usr/bin/env bash
# psql.sh — ejecuta psql DENTRO del contenedor de Postgres del proyecto (docker-compose.yml).
# El repo está montado en /workspace, así que los argumentos relativos (-f modelo-fisico.sql,
# \copy ... FROM 'datos/csv/x.csv') funcionan igual que con un psql local.
#
#   bash datos/psql.sh -d portal_b2b -c "SELECT count(*) FROM ordenes.ordenes_compra"
#   bash datos/psql.sh -d portal_b2b -f datos/consultas.sql
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash en Windows: no convertir '/workspace' en una ruta de Windows

CONTENEDOR="${PG_CONTAINER:-pg-portal-b2b}"

exec docker exec -i -w /workspace \
    -e PGUSER="${PGUSER:-postgres}" \
    -e PGDATABASE="${PGDATABASE:-portal_b2b}" \
    -e PGOPTIONS="${PGOPTIONS:--c timezone=UTC}" \
    -e PGCLIENTENCODING="${PGCLIENTENCODING:-UTF8}" \
    "$CONTENEDOR" psql "$@"
