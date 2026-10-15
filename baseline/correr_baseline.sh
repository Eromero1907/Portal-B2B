#!/usr/bin/env bash
# =====================================================================
# correr_baseline.sh — Momento 1 del Entregable 3: línea base reproducible derivada del Entregable 2
#
# Reconstruye el estado canónico del E2 DESDE CERO y mide, SIN FALLAS ACTIVAS, todas las métricas de tiempo
# reportadas en el E2 con su mismo protocolo, más la ruta de confirmación de la plataforma nueva:
#   0. detiene la plataforma (las consultas del E2 se midieron sin aplicación corriendo)
#   1. datos: PostgreSQL + generar --seed 42 --scale min + carga COPY cronometrada  (= make datos)
#   2. verificación de volumen, sesgo y casos borde                                  (= make verificar)
#   3. Q1–Q5 frío/caliente, CORRIDAS veces (variabilidad entre corridas)             (medicion/medir.py)
#   4. [COMPLETA=1] Q3 con 16/32/64 hilos, DURACION_Q3 s de medición por hilo (5 s en el E2) (medicion/concurrencia_q3.py)
#   5. [COMPLETA=1] estrategias de inyección E1a, E1b, E2, E3, E4                    (baseline/estrategias.py)
#   6. plataforma (esquema E3 + 3 apps + nginx + stub) y carga estable de la ruta   (carga/correr_carga.sh)
#   2b. manifest (semilla, conteos del E2, PostgreSQL, imágenes, máquina, commit)    (baseline/manifest.py)
#   7. comparación contra el E2 y la meta −10 %                                      (baseline/objetivos.py)
#   8. reset del estado de la plataforma (la base queda como el E2 + esquema E3 vacío)
#
# Variables: CORRIDAS (3) · COMPLETA (1) · DURACION_Q3 (5) · FLUJOS (100) · DURACION (300) · CALENTAMIENTO (30)
#            ID (nombre de la corrida; por defecto <equipo>-<fecha>) · NOTA (texto libre para el manifest)
# Resultado: baseline/corridas/<ID>/ con los CSV crudos de cada paso, manifest.json, comparacion_e2.csv y el log.
# Duración aproximada con COMPLETA=1: 20–40 min según la máquina (E4 ≈ 8 min en la máquina del E2, 15 en la de JJ;
# ruta ≈ 6 min; Q3 concurrente ≈ 1–3 min).
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8

CORRIDAS="${CORRIDAS:-3}"
COMPLETA="${COMPLETA:-1}"
DURACION_Q3="${DURACION_Q3:-5}"
FLUJOS="${FLUJOS:-100}"
DURACION="${DURACION:-300}"
CALENTAMIENTO="${CALENTAMIENTO:-30}"
EQUIPO="$(hostname 2>/dev/null || echo equipo)"
ID="${ID:-${EQUIPO}-$(date +%Y%m%d-%H%M%S)}"
DIR="baseline/corridas/${ID}"
PLATAFORMA="stub-credito app1 app2 app3 nginx"

if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else echo "ERROR: falta el entorno del host para medicion/. Ejecuta primero: make venv" >&2; exit 1; fi
PY3="${PYTHON:-python3}"

mkdir -p "$DIR"
exec > >(tee -a "$DIR/baseline.log") 2>&1
paso() { echo; echo "===== [$(date +%H:%M:%S)] $* ====="; }
# Los scripts del E2 escriben su evidencia en datos/resultados/ (versionada con la corrida del informe E2):
# se copia a la carpeta de esta corrida y se restaura la versión del repositorio.
preservar_e2() { git checkout -- datos/resultados/ 2>/dev/null || true; }

paso "Línea base ${ID}: CORRIDAS=${CORRIDAS} COMPLETA=${COMPLETA} DURACION_Q3=${DURACION_Q3}s ruta=${FLUJOS} flujos/s × ${DURACION}s"

paso "0. Plataforma detenida (las consultas del E2 se midieron sin aplicación)"
docker compose stop $PLATAFORMA 2>/dev/null || true

paso "1. Datos desde cero: --seed 42 --scale min + carga COPY"
docker compose up -d --wait db
"$PY3" datos/generar.py --seed 42 --scale min
bash datos/cargar.sh
cp datos/resultados/carga_tiempos.csv datos/resultados/entorno_bd.csv "$DIR/"

paso "2. Verificación de volumen, sesgo, integridad y casos borde"
"$PY3" datos/verificar.py > "$DIR/verificacion.txt" || { echo "La verificación FALLA: la línea base no es válida"; exit 1; }
tail -3 "$DIR/verificacion.txt"
preservar_e2

paso "2b. Manifest (volumen heredado del E2, configuración, máquina; antes de que la plataforma escriba nada)"
"$PY3" baseline/manifest.py --salida "$DIR" --nota "${NOTA:-}"

for k in $(seq 1 "$CORRIDAS"); do
    paso "3. Q1–Q5 frío/caliente, corrida ${k} de ${CORRIDAS}"
    SALIDA_DIR="$DIR/q1q5_${k}" "$PY" medicion/medir.py
done

if [ "$COMPLETA" = "1" ]; then
    paso "4. Q3 concurrente 16/32/64 hilos, ${DURACION_Q3} s de medición por hilo"
    DURACION_S="$DURACION_Q3" SALIDA_DIR="$DIR" "$PY" medicion/concurrencia_q3.py
    paso "5. Estrategias de inyección E1a, E1b, E2, E3, E4 (subconjunto S)"
    "$PY" baseline/estrategias.py --salida "$DIR"
else
    paso "4–5. Omitidos (COMPLETA=0): Q3 concurrente y estrategias de inyección"
fi

paso "6. Plataforma y carga estable de la ruta de confirmación"
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/esquema_e3.sql
docker compose up -d --build --wait $PLATAFORMA
bash carga/correr_carga.sh --salida "$DIR/ruta" --flujos-por-s "$FLUJOS" --duracion "$DURACION" \
    --calentamiento "$CALENTAMIENTO" --semilla 42

paso "7. Comparación contra el E2 y la meta −10 %"
"$PY3" baseline/objetivos.py comparar --corrida "$DIR"

paso "8. Estado limpio para el siguiente uso (se borran las órdenes que creó la carga)"
bash datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql

paso "Listo: $DIR"
