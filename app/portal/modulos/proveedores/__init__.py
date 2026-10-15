"""Módulo Proveedores · interfaz publicada.

Única autoridad sobre proveedores y contratos (Entrega 1, ownership). Los demás módulos solo llaman a estas
funciones; nunca leen el esquema `proveedores` ni importan `proveedores.interno`.
"""
from datetime import date

from psycopg import AsyncConnection

from portal.modulos.proveedores.interno import repositorio

CAUSA_INEXISTENTE = "proveedor_inexistente"
CAUSA_NO_ACTIVO = "proveedor_no_activo"
CAUSA_SIN_CONTRATO = "sin_contrato_vigente"


async def validar_elegibilidad(conn: AsyncConnection, proveedor_id: int, fecha: date) -> str | None:
    """None si el proveedor puede vender en `fecha`; si no, la causa del rechazo (RN-01, RN-02)."""
    fila = await repositorio.leer_elegibilidad(conn, proveedor_id, fecha)
    if fila is None:
        return CAUSA_INEXISTENTE
    estado, contrato_vigente = fila
    if estado != "ACTIVO":
        return CAUSA_NO_ACTIVO
    if not contrato_vigente:
        return CAUSA_SIN_CONTRATO
    return None
