"""Adaptador del servicio externo de crédito/tributación (Credit/Tax Adapter de la Entrega 1).

PUNTO ÚNICO DE LLAMADA AL EXTERNO. Todas las confirmaciones pasan por `validar()`; aquí es donde el relevo 2
(resiliencia) envuelve la llamada con timeout ajustado, reintentos con backoff y jitter, circuit breaker y
bulkhead, y define la degradación graciosa. En este relevo la llamada es directa a propósito, para poder medir
el sistema "sin" y "con" mecanismos de resiliencia.

Estado actual (línea base): timeout explícito de CREDITO_TIMEOUT_S (30 s por defecto), sin reintentos, sin
breaker, sin bulkhead: todas las llamadas comparten un mismo pool de CREDITO_MAX_CONEXIONES conexiones HTTP.

Cliente aiohttp (no httpx): con cientos de llamadas concurrentes —lo que provocan las fallas de latencia— el pool
de httpx se degrada por sí mismo y contaminaría los experimentos (medido en el generador de carga del relevo 1).
"""
import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal

import aiohttp

from portal import config
from portal.observabilidad import CREDITO_DURACION, CREDITO_LLAMADAS, traceparent


@dataclass(frozen=True)
class ResultadoCredito:
    aprobado: bool
    motivo: str | None
    referencia: str | None


class CreditoNoDisponible(Exception):
    """El externo no respondió a tiempo, devolvió 5xx o no hubo conexión. Nunca se interpreta como aprobado
    (RN-11): quien llama decide el rechazo controlado o el estado pendiente."""


_sesion: aiohttp.ClientSession | None = None


def abrir() -> None:
    global _sesion
    _sesion = aiohttp.ClientSession(
        base_url=config.CREDITO_URL,
        timeout=aiohttp.ClientTimeout(total=config.CREDITO_TIMEOUT_S),
        connector=aiohttp.TCPConnector(limit=config.CREDITO_MAX_CONEXIONES),
    )


async def cerrar() -> None:
    if _sesion is not None:
        await _sesion.close()


async def validar(*, proveedor_id: int, orden_id: int, total: Decimal, trace_id: str) -> ResultadoCredito:
    """Consulta validación tributaria y cupo de crédito (RN-10). Lanza CreditoNoDisponible ante fallas técnicas."""
    inicio = time.perf_counter()
    resultado = "error"
    try:
        async with _sesion.post(
            "/v1/validaciones",
            json={"proveedor_id": proveedor_id, "orden_id": orden_id, "total": str(total)},
            headers={"traceparent": traceparent(trace_id), "x-trace-id": trace_id},
        ) as r:
            if r.status >= 500:
                raise CreditoNoDisponible(f"HTTP {r.status}")
            if r.status >= 400:
                raise CreditoNoDisponible(f"HTTP {r.status} inesperado")
            cuerpo = await r.json()
        resultado = "aprobado" if cuerpo["aprobado"] else "denegado"
        return ResultadoCredito(bool(cuerpo["aprobado"]), cuerpo.get("motivo"), cuerpo.get("referencia"))
    except asyncio.TimeoutError as e:
        resultado = "timeout"
        raise CreditoNoDisponible("timeout") from e
    except aiohttp.ClientError as e:
        raise CreditoNoDisponible(type(e).__name__) from e
    finally:
        CREDITO_LLAMADAS.labels(resultado).inc()
        CREDITO_DURACION.observe(time.perf_counter() - inicio)
