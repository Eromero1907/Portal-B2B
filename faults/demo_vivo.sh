#!/usr/bin/env bash
# =====================================================================
# demo_vivo.sh — Reproducción en vivo para la presentación de 15 minutos
#
# Demuestra en < 3 minutos con Grafana en http://localhost:3000 (refresco 5s):
#   1. Estado Inicial (sin mecanismos de resiliencia):
#      - Carga estable en segundo plano (100 flujos/s = 200 req/s)
#      - Activación combinada en caliente de A1 (latencia) + D2 (errores 503) + B2 (lock franja 91150)
#      - Observación en vivo en Grafana del salto en p99 (> 1000 ms) y tasa de errores (~13.4 %)
#      - Reversión instantánea (< 2 s) con Kill Switch Global
#   2. Estado Final Corregido (con Perfil M + umbral breaker 70 % + fix LockNotAvailable -> 503):
#      - Recreación en caliente de app1..3 con docker-compose.resiliencia.yml y docker-compose.var-umbral70.yml
#      - Re-inyección de la misma combinación y verificación del cumplimiento de SLO y degradación controlada
#
# Uso:
#   make demo-vivo                   # corre el ciclo completo (Estado Inicial -> Estado Final)
#   bash faults/demo_vivo.sh sin     # corre solo la demostración del Estado Inicial (90 s)
#   bash faults/demo_vivo.sh con     # corre solo la demostración del Estado Final (90 s)
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8

MODO="${1:-completo}"
FLUJOS="${FLUJOS:-100}"
DURACION="${DURACION:-75}"
CALENTAMIENTO="${CALENTAMIENTO:-10}"

if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else PY=python3; fi

CTRL="$PY faults/controlador_fallas.py"
trap '$CTRL kill-switch on >/dev/null 2>&1 || true' EXIT INT TERM

correr_bloque() {
    local etiqueta="$1"
    local compose_args="$2"
    local salida="resultados/demo_${etiqueta}"

    echo "====================================================================="
    echo " [DEMO EN VIVO] Configuración: ${etiqueta^^}"
    echo " Tablero Grafana en vivo: http://localhost:3000/d/portal-b2b/portal-b2b-c2b7-resiliencia-e3?orgId=1&refresh=5s"
    echo "====================================================================="

    $CTRL kill-switch on >/dev/null
    bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql >/dev/null
    # Asegurar que la franja 91150 tenga cupo libre para observar el bloqueo B2 desde el inicio
    bash datos/psql.sh -X -q -d portal_b2b -c "UPDATE logistica.franjas_cedi SET capacidad_reservada = 0 WHERE id = 91150;" >/dev/null

    echo "-> Aplicando configuración de contenedores (${etiqueta})..."
    docker compose $compose_args up -d --wait db rabbitmq stub-credito app1 app2 app3 publicador-outbox consumidor-eventos nginx
    docker compose -f docker-compose.yml -f docker-compose.observabilidad.yml up -d prometheus grafana cadvisor postgres-exporter nginx-exporter jaeger >/dev/null 2>&1 || true

    echo "-> [t=0s] Iniciando carga en vivo (${FLUJOS} flujos/s = $((FLUJOS * 2)) req/s durante ${DURACION}s)..."
    bash carga/correr_carga.sh --salida "$salida" --flujos-por-s "$FLUJOS" \
        --duracion "$DURACION" --calentamiento "$CALENTAMIENTO" --semilla 42 &
    PID_CARGA=$!

    sleep 18
    echo "-> [t=18s] Inyectando COMBINACIÓN DE FALLAS EN CALIENTE: A1 (latencia) + D2 (50% HTTP 503) + B2 (lock franja 91150)..."
    FALLA_DURACION_S=35 $CTRL activar B2
    $CTRL activar A1
    $CTRL activar D2
    $CTRL estado

    sleep 35
    echo "-> [t=53s] Ejecutando KILL SWITCH GLOBAL (reversión en <= 2 s)..."
    $CTRL kill-switch on
    $CTRL estado

    wait "$PID_CARGA" || true
    echo "-> Resumen medido en '${etiqueta}':"
    cat "$salida/resumen.csv"
    echo
}

if [ "$MODO" = "sin" ] || [ "$MODO" = "completo" ]; then
    correr_bloque "estado_inicial_sin_resiliencia" "-f docker-compose.yml"
fi

if [ "$MODO" = "con" ] || [ "$MODO" = "completo" ]; then
    correr_bloque "estado_final_con_resiliencia" "-f docker-compose.yml -f docker-compose.resiliencia.yml -f docker-compose.var-umbral70.yml"
fi
