#!/usr/bin/env bash
# palanca.sh — A/B de una palanca de la meta −10 % (baseline/palancas.md), en la MISMA base y condición de medición:
#   antes (control) -> aplica palancas/<P>.sql -> despues -> revierte con palancas/<P>_revertir.sql.
# Uso: bash baseline/palanca.sh P1 [CORRIDAS]      (o: make palanca P=P1)
# Salida: baseline/corridas/meta-<P>/{antes,despues}/q1q5_k/ + comparacion.csv + comparacion.txt
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
P="${1:?Falta la palanca: P1 | P2 | P3}"; N="${2:-5}"
DIR="baseline/corridas/meta-$P"
[ -e "$DIR/comparacion.csv" ] && { echo "Ya existe $DIR; bórrala a mano para repetir."; exit 1; }
PY=.venv/Scripts/python.exe; [ -f "$PY" ] || PY=.venv/bin/python
PY3="${PYTHON:-python3}"
sql() { bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b "$@"; }
paso() { echo; echo "===== [$(date +%H:%M:%S)] $* ====="; }
mkdir -p "$DIR"
exec > >(tee -a "$DIR/palanca.log") 2>&1

paso "0. Plataforma detenida (las consultas del E2 se miden sin aplicación) y base en el mismo estado para antes y después"
docker compose stop stub-credito app1 app2 app3 nginx publicador-outbox consumidor-eventos 2>/dev/null || true
docker compose up -d --wait db
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql > /dev/null
sql -c "VACUUM (ANALYZE) ordenes.ordenes_compra" -c "VACUUM (ANALYZE) ordenes.lineas_orden"
sql -c "SELECT name, setting FROM pg_settings WHERE name IN ('jit','random_page_cost','shared_buffers','work_mem')" | tee "$DIR/ajustes_antes.txt"
sql -c "\\di+ ordenes.*" > "$DIR/indices_antes.txt"

paso "1. ANTES (control): Q1–Q5 frío/caliente x$N"
for k in $(seq 1 "$N"); do SALIDA_DIR="$DIR/antes/q1q5_${k}" "$PY" medicion/medir.py > /dev/null; done

paso "2. Aplicar $P"
if [ "$P" = P1 ]; then
    sql -c "EXPLAIN (ANALYZE, BUFFERS) SELECT o.id, o.fecha_compromiso, o.fecha_entrega FROM ordenes.ordenes_compra o WHERE o.proveedor_id = 1 AND o.fecha_emision >= DATE '2024-09-17' AND o.fecha_emision < DATE '2026-09-17' AND o.estado = 'CONFIRMADA' AND o.fecha_entrega IS NOT NULL" > "$DIR/explain_q4_antes.txt" 2>&1 || true
fi
sql -f "baseline/palancas/$P.sql"
sql -c "SELECT name, setting FROM pg_settings WHERE name IN ('jit','random_page_cost','shared_buffers','work_mem')" | tee "$DIR/ajustes_despues.txt"
sql -c "\\di+ ordenes.*" > "$DIR/indices_despues.txt"
if [ "$P" = P1 ]; then
    Q4="EXPLAIN (ANALYZE, BUFFERS) SELECT o.id, o.fecha_compromiso, o.fecha_entrega FROM ordenes.ordenes_compra o WHERE o.proveedor_id = 1 AND o.fecha_emision >= DATE '2024-09-17' AND o.fecha_emision < DATE '2026-09-17' AND o.estado = 'CONFIRMADA' AND o.fecha_entrega IS NOT NULL"
    sql -c "$Q4" > "$DIR/explain_q4_despues.txt" 2>&1 || true
fi

paso "3. DESPUÉS: Q1–Q5 frío/caliente x$N"
for k in $(seq 1 "$N"); do SALIDA_DIR="$DIR/despues/q1q5_${k}" "$PY" medicion/medir.py > /dev/null; done

paso "4. Revertir $P (la base queda como estaba)"
sql -f "baseline/palancas/${P}_revertir.sql"

paso "5. Comparación antes/después contra el objetivo −10 %"
"$PY3" baseline/comparar_palanca.py --antes "$DIR/antes" --despues "$DIR/despues" --salida "$DIR" | tee "$DIR/comparacion.txt"
paso "Listo: $DIR"
