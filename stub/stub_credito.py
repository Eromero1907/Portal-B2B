"""Stub propio del servicio externo de crédito/tributación (restricción 4 del curso).

Línea base: responde siempre, con una latencia base fija (LATENCIA_BASE_MS, 20 ms por defecto) que modela una
dependencia externa real, y una decisión determinista por proveedor (≈ 3 % de proveedores sin cupo).

El relevo 2 agrega aquí la inyección de fallas configurable en caliente (latencia, jitter, errores 5xx) leyendo
el motor de fallas: el punto de enganche es `_aplicar_fallas()`.

POST /v1/validaciones  {proveedor_id, orden_id, total} -> {aprobado, motivo, referencia}
GET  /salud · GET /metrics
"""
import asyncio
import json
import os
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

LATENCIA_BASE_MS = float(os.environ.get("LATENCIA_BASE_MS", "20"))
PORCENTAJE_SIN_CUPO = int(os.environ.get("PORCENTAJE_SIN_CUPO", "3"))

SOLICITUDES = Counter("stub_credito_solicitudes_total", "Validaciones atendidas", ["resultado", "codigo"])
DURACION = Histogram("stub_credito_duracion_segundos", "Duración de la validación",
                     buckets=(0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30))

app = FastAPI(title="Stub crédito/tributación", docs_url=None, redoc_url=None)


class Validacion(BaseModel):
    proveedor_id: int
    orden_id: int
    total: str


def _sin_cupo(proveedor_id: int) -> bool:
    """Decisión determinista (hash multiplicativo de Knuth): el mismo proveedor siempre recibe la misma respuesta."""
    return (proveedor_id * 2654435761) % 100 < PORCENTAJE_SIN_CUPO


async def _aplicar_fallas(_solicitud: Validacion) -> None:
    """Enganche del motor de fallas (relevo 2). En la línea base no inyecta nada."""


def _log(**campos) -> None:
    campos["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    campos["servicio"] = "stub-credito"
    sys.stdout.write(json.dumps(campos, ensure_ascii=False) + "\n")


@app.post("/v1/validaciones")
async def validar(solicitud: Validacion, request: Request):
    inicio = time.perf_counter()
    trace_id = request.headers.get("x-trace-id")
    await asyncio.sleep(LATENCIA_BASE_MS / 1000)
    await _aplicar_fallas(solicitud)
    sin_cupo = _sin_cupo(solicitud.proveedor_id)
    cuerpo = {"aprobado": not sin_cupo, "motivo": "cupo_credito_insuficiente" if sin_cupo else None,
              "referencia": str(uuid.uuid4())}
    duracion = time.perf_counter() - inicio
    resultado = "denegado" if sin_cupo else "aprobado"
    SOLICITUDES.labels(resultado, "200").inc()
    DURACION.observe(duracion)
    _log(evento="validacion", orden_id=solicitud.orden_id, proveedor_id=solicitud.proveedor_id,
         resultado=resultado, duracion_ms=round(duracion * 1000, 2), trace_id=trace_id)
    return cuerpo


@app.get("/salud")
async def salud():
    return {"estado": "vivo", "latencia_base_ms": LATENCIA_BASE_MS}


@app.get("/metrics")
async def metricas():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
