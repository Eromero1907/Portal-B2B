from db import conectar, preparar_sesion, cargar_pools, RAIZ
from queries import (
    medir_consulta, construir_params_q2, construir_params_q4,
    medir_q5_offset, medir_q5_keyset,
)
from stats import calcular_percentiles
from reportes_io import guardar_mediciones_csv, guardar_percentiles_csv

# (consulta, nombre_prepared, pool_caliente, pool_frio)
CONFIG_CONSULTAS = [
    ("q1", "q1", "P3", "P4"),
    ("q3", "q3", "P6", "P7"),
    ("q2", "q2", "P3_q2", "P4_q2"),
    ("q4", "q4", "P3_q4", "P4_q4"),
]


def agregar_resultado(todas_mediciones, todos_percentiles, consulta, escenario, resultados):
    pct = calcular_percentiles(resultados, consulta, escenario)
    todos_percentiles.append(pct)
    print(" ", pct)
    for i, r in enumerate(resultados):
        p = list(r["params"]) + [None, None, None]
        todas_mediciones.append({
            "consulta": consulta, "escenario": escenario, "ejecucion": i,
            "param_1": p[0], "param_2": p[1], "param_3": p[2],
            "latencia_ms": r["latencia_ms"], "filas": r["filas"],
            "ts_utc": r["ts_utc"].isoformat(),
        })


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
            agregar_resultado(todas_mediciones, todos_percentiles, consulta, escenario, resultados)

    print("Midiendo q5 pagina1 / offset5000 (200 c/u)...")
    res_pagina1, res_profunda = medir_q5_offset(conn, pools["P8"])
    agregar_resultado(todas_mediciones, todos_percentiles, "q5", "pagina1", res_pagina1)
    agregar_resultado(todas_mediciones, todos_percentiles, "q5", "offset5000", res_profunda)

    print("Midiendo q5 keyset (200)...")
    res_keyset = medir_q5_keyset(conn)
    agregar_resultado(todas_mediciones, todos_percentiles, "q5", "keyset", res_keyset)

    guardar_mediciones_csv(todas_mediciones, RAIZ / "reportes" / "mediciones.csv")
    guardar_percentiles_csv(todos_percentiles, RAIZ / "reportes" / "percentiles.csv")
    print("\nGuardado: reportes/mediciones.csv y reportes/percentiles.csv")

    conn.close()