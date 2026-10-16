#!/usr/bin/env bash
# cola.sh — encadena corridas de experimentos SIN supervisión (por ejemplo, de noche).
#  - Salta las corridas que ya tienen resumen.json (se puede relanzar sin repetir trabajo).
#  - Si una corrida falla, apaga las fallas, aparta la carpeta incompleta y sigue con la siguiente.
#  - Si fallan 3 seguidas aborta (algo está roto; no tiene sentido gastar la noche).
# Uso: make cola                      (A1, D2 y A2: sin/con x 2 repeticiones, alternando)
#      EXPS="D1 B1 B2 C1 C2" bash faults/cola.sh      (otros experimentos; CFGS="con-umbral70" para variantes)
#      bash faults/cola.sh "A1 sin 2" "A1 con 2"   (lista explícita: "ID cfg rep")
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
EVI="Entrega 3/evidencia"
LOG="$EVI/cola.log"
mkdir -p "$EVI/_consola"
PY=.venv/Scripts/python.exe
[ -f "$PY" ] || PY=.venv/bin/python

CORRIDAS=("$@")
# Listas predefinidas:  make cola LISTA=resto   (B1, B2, C1, C2, D1: primero una corrida de cada una para detectar
# fallas del montaje pronto, después el resto hasta 2 repeticiones sin/con)   |   make cola LISTA=d2fix (corrección de D2)
if [ ${#CORRIDAS[@]} -eq 0 ] && [ "${LISTA:-}" = "resto" ]; then
    CORRIDAS=("D1 sin 1" "B2 sin 1" "C2 sin 1" "B1 sin 1" "C1 sin 1"
              "D1 con 1" "B2 con 1" "C2 con 1" "B1 con 1" "C1 con 1"
              "D1 sin 2" "B2 sin 2" "C2 sin 2" "B1 sin 2" "C1 sin 2"
              "D1 con 2" "B2 con 2" "C2 con 2" "B1 con 2" "C1 con 2")
elif [ ${#CORRIDAS[@]} -eq 0 ] && [ "${LISTA:-}" = "rep3" ]; then
    # (1) repetición de 4 corridas "con r2" contaminadas (B2 no se repite en su forma original: no ejercita el bloqueo);
    # (2) B2 variante lock0, (3) D2 con umbral 70, (4) C1 con 0,10 CPU
    CORRIDAS=("D1 con 3" "C2 con 3" "B1 con 3" "C1 con 3"
              "B2 sin-lock0 1" "B2 con-lock0 1" "B2 sin-lock0 2" "B2 con-lock0 2"
              "D2 con-umbral70 1" "D2 con-umbral70 2"
              "C1 sin-cpu010 1" "C1 con-cpu010 1")
elif [ ${#CORRIDAS[@]} -eq 0 ] && [ "${LISTA:-}" = "d2fix" ]; then
    CORRIDAS=("D2 con-umbral70 1" "D2 con-umbral70 2")
fi
if [ ${#CORRIDAS[@]} -eq 0 ]; then
    for e in ${EXPS:-A1 D2 A2}; do for r in 1 2; do for c in ${CFGS:-sin con}; do CORRIDAS+=("$e $c $r"); done; done; done
fi

seguidas=0
echo "[cola] $(date '+%F %T') comienzo: ${#CORRIDAS[@]} corridas" | tee -a "$LOG"
for corrida in "${CORRIDAS[@]}"; do
    set -- $corrida; ID=$1; CFG=$2; REP=$3
    OUT="$EVI/$ID/${CFG}_r${REP}"
    if [ -e "$OUT/resumen.json" ]; then echo "[cola] salto $corrida (ya existe)" | tee -a "$LOG"; continue; fi
    if [ -d "$OUT" ]; then mv "$OUT" "${OUT}_incompleta_$(date +%H%M%S)"; fi
    echo "[cola] $(date '+%T') inicio $corrida" | tee -a "$LOG"
    if bash faults/experimento.sh "$ID" "$CFG" "$REP" > "$EVI/_consola/${ID}_${CFG}_r${REP}.txt" 2>&1; then
        seguidas=0
        echo "[cola] $(date '+%T') OK    $corrida :: $(grep -E '^\{"global"' "$EVI/_consola/${ID}_${CFG}_r${REP}.txt" | cut -c1-200)" | tee -a "$LOG"
    else
        seguidas=$((seguidas + 1))
        echo "[cola] $(date '+%T') FALLÓ $corrida (ver $EVI/_consola/${ID}_${CFG}_r${REP}.txt)" | tee -a "$LOG"
        $PY faults/controlador_fallas.py kill-switch on > /dev/null 2>&1 || true
        if [ "$seguidas" -ge 3 ]; then echo "[cola] 3 fallos seguidos: aborto." | tee -a "$LOG"; exit 1; fi
    fi
done
echo "[cola] $(date '+%F %T') TERMINADA" | tee -a "$LOG"
