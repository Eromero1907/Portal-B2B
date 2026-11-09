"""Figura de la tabla E2 vs E3 (rúbrica final, criterio 4): una fila por consulta y escenario, p50/p95/p99.

Lee baseline/corridas/<id>/tabla_e2_e3.csv (de baseline/tabla_e2_e3.py) y dibuja, en escala logarítmica, el estado E2
medido hoy (gris, con su rango entre rondas), el estado E3 final (azul, con su rango) y el valor del informe del E2 (marca).

  .venv/Scripts/python.exe baseline/grafica_e2_e3.py --corrida baseline/corridas/ab-e2-e3-maquina-jj \
      --salida "Entrega 3/evidencia/resumen_graficas/e2_vs_e3_consultas.png"
"""
import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

NOMBRES = {"q1": "Q1 proveedor+contrato", "q2": "Q2 precio 20 SKU", "q3": "Q3 franjas con cupo",
           "q4": "Q4 OTIF y fill rate", "q5": "Q5 últimas 50 órdenes"}
GRIS, AZUL, TINTA, TENUE, FONDO = "#8a94a6", "#2f7fd8", "#1d2433", "#6b7385", "#ffffff"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corrida", required=True)
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    filas = list(csv.DictReader(open(Path(a.corrida) / "tabla_e2_e3.csv", encoding="utf-8")))
    grupos = []
    for f in filas:
        k = (f["consulta"], f["escenario"])
        if k not in grupos:
            grupos.append(k)

    fig, ejes = plt.subplots(1, 3, figsize=(15, 6.2), sharey=True, facecolor=FONDO)
    for eje, m in zip(ejes, ("p50", "p95", "p99")):
        eje.set_facecolor(FONDO)
        for i, g in enumerate(grupos):
            f = next(x for x in filas if (x["consulta"], x["escenario"]) == g and x["metrica"] == m)
            y = len(grupos) - 1 - i
            hoy, fin, inf = float(f["e2_hoy_ms"]), float(f["e3_final_ms"]), float(f["e2_informe_ms"])
            eje.plot([float(f["e2_hoy_min"]), float(f["e2_hoy_max"])], [y + 0.14] * 2, color=GRIS, lw=2, alpha=.45,
                     solid_capstyle="round")
            eje.plot([float(f["e3_min"]), float(f["e3_max"])], [y - 0.14] * 2, color=AZUL, lw=2, alpha=.45,
                     solid_capstyle="round")
            eje.scatter([hoy], [y + 0.14], s=46, color=GRIS, zorder=3, edgecolor=FONDO, linewidth=1.5)
            eje.scatter([fin], [y - 0.14], s=46, color=AZUL, zorder=3, edgecolor=FONDO, linewidth=1.5)
            eje.scatter([inf], [y], s=60, marker="|", color=TINTA, zorder=3, linewidth=1.6)
            if f["mejora_atribuible"] == "SÍ":
                eje.annotate(f"{float(f['cambio_vs_e2_hoy_pct']):+.0f} %".replace(".", ","), (fin, y - 0.14),
                             xytext=(-8, -2), textcoords="offset points", ha="right", va="center", fontsize=9,
                             color=TINTA, fontweight="bold")
        eje.set_xscale("log")
        eje.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}".replace(".", ",")))
        eje.xaxis.set_minor_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: f"{v:g}".replace(".", ",") if f"{v:g}"[0] in "25" else ""))
        eje.set_title(m, fontsize=12, color=TINTA, loc="left", fontweight="bold")
        eje.grid(axis="x", color="#e6e9ef", lw=.8)
        eje.tick_params(colors=TENUE, labelsize=9)
        for s in ("top", "right", "left"):
            eje.spines[s].set_visible(False)
        eje.spines["bottom"].set_color("#c9ced8")
        eje.set_xlabel("ms (escala log, latencia del cliente)", color=TENUE, fontsize=9)
    ejes[0].set_yticks(range(len(grupos)))
    ejes[0].set_yticklabels([f"{NOMBRES[c]} · {e}" for c, e in reversed(grupos)], color=TINTA, fontsize=10)
    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([], [], marker="o", ls="-", color=GRIS, label="Estado E2 medido hoy (mediana y rango, 5 rondas)"),
                        Line2D([], [], marker="o", ls="-", color=AZUL, label="Estado E3 final (mediana y rango, 5 rondas)"),
                        Line2D([], [], marker="|", ls="", color=TINTA, markersize=10, label="Valor del informe del E2")],
               loc="upper center", ncol=3, frameon=False, fontsize=10, bbox_to_anchor=(.5, .955))
    fig.suptitle("Q1–Q5: E2 vs E3 en la misma máquina, rondas intercaladas (porcentaje = mejora atribuible frente a E2 hoy)",
                 fontsize=13, color=TINTA, y=.995)
    fig.tight_layout(rect=(0, 0, 1, .92))
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.salida, dpi=150, facecolor=FONDO)
    print(f"Guardado en {a.salida}")


if __name__ == "__main__":
    main()
