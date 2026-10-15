"""Tabla de objetivos del Entregable 3 y comparación de una corrida contra el Entregable 2.

  python baseline/objetivos.py generar
      Escribe baseline/objetivos.csv: cada métrica de tiempo reportada en el informe final del E2 y su objetivo
      E3 = 0,90 × valor E2 (rúbrica §3). Para throughput (filas/s) el objetivo equivalente es valor / 0,90.

  python baseline/objetivos.py comparar --corrida baseline/corridas/<id> [--salida archivo.csv]
      Lee lo que dejó una corrida (q1q5_*/percentiles.csv, concurrencia_q3.csv, carga_tiempos.csv,
      estrategias.csv) y escribe comparacion_e2.csv: valor E2, objetivo, valor E3 (mediana de las corridas
      repetidas), rango entre corridas y si cumple. La regla de la rúbrica se respeta por construcción: misma
      consulta, mismo escenario y misma métrica en cada fila; nunca un p95 contra un promedio.

Solo biblioteca estándar: corre con cualquier python3.
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REFERENCIA = RAIZ / "referencia_e2.json"
FACTOR = 0.90

CAMPOS = ["id", "grupo", "objeto", "escenario", "metrica", "unidad", "sentido", "valor_e2", "objetivo_e3"]


def filas_objetivo() -> list[dict]:
    ref = json.loads(REFERENCIA.read_text(encoding="utf-8"))
    filas = []

    def agregar(grupo, objeto, escenario, metrica, unidad, valor, sentido="menor_o_igual"):
        objetivo = round(valor * FACTOR, 4) if sentido == "menor_o_igual" else round(valor / FACTOR, 2)
        filas.append({"id": f"{grupo}:{objeto}:{escenario}:{metrica}", "grupo": grupo, "objeto": objeto,
                      "escenario": escenario, "metrica": metrica, "unidad": unidad, "sentido": sentido,
                      "valor_e2": valor, "objetivo_e3": objetivo})

    for c in ref["consultas"]:
        for m in ("p50_ms", "p95_ms", "p99_ms"):
            agregar("consulta", c["consulta"], c["escenario"], m.replace("_ms", ""), "ms", c[m])
    for c in ref["concurrencia_q3"]:
        esc = f"{c['clave']}_{c['n_hilos']}h"
        for m in ("p50_ms", "p95_ms", "p99_ms"):
            agregar("q3_concurrente", "q3", esc, m.replace("_ms", ""), "ms", c[m])
        # throughput_por_s del E2 NO entra como objetivo: es un artefacto de medición (ver nota_concurrencia_q3)
    for c in ref["carga_masiva"]:
        agregar("carga_masiva", c["fase"], "make datos", "tiempo", "s", c["segundos"])
    for e in ref["estrategias_inyeccion"]:
        agregar("estrategia", e["estrategia"], e["descripcion"], "tiempo", "s", e["segundos"])
        agregar("estrategia", e["estrategia"], e["descripcion"], "throughput", "filas/s", e["filas_por_s"],
                "mayor_o_igual")
    return filas


def generar(destino: Path) -> None:
    filas = filas_objetivo()
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"{len(filas)} métricas con objetivo → {destino}")


# ---------------------------------------------------------------------------
# Comparación
# ---------------------------------------------------------------------------
def _leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def medidas_de_corrida(corrida: Path) -> dict[str, list[float]]:
    """id de métrica → lista de valores (uno por corrida repetida)."""
    medidas: dict[str, list[float]] = {}

    def poner(clave, valor):
        if valor not in (None, ""):
            medidas.setdefault(clave, []).append(float(valor))

    for pct in sorted(corrida.glob("q1q5_*/percentiles.csv")):
        for r in _leer_csv(pct):
            for m in ("p50", "p95", "p99"):
                poner(f"consulta:{r['consulta']}:{r['escenario']}:{m}", r[f"{m}_ms"])
    for conc in sorted(corrida.glob("concurrencia_q3*.csv")):
        for r in _leer_csv(conc):
            esc = f"{r['clave']}_{r['n_hilos']}h"
            for m in ("p50", "p95", "p99"):
                poner(f"q3_concurrente:q3:{esc}:{m}", r[f"{m}_ms"])
    carga = corrida / "carga_tiempos.csv"
    if carga.exists():
        for r in _leer_csv(carga):
            if r["fase"] == "copy" and r["objeto"] == "TOTAL":
                poner("carga_masiva:copy_total:make datos:tiempo", r["segundos"])
            if r["fase"] == "total":
                poner("carga_masiva:total:make datos:tiempo", r["segundos"])
    estr = corrida / "estrategias.csv"
    if estr.exists():
        for r in _leer_csv(estr):
            desc = r["descripcion"]
            poner(f"estrategia:{r['estrategia']}:{desc}:tiempo", r["segundos"])
            poner(f"estrategia:{r['estrategia']}:{desc}:throughput", r["filas_por_s"])
    return medidas


def comparar(corrida: Path, destino: Path) -> None:
    medidas = medidas_de_corrida(corrida)
    salida = []
    for o in filas_objetivo():
        valores = medidas.get(o["id"])
        fila = {**o, "n_corridas": 0, "e3_mediana": "", "e3_min": "", "e3_max": "", "rango_entre_corridas_pct": "",
                "cambio_vs_e2_pct": "", "cumple_objetivo": "sin_medir"}
        if valores:
            med = statistics.median(valores)
            fila.update(n_corridas=len(valores), e3_mediana=round(med, 4), e3_min=round(min(valores), 4),
                        e3_max=round(max(valores), 4),
                        rango_entre_corridas_pct=round(100 * (max(valores) - min(valores)) / med, 1) if med else "",
                        cambio_vs_e2_pct=round(100 * (med - o["valor_e2"]) / o["valor_e2"], 1))
            ok = med <= o["objetivo_e3"] if o["sentido"] == "menor_o_igual" else med >= o["objetivo_e3"]
            fila["cumple_objetivo"] = "SI" if ok else "NO"
        salida.append(fila)
    campos = CAMPOS + ["n_corridas", "e3_mediana", "e3_min", "e3_max", "rango_entre_corridas_pct",
                       "cambio_vs_e2_pct", "cumple_objetivo"]
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(salida)
    medidas_n = sum(1 for s in salida if s["n_corridas"])
    cumplen = sum(1 for s in salida if s["cumple_objetivo"] == "SI")
    print(f"{medidas_n} de {len(salida)} métricas medidas en {corrida}; {cumplen} ya cumplen el objetivo E3 → {destino}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="accion", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--salida", default=str(RAIZ / "objetivos.csv"))
    c = sub.add_parser("comparar")
    c.add_argument("--corrida", required=True)
    c.add_argument("--salida")
    args = ap.parse_args()
    if args.accion == "generar":
        generar(Path(args.salida))
    else:
        corrida = Path(args.corrida)
        comparar(corrida, Path(args.salida) if args.salida else corrida / "comparacion_e2.csv")


if __name__ == "__main__":
    main()
