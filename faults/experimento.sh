#!/usr/bin/env bash
# experimento.sh — UNA corrida de un experimento de la Entrega 3 (falla x configuración x repetición).
# Uso: bash faults/experimento.sh <A1|A2|B1|C1|C2|D1|D2> <sin|con> <repetición>
#   o:  make experimento ID=A1 CFG=sin REP=1
# Hace: kill switch -> recrea apps con la configuración -> carga con la falla activada/desactivada en el
# segundo exacto de faults.yaml (t=0 es el fin del calentamiento) -> deja todo en Entrega 3/evidencia/<ID>/<cfg>_r<n>/
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

ID="${1:?Falta el ID (A1, A2, B1, C1, C2, D1, D2)}"; ID="${ID^^}"
CFG="${2:?Falta la configuración: sin | con}"
REP="${3:?Falta el número de repetición}"
case "$CFG" in sin|con) ;; *) echo "CFG debe ser 'sin' o 'con'"; exit 1 ;; esac
if [ "$ID" = "B2" ]; then echo "B2 (bloqueo de la franja) todavía no está automatizado."; exit 2; fi

PY=.venv/Scripts/python.exe
[ -f "$PY" ] || PY=.venv/bin/python
CTRL="$PY faults/controlador_fallas.py"

read -r INICIO DUR <<< "$($PY -c "import sys,yaml; c=yaml.safe_load(open('faults/faults.yaml',encoding='utf-8')); f=[x for x in c['fallas'] if x['id']==sys.argv[1]][0]; print(f['inicio_s'], f['duracion_s'])" "$ID" | tr -d '\r')"
INICIO="${INICIO_S:-$INICIO}"
DUR="${DURACION_FALLA_S:-$DUR}"
CALENT=30
CARGA_S="${DURACION_CARGA_S:-$((INICIO + DUR + 60))}"

OUT="Entrega 3/evidencia/$ID/${CFG}_r${REP}"
if [ -e "$OUT/resumen.json" ]; then echo "Ya existe $OUT. Usa otra repetición o bórrala a mano."; exit 1; fi
mkdir -p "$OUT"
EV="$OUT/eventos.log"
# Reloj de referencia = el de los contenedores (el mismo que usa el generador de carga y Prometheus).
# El reloj de Windows (Git Bash) se desvía ~4 % respecto al de la VM de Docker/WSL2: por eso NO se usa para programar la falla.
REL=portal-rabbitmq
vm() { docker exec "$REL" date +%s | tr -d '\r'; }
marca() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) host=$(date +%s) vm=$(vm) $*" | tee -a "$EV"; }
esperar() {  # espera hasta el instante $1 (epoch según el reloj de la VM)
    local falta=$(( $1 - $(vm) ))
    if [ "$falta" -gt 0 ]; then docker exec "$REL" sleep "$falta"; fi
}

marca "experimento $ID config=$CFG rep=$REP (falla en t=${INICIO}s durante ${DUR}s; carga ${CARGA_S}s + ${CALENT}s de calentamiento)"
$CTRL kill-switch on > /dev/null

if [ "$CFG" = "con" ]; then FILES="-f docker-compose.yml -f docker-compose.resiliencia.yml"; else FILES="-f docker-compose.yml"; fi
marca "recreando app1 app2 app3 nginx con la configuración '$CFG'"
docker compose $FILES up -d --force-recreate --wait app1 app2 app3 nginx 2> "$OUT/compose.log"

{
  echo "experimento=$ID config=$CFG repeticion=$REP"
  echo "commit=$(git rev-parse HEAD)"
  echo "cambios_sin_commit_en_codigo=$([ -n "$(git status --short -- . ':!Entrega 3/evidencia' ':!resultados' ':!baseline/corridas')" ] && echo true || echo false)"
  echo "falla_inicio_s=$INICIO falla_duracion_s=$DUR carga_s=$CARGA_S calentamiento_s=$CALENT semilla=42 flujos_por_s=100"
  echo "--- entorno de app1 ---"
  docker exec portal-app1 env | tr -d '\r' | grep -E '^(CREDITO_|REINTENTOS_|BREAKER_|BULKHEAD_|DEGRADACION_|DB_LOCK_|BD_POOL_|OTEL_ACTIVO)' | sort
} > "$OUT/manifest.txt"
cp faults/faults.yaml "$OUT/faults.yaml"

bash carga/correr_carga.sh --flujos-por-s 100 --duracion "$CARGA_S" --calentamiento "$CALENT" \
    --semilla 42 --salida "$OUT" > "$OUT/carga.log" 2>&1 &
CARGA_PID=$!
until grep -q "Carga planificada" "$OUT/carga.log" 2>/dev/null; do
    if ! kill -0 "$CARGA_PID" 2>/dev/null; then echo "La carga terminó sin arrancar:"; tail -20 "$OUT/carga.log"; exit 1; fi
    sleep 0.5
done
T0=$(vm)
marca "carga iniciada: t0 aprox. (calentamiento de ${CALENT}s; t=0 de la ficha es el fin del calentamiento)"

esperar $((T0 + CALENT + INICIO))
marca "ACTIVAR $ID (t=${INICIO}s)"
$CTRL activar "$ID" | tee -a "$EV"

esperar $((T0 + CALENT + INICIO + DUR))
marca "DESACTIVAR $ID (t=$((INICIO + DUR))s)"
$CTRL desactivar "$ID" | tee -a "$EV"

wait "$CARGA_PID" || { echo "La carga terminó con error:"; tail -20 "$OUT/carga.log"; }
marca "carga terminada"
$CTRL kill-switch on > /dev/null
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql > /dev/null
echo
echo "== Resultado global ($ID $CFG r$REP) =="
grep -E '^\{"global"' "$OUT/carga.log" || tail -5 "$OUT/carga.log"
echo "Evidencia en: $OUT"
