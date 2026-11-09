"""Equivalencia de Q4: la versión del E3 (modelo de lectura) devuelve EXACTAMENTE lo mismo que la del E2.

Una optimización que cambia el resultado no es una optimización. Se ejecutan las dos versiones de Q4 (cada una en su
propia sesión, con su propio PREPARE) sobre los mismos parámetros y se comparan fila por fila:
  · los 40 proveedores con más órdenes (caliente), 40 de la cola larga con contrato (frío, 9001..10000)
  · casos borde: 1 (hot), 10 (mes sin órdenes, 2025-06), 2 (contrato vencido), 55555 (sin contrato)
  · 60 proveedores al azar con semilla 42, ventana completa de 24 meses y una ventana parcial
Sale con código 1 si alguna fila difiere.

  python baseline/equivalencia_q4.py --e2 consultas_e2.sql --e3 consultas_e3.sql --salida equivalencia_q4.txt
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "medicion"))
from db import conectar  # noqa: E402
from psycopg import sql  # noqa: E402

VENTANAS = [("2024-09-01", "2026-10-01"), ("2025-03-01", "2025-09-01")]


def sesion(ruta_sql: str):
    conn = conectar()
    with conn.cursor() as cur:
        cur.execute(Path(ruta_sql).read_text(encoding="utf-8"))
    conn.commit()
    return conn


def ejecutar(conn, proveedor, desde, hasta):
    with conn.cursor() as cur:
        # EXECUTE no admite parámetros del protocolo extendido: literales, como hace medicion/queries.py
        cur.execute(sql.SQL("EXECUTE q4({}::int, {}::date, {}::date)").format(
            sql.Literal(proveedor), sql.Literal(desde), sql.Literal(hasta)))
        return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2", required=True)
    ap.add_argument("--e3", required=True)
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()

    c2, c3 = sesion(a.e2), sesion(a.e3)
    with c3.cursor() as cur:
        cur.execute("SELECT proveedor_id FROM ordenes.ordenes_compra GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 40")
        calientes = [p for (p,) in cur.fetchall()]
        cur.execute("SELECT DISTINCT proveedor_id FROM ordenes.ordenes_compra WHERE proveedor_id BETWEEN 9001 AND 10000 "
                    "ORDER BY 1 LIMIT 40")
        frios = [p for (p,) in cur.fetchall()]
    rng = random.Random(42)
    proveedores = list(dict.fromkeys(calientes + frios + [1, 10, 2, 55555] + rng.sample(range(1, 100001), 60)))

    comparaciones = filas = 0
    diferencias = []
    for p in proveedores:
        for desde, hasta in VENTANAS:
            r2, r3 = ejecutar(c2, p, desde, hasta), ejecutar(c3, p, desde, hasta)
            comparaciones += 1
            filas += len(r2)
            if r2 != r3:
                diferencias.append((p, desde, hasta, r2[:3], r3[:3]))
    c2.close()
    c3.close()

    ok = not diferencias
    texto = [f"Equivalencia Q4 (E2 vs E3): {'IDÉNTICA' if ok else 'DIFIERE'}",
             f"{comparaciones} comparaciones ({len(proveedores)} proveedores × {len(VENTANAS)} ventanas), {filas} filas por versión",
             f"Proveedores: 40 calientes, 40 fríos, casos borde 1/10/2/55555 y 60 al azar (semilla 42)"]
    for d in diferencias[:10]:
        texto.append(f"DIFIERE proveedor={d[0]} ventana={d[1]}..{d[2]}\n  E2={d[3]}\n  E3={d[4]}")
    Path(a.salida).write_text("\n".join(texto) + "\n", encoding="utf-8")
    print("\n".join(texto))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
