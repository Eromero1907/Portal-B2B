"""Motor de inyección de fallas en proceso para el stub de crédito (Relevo 2).

Implementa:
- A1: Latencia fija + jitter uniforme.
- A2: Jitter lognormal (cola larga).
- D2: Errores HTTP 5xx configurables.

Propiedades:
- Cero redespliegues: recarga en caliente leyendo mtime de faults.yaml sin reiniciar el proceso.
- Kill switch global: si 'enabled: false', retorna de inmediato con 0 sobrecarga.
- Determinismo: selección y magnitud basadas en hash sha256(seed, falla_id, orden_id, intento).
"""
import asyncio
import hashlib
import math
import os
import random
import time
from typing import Any, Dict, Optional

import yaml
from fastapi import HTTPException
from prometheus_client import Counter, Gauge

STUB_FALLAS_INYECTADAS = Counter(
    "stub_fallas_inyectadas_total",
    "Fallas inyectadas activamente en el stub de crédito",
    ["tipo", "falla_id"],
)
STUB_MOTOR_ACTIVO = Gauge(
    "stub_motor_fallas_activo",
    "Estado del motor de fallas en el stub (1 activo / 0 inactivo)",
)

# Ruta configurable del archivo de fallas
RUTA_FALLAS_DEFECTO = os.environ.get("RUTA_FALLAS", "/srv/faults/faults.yaml")

_ultimo_mtime: float = -1.0
_config_cache: Dict[str, Any] = {"enabled": False, "semilla": 42, "fallas": []}


def _recargar_si_cambio(ruta: str = RUTA_FALLAS_DEFECTO) -> Dict[str, Any]:
    """Recarga el archivo YAML si cambió su timestamp de modificación (mtime)."""
    global _ultimo_mtime, _config_cache
    try:
        if not os.path.exists(ruta):
            if _config_cache.get("enabled"):
                STUB_MOTOR_ACTIVO.set(0)
            _config_cache = {"enabled": False, "semilla": 42, "fallas": []}
            return _config_cache

        mtime = os.path.getmtime(ruta)
        if mtime != _ultimo_mtime:
            with open(ruta, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            _config_cache = data
            _ultimo_mtime = mtime
            STUB_MOTOR_ACTIVO.set(1 if data.get("enabled", False) else 0)
    except Exception as e:
        # En caso de concurrencia o escritura atómica parcial, mantiene el caché previo
        pass
    return _config_cache


def _hash_determinista(semilla: int, falla_id: str, orden_id: int, intento: int) -> int:
    """Calcula un hash entero determinista para la combinación dada."""
    clave = f"{semilla}:{falla_id}:{orden_id}:{intento}".encode("utf-8")
    digest = hashlib.sha256(clave).digest()
    return int.from_bytes(digest[:8], byteorder="big")


async def aplicar_fallas_proceso(orden_id: int, proveedor_id: int, intento: int = 1) -> None:
    """Evalúa e inyecta las fallas de proceso (A1, A2, D2) según la configuración activa."""
    config = _recargar_si_cambio()
    if not config.get("enabled", False):
        return

    semilla = int(config.get("semilla", 42))
    fallas = config.get("fallas", [])

    for f in fallas:
        if not f.get("enabled", False):
            continue

        inyector = f.get("inyector", "")
        if inyector != "proceso":
            continue

        objetivo = f.get("objetivo", {})
        if objetivo.get("servicio") != "stub-credito":
            continue

        falla_id = f.get("id")
        params = f.get("parametros", {})

        # -------------------------------------------------------------
        # Falla A1: Latencia fija + jitter uniforme
        # -------------------------------------------------------------
        if falla_id == "A1":
            pct = objetivo.get("porcentaje", 30)
            h = _hash_determinista(semilla, "A1", orden_id, intento)
            if (h % 100) < pct:
                latencia_ms = float(params.get("latencia_ms", 800))
                jitter_ms = float(params.get("jitter_ms", 300))
                rnd = random.Random(h)
                extra_ms = rnd.uniform(latencia_ms - jitter_ms, latencia_ms + jitter_ms)
                if extra_ms > 0:
                    STUB_FALLAS_INYECTADAS.labels(tipo="latencia_uniforme", falla_id="A1").inc()
                    await asyncio.sleep(extra_ms / 1000.0)

        # -------------------------------------------------------------
        # Falla A2: Jitter lognormal (cola larga pesada)
        # -------------------------------------------------------------
        elif falla_id == "A2":
            pct = objetivo.get("porcentaje", 100)
            h = _hash_determinista(semilla, "A2", orden_id, intento)
            if (h % 100) < pct:
                mediana_ms = float(params.get("mediana_ms", 50))
                sigma = float(params.get("sigma", 1.5))
                tope_ms = float(params.get("tope_ms", 20000))
                rnd = random.Random(h)
                mu = math.log(mediana_ms)
                z = rnd.gauss(0, 1)
                extra_ms = min(math.exp(mu + sigma * z), tope_ms)
                if extra_ms > 0:
                    STUB_FALLAS_INYECTADAS.labels(tipo="latencia_lognormal", falla_id="A2").inc()
                    await asyncio.sleep(extra_ms / 1000.0)

        # -------------------------------------------------------------
        # Falla D2: Errores HTTP 5xx
        # -------------------------------------------------------------
        elif falla_id == "D2":
            pct = float(params.get("probabilidad", 50))
            h = _hash_determinista(semilla, "D2", orden_id, intento)
            if (h % 100) < pct:
                codigo = int(params.get("codigo_error", 503))
                STUB_FALLAS_INYECTADAS.labels(tipo="error_5xx", falla_id="D2").inc()
                raise HTTPException(
                    status_code=codigo,
                    detail=f"Falla inyectada D2: stub no disponible ({codigo})"
                )
