#!/usr/bin/env python3
"""Compara dos carpetas con q1q5_*/percentiles.csv (antes / después de una palanca).
Por métrica: mediana de las N corridas, rango entre corridas, cambio %, y veredicto:
  MEJORA REAL      mediana_después ≤ 0,90 × mediana_antes (−10 %) Y la mejora supera el rango entre corridas del 'antes'
  DENTRO DEL RUIDO |cambio| menor que el rango entre corridas
  EMPEORA          mediana_después > 1,10 × mediana_antes y supera el rango
  (sin cambio relevante)  en cualquier otro caso
Además indica si la mediana 'después' cumple el objetivo E3 de baseline/objetivos.csv."""
import argparse, csv, statistics
from pathlib import Path

def leer(carpeta):
    datos = {}
    for pct in sorted(Path(carpeta).glob("q1q5_*/percentiles.csv")):
        for r in csv.DictReader(open(pct, encoding="utf-8")):
            for m in ("p50", "p95", "p99"):
                datos.setdefault(f"consulta:{r['consulta']}:{r['escenario']}:{m}", []).append(float(r[f"{m}_ms"]))
    return datos

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--antes", required=True); ap.add_argument("--despues", required=True)
    ap.add_argument("--salida", required=True); a = ap.parse_args()
    antes, despues = leer(a.antes), leer(a.despues)
    obj = {r["id"]: float(r["objetivo_e3"]) for r in csv.DictReader(open(Path(__file__).parent / "objetivos.csv", encoding="utf-8"))}
    filas = []
    for k in sorted(antes):
        if k not in despues: continue
        A, D = antes[k], despues[k]
        ma, md = statistics.median(A), statistics.median(D)
        rango = max(A) - min(A)
        cambio = 100 * (md - ma) / ma
        if md <= 0.9 * ma and (ma - md) > rango: v = "MEJORA REAL"
        elif md > 1.1 * ma and (md - ma) > rango: v = "EMPEORA"
        elif abs(md - ma) <= rango: v = "DENTRO DEL RUIDO"
        else: v = "sin cambio relevante"
        o = obj.get(k)
        filas.append({"metrica": k, "n_antes": len(A), "mediana_antes_ms": round(ma, 4), "rango_antes_ms": round(rango, 4),
                      "mediana_despues_ms": round(md, 4), "cambio_pct": round(cambio, 1), "veredicto": v,
                      "objetivo_e3_ms": o if o is not None else "", "cumple_objetivo_despues": ("SI" if o is not None and md <= o else "NO")})
    with open(Path(a.salida) / "comparacion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
    print(f"{'métrica':44s} {'antes':>9s} {'±rango':>8s} {'después':>9s} {'cambio':>8s}  veredicto / objetivo")
    for r in filas:
        print(f"{r['metrica']:44s} {r['mediana_antes_ms']:9.4f} {r['rango_antes_ms']:8.4f} {r['mediana_despues_ms']:9.4f} {r['cambio_pct']:7.1f}%  {r['veredicto']} / meta {r['cumple_objetivo_despues']}")
main()
