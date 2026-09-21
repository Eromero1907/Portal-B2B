import psycopg
import time 
import numpy as np
import csv


from datetime import datetime, timezone
from pathlib import Path
from psycopg import sql



CONN_INFO = {
    "host": "localhost",
    "port": 5433,
    "dbname": "portal_b2b",
    "user": "postgres",
    "password": "portal",
}

# (consulta, nombre_prepared, pool_caliente, pool_frio)
CONFIG_CONSULTAS = [
    ("q1", "q1", "P3", "P4"),
    ("q3", "q3", "P6", "P7"),
    ("q2", "q2", "P3_q2", "P4_q2"),
    ("q4", "q4", "P3_q4", "P4_q4"),
]

RAIZ = Path(__file__).resolve().parent.parent  # carpeta Portal-B2B


def conectar():
    conn = psycopg.connect(**CONN_INFO)
    return conn


def preparar_sesion(conn):
    """Carga los PREPARE de consultas.sql y fuerza plan_cache_mode=force_custom_plan."""
    sql = (RAIZ / "datos" / "consultas.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def cargar_pools(conn):
    """Corre los 9 SELECT de parametros.sql y devuelve un dict {P1: [...], P2: [...], ...}."""
    texto = (RAIZ / "datos" / "parametros.sql").read_text(encoding="utf-8")
    bloques = {}
    for parte in texto.split("-- P")[1:]:
        num = parte.split(" ", 1)[0].strip("·").strip()
        select_sql = parte.split("SELECT", 1)[1]
        select_sql = "SELECT" + select_sql.split(";")[0] + ";"
        with conn.cursor() as cur:
            cur.execute(select_sql)
            filas = cur.fetchall()
        bloques[f"P{num}"] = filas
    return bloques

def obtener_skus_proveedor(conn, proveedor_id):
    """Los 20 SKU de un proveedor (cada uno con contrato tiene exactamente 20 ofertas)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT array_agg(sku ORDER BY sku) FROM catalogo.sku_catalogo WHERE proveedor_id = %s",
            (proveedor_id,),
        )
        (skus,) = cur.fetchone()
    return skus

def construir_params_q2(conn, pool_proveedor_fecha):
    """A partir de una lista (proveedor_id, fecha) como P3/P4, arma (proveedor_id, skus_20, fecha)."""
    cache = {}
    resultado = []
    for proveedor_id, fecha in pool_proveedor_fecha:
        if proveedor_id not in cache:
            cache[proveedor_id] = obtener_skus_proveedor(conn, proveedor_id)
        resultado.append((proveedor_id, cache[proveedor_id], fecha))
    return resultado

def construir_params_q4(pool_proveedor_fecha, pool_ventana):
    """A partir de (proveedor_id, fecha) y la ventana fija P9, arma (proveedor_id, desde, hasta).
    La 'fecha' de P3/P4 no se usa aquí -- Q4 siempre mide la ventana completa de 24 meses."""
    desde, hasta = pool_ventana[0]
    return [(proveedor_id, desde, hasta) for proveedor_id, _fecha in pool_proveedor_fecha]

def medir_q5_offset(conn, pool_p8, n=200):
    """Mide q5 con OFFSET. Página 1 = offset 0, repetido n veces con calentamiento propio.
    Página profunda = offset 5000 (proveedor 1), repetido n veces igual."""
    pagina1_params = [(1, 0)] * n
    profunda_params = [(1, 5000)] * n

    res_pagina1 = medir_consulta(conn, "q5", pagina1_params)
    res_profunda = medir_consulta(conn, "q5", profunda_params)
    return res_pagina1, res_profunda

def obtener_cursores_keyset(conn, proveedor_id, num_paginas=100):
    """Devuelve una lista de (fecha_emision, id) -- la última fila de cada página de 50,
    para usarlos como parámetros de q5_keyset."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fecha_emision, id
              FROM ordenes.ordenes_compra
             WHERE proveedor_id = %s
             ORDER BY fecha_emision DESC, id DESC
            """,
            (proveedor_id,),
        )
        filas = cur.fetchall()
    # una fila de cada 50 (el "borde" de cada página), hasta num_paginas
    return [filas[i] for i in range(49, min(len(filas), num_paginas * 50), 50)]


def medir_q5_keyset(conn, proveedor_id=1, n=200):
    cursores = obtener_cursores_keyset(conn, proveedor_id)
    # ciclamos los cursores reales hasta completar n mediciones
    params = [(proveedor_id, *cursores[i % len(cursores)]) for i in range(n)]
    return medir_consulta(conn, "q5_keyset", params)

def medir_una(conn, nombre_prepared, params):
    partes = []
    for p in params:
        if isinstance(p, list):
            # arreglo (ej. los 20 SKU de Q2): ARRAY['SKU-1','SKU-2',...]
            literal_arr = sql.SQL(", ").join(sql.Literal(x) for x in p)
            partes.append(sql.SQL("ARRAY[{}]").format(literal_arr))
        else:
            partes.append(sql.Literal(p))
    args_sql = sql.SQL(", ").join(partes)
    query = sql.SQL("EXECUTE " + nombre_prepared + " ({})").format(args_sql)
    with conn.cursor() as cur:
        ts = datetime.now(timezone.utc)
        t0 = time.perf_counter_ns()
        cur.execute(query)
        filas = cur.fetchall()
        t1 = time.perf_counter_ns()
    latencia_ms = (t1 - t0) / 1_000_000
    return latencia_ms, len(filas), ts

def medir_consulta(conn, nombre_prepared, lista_params, calentamiento=20):
    for _ in range(calentamiento):
        medir_una(conn, nombre_prepared, lista_params[0])

    resultados = []
    for params in lista_params:
        lat_ms, nfilas, ts = medir_una(conn, nombre_prepared, params)
        resultados.append({"params": params, "latencia_ms": lat_ms, "filas": nfilas, "ts_utc": ts})
    return resultados

def calcular_percentiles(resultados, consulta, escenario):
    """Recibe la lista de dicts de medir_consulta() y devuelve un dict con
    p50/p95/p99/min/max en ms, listo para una fila de percentiles.csv."""
    lats = np.array([r["latencia_ms"] for r in resultados])
    return {
        "consulta": consulta,
        "escenario": escenario,
        "n": len(lats),
        "p50_ms": round(float(np.percentile(lats, 50)), 4),
        "p95_ms": round(float(np.percentile(lats, 95)), 4),
        "p99_ms": round(float(np.percentile(lats, 99)), 4),
        "min_ms": round(float(lats.min()), 4),
        "max_ms": round(float(lats.max()), 4),
    }
    
def guardar_mediciones_csv(todas_las_filas, ruta):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        campos = ["consulta", "escenario", "ejecucion", "param_1", "param_2", "param_3", "latencia_ms", "filas", "ts_utc"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(todas_las_filas)


def guardar_percentiles_csv(lista_percentiles, ruta):
    """lista_percentiles: lista de dicts de calcular_percentiles(). Escribe reportes/percentiles.csv."""
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        campos = ["consulta", "escenario", "n", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(lista_percentiles)
    

if __name__ == "__main__":
    conn = conectar()
    print("Conectado:", conn.info.dbname, conn.info.user)
    preparar_sesion(conn)
    pools = cargar_pools(conn)
    pools["P3_q2"] = construir_params_q2(conn, pools["P3"])
    pools["P4_q2"] = construir_params_q2(conn, pools["P4"])
    pools["P3_q4"] = construir_params_q4(pools["P3"], pools["P9"])
    pools["P4_q4"] = construir_params_q4(pools["P4"], pools["P9"])

    todas_mediciones = []
    todos_percentiles = []

    for consulta, nombre_prepared, pool_cal, pool_frio in CONFIG_CONSULTAS:
        for escenario, pool_nombre in [("caliente", pool_cal), ("frio", pool_frio)]:
            print(f"Midiendo {consulta} {escenario} ({len(pools[pool_nombre])} ejecuciones)...")
            resultados = medir_consulta(conn, nombre_prepared, pools[pool_nombre])

            pct = calcular_percentiles(resultados, consulta, escenario)
            todos_percentiles.append(pct)
            print(" ", pct)

            for i, r in enumerate(resultados):
                p = list(r["params"]) + [None, None, None]  # rellena hasta 3
                todas_mediciones.append({
                    "consulta": consulta, "escenario": escenario, "ejecucion": i,
                    "param_1": p[0], "param_2": p[1], "param_3": p[2],
                    "latencia_ms": r["latencia_ms"], "filas": r["filas"],
                    "ts_utc": r["ts_utc"].isoformat(),
                })
                
    # Q5: página 1, página profunda (OFFSET), y keyset
    res_pagina1, res_profunda = medir_q5_offset(conn, pools["P8"])
    res_keyset = medir_q5_keyset(conn)

    for nombre_escenario, resultados in [
        ("pagina1", res_pagina1),
        ("offset5000", res_profunda),
        ("keyset", res_keyset),
    ]:
        pct = calcular_percentiles(resultados, "q5", nombre_escenario)
        todos_percentiles.append(pct)
        print(" ", pct)
        for i, r in enumerate(resultados):
            p = list(r["params"]) + [None, None, None]
            todas_mediciones.append({
                "consulta": "q5", "escenario": nombre_escenario, "ejecucion": i,
                "param_1": p[0], "param_2": p[1], "param_3": p[2],
                "latencia_ms": r["latencia_ms"], "filas": r["filas"],
                "ts_utc": r["ts_utc"].isoformat(),
            })

    guardar_mediciones_csv(todas_mediciones, RAIZ / "reportes" / "mediciones.csv")
    guardar_percentiles_csv(todos_percentiles, RAIZ / "reportes" / "percentiles.csv")
    print("\nGuardado: reportes/mediciones.csv y reportes/percentiles.csv")

    conn.close()