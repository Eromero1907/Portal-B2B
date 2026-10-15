#!/usr/bin/env bash
# correr_carga.sh — carga estable de la ruta de confirmación desde un estado conocido.
#   1. reset-estado (la carga siempre parte de cero: sin órdenes de corridas previas)
#   2. generador dentro de la red de Docker contra nginx (las 3 instancias)
#   3. recursos: muestras de `docker stats` cada 5 s mientras corre la carga (USE básico de la línea base)
# Uso: bash carga/correr_carga.sh [--flujos-por-s 100] [--duracion 300] [--calentamiento 30] [--semilla 42] [--salida DIR]
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

SALIDA=""
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --salida) SALIDA="$2"; shift 2 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
SALIDA="${SALIDA:-resultados/carga/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$SALIDA"

echo "[carga] estado limpio..."
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql > "$SALIDA/reset_estado.txt"

echo "[carga] muestreo de recursos cada 5 s -> $SALIDA/recursos.csv"
echo "ts_utc,contenedor,cpu_pct,mem_uso,mem_pct" > "$SALIDA/recursos.csv"
(
    while true; do
        ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' 2>/dev/null \
            | grep -E '^(pg-portal-b2b|portal-)' | sed "s|^|$ts,|; s|%||g; s| / [^,]*||" >> "$SALIDA/recursos.csv" || true
        sleep 5
    done
) &
MUESTREO=$!
trap 'kill $MUESTREO 2>/dev/null || true' EXIT

docker compose --profile herramientas run --rm -T carga \
    python carga/generador.py --salida "$SALIDA" "${ARGS[@]}"

echo "[carga] listo: $SALIDA (solicitudes.csv, resumen.json, resumen.csv, recursos.csv)"
