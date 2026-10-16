#!/usr/bin/env bash
# cola.sh — encadena corridas de experimentos SIN supervisión (por ejemplo, de noche).
#  - Salta las corridas que ya tienen resumen.json (se puede relanzar sin repetir trabajo).
#  - Si una corrida falla, apaga las fallas, aparta la carpeta incompleta y sigue con la siguiente.
#  - Si fallan 3 seguidas aborta (algo está roto; no tiene sentido gastar la noche).
# Uso: make cola                      (A1, D2 y A2: sin/con x 2 repeticiones, alternando)
#      bash faults/cola.sh "A1 sin 2" "A1 con 2"   (lista explícita: "ID cfg rep")
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
EVI="Entrega 3/evidencia"
LOG="$EVI/cola.log"
mkdir -p "$EVI/_consola"
PY=.venv/Scripts/python.exe
[ -f "$PY" ] || PY=.venv/bin/python

CORRIDAS=("$@")
if [ ${#CORRIDAS[@]} -eq 0 ]; then
    for e in A1 D2 A2; do for r in 1 2; do for c in sin con; do CORRIDAS+=("$e $c $r"); done; done; done
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
