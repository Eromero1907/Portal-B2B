"""Módulo Logística · interfaz publicada.

Única autoridad sobre franjas, capacidad y reservas (ADR-003). Nadie más modifica `capacidad_reservada`.
"""
from datetime import date

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from portal.modulos.logistica.interno import repositorio

CAUSA_SIN_CUPO = "sin_cupo_franja"
CAUSA_FRANJA_INEXISTENTE = "franja_inexistente"


class ReservaActivaExistente(Exception):
    """La orden ya tiene una reserva PENDIENTE o CONFIRMADA (otra confirmación de la misma orden en curso)."""


async def fecha_de_franja(conn: AsyncConnection, franja_id: int) -> date | None:
    return await repositorio.fecha_de_franja(conn, franja_id)


async def reservar(conn: AsyncConnection, franja_id: int, orden_id: int, ttl_s: int) -> str | None:
    """Reserva un cupo de la franja para la orden (RN-07, RN-08). None si quedó reservada; si no, la causa.
    Lanza ReservaActivaExistente si la orden ya tiene una reserva activa (debe ir dentro de una transacción)."""
    try:
        if await repositorio.reservar(conn, franja_id, orden_id, ttl_s):
            return None
    except UniqueViolation as e:
        raise ReservaActivaExistente(orden_id) from e
    if await repositorio.fecha_de_franja(conn, franja_id) is None:
        return CAUSA_FRANJA_INEXISTENTE
    return CAUSA_SIN_CUPO


async def confirmar_reserva(conn: AsyncConnection, orden_id: int) -> bool:
    """PENDIENTE → CONFIRMADA. False si la reserva ya no estaba pendiente (p. ej. expiró)."""
    return await repositorio.confirmar(conn, orden_id)


async def liberar_reserva(conn: AsyncConnection, orden_id: int) -> bool:
    """PENDIENTE → LIBERADA y devuelve el cupo."""
    return await repositorio.liberar(conn, orden_id)


async def liberar_reservas_expiradas(conn: AsyncConnection, limite: int = 500) -> int:
    """RN-09 / RF-11: libera reservas PENDIENTE vencidas. Devuelve cuántas liberó."""
    return await repositorio.liberar_expiradas(conn, limite)
