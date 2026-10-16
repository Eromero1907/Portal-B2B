import os
import sys
import csv
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict


sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import conectar, RAIZ

COLS_ORDENES = "id,numero_orden,proveedor_id,franja_id,fecha_emision,estado,total_orden,idempotency_key,created_at,fecha_compromiso,fecha_entrega"
COLS_LINEAS = "id,orden_id,sku_id,cantidad,precio_unitario,subtotal,cantidad_entregada"
COLS_LINEA_INSERT = "id,orden_id,sku_id,cantidad,precio_unitario,subtotal,cantidad_entregada"

# Variante de E4 para la palanca P8; por defecto E4 es idéntico al del E2 (una consulta por línea).
VARIANTE_LOTE = os.environ.get("E4_VARIANTE", "") == "lote"


def agrupar_lineas_por_orden(lineas):
    por_orden = defaultdict(list)
    for l in lineas:
        por_orden[l["orden_id"]].append(l)
    return por_orden

def reset_bench(conn):
    """Vacía ordenes_compra y lineas_orden de bench; franjas_cedi se deja intacta
    (E4 la necesita con su estado real de capacidad)."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench.lineas_orden, bench.ordenes_compra;")
    conn.commit()


def leer_csv_ordenes():
    """Lee el subconjunto de órdenes, devuelve lista de tuplas en el orden de columnas
    del CSV original (ver CONTRATO_DATOS.md para el orden real de columnas)."""
    ruta = RAIZ / "datos" / "csv" / "subset_ordenes.csv"
    with open(ruta, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def leer_csv_lineas():
    ruta = RAIZ / "datos" / "csv" / "subset_lineas.csv"
    with open(ruta, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)
    

def copy_tabla(conn, tabla, columnas, filas_dict):
    """COPY genérico: filas_dict es una lista de dicts (salida de csv.DictReader).
    Convierte '' a None (NULL) para las columnas que lo permiten (fecha_entrega, cantidad_entregada)."""
    cols_lista = columnas.split(",")
    with conn.cursor() as cur:
        with cur.copy(f"COPY {tabla} ({columnas}) FROM STDIN") as copy:
            for fila in filas_dict:
                valores = [fila[c] if fila[c] != "" else None for c in cols_lista]
                copy.write_row(valores)
    conn.commit()


def medir_e1a_copy_con_indices(conn, ordenes, lineas):
    reset_bench(conn)
    t0 = time.perf_counter()
    copy_tabla(conn, "bench.ordenes_compra", COLS_ORDENES, ordenes)
    copy_tabla(conn, "bench.lineas_orden", COLS_LINEAS, lineas)
    t1 = time.perf_counter()
    return t1 - t0

def medir_e1b_copy_sin_indices(conn, ordenes, lineas):
    """Igual que E1a, pero contra las tablas _sinidx (sin PK ni índices secundarios) --
    el 'piso teórico': lo que hace cargar.sh antes de la fase de restricciones/índices."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench.lineas_orden_sinidx, bench.ordenes_compra_sinidx;")
    conn.commit()

    t0 = time.perf_counter()
    copy_tabla(conn, "bench.ordenes_compra_sinidx", COLS_ORDENES, ordenes)
    copy_tabla(conn, "bench.lineas_orden_sinidx", COLS_LINEAS, lineas)
    t1 = time.perf_counter()
    return t1 - t0


def medir_e2_lotes(conn, ordenes, lineas, tam_lote=1000):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench.lineas_orden, bench.ordenes_compra;")
    conn.commit()

    t0 = time.perf_counter()
    _insertar_por_lotes(conn, "bench.ordenes_compra", COLS_ORDENES, ordenes, tam_lote)
    _insertar_por_lotes(conn, "bench.lineas_orden", COLS_LINEAS, lineas, tam_lote)
    t1 = time.perf_counter()
    return t1 - t0


def _insertar_por_lotes(conn, tabla, columnas, filas_dict, tam_lote):
    cols_lista = columnas.split(",")
    placeholders = "(" + ", ".join(["%s"] * len(cols_lista)) + ")"
    sql_insert = f"INSERT INTO {tabla} ({columnas}) VALUES "

    with conn.cursor() as cur:
        for i in range(0, len(filas_dict), tam_lote):
            lote = filas_dict[i : i + tam_lote]
            valores_lote = []
            placeholders_lote = []
            for fila in lote:
                valores_lote.extend(fila[c] if fila[c] != "" else None for c in cols_lista)
                placeholders_lote.append(placeholders)
            query = sql_insert + ", ".join(placeholders_lote)
            cur.execute(query, valores_lote)
            conn.commit()  # una transacción POR LOTE, tal como pide la guía
            
def medir_e3_fila_por_fila(conn, ordenes, lineas, limite_filas=None):
    """INSERT de una fila por sentencia, autocommit=True (cada fila es su propia transacción).
    limite_filas: si se pasa, mide solo esa porción (para no esperar minutos) y lo declara."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench.lineas_orden, bench.ordenes_compra;")
    conn.commit()

    conn.autocommit = True  # cada INSERT hace su propio commit inmediato

    if limite_filas:
        # proporción: recorta ordenes y lineas manteniendo la relación orden_id
        ids_incluidos = {o["id"] for o in ordenes[:limite_filas]}
        ordenes_medir = ordenes[:limite_filas]
        lineas_medir = [l for l in lineas if l["orden_id"] in ids_incluidos]
    else:
        ordenes_medir = ordenes
        lineas_medir = lineas

    t0 = time.perf_counter()
    _insertar_fila_por_fila(conn, "bench.ordenes_compra", COLS_ORDENES, ordenes_medir)
    _insertar_fila_por_fila(conn, "bench.lineas_orden", COLS_LINEAS, lineas_medir)
    t1 = time.perf_counter()

    conn.autocommit = False  # regresar al modo normal para las siguientes estrategias
    return t1 - t0, len(ordenes_medir) + len(lineas_medir)


def _insertar_fila_por_fila(conn, tabla, columnas, filas_dict):
    cols_lista = columnas.split(",")
    placeholders = "(" + ", ".join(["%s"] * len(cols_lista)) + ")"
    query = f"INSERT INTO {tabla} ({columnas}) VALUES {placeholders}"
    with conn.cursor() as cur:
        for fila in filas_dict:
            valores = [fila[c] if fila[c] != "" else None for c in cols_lista]
            cur.execute(query, valores)
            
def procesar_orden_e4(conn, orden, lineas_orden):
    """Los 5 pasos de la ruta transaccional, en UNA transacción por orden.
    Devuelve (aceptada: bool, motivo: str)."""
    proveedor_id = int(orden["proveedor_id"])
    franja_id = int(orden["franja_id"])
    fecha = orden["fecha_emision"][:10]  # solo la parte de fecha

    with conn.cursor() as cur:
        # Paso 1 -- RN-01/02: proveedor ACTIVO y contrato vigente en la fecha
        cur.execute(
            """
            SELECT c.id
              FROM proveedores.proveedores p
              LEFT JOIN proveedores.contratos_suministro c
                     ON c.proveedor_id = p.id AND c.estado = 'VIGENTE'
                    AND c.fecha_inicio <= %s AND c.fecha_fin >= %s
             WHERE p.id = %s AND p.estado = 'ACTIVO'
            """,
            (fecha, fecha, proveedor_id),
        )
        fila = cur.fetchone()
        if fila is None or fila[0] is None:
            conn.rollback()
            return False, "sin_proveedor_o_contrato"

        # Paso 2 -- RN-03/04/05: cada SKU debe ser oferta vigente del proveedor, precio correcto
        if VARIANTE_LOTE:
            # Palanca P8 (baseline/palancas.md): una sola consulta por orden (unnest) en vez de una por línea.
            # Misma regla: la orden es válida si TODAS sus líneas casan con una oferta vigente al precio negociado.
            if lineas_orden:
                cur.execute(
                    """
                    SELECT count(*)
                      FROM unnest(%s::bigint[], %s::numeric[]) AS l(sku_id, precio)
                      JOIN catalogo.sku_catalogo s ON s.id = l.sku_id AND s.proveedor_id = %s
                       AND s.vigencia_desde <= %s AND s.vigencia_hasta >= %s
                       AND s.precio_negociado = l.precio
                    """,
                    ([int(l["sku_id"]) for l in lineas_orden], [l["precio_unitario"] for l in lineas_orden],
                     proveedor_id, fecha, fecha),
                )
                if cur.fetchone()[0] != len(lineas_orden):
                    conn.rollback()
                    return False, "sku_invalido_o_precio"
        for linea in ([] if VARIANTE_LOTE else lineas_orden):
            cur.execute(
                """
                SELECT 1 FROM catalogo.sku_catalogo
                 WHERE id = %s AND proveedor_id = %s
                   AND vigencia_desde <= %s AND vigencia_hasta >= %s
                   AND precio_negociado = %s
                """,
                (int(linea["sku_id"]), proveedor_id, fecha, fecha, linea["precio_unitario"]),
            )
            if cur.fetchone() is None:
                conn.rollback()
                return False, "sku_invalido_o_precio"

        # Paso 3 -- RN-07/08: reservar franja, atómico y condicional
        cur.execute(
            "UPDATE bench.franjas_cedi SET capacidad_reservada = capacidad_reservada + 1 "
            "WHERE id = %s AND capacidad_reservada < capacidad_total",
            (franja_id,),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False, "sin_cupo_franja"

        # Paso 4 -- insertar orden (estado forzado a CONFIRMADA) y sus líneas
        valores_orden = [
            orden["id"], orden["numero_orden"], proveedor_id, franja_id,
            orden["fecha_emision"], "CONFIRMADA", orden["total_orden"],
            orden["idempotency_key"], orden["created_at"],
            orden["fecha_compromiso"], orden["fecha_entrega"] or None,
        ]
        cur.execute(
            f"INSERT INTO bench.ordenes_compra ({COLS_ORDENES}) VALUES ({','.join(['%s']*11)})",
            valores_orden,
        )
        valores_lineas = [
            [l["id"], l["orden_id"], l["sku_id"], l["cantidad"],
             l["precio_unitario"], l["subtotal"], l["cantidad_entregada"] or None]
            for l in lineas_orden
        ]
        sql_linea = f"INSERT INTO bench.lineas_orden ({COLS_LINEA_INSERT}) VALUES ({','.join(['%s']*7)})"
        if VARIANTE_LOTE:
            # P8: todas las líneas de la orden en un solo viaje (executemany usa modo pipeline en psycopg 3.2)
            if valores_lineas:
                cur.executemany(sql_linea, valores_lineas)
        else:
            for valores_linea in valores_lineas:
                cur.execute(sql_linea, valores_linea)

    # Paso 5 -- COMMIT
    conn.commit()
    return True, "confirmada"

def medir_e4_transaccional(conn, ordenes, lineas, limite_filas=None):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench.lineas_orden, bench.ordenes_compra;")
        cur.execute("UPDATE bench.franjas_cedi SET capacidad_reservada = 0;")  # reset del recurso escaso
    conn.commit()

    lineas_por_orden = agrupar_lineas_por_orden(lineas)
    ordenes_medir = ordenes[:limite_filas] if limite_filas else ordenes

    contador_motivos = defaultdict(int)
    n_aceptadas = 0
    n_filas_insertadas = 0

    t0 = time.perf_counter()
    for orden in ordenes_medir:
        lineas_orden = lineas_por_orden.get(orden["id"], [])
        aceptada, motivo = procesar_orden_e4(conn, orden, lineas_orden)
        contador_motivos[motivo] += 1
        if aceptada:
            n_aceptadas += 1
            n_filas_insertadas += 1 + len(lineas_orden)
    t1 = time.perf_counter()

    duracion = t1 - t0
    return {
        "duracion_s": duracion,
        "ordenes_procesadas": len(ordenes_medir),
        "ordenes_aceptadas": n_aceptadas,
        "filas_insertadas": n_filas_insertadas,
        "ordenes_por_s": len(ordenes_medir) / duracion,
        "filas_por_s": n_filas_insertadas / duracion if n_filas_insertadas else 0,
        "motivos_rechazo": dict(contador_motivos),
    }

if __name__ == "__main__":
    conn = conectar()
    print("Conectado:", conn.info.dbname, conn.info.user)

    ordenes = leer_csv_ordenes()
    lineas = leer_csv_lineas()
    print(f"Leídas {len(ordenes)} órdenes, {len(lineas)} líneas del subconjunto S")
    total_filas = len(ordenes) + len(lineas)

    dur_a = medir_e1a_copy_con_indices(conn, ordenes, lineas)
    print(f"E1a COPY con índices:  {total_filas} filas en {dur_a:.3f} s = {total_filas/dur_a:.0f} filas/s")

    dur_b = medir_e1b_copy_sin_indices(conn, ordenes, lineas)
    print(f"E1b COPY sin índices:  {total_filas} filas en {dur_b:.3f} s = {total_filas/dur_b:.0f} filas/s")
    
    dur_e2 = medir_e2_lotes(conn, ordenes, lineas)
    print(f"E2 Lotes de 1000:      {total_filas} filas en {dur_e2:.3f} s = {total_filas/dur_e2:.0f} filas/s")
    
    dur_e3, n_e3 = medir_e3_fila_por_fila(conn, ordenes, lineas, limite_filas=5000)
    print(f"E3 Fila a fila (muestra 5000 órdenes): {n_e3} filas en {dur_e3:.3f} s = {n_e3/dur_e3:.0f} filas/s")
    
    resultado_e4 = medir_e4_transaccional(conn, ordenes, lineas, limite_filas=None)
    print(f"E4 Ruta transaccional (50000 órdenes completas): {resultado_e4}")

    conn.close()