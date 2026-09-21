import time
from datetime import datetime, timezone
from psycopg import sql


def medir_una(conn, nombre_prepared, params):
    partes = []
    for p in params:
        if isinstance(p, list):
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
    """Mide q5 con OFFSET. Página 1 = offset 0, repetido n veces.
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
    return [filas[i] for i in range(49, min(len(filas), num_paginas * 50), 50)]


def medir_q5_keyset(conn, proveedor_id=1, n=200):
    cursores = obtener_cursores_keyset(conn, proveedor_id)
    params = [(proveedor_id, *cursores[i % len(cursores)]) for i in range(n)]
    return medir_consulta(conn, "q5_keyset", params)