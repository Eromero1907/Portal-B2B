"""A/B de la palanca P8 sobre E4 (ruta transaccional): control (una consulta por línea) frente a variante `lote`
(una consulta por orden con unnest + executemany en modo pipeline). Misma base, mismo subconjunto S, mismo cliente.
Alterna control/variante para que la deriva del equipo afecte a ambas por igual.

  python baseline/e4_ab.py --salida baseline/corridas/meta-P8 [--limite 10000] [--n 3]
"""
import argparse, csv, statistics, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "medicion")); sys.path.insert(0, str(RAIZ / "baseline"))
import benchmark_carga as b  # noqa: E402
import estrategias as est  # noqa: E402
from db import conectar  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", required=True)
    ap.add_argument("--limite", type=int, default=10000)
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.salida); out.mkdir(parents=True, exist_ok=True)
    est.preparar_subconjunto()
    conn = conectar()
    with conn.cursor() as cur:
        cur.execute(est.SQL_BENCH)
    conn.commit()
    ordenes, lineas = b.leer_csv_ordenes(), b.leer_csv_lineas()
    filas = []
    for k in range(1, a.n + 1):
        orden_rep = (("control", False), ("lote", True)) if k % 2 else (("lote", True), ("control", False))
        for nombre, lote in orden_rep:
            b.VARIANTE_LOTE = lote
            r = b.medir_e4_transaccional(conn, ordenes, lineas, limite_filas=a.limite)
            filas.append({"rep": k, "variante": nombre, "ordenes": r["ordenes_procesadas"], "aceptadas": r["ordenes_aceptadas"],
                          "filas_insertadas": r["filas_insertadas"], "segundos": round(r["duracion_s"], 3),
                          "ordenes_por_s": round(r["ordenes_por_s"], 1), "filas_por_s": round(r["filas_por_s"])})
            print(filas[-1], flush=True)
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA bench CASCADE")
    conn.commit(); conn.close()
    with open(out / "e4_ab.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
    c = [r["segundos"] for r in filas if r["variante"] == "control"]; v = [r["segundos"] for r in filas if r["variante"] == "lote"]
    mc, mv = statistics.median(c), statistics.median(v)
    ac = [r for r in filas if r["variante"] == "control"][0]; av = [r for r in filas if r["variante"] == "lote"][0]
    rango = (max(c) - min(c)) / mc * 100
    txt = (f"E4 sobre las primeras {a.limite} órdenes, {a.n} repeticiones alternadas\n"
           f"control: mediana {mc:.2f} s (min {min(c):.2f}, max {max(c):.2f}; rango {rango:.1f} %)\n"
           f"lote   : mediana {mv:.2f} s (min {min(v):.2f}, max {max(v):.2f})\n"
           f"cambio : {100*(mv-mc)/mc:+.1f} % en tiempo  (meta ≤ −10 %; ruido ±{rango:.1f} %)\n"
           f"equivalencia: aceptadas control={ac['aceptadas']} lote={av['aceptadas']}; filas insertadas {ac['filas_insertadas']} vs {av['filas_insertadas']}\n")
    (out / "resumen.txt").write_text(txt, encoding="utf-8"); print(txt)


if __name__ == "__main__":
    main()
