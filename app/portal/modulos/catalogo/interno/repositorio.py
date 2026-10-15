"""SQL del módulo Catálogo. Solo toca el esquema `catalogo`."""
from datetime import date
from decimal import Decimal

from psycopg import AsyncConnection

# RN-03/04/05: cada línea debe ser una oferta del proveedor, vigente en la fecha y al precio negociado.
# Una sola ida y vuelta para todas las líneas de la orden (unnest de dos arreglos paralelos).
_SQL_LINEAS_VALIDAS = """
SELECT count(*)
  FROM unnest(%(skus)s::int[], %(precios)s::numeric[]) AS l(sku_id, precio)
  JOIN catalogo.sku_catalogo s
    ON s.id = l.sku_id
   AND s.proveedor_id = %(proveedor_id)s
   AND s.vigencia_desde <= %(fecha)s
   AND s.vigencia_hasta >= %(fecha)s
   AND s.precio_negociado = l.precio
"""


async def contar_lineas_validas(conn: AsyncConnection, proveedor_id: int, fecha: date,
                                skus: list[int], precios: list[Decimal]) -> int:
    async with conn.cursor() as cur:
        await cur.execute(_SQL_LINEAS_VALIDAS, {"skus": skus, "precios": precios,
                                                "proveedor_id": proveedor_id, "fecha": fecha})
        (n,) = await cur.fetchone()
        return n
