#!/usr/bin/env bash
# experimento.sh — UNA corrida de un experimento de la Entrega 3 (falla x configuración x repetición).
# Uso: bash faults/experimento.sh <A1|A2|B1|B2|C1|C2|D1|D2> <sin|con|con-VARIANTE> <repetición>
#   o:  make experimento ID=A1 CFG=sin REP=1
# Hace: kill switch -> recrea apps con la configuración -> carga con la falla activada/desactivada en el
# segundo exacto de faults.yaml (t=0 es el fin del calentamiento) -> deja todo en Entrega 3/evidencia/<ID>/<cfg>_r<n>/
#
# Configuraciones:
#   sin            = defaults de la plataforma (docker-compose.yml)
#   con            = + perfil M (docker-compose.resiliencia.yml). Excepciones por experimento (ver fichas):
#                      C1 con = perfil M + nginx con limit_req (docker-compose.ratelimit.yml)
#                      C2 sin = consumidor SIN deduplicación (docker-compose.c2-sin.yml); con = consumidor idempotente
#                      D1     = ambas usan la plataforma por defecto; "con" = el CLIENTE reintenta 2 veces (--reintentos-cliente 2)
#   con-VARIANTE   = perfil M + docker-compose.var-VARIANTE.yml (correcciones; p. ej. con-umbral70 para D2)
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

ID="${1:?Falta el ID (A1, A2, B1, B2, C1, C2, D1, D2)}"; ID="${ID^^}"
CFG="${2:?Falta la configuración: sin | con | con-VARIANTE}"
REP="${3:?Falta el número de repetición}"
BASECFG="${CFG%%-*}"
VARIANTE=""; if [[ "$CFG" == *-* ]]; then VARIANTE="${CFG#*-}"; fi
case "$BASECFG" in sin|con) ;; *) echo "CFG debe ser 'sin', 'con' o 'con-VARIANTE'"; exit 1 ;; esac
if [ -n "$VARIANTE" ] && [ ! -f "docker-compose.var-$VARIANTE.yml" ]; then echo "Falta docker-compose.var-$VARIANTE.yml"; exit 1; fi

PY=.venv/Scripts/python.exe
[ -f "$PY" ] || PY=.venv/bin/python
CTRL="$PY faults/controlador_fallas.py"

read -r INICIO DUR <<< "$($PY -c "import sys,yaml; c=yaml.safe_load(open('faults/faults.yaml',encoding='utf-8')); f=[x for x in c['fallas'] if x['id']==sys.argv[1]][0]; print(f['inicio_s'], f['duracion_s'])" "$ID" | tr -d '\r')"
INICIO="${INICIO_S:-$INICIO}"
DUR="${DURACION_FALLA_S:-$DUR}"
CALENT=30
case "$ID" in B1|B2|D1) CARGA_DEF=300 ;; *) CARGA_DEF=$((INICIO + DUR + 60)) ;; esac   # duraciones de carga de las fichas
CARGA_S="${DURACION_CARGA_S:-$CARGA_DEF}"

# --- Archivos de compose y servicios a recrear según experimento/configuración -----------------------------
FILES="-f docker-compose.yml"
if [ "$BASECFG" = con ] && [ "$ID" != D1 ]; then FILES="$FILES -f docker-compose.resiliencia.yml"; fi
if [ -n "$VARIANTE" ]; then FILES="$FILES -f docker-compose.var-$VARIANTE.yml"; fi
if [ "$ID" = C1 ] && [ "$BASECFG" = con ]; then FILES="$FILES -f docker-compose.ratelimit.yml"; fi
if [ "$ID" = C2 ] && [ "$BASECFG" = sin ]; then FILES="$FILES -f docker-compose.c2-sin.yml"; fi
SERVICIOS="app1 app2 app3 nginx"
if [ "$ID" = C2 ]; then SERVICIOS="$SERVICIOS consumidor-eventos"; fi

# --- Argumentos extra del generador --------------------------------------------------------------------
GEN_EXTRA=()
# B1 sin mecanismos: ~200 sol/s x 10 s de PoolTimeout = ~2 000 en vuelo; con el límite por defecto (1 000) el generador
# haría cola propia y mediría su retraso en lugar del servidor.
if [ "$ID" = B1 ]; then GEN_EXTRA+=(--max-conexiones 3000); fi
if [ "$ID" = D1 ]; then
    if [ "$BASECFG" = con ]; then GEN_EXTRA+=(--reintentos-cliente 2); else GEN_EXTRA+=(--reintentos-cliente 0); fi
fi

OUT="Entrega 3/evidencia/$ID/${CFG}_r${REP}"
if [ -e "$OUT/resumen.json" ]; then echo "Ya existe $OUT. Usa otra repetición o bórrala a mano."; exit 1; fi
mkdir -p "$OUT"
rm -f "$OUT/.fin"
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
# consulta SQL directa en el contenedor de PostgreSQL (resultado "plano": filas separadas por salto, columnas por |)
sq() { docker exec -e PGUSER=postgres pg-portal-b2b psql -X -q -At -d portal_b2b -c "$1" | tr -d '\r'; }
cola_mensajes() { docker exec "$REL" rabbitmqctl -q list_queues name messages 2>/dev/null | tr -d '\r' | awk '$1=="ordenes_eventos"{print $2}'; }

marca "experimento $ID config=$CFG rep=$REP (falla en t=${INICIO}s durante ${DUR}s; carga ${CARGA_S}s + ${CALENT}s de calentamiento)"
$CTRL kill-switch on > /dev/null

marca "recreando $SERVICIOS con: $FILES"
docker compose $FILES up -d --force-recreate --wait $SERVICIOS 2> "$OUT/compose.log"

{
  echo "experimento=$ID config=$CFG repeticion=$REP"
  echo "commit=$(git rev-parse HEAD)"
  echo "cambios_sin_commit_en_codigo=$([ -n "$(git status --short -- . ':!Entrega 3/evidencia' ':!resultados' ':!baseline/corridas' ':!faults/faults.yaml')" ] && echo true || echo false)"
  echo "falla_inicio_s=$INICIO falla_duracion_s=$DUR carga_s=$CARGA_S calentamiento_s=$CALENT semilla=42 flujos_por_s=100"
  echo "compose=$FILES"
  echo "generador_extra=${GEN_EXTRA[*]:-}"
  echo "nginx_directivas_limit_req=$(docker exec portal-nginx grep -c 'limit_req' /etc/nginx/nginx.conf | tr -d '\r' || true)"
  echo "consumidor_CONSUMIDOR_DEDUPLICAR=$(docker exec portal-consumidor-eventos printenv CONSUMIDOR_DEDUPLICAR | tr -d '\r' || true)"
  echo "--- entorno de app1 ---"
  docker exec portal-app1 env | tr -d '\r' | grep -E '^(CREDITO_|REINTENTOS_|BREAKER_|BULKHEAD_|DEGRADACION_|DB_LOCK_|BD_POOL_|OTEL_ACTIVO)' | sort
} > "$OUT/manifest.txt"
cp faults/faults.yaml "$OUT/faults.yaml"

# --- Muestreos auxiliares (paran con el archivo .fin) ---------------------------------------------------------
muestreo_salud() {   # /salud/lista de cada instancia cada ~1 s: marca cuándo vuelve cada una (B1, D1)
    echo "ts_host,app1,app2,app3" > "$OUT/salud.csv"
    while [ ! -e "$OUT/.fin" ]; do
        local l
        l=$(docker exec portal-nginx sh -c 'for a in app1 app2 app3; do c=$(wget -T 1 -S -O /dev/null "http://$a:8000/salud/lista" 2>&1 | awk "/HTTP\\//{print \$2; exit}"); printf "%s," "${c:-000}"; done' 2>/dev/null | tr -d '\r') || l=",,,"
        echo "$(date +%s),${l%,}" >> "$OUT/salud.csv"
        sleep 1
    done
}
muestreo_lag() {     # cola de RabbitMQ y outbox cada 3 s (C2)
    echo "ts_host,cola_ready,cola_unacked,outbox_pendientes,eventos_procesados_total" > "$OUT/lag.csv"
    while [ ! -e "$OUT/.fin" ]; do
        local q d
        q=$(docker exec "$REL" rabbitmqctl -q list_queues name messages_ready messages_unacknowledged 2>/dev/null | tr -d '\r' | awk '$1=="ordenes_eventos"{print $2","$3}') || q=","
        d=$(sq "SELECT (SELECT count(*) FROM ordenes.outbox WHERE publicado_en IS NULL)||','||(SELECT count(*) FROM notificaciones.eventos_procesados)" 2>/dev/null) || d=","
        echo "$(date +%s),${q:-,},${d:-,}" >> "$OUT/lag.csv"
        sleep 3
    done
}
SAMPLERS=()
cleanup() { touch "$OUT/.fin"; for p in ${SAMPLERS[@]+"${SAMPLERS[@]}"}; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

EP0=$(sq "SELECT count(*) FROM notificaciones.eventos_procesados" || echo "?")

bash carga/correr_carga.sh --flujos-por-s 100 --duracion "$CARGA_S" --calentamiento "$CALENT" \
    --semilla 42 ${GEN_EXTRA[@]+"${GEN_EXTRA[@]}"} --salida "$OUT" > "$OUT/carga.log" 2>&1 &
CARGA_PID=$!
until grep -q "Carga planificada" "$OUT/carga.log" 2>/dev/null; do
    if ! kill -0 "$CARGA_PID" 2>/dev/null; then echo "La carga terminó sin arrancar:"; tail -20 "$OUT/carga.log"; exit 1; fi
    sleep 0.5
done
T0=$(vm)
marca "carga iniciada: t0 aprox. (calentamiento de ${CALENT}s; t=0 de la ficha es el fin del calentamiento)"

if [ "$ID" = B1 ] || [ "$ID" = D1 ]; then muestreo_salud & SAMPLERS+=($!); fi
if [ "$ID" = C2 ]; then muestreo_lag & SAMPLERS+=($!); fi

esperar $((T0 + CALENT + INICIO))
marca "ACTIVAR $ID (t=${INICIO}s)"
$CTRL activar "$ID" | tee -a "$EV"
if [ "$ID" = D1 ]; then
    marca "D1 +0s: portal-app2 estado=$(docker inspect -f '{{.State.Status}}' portal-app2 2>&1 | tr -d '\r')"
    ( docker exec "$REL" sleep 25; marca "D1 +25s: portal-app2 estado=$(docker inspect -f '{{.State.Status}}' portal-app2 2>&1 | tr -d '\r') (debe seguir exited: sin reinicio automático)" ) &
fi

esperar $((T0 + CALENT + INICIO + DUR))
marca "DESACTIVAR $ID (t=$((INICIO + DUR))s)"
$CTRL desactivar "$ID" | tee -a "$EV"

if [ "$ID" = B1 ]; then
    T_UP=$(vm)
    for _ in $(seq 1 120); do
        if docker exec pg-portal-b2b pg_isready -U postgres -q 2>/dev/null; then break; fi
        sleep 0.5
    done
    marca "B1: PostgreSQL acepta conexiones (+$(( $(vm) - T_UP )) s tras docker start)"
fi

if [ "$ID" = C2 ]; then   # ¿cuánto tarda en vaciarse la cola tras reanudar el consumidor?
    T_UN=$(vm); vaciada=0
    while [ "$(vm)" -lt $((T_UN + 600)) ]; do
        n=$(cola_mensajes || true)
        if [ "${n:-x}" = "0" ]; then marca "C2: cola ordenes_eventos vacía (+$(( $(vm) - T_UN )) s tras reanudar el consumidor)"; vaciada=1; break; fi
        sleep 2
    done
    if [ "$vaciada" = 0 ]; then
        marca "C2: la cola NO se vació en 600 s (quedan ${n:-?}); se purga para no contaminar la siguiente corrida"
        docker exec "$REL" rabbitmqctl -q purge_queue ordenes_eventos > /dev/null || true
    fi
fi

wait "$CARGA_PID" || { echo "La carga terminó con error:"; tail -20 "$OUT/carga.log"; }
marca "carga terminada"
$CTRL kill-switch on > /dev/null

# La BD debe estar lista antes de verificar/reiniciar el estado (B1)
for _ in $(seq 1 120); do
    if docker exec pg-portal-b2b pg_isready -U postgres -q 2>/dev/null; then break; fi
    sleep 0.5
done

# Verificación de negocio ANTES del reset (el reset borra órdenes, reservas y outbox)
{
    echo "== verificación de negocio previa al reset ($(date -u +%FT%TZ)) =="
    echo "eventos_procesados_total_antes=$EP0"
    echo "eventos_procesados_total_despues=$(sq "SELECT count(*) FROM notificaciones.eventos_procesados" || echo '?')"
    sq "SELECT 'ordenes_' || estado || '|' || count(*) FROM ordenes.ordenes_compra WHERE numero_orden LIKE 'OC-E3-%' GROUP BY estado ORDER BY 1" || true
    sq "SELECT 'outbox_total|' || count(*) FROM ordenes.outbox" || true
    sq "SELECT 'outbox_pendientes|' || count(*) FROM ordenes.outbox WHERE publicado_en IS NULL" || true
    sq "SELECT 'reservas_' || estado || '|' || count(*) FROM logistica.reservas GROUP BY estado ORDER BY 1" || true
    sq "SELECT 'idempotencia_EN_CURSO|' || count(*) FROM ordenes.idempotencia WHERE estado = 'EN_CURSO'" || true
    sq "SELECT 'violaciones_invariante_reservada_mayor_total|' || count(*) FROM logistica.franjas_cedi WHERE capacidad_reservada > capacidad_total" || true
    sq "SELECT 'franja_91150_reservada_de_total|' || capacidad_reservada || '/' || capacidad_total FROM logistica.franjas_cedi WHERE id = 91150" || true
} > "$OUT/verificacion.txt" 2>&1 || true
cat "$OUT/verificacion.txt"

if [ "$ID" = C2 ]; then   # deja el consumidor con su configuración por defecto
    docker compose -f docker-compose.yml up -d --force-recreate consumidor-eventos 2>> "$OUT/compose.log" || true
fi
docker ps -a --format '{{.Names}}\t{{.Status}}' | tr -d '\r' > "$OUT/contenedores_final.txt" || true

cleanup; trap - EXIT   # detiene los muestreos
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql > /dev/null
echo
echo "== Resultado global ($ID $CFG r$REP) =="
grep -E '^\{"global"' "$OUT/carga.log" || tail -5 "$OUT/carga.log"
echo "Evidencia en: $OUT"
sleep 4; rm -f "$OUT/.fin"
