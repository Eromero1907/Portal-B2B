"""Re-ejecuta el benchmark de estrategias de inyección del E2 (E1a, E1b, E2, E3, E4) de forma reproducible.

En el E2 el subconjunto S y el esquema `bench` se preparaban a mano (guía sando.md, 2.2). Aquí se preparan solos
y el resultado queda en un CSV (el E2 solo lo imprimía). Usa SIN CAMBIOS las funciones de medicion/benchmark_carga.py,
para que la condición sea la misma del E2: mismo subconjunto S (órdenes 1..50 000 y sus líneas = 375 199 filas),
mismo cliente (psycopg desde el host), misma muestra de E3 (5 000 órdenes) y E4 completo (50 000 órdenes).

  python baseline/estrategias.py --salida baseline/corridas/<id>
"""
import argparse
import csv
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "medicion"))
import benchmark_carga as b  # noqa: E402
from db import conectar  # noqa: E402

N_ORDENES_S = 50_000

SQL_BENCH = """
DROP SCHEMA IF EXISTS bench CASCADE;
CREATE SCHEMA bench;
CREATE TABLE bench.ordenes_compra (LIKE ordenes.ordenes_compra INCLUDING ALL);
CREATE TABLE bench.lineas_orden   (LIKE ordenes.lineas_orden   INCLUDING ALL);
CREATE TABLE bench.franjas_cedi   (LIKE logistica.franjas_cedi INCLUDING ALL);
ALTER TABLE bench.ordenes_compra SET (fillfactor = 90);
ALTER TABLE bench.franjas_cedi   SET (fillfactor = 80);
-- E1b: mismas columnas, sin PK ni índices (lo que carga cargar.sh antes de crear restricciones e índices)
CREATE TABLE bench.ordenes_compra_sinidx (LIKE ordenes.ordenes_compra);
CREATE TABLE bench.lineas_orden_sinidx   (LIKE ordenes.lineas_orden);
INSERT INTO bench.franjas_cedi SELECT * FROM logistica.franjas_cedi WHERE fecha < DATE '2026-09-17';
"""


def preparar_subconjunto():
    """datos/csv/subset_*.csv: las órdenes 1..50 000 y sus líneas (prefijo contiguo de los CSV del E2)."""
    csv_dir = RAIZ / "datos" / "csv"
    with open(csv_dir / "ordenes_compra.csv", encoding="utf-8") as fo, \
         open(csv_dir / "subset_ordenes.csv", "w", encoding="utf-8", newline="") as so:
        for i, linea in enumerate(fo):
            if i > N_ORDENES_S:
                break
            so.write(linea)
    with open(csv_dir / "lineas_orden.csv", encoding="utf-8") as fl, \
         open(csv_dir / "subset_lineas.csv", "w", encoding="utf-8", newline="") as sl:
        for i, linea in enumerate(fl):
            if i == 0 or int(linea.split(",", 2)[1]) <= N_ORDENES_S:
                sl.write(linea)
            elif i > 0:
                break  # las líneas vienen ordenadas por orden_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    preparar_subconjunto()
    conn = conectar()
    with conn.cursor() as cur:
        cur.execute(SQL_BENCH)
    conn.commit()

    ordenes = b.leer_csv_ordenes()
    lineas = b.leer_csv_lineas()
    total = len(ordenes) + len(lineas)
    print(f"Subconjunto S: {len(ordenes)} órdenes + {len(lineas)} líneas = {total} filas", flush=True)

    filas = []

    def registrar(estrategia, descripcion, n_filas, segundos, extra=""):
        filas.append({"estrategia": estrategia, "descripcion": descripcion, "filas": n_filas,
                      "segundos": round(segundos, 3), "filas_por_s": round(n_filas / segundos) if segundos else 0,
                      "detalle": extra})
        print(f"{estrategia:<4} {descripcion:<24} {n_filas:>8} filas en {segundos:8.3f} s = "
              f"{n_filas / segundos:>9.0f} filas/s {extra}", flush=True)

    registrar("E1a", "COPY con índices", total, b.medir_e1a_copy_con_indices(conn, ordenes, lineas))
    registrar("E1b", "COPY sin índices", total, b.medir_e1b_copy_sin_indices(conn, ordenes, lineas))
    registrar("E2", "Lotes de 1000", total, b.medir_e2_lotes(conn, ordenes, lineas))
    dur, n = b.medir_e3_fila_por_fila(conn, ordenes, lineas, limite_filas=5000)
    registrar("E3", "Fila a fila (muestra)", n, dur, "muestra de 5000 órdenes")
    e4 = b.medir_e4_transaccional(conn, ordenes, lineas, limite_filas=None)
    registrar("E4", "Ruta transaccional", e4["filas_insertadas"], e4["duracion_s"],
              f"aceptadas={e4['ordenes_aceptadas']}/{e4['ordenes_procesadas']} motivos={e4['motivos_rechazo']}")

    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA bench CASCADE")
    conn.commit()
    conn.close()

    with open(salida / "estrategias.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["estrategia", "descripcion", "filas", "segundos", "filas_por_s", "detalle"])
        w.writeheader()
        w.writerows(filas)
    print(f"Guardado {salida / 'estrategias.csv'}  ({time.strftime('%H:%M:%S')})")


if __name__ == "__main__":
    main()
