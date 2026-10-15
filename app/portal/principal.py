"""Aplicación HTTP del Portal B2B (una instancia del monolito modular).

Endpoints
  POST /ordenes-compra                         crea una orden EN_PROCESO (cabecera Idempotency-Key opcional)
  POST /ordenes-compra/{id}/confirmacion       confirma la orden (cabecera Idempotency-Key OBLIGATORIA, RN-13)
  GET  /ordenes-compra/{id}                    estado de la orden (RF-13)
  GET  /salud                                  vida del proceso (no toca la BD; lo usa Docker/nginx)
  GET  /salud/lista                            lista para atender: la BD responde
  GET  /metrics                                métricas Prometheus

Arranque: uvicorn portal.principal:app --host 0.0.0.0 --port 8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, condecimal

from portal import config
from portal.bd import pool
from portal.integraciones import credito
from portal.modulos import logistica, ordenes
from portal.observabilidad import (
    RESERVAS_EXPIRADAS, MiddlewareObservabilidad, exportar_metricas, registrar,
)


# ---------------------------------------------------------------------------
# Tarea de fondo: liberador de reservas vencidas (RN-09, RF-11)
# ---------------------------------------------------------------------------
async def _liberador():
    while True:
        await asyncio.sleep(config.LIBERADOR_PERIODO_S)
        try:
            async with pool.connection() as conn:
                async with conn.transaction():
                    n = await logistica.liberar_reservas_expiradas(conn)
            if n:
                RESERVAS_EXPIRADAS.inc(n)
                registrar("reservas_expiradas_liberadas", cantidad=n)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # p. ej. BD caída: se registra y se reintenta en el siguiente periodo
            registrar("liberador_fallo", logging.WARNING, error=type(e).__name__, detalle=str(e)[:200])


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    await pool.open(wait=False)
    credito.abrir()
    tarea = asyncio.create_task(_liberador())
    registrar("instancia_iniciada", version=config.VERSION, pool_max=config.BD_POOL_MAX,
              credito_url=config.CREDITO_URL, credito_timeout_s=config.CREDITO_TIMEOUT_S)
    yield
    tarea.cancel()
    await credito.cerrar()
    await pool.close()


app = FastAPI(title="Portal B2B · Entregable 3", version=config.VERSION, lifespan=ciclo_de_vida,
              docs_url=None, redoc_url=None)
app.add_middleware(MiddlewareObservabilidad)


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------
class LineaEntrada(BaseModel):
    sku_id: int = Field(gt=0)
    cantidad: int = Field(gt=0, le=1_000_000)
    precio_unitario: condecimal(gt=0, max_digits=12, decimal_places=2)


class OrdenEntrada(BaseModel):
    proveedor_id: int = Field(gt=0)
    franja_id: int = Field(gt=0)
    fecha_emision: datetime | None = None
    lineas: list[LineaEntrada] = Field(min_length=1, max_length=300)


def _json(r: ordenes.Respuesta) -> JSONResponse:
    headers = getattr(r, "cabeceras", None) or None
    return JSONResponse(status_code=r.codigo_http, content=r.cuerpo, headers=headers)



# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@app.post("/ordenes-compra")
async def crear_orden(entrada: OrdenEntrada,
                      idempotency_key: Annotated[str | None, Header(max_length=36)] = None):
    r = await ordenes.crear_orden(
        proveedor_id=entrada.proveedor_id, franja_id=entrada.franja_id, fecha_emision=entrada.fecha_emision,
        clave=idempotency_key,
        lineas=[(l.sku_id, l.cantidad, Decimal(l.precio_unitario)) for l in entrada.lineas])
    return _json(r)


@app.post("/ordenes-compra/{orden_id}/confirmacion")
async def confirmar_orden(orden_id: int, request: Request,
                          idempotency_key: Annotated[str | None, Header(max_length=64)] = None):
    trace_id = request.scope["state"]["trace_id"]
    if not idempotency_key:
        return JSONResponse(status_code=400, content={"error": "falta_idempotency_key", "trace_id": trace_id})
    return _json(await ordenes.confirmar_orden(orden_id, idempotency_key, trace_id))


@app.get("/ordenes-compra/{orden_id}")
async def consultar_orden(orden_id: int):
    return _json(await ordenes.consultar_orden(orden_id))


@app.get("/salud")
async def salud():
    return {"estado": "vivo", "instancia": config.INSTANCIA}


@app.get("/salud/lista")
async def salud_lista():
    try:
        async with pool.connection(timeout=2) as conn:
            await conn.execute("SELECT 1")
        return {"estado": "lista", "instancia": config.INSTANCIA}
    except Exception as e:
        return JSONResponse(status_code=503, content={"estado": "no_lista", "instancia": config.INSTANCIA,
                                                      "error": type(e).__name__})


@app.get("/metrics")
async def metricas():
    cuerpo, tipo = exportar_metricas()
    return Response(content=cuerpo, media_type=tipo)


@app.exception_handler(Exception)
async def error_no_controlado(request: Request, exc: Exception):
    trace_id = request.scope.get("state", {}).get("trace_id")
    registrar("error_no_controlado", logging.ERROR, ruta=request.url.path, error=type(exc).__name__,
              detalle=str(exc)[:300], trace_id=trace_id)
    return JSONResponse(status_code=500, content={"error": "error_interno", "tipo": type(exc).__name__,
                                                  "trace_id": trace_id})
