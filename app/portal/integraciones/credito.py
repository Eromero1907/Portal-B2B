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

from portal import config, trazas
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


async def _llamar_stub(
    *,
    intento: int,
    proveedor_id: int,
    orden_id: int,
    total: Decimal,
    trace_id: str,
    idempotency_key: str | None,
) -> ResultadoCredito:
    cabeceras = {
        "traceparent": traceparent(trace_id),
        "x-trace-id": trace_id,
        "x-intento": str(intento),
    }
    if idempotency_key:
        cabeceras["x-idempotency-key"] = idempotency_key

    with trazas.span("credito.http_post", intento=intento, orden_id=orden_id, idempotency_key=idempotency_key):
        cabeceras.update(trazas.cabeceras())
        async with _sesion.post(
            "/v1/validaciones",
            json={"proveedor_id": proveedor_id, "orden_id": orden_id, "total": str(total)},
            headers=cabeceras,
        ) as r:
            if r.status >= 500:
                raise CreditoNoDisponible(f"HTTP {r.status}")
            if r.status >= 400:
                raise CreditoNoDisponible(f"HTTP {r.status} inesperado")
            cuerpo = await r.json()
        return ResultadoCredito(bool(cuerpo["aprobado"]), cuerpo.get("motivo"), cuerpo.get("referencia"))


async def validar(
    *,
    proveedor_id: int,
    orden_id: int,
    total: Decimal,
    trace_id: str,
    idempotency_key: str | None = None,
) -> ResultadoCredito:
    """Consulta validación tributaria y cupo de crédito (RN-10).

    Aplica timeout por intento, reintentos con full jitter y presupuesto, Circuit Breaker
    y Bulkhead según configuración. Lanza CreditoNoDisponible ante fallas técnicas.
    """
    inicio = time.perf_counter()
    resultado = "error"
    try:
        from portal.integraciones.resiliencia import ejecutar_con_reintentos

        async def _intento(n: int):
            return await _llamar_stub(
                intento=n,
                proveedor_id=proveedor_id,
                orden_id=orden_id,
                total=total,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            )

        res = await ejecutar_con_reintentos(_intento, idempotency_key=idempotency_key)
        resultado = "aprobado" if res.aprobado else "denegado"
        return res
    except asyncio.TimeoutError as e:
        resultado = "timeout"
        raise CreditoNoDisponible("timeout") from e
    except aiohttp.ClientError as e:
        resultado = "error_conexion"
        raise CreditoNoDisponible(type(e).__name__) from e
    except CreditoNoDisponible as e:
        resultado = "error"
        raise
    finally:
        CREDITO_LLAMADAS.labels(resultado).inc()
        CREDITO_DURACION.observe(time.perf_counter() - inicio)

