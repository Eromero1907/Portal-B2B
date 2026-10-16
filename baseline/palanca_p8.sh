#!/usr/bin/env bash
# palanca_p8.sh — Palanca P8 (baseline/palancas.md): E4 con validación de catálogo en una consulta por orden.
#  1) A/B alternado control/lote sobre las primeras 10 000 órdenes (3 repeticiones).
#  2) E4 completo (50 000 órdenes) con la variante, por el mismo camino del E2 (baseline/estrategias.py), para
#     compararlo con valor_e2 y el objetivo de baseline/objetivos.csv.
# Plataforma detenida; usar con el equipo quieto y enchufado. Uso: make palanca-p8
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
DIR=baseline/corridas/meta-P8
[ -e "$DIR/ab/resumen.txt" ] && { echo "Ya existe $DIR; bórrala a mano para repetir."; exit 1; }
PY=.venv/Scripts/python.exe; [ -f "$PY" ] || PY=.venv/bin/python
mkdir -p "$DIR"; exec > >(tee -a "$DIR/palanca.log") 2>&1
paso() { echo; echo "===== [$(date +%H:%M:%S)] $* ====="; }
paso "0. Plataforma detenida"
docker compose stop stub-credito app1 app2 app3 nginx publicador-outbox consumidor-eventos 2>/dev/null || true
docker compose up -d --wait db
paso "1. A/B alternado (10 000 órdenes x 3)"
"$PY" baseline/e4_ab.py --salida "$DIR/ab" --limite 10000 --n 3
paso "2. E4 completo con la variante lote (camino del E2)"
E4_VARIANTE=lote "$PY" baseline/estrategias.py --salida "$DIR/completa_lote"
paso "Listo: $DIR (comparar E4 de $DIR/completa_lote/estrategias.csv con valor_e2 = 486,42 s y objetivo 437,78 s)"
