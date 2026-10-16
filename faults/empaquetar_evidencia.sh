#!/usr/bin/env bash
# empaquetar_evidencia.sh — comprime solicitudes.csv de cada corrida terminada (tiene resumen.json).
# El CSV crudo queda en disco (git lo ignora) y se versiona solicitudes.csv.gz (~5x más pequeño).
cd "$(dirname "$0")/.."
n=0
while IFS= read -r -d '' resumen; do
    d="$(dirname "$resumen")"
    if [ -f "$d/solicitudes.csv" ] && { [ ! -f "$d/solicitudes.csv.gz" ] || [ "$d/solicitudes.csv" -nt "$d/solicitudes.csv.gz" ]; }; then
        gzip -kf "$d/solicitudes.csv" && n=$((n + 1))
    fi
done < <(find "Entrega 3/evidencia" -name resumen.json -print0)
echo "[empaquetar] $n corrida(s) comprimida(s)"
