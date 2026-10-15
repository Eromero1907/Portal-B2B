"""Módulo Catálogo · interfaz publicada.

Única autoridad sobre SKU, ofertas por proveedor, precio negociado y vigencia (Entrega 1, ownership).
"""
from datetime import date
from decimal import Decimal

from psycopg import AsyncConnection

from portal.modulos.catalogo.interno import repositorio

CAUSA_OFERTA_INVALIDA = "sku_fuera_de_catalogo_o_precio"
CAUSA_SIN_LINEAS = "orden_sin_lineas"


async def validar_lineas(conn: AsyncConnection, proveedor_id: int, fecha: date,
                         lineas: list[tuple[int, Decimal]]) -> str | None:
    """lineas = [(sku_id, precio_unitario)]. None si todas son ofertas vigentes del proveedor al precio
    negociado (RN-03, RN-04, RN-05); si no, la causa del rechazo."""
    if not lineas:
        return CAUSA_SIN_LINEAS
    skus = [s for s, _ in lineas]
    precios = [p for _, p in lineas]
    validas = await repositorio.contar_lineas_validas(conn, proveedor_id, fecha, skus, precios)
    return None if validas == len(lineas) else CAUSA_OFERTA_INVALIDA
