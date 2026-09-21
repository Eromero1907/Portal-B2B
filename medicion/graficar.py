import csv
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "datos" / "resultados"
SALIDA = RAIZ / "reportes" / "graficas"
SALIDA.mkdir(parents=True, exist_ok=True)


def graficar_zipf():
    rangos, ordenes, acumulado = [], [], []
    with open(RESULTADOS / "zipf_proveedores.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            rangos.append(int(fila["rango"]))
            ordenes.append(int(fila["ordenes"]))
            acumulado.append(float(fila["acumulado_pct"]))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.loglog(rangos, ordenes, marker=".", linestyle="none", markersize=3)
    ax1.set_xlabel("Rango del proveedor (log)")
    ax1.set_ylabel("Órdenes (log)")
    ax1.set_title("Distribución Zipf-Mandelbrot (s=1.15, q=1940)")
    ax1.grid(True, which="both", alpha=0.3)

    ax2.plot(rangos, acumulado)
    ax2.axhline(15.34, color="gray", linestyle="--", alpha=0.5, label="Top 1% = 15.34%")
    ax2.axhline(40.84, color="gray", linestyle=":", alpha=0.5, label="Top 5% = 40.84%")
    ax2.set_xlabel("Rango del proveedor")
    ax2.set_ylabel("% acumulado de órdenes")
    ax2.set_title("Concentración acumulada de la demanda")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    fig.suptitle("Sesgo Zipf en proveedores — 100 000 proveedores, 300 000 órdenes")
    fig.tight_layout()
    fig.savefig(SALIDA / "zipf.png", dpi=150)
    plt.close(fig)
    print("Guardado: zipf.png")


def graficar_ordenes_por_dia():
    fechas, ordenes, marcados = [], [], []
    with open(RESULTADOS / "ordenes_por_dia.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            fechas.append(datetime.strptime(fila["fecha"], "%Y-%m-%d"))
            ordenes.append(int(fila["ordenes"]))
            marcados.append(fila["es_ultimo_3_habiles_mes"] == "1")

    fechas, ordenes, marcados = fechas[-60:], ordenes[-60:], marcados[-60:]
    colores = ["#d62728" if m else "#1f77b4" for m in marcados]

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.bar(fechas, ordenes, color=colores, width=0.8)
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Órdenes")
    ax.set_title("Órdenes por día — últimos 60 días (rojo = últimos 3 días hábiles del mes)")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    fig.autofmt_xdate()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(SALIDA / "ordenes_por_dia.png", dpi=150)
    plt.close(fig)
    print("Guardado: ordenes_por_dia.png")


def graficar_ordenes_por_hora():
    horas, ordenes = [], []
    with open(RESULTADOS / "ordenes_por_hora.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            horas.append(int(fila["hora_utc"]))
            ordenes.append(int(fila["ordenes"]))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(horas, ordenes, color="#2ca02c")
    ax.set_xlabel("Hora UTC")
    ax.set_ylabel("Órdenes")
    ax.set_title("Estacionalidad horaria — pico 08:00-10:59, valle 22:00-05:59")
    ax.set_xticks(range(0, 24))
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(SALIDA / "ordenes_por_hora.png", dpi=150)
    plt.close(fig)
    print("Guardado: ordenes_por_hora.png")


if __name__ == "__main__":
    graficar_zipf()
    graficar_ordenes_por_dia()
    graficar_ordenes_por_hora()