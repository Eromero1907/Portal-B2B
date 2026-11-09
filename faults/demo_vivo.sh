#!/usr/bin/env bash
# =====================================================================
# demo_vivo.sh — Reproducción en vivo para la presentación final (rúbrica: criterios 2 y 4)
#
# Misma carga (100 flujos/s = 200 req/s, semilla 42) y MISMA combinación en caliente en los dos estados:
#   A1 (30 % de llamadas al crédito con +800 ± 300 ms) + D2 (503 del crédito con probabilidad 50 %) + B2 (lock de la franja 91150)
#   t≈25 s inyección · t≈60 s kill switch global (reversión < 2 s)
#
#   1. Estado inicial: plataforma del E2 sin mecanismos (timeout de crédito 5 s, sin reintentos, sin breaker, sin lock_timeout)
#   2. Estado final:   perfil M (timeout por intento 200 ms + 3 reintentos con backoff, breaker 70 %, bulkhead 20,
#                      lock_timeout 2 s -> 503 franja_bloqueada, pool timeout 2 s, degradación 503 + Retry-After)
#
# Grafana: http://localhost:3000 (refresco 5 s). Las marcas de inyección y kill switch se guardan en marcas.json (epoch) y
# faults/resumen_demo.py imprime al final la tabla ANTES / DURANTE / DESPUÉS y la comparación inicial vs final
# (resultados/demo_comparacion.md). La comparación válida es la ventana DURANTE: volver a la línea base tras el kill
# switch es recuperación, no corrección.
#
# Uso:
#   make demo-vivo                   # ciclo completo (estado inicial -> estado final), ~4 min
#   bash faults/demo_vivo.sh sin     # solo el estado inicial (~2 min)
#   bash faults/demo_vivo.sh con     # solo el estado final (~2 min)
#   python faults/resumen_demo.py    # vuelve a imprimir las tablas de la última corrida
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

    sleep 25   # ~10 s de calentamiento + ~10 s de línea base visible en Grafana antes de inyectar
    echo "-> [t=25s] Inyectando COMBINACIÓN DE FALLAS EN CALIENTE: A1 (latencia) + D2 (50% HTTP 503) + B2 (lock franja 91150)..."
    T_INY=$(date +%s.%N)
    FALLA_DURACION_S=35 $CTRL activar B2
    $CTRL activar A1
    $CTRL activar D2
    $CTRL estado

    sleep 35
    echo "-> [t=60s] Ejecutando KILL SWITCH GLOBAL (reversión en <= 2 s)..."
    T_KS=$(date +%s.%N)
    $CTRL kill-switch on
    $CTRL estado

    wait "$PID_CARGA" || true
    echo "{\"inyeccion_epoch\": ${T_INY}, \"kill_switch_epoch\": ${T_KS}, \"combinacion\": \"A1+D2+B2\"}" > "$salida/marcas.json"
    echo "-> Resumen medido en '${etiqueta}':"
    cat "$salida/resumen.csv"
    echo
    "$PY" faults/resumen_demo.py "$etiqueta" || true
}

if [ "$MODO" = "sin" ] || [ "$MODO" = "completo" ]; then
    correr_bloque "estado_inicial_sin_resiliencia" "-f docker-compose.yml"
fi

if [ "$MODO" = "con" ] || [ "$MODO" = "completo" ]; then
    correr_bloque "estado_final_con_resiliencia" "-f docker-compose.yml -f docker-compose.resiliencia.yml -f docker-compose.var-umbral70.yml"
fi
