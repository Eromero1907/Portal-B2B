#!/usr/bin/env bash
# =====================================================================
# ab_e2_e3.sh — Evidencia de la mejora de tiempos del E2 al E3 (rúbrica final, criterio 4)
#
# Compara la MISMA consulta, el MISMO escenario y la MISMA métrica bajo condiciones comparables:
#   · mismo cliente (medicion/medir.py del E2: 20 de calentamiento + 200 ejecuciones, force_custom_plan, p50/p95/p99)
#   · misma máquina, misma sesión, mismos datos (--seed 42), plataforma detenida (como en el E2)
#   · rondas INTERCALADAS  E2 → E3 → E2 → E3 …  para que la deriva de la máquina afecte por igual a ambos estados
#
#   estado E2 = consultas del E2 (git a1b9141:datos/consultas.sql) + índice idx_ordenes_proveedor_fecha del E2
#   estado E3 = consultas finales (datos/consultas.sql) + índices finales de modelo-fisico.sql (L4 y L5)
#
# Antes de medir verifica que Q4 del E3 devuelve EXACTAMENTE lo mismo que Q4 del E2 (equivalencia).
# Al final deja la base en el estado E3 y genera tabla_e2_e3.csv / .md con baseline/tabla_e2_e3.py.
#
# Uso:  RONDAS=5 ID=<nombre> bash baseline/ab_e2_e3.sh          (make comparar-e2)
# Duración: ~1 min por ronda en la máquina del E2.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8

RONDAS="${RONDAS:-5}"
EQUIPO="$(hostname 2>/dev/null || echo equipo)"
ID="${ID:-ab-e2-e3-${EQUIPO}-$(date +%Y%m%d-%H%M%S)}"
DIR="baseline/corridas/${ID}"
PLATAFORMA="publicador-outbox consumidor-eventos nginx app1 app2 app3 stub-credito rabbitmq"
COMMIT_E2="a1b9141"

if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else echo "ERROR: falta el entorno del host. Ejecuta primero: make venv" >&2; exit 1; fi
PY3="${PYTHON:-python3}"

mkdir -p "$DIR"
exec > >(tee -a "$DIR/ab.log") 2>&1
paso() { echo; echo "===== [$(date +%H:%M:%S)] $* ====="; }
sql() { bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b "$@"; }

git show "${COMMIT_E2}:datos/consultas.sql" > "$DIR/consultas_e2.sql"
cp datos/consultas.sql "$DIR/consultas_e3.sql"

estado_e2() {
    sql -c "DROP INDEX IF EXISTS ordenes.idx_ordenes_proveedor_fecha" \
        -c "CREATE INDEX idx_ordenes_proveedor_fecha ON ordenes.ordenes_compra (proveedor_id, fecha_emision DESC, id DESC)" \
        -c "VACUUM ANALYZE ordenes.ordenes_compra"
}
estado_e3() {
    sql -c "DROP INDEX IF EXISTS ordenes.idx_ordenes_proveedor_fecha"
    sql -v tablas=false -v restricciones=false -v indices=true -f modelo-fisico.sql
    sql -c "VACUUM ANALYZE ordenes.ordenes_compra"
}

paso "A/B E2 vs E3 · ${ID} · ${RONDAS} rondas intercaladas"
paso "0. Plataforma detenida (el E2 midió las consultas sin aplicación corriendo)"
docker compose stop $PLATAFORMA >/dev/null 2>&1 || true
sql -f app/sql/reset_estado.sql > /dev/null 2>&1 || true

paso "1. Equivalencia: Q4 del E3 devuelve lo mismo que Q4 del E2"
estado_e3
"$PY" baseline/equivalencia_q4.py --e2 "$DIR/consultas_e2.sql" --e3 "$DIR/consultas_e3.sql" --salida "$DIR/equivalencia_q4.txt"

paso "2. Planes de ejecución antes/después (Q4 caliente y Q5 OFFSET 5000)"
for est in e2 e3; do
    "estado_${est}"
    { cat "$DIR/consultas_${est}.sql"
      echo "\\echo '=== Q4 caliente (proveedor 1, 24 meses)'"
      echo "EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON) EXECUTE q4(1, '2024-09-01', '2026-10-01');"
      echo "\\echo '=== Q5 OFFSET 5000 (proveedor 1)'"
      echo "EXPLAIN (ANALYZE, BUFFERS, SUMMARY ON) EXECUTE q5(1, 5000);"
    } | sql -f - > "$DIR/explain_${est}.txt"
    grep -E "^===|Execution Time|Planning Time" "$DIR/explain_${est}.txt" | sed "s/^/  [${est}] /"
done

for r in $(seq 1 "$RONDAS"); do
    for est in e2 e3; do
        paso "3. Ronda ${r}/${RONDAS} · estado ${est^^}"
        "estado_${est}"
        CONSULTAS_SQL="$DIR/consultas_${est}.sql" SALIDA_DIR="$DIR/${est}_r${r}" "$PY" medicion/medir.py \
            | grep -E "Guardado" || true
    done
done

paso "4. Base en el estado E3 final y tabla E2 vs E3"
estado_e3
"$PY3" baseline/manifest.py --salida "$DIR" --nota "A/B E2 vs E3 (${RONDAS} rondas intercaladas)" > /dev/null
"$PY3" baseline/tabla_e2_e3.py --corrida "$DIR"

paso "Listo: $DIR (tabla_e2_e3.md, tabla_e2_e3.csv, equivalencia_q4.txt, explain_e2.txt, explain_e3.txt)"
echo "La plataforma quedó detenida. Para volver a levantarla: make plataforma"
