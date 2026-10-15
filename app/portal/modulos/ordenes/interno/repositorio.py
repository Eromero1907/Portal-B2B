"""SQL del módulo Órdenes. Solo toca el esquema `ordenes` (órdenes, líneas, idempotencia y outbox)."""
from datetime import date, datetime
from decimal import Decimal

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

# ---------------------------------------------------------------------------
# Órdenes y líneas
# ---------------------------------------------------------------------------
_SQL_CREAR_ORDEN = """
WITH nueva AS (SELECT nextval('ordenes.ordenes_compra_id_seq')::int AS id)
INSERT INTO ordenes.ordenes_compra
       (id, numero_orden, proveedor_id, franja_id, fecha_compromiso, fecha_entrega,
        fecha_emision, created_at, total_orden, estado, idempotency_key)
SELECT id, 'OC-E3-' || lpad(id::text, 9, '0'), %(proveedor_id)s, %(franja_id)s, %(fecha_compromiso)s, NULL,
       %(fecha_emision)s, now(), %(total)s, 'EN_PROCESO', %(clave)s
  FROM nueva
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id, numero_orden
"""

_SQL_ORDEN_POR_CLAVE = "SELECT id, numero_orden FROM ordenes.ordenes_compra WHERE idempotency_key = %(clave)s"

_SQL_CREAR_LINEAS = """
INSERT INTO ordenes.lineas_orden (id, orden_id, sku_id, cantidad, precio_unitario, subtotal)
SELECT nextval('ordenes.lineas_orden_id_seq'), %(orden_id)s, l.sku_id, l.cantidad, l.precio, l.cantidad * l.precio
  FROM unnest(%(skus)s::int[], %(cantidades)s::int[], %(precios)s::numeric[]) AS l(sku_id, cantidad, precio)
"""

_SQL_ORDEN_PARA_CONFIRMAR = """
SELECT id, proveedor_id, franja_id, estado, fecha_emision, total_orden
  FROM ordenes.ordenes_compra
 WHERE id = %(orden_id)s
   FOR UPDATE
"""

_SQL_LINEAS = "SELECT sku_id, precio_unitario FROM ordenes.lineas_orden WHERE orden_id = %(orden_id)s ORDER BY id"

_SQL_CONSULTAR = """
SELECT id, numero_orden, proveedor_id, franja_id, estado, fecha_emision, fecha_compromiso, total_orden
  FROM ordenes.ordenes_compra
 WHERE id = %(orden_id)s
"""

_SQL_CAMBIAR_ESTADO = """
UPDATE ordenes.ordenes_compra
   SET estado = %(estado)s
 WHERE id = %(orden_id)s AND estado = 'EN_PROCESO'
"""

# ---------------------------------------------------------------------------
# Idempotencia de la confirmación (RN-13)
# ---------------------------------------------------------------------------
_SQL_IDEM_TOMAR = """
INSERT INTO ordenes.idempotencia (clave, orden_id, estado)
VALUES (%(clave)s, %(orden_id)s, 'EN_CURSO')
ON CONFLICT (clave) DO NOTHING
RETURNING clave
"""

_SQL_IDEM_LEER = """
SELECT orden_id, estado, codigo_http, respuesta,
       actualizado_en < now() - make_interval(secs => %(abandono_s)s::double precision) AS abandonada
  FROM ordenes.idempotencia
 WHERE clave = %(clave)s
   FOR UPDATE
"""

_SQL_IDEM_RETOMAR = "UPDATE ordenes.idempotencia SET actualizado_en = now() WHERE clave = %(clave)s"

_SQL_IDEM_COMPLETAR = """
UPDATE ordenes.idempotencia
   SET estado = 'COMPLETADA', codigo_http = %(codigo)s, respuesta = %(respuesta)s, actualizado_en = now()
 WHERE clave = %(clave)s
"""

_SQL_IDEM_BORRAR = "DELETE FROM ordenes.idempotencia WHERE clave = %(clave)s AND estado = 'EN_CURSO'"

# ---------------------------------------------------------------------------
# Outbox (ADR-005)
# ---------------------------------------------------------------------------
_SQL_OUTBOX = """
INSERT INTO ordenes.outbox (evento_id, tipo, agregado_id, payload)
VALUES (%(evento_id)s, %(tipo)s, %(agregado_id)s, %(payload)s)
"""


async def _una(conn: AsyncConnection, sql: str, params: dict):
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def _ejecutar(conn: AsyncConnection, sql: str, params: dict) -> int:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        return cur.rowcount


async def crear_orden(conn: AsyncConnection, *, proveedor_id: int, franja_id: int, fecha_compromiso: date,
                      fecha_emision: datetime, clave: str, lineas: list[tuple[int, int, Decimal]]):
    """Inserta la orden EN_PROCESO y sus líneas. Devuelve (id, numero_orden, creada: bool).
    Si la clave de creación ya existe, devuelve la orden existente (creación idempotente)."""
    total = sum(Decimal(c) * p for _, c, p in lineas)
    fila = await _una(conn, _SQL_CREAR_ORDEN, {
        "proveedor_id": proveedor_id, "franja_id": franja_id, "fecha_compromiso": fecha_compromiso,
        "fecha_emision": fecha_emision, "total": total, "clave": clave})
    if fila is None:
        existente = await _una(conn, _SQL_ORDEN_POR_CLAVE, {"clave": clave})
        return existente[0], existente[1], False
    orden_id, numero = fila
    await _ejecutar(conn, _SQL_CREAR_LINEAS, {
        "orden_id": orden_id,
        "skus": [s for s, _, _ in lineas],
        "cantidades": [c for _, c, _ in lineas],
        "precios": [p for _, _, p in lineas]})
    return orden_id, numero, True


async def orden_para_confirmar(conn: AsyncConnection, orden_id: int):
    return await _una(conn, _SQL_ORDEN_PARA_CONFIRMAR, {"orden_id": orden_id})


async def lineas(conn: AsyncConnection, orden_id: int) -> list[tuple[int, Decimal]]:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_LINEAS, {"orden_id": orden_id})
        return await cur.fetchall()


async def consultar(conn: AsyncConnection, orden_id: int):
    return await _una(conn, _SQL_CONSULTAR, {"orden_id": orden_id})


async def cambiar_estado(conn: AsyncConnection, orden_id: int, estado: str) -> int:
    return await _ejecutar(conn, _SQL_CAMBIAR_ESTADO, {"orden_id": orden_id, "estado": estado})


async def idem_tomar(conn: AsyncConnection, clave: str, orden_id: int) -> bool:
    return await _una(conn, _SQL_IDEM_TOMAR, {"clave": clave, "orden_id": orden_id}) is not None


async def idem_leer(conn: AsyncConnection, clave: str, abandono_s: int):
    return await _una(conn, _SQL_IDEM_LEER, {"clave": clave, "abandono_s": abandono_s})


async def idem_retomar(conn: AsyncConnection, clave: str) -> None:
    await _ejecutar(conn, _SQL_IDEM_RETOMAR, {"clave": clave})


async def idem_completar(conn: AsyncConnection, clave: str, codigo: int, respuesta: dict) -> None:
    await _ejecutar(conn, _SQL_IDEM_COMPLETAR, {"clave": clave, "codigo": codigo, "respuesta": Jsonb(respuesta)})


async def idem_borrar(conn: AsyncConnection, clave: str) -> None:
    await _ejecutar(conn, _SQL_IDEM_BORRAR, {"clave": clave})


async def registrar_evento(conn: AsyncConnection, *, evento_id, tipo: str, agregado_id: int, payload: dict) -> None:
    await _ejecutar(conn, _SQL_OUTBOX, {"evento_id": evento_id, "tipo": tipo, "agregado_id": agregado_id,
                                        "payload": Jsonb(payload)})
