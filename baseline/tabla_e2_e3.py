"""Tabla de la rúbrica final: E2 vs E3 por consulta, escenario y métrica (p50/p95/p99), con la meta del −10 %.

Lee una corrida de baseline/ab_e2_e3.sh (rondas intercaladas e2_r*/ y e3_r*/) y escribe:
  tabla_e2_e3.csv  — todas las columnas, para análisis
  tabla_e2_e3.md   — la tabla para el informe y la presentación

Columnas clave
  E2 informe   valor reportado en el informe final del E2 (baseline/referencia_e2.json)
  Meta         0,90 × E2 informe
  E2 hoy       mediana de las rondas en ESTADO E2 medidas en esta misma sesión (control de condiciones)
  E3 final     mediana de las rondas en ESTADO E3
  Cumple meta  E3 final ≤ Meta
  Mejora atribuible  E3 final ≤ 0,90 × E2 hoy y TODAS las rondas E3 por debajo de TODAS las rondas E2 (sin solape):
                     la mejora es del sistema, no de la máquina ni del ruido
Solo biblioteca estándar.

  python baseline/tabla_e2_e3.py --corrida baseline/corridas/<id>
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
NOMBRES = {"q1": "Q1 proveedor + contrato", "q2": "Q2 precio de 20 SKU", "q3": "Q3 franjas con cupo",
           "q4": "Q4 OTIF y fill rate", "q5": "Q5 últimas 50 órdenes"}


def leer(corrida: Path, estado: str) -> dict:
    datos = {}
    for pct in sorted(corrida.glob(f"{estado}_r*/percentiles.csv")):
        with open(pct, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                for m in ("p50", "p95", "p99"):
                    datos.setdefault((r["consulta"], r["escenario"], m), []).append(float(r[f"{m}_ms"]))
    return datos


def fmt(x, dec=2):
    return "—" if x is None else f"{x:.{dec}f}".replace(".", ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corrida", required=True)
    a = ap.parse_args()
    corrida = Path(a.corrida)
    ref = json.loads((RAIZ / "referencia_e2.json").read_text(encoding="utf-8"))
    e2, e3 = leer(corrida, "e2"), leer(corrida, "e3")
    manifest = corrida / "manifest.json"
    maquina = json.loads(manifest.read_text(encoding="utf-8")).get("maquina", {}) if manifest.exists() else {}

    filas = []
    for c in ref["consultas"]:
        for m in ("p50", "p95", "p99"):
            clave = (c["consulta"], c["escenario"], m)
            v_inf = c[f"{m}_ms"]
            meta = round(v_inf * 0.9, 4)
            r2, r3 = e2.get(clave, []), e3.get(clave, [])
            hoy = statistics.median(r2) if r2 else None
            fin = statistics.median(r3) if r3 else None
            fila = {"consulta": c["consulta"], "escenario": c["escenario"], "metrica": m, "e2_informe_ms": v_inf,
                    "meta_e3_ms": meta, "e2_hoy_ms": hoy, "e2_hoy_min": min(r2) if r2 else None,
                    "e2_hoy_max": max(r2) if r2 else None, "e3_final_ms": fin, "e3_min": min(r3) if r3 else None,
                    "e3_max": max(r3) if r3 else None, "rondas": min(len(r2), len(r3))}
            fila["cambio_vs_informe_pct"] = round(100 * (fin - v_inf) / v_inf, 1) if fin is not None else None
            fila["cambio_vs_e2_hoy_pct"] = round(100 * (fin - hoy) / hoy, 1) if fin is not None and hoy else None
            fila["cumple_meta"] = "SÍ" if fin is not None and fin <= meta else "NO"
            if fin is None or hoy is None:
                atrib = "sin medir"
            elif fin <= 0.9 * hoy and max(r3) < min(r2):
                atrib = "SÍ"
            elif fin <= 0.9 * hoy:
                atrib = "solo en mediana"
            elif fin >= 1.1 * hoy and min(r3) > max(r2):
                atrib = "empeora"
            else:
                atrib = "dentro del ruido"
            fila["mejora_atribuible"] = atrib
            filas.append(fila)

    with open(corrida / "tabla_e2_e3.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)

    md = [f"# Tabla E2 vs E3 · corrida `{corrida.name}`", "",
          f"Máquina: {maquina.get('cpu', '?')} · {maquina.get('ram_gb', '?')} GB · Docker {maquina.get('docker', '?')}. "
          f"Mismo cliente que el E2 (`medicion/medir.py`, 200 ejecuciones + 20 de calentamiento, `force_custom_plan`), "
          f"plataforma detenida, {filas[0]['rondas']} rondas intercaladas E2 → E3. Valores en ms; E2 hoy y E3 final "
          "son medianas entre rondas (rango entre corchetes).", "",
          "| Consulta | Escenario | Métrica | E2 informe | Meta E3 (−10 %) | E2 hoy [rango] | E3 final [rango] | E3 vs E2 informe | E3 vs E2 hoy | Cumple meta | Mejora atribuible |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|:---:|:---:|"]
    for f in filas:
        md.append(f"| {NOMBRES.get(f['consulta'], f['consulta'])} | {f['escenario']} | {f['metrica']} | "
                  f"{fmt(f['e2_informe_ms'])} | {fmt(f['meta_e3_ms'], 3)} | "
                  f"{fmt(f['e2_hoy_ms'])} [{fmt(f['e2_hoy_min'])}–{fmt(f['e2_hoy_max'])}] | "
                  f"**{fmt(f['e3_final_ms'])}** [{fmt(f['e3_min'])}–{fmt(f['e3_max'])}] | "
                  f"{fmt(f['cambio_vs_informe_pct'], 1)} % | {fmt(f['cambio_vs_e2_hoy_pct'], 1)} % | "
                  f"{f['cumple_meta']} | {f['mejora_atribuible']} |")
    cumplen = sum(f["cumple_meta"] == "SÍ" for f in filas)
    atrib = sum(f["mejora_atribuible"] == "SÍ" for f in filas)
    md += ["", f"**Resumen:** {cumplen} de {len(filas)} métricas cumplen la meta frente al informe del E2; "
           f"{atrib} tienen una mejora atribuible al sistema (≥ 10 % frente al estado E2 medido hoy y sin solape entre rondas)."]
    (corrida / "tabla_e2_e3.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
