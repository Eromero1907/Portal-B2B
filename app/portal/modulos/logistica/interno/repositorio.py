"""SQL del módulo Logística. Solo toca el esquema `logistica`.

La invariante reservada <= total (RN-07/08) la garantiza el UPDATE condicional: es atómico en PostgreSQL aunque
lo ejecuten las 3 instancias a la vez (el segundo UPDATE sobre la misma fila espera al primero y re-evalúa el WHERE).
"""
from datetime import date

from psycopg import AsyncConnection

_SQL_FECHA_FRANJA = "SELECT fecha FROM logistica.franjas_cedi WHERE id = %(franja_id)s"

# Ocupa un cupo y crea la reserva PENDIENTE en la misma sentencia: o se hacen las dos cosas o ninguna.
_SQL_RESERVAR = """
WITH cupo AS (
    UPDATE logistica.franjas_cedi
       SET capacidad_reservada = capacidad_reservada + 1
     WHERE id = %(franja_id)s
       AND capacidad_reservada < capacidad_total
 RETURNING id
)
INSERT INTO logistica.reservas (franja_id, orden_id, estado, expira_en)
SELECT id, %(orden_id)s, 'PENDIENTE', now() + make_interval(secs => %(ttl_s)s::double precision)
  FROM cupo
RETURNING id
"""

_SQL_CONFIRMAR = """
UPDATE logistica.reservas
   SET estado = 'CONFIRMADA', actualizado_en = now()
 WHERE orden_id = %(orden_id)s AND estado = 'PENDIENTE'
RETURNING id
"""

_SQL_LIBERAR = """
WITH liberada AS (
    UPDATE logistica.reservas
       SET estado = 'LIBERADA', actualizado_en = now()
     WHERE orden_id = %(orden_id)s AND estado = 'PENDIENTE'
 RETURNING franja_id
)
UPDATE logistica.franjas_cedi f
   SET capacidad_reservada = f.capacidad_reservada - 1
  FROM liberada
 WHERE f.id = liberada.franja_id
RETURNING f.id
"""

# RN-09: libera en lote las reservas PENDIENTE vencidas. SKIP LOCKED: las 3 instancias corren el liberador
# sin pisarse ni esperarse.
_SQL_LIBERAR_EXPIRADAS = """
WITH vencidas AS (
    SELECT id
      FROM logistica.reservas
     WHERE estado = 'PENDIENTE' AND expira_en < now()
     ORDER BY expira_en
     LIMIT %(limite)s
       FOR UPDATE SKIP LOCKED
), expiradas AS (
    UPDATE logistica.reservas r
       SET estado = 'EXPIRADA', actualizado_en = now()
      FROM vencidas
     WHERE r.id = vencidas.id
 RETURNING r.franja_id
), por_franja AS (
    SELECT franja_id, count(*) AS n FROM expiradas GROUP BY franja_id
)
UPDATE logistica.franjas_cedi f
   SET capacidad_reservada = f.capacidad_reservada - por_franja.n
  FROM por_franja
 WHERE f.id = por_franja.franja_id
RETURNING por_franja.n
"""


async def fecha_de_franja(conn: AsyncConnection, franja_id: int) -> date | None:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_FECHA_FRANJA, {"franja_id": franja_id})
        fila = await cur.fetchone()
        return fila[0] if fila else None


async def reservar(conn: AsyncConnection, franja_id: int, orden_id: int, ttl_s: int) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_RESERVAR, {"franja_id": franja_id, "orden_id": orden_id, "ttl_s": ttl_s})
        return await cur.fetchone() is not None


async def confirmar(conn: AsyncConnection, orden_id: int) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_CONFIRMAR, {"orden_id": orden_id})
        return await cur.fetchone() is not None


async def liberar(conn: AsyncConnection, orden_id: int) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_LIBERAR, {"orden_id": orden_id})
        return await cur.fetchone() is not None


async def liberar_expiradas(conn: AsyncConnection, limite: int) -> int:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_LIBERAR_EXPIRADAS, {"limite": limite})
        return sum(n for (n,) in await cur.fetchall())
