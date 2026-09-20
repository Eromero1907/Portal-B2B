#!/usr/bin/env bash
# _comun.sh — preámbulo compartido por db-reset.sh, cargar.sh e indices.sh (se usa con `source`).
#
# Conexión a PostgreSQL:
#   · Por defecto se usa el contenedor Docker del proyecto (docker-compose.yml, `make db-up`): psql corre
#     DENTRO del contenedor con el repo montado en /workspace. Solo hace falta Docker.
#   · Para usar un PostgreSQL propio: PSQL=/ruta/a/psql PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=...
#   · PGDATABASE (def. portal_b2b) se crea si no existe.

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PGDATABASE="${PGDATABASE:-portal_b2b}"
export PGCLIENTENCODING=UTF8
export PGOPTIONS="-c timezone=UTC -c client_min_messages=warning"

# psql silencioso y que aborta ante el primer error
sql() {
    if [ -n "${PSQL:-}" ]; then
        "$PSQL" -X -q -v ON_ERROR_STOP=1 "$@"
    else
        bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 "$@"
    fi
}

# Reloj de alta resolución (EPOCHREALTIME es de bash >= 5; si no existe, python3)
ahora() {
    if [ -n "${EPOCHREALTIME:-}" ]; then echo "${EPOCHREALTIME/,/.}"
    else python3 -c 'import time; print(time.time())'; fi
}
delta() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.3f", b - a }'; }
tasa()  { awk -v n="$1" -v s="$2" 'BEGIN { if (s > 0) printf "%.0f", n / s; else print "-" }'; }

# Comprueba que hay con qué conectarse (falla pronto y con un mensaje útil)
verificar_conexion() {
    if [ -n "${PSQL:-}" ]; then
        command -v "$PSQL" >/dev/null 2>&1 || [ -x "$PSQL" ] || {
            echo "ERROR: no se encontró PSQL='$PSQL'." >&2; exit 1; }
    else
        command -v docker >/dev/null 2>&1 || {
            echo "ERROR: falta Docker. Instálalo o define PSQL=/ruta/a/psql y las variables PG* de tu servidor." >&2; exit 1; }
        [ "$(docker inspect -f '{{.State.Running}}' "${PG_CONTAINER:-pg-portal-b2b}" 2>/dev/null)" = "true" ] || {
            echo "ERROR: el contenedor '${PG_CONTAINER:-pg-portal-b2b}' no está corriendo. Ejecuta primero: make db-up" >&2; exit 1; }
    fi
}
