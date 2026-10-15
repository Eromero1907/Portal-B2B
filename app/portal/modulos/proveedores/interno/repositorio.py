"""SQL del módulo Proveedores. Solo toca el esquema `proveedores`."""
from datetime import date

from psycopg import AsyncConnection

# RN-01 (proveedor existe y está ACTIVO) y RN-02 (contrato VIGENTE en la fecha de la orden, fecha_fin inclusiva).
# Usa idx_contratos_prov_vigencia (Q1 del E2).
_SQL_ELEGIBILIDAD = """
SELECT p.estado,
       EXISTS (SELECT 1
                 FROM proveedores.contratos_suministro c
                WHERE c.proveedor_id = p.id
                  AND c.estado = 'VIGENTE'
                  AND c.fecha_inicio <= %(fecha)s
                  AND c.fecha_fin    >= %(fecha)s) AS contrato_vigente
  FROM proveedores.proveedores p
 WHERE p.id = %(proveedor_id)s
"""


async def leer_elegibilidad(conn: AsyncConnection, proveedor_id: int, fecha: date):
    async with conn.cursor() as cur:
        await cur.execute(_SQL_ELEGIBILIDAD, {"proveedor_id": proveedor_id, "fecha": fecha})
        return await cur.fetchone()
