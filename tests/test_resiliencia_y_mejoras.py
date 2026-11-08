"""Pruebas unitarias de mecanismos de resiliencia, motor de fallas y optimizaciones de carga."""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent
for ruta in (RAIZ / "app", RAIZ / "stub", RAIZ / "medicion", RAIZ / "carga"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

# Compatibilidad con entornos ligeros de pruebas (CI / venv de linting)
if "fastapi" not in sys.modules:
    try:
        import fastapi  # noqa: F401
    except ModuleNotFoundError:
        fastapi_mod = types.ModuleType("fastapi")

        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail: str = ""):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        fastapi_mod.HTTPException = _HTTPException
        sys.modules["fastapi"] = fastapi_mod

if "prometheus_client" not in sys.modules:
    try:
        import prometheus_client  # noqa: F401
    except ModuleNotFoundError:
        prom_mod = types.ModuleType("prometheus_client")

        class _MetricaDummy:
            def __init__(self, *args, **kwargs):
                pass

            def labels(self, *args, **kwargs):
                return self

            def inc(self, *args, **kwargs):
                pass

            def dec(self, *args, **kwargs):
                pass

            def set(self, *args, **kwargs):
                pass

            def observe(self, *args, **kwargs):
                pass

        prom_mod.Counter = _MetricaDummy
        prom_mod.Gauge = _MetricaDummy
        prom_mod.Histogram = _MetricaDummy
        prom_mod.REGISTRY = MagicMock()
        prom_mod.CONTENT_TYPE_LATEST = "text/plain"
        prom_mod.generate_latest = lambda *a, **kw: b""
        prom_mod.start_http_server = lambda *a, **kw: None
        prom_core = types.ModuleType("prometheus_client.core")
        prom_core.CounterMetricFamily = MagicMock
        prom_core.GaugeMetricFamily = MagicMock
        prom_mod.core = prom_core
        sys.modules["prometheus_client"] = prom_mod
        sys.modules["prometheus_client.core"] = prom_core

if "psycopg" not in sys.modules:
    try:
        import psycopg  # noqa: F401
    except ModuleNotFoundError:
        psycopg_mod = types.ModuleType("psycopg")
        psycopg_errors = types.ModuleType("psycopg.errors")

        class _LockNotAvailable(Exception):
            pass

        class _UniqueViolation(Exception):
            pass

        psycopg_errors.LockNotAvailable = _LockNotAvailable
        psycopg_errors.UniqueViolation = _UniqueViolation
        psycopg_mod.errors = psycopg_errors
        psycopg_mod.AsyncConnection = object
        psycopg_mod.Error = Exception
        psycopg_mod.connect = MagicMock()
        psycopg_types = types.ModuleType("psycopg.types")
        psycopg_json = types.ModuleType("psycopg.types.json")
        psycopg_json.Jsonb = lambda x: x
        sys.modules["psycopg"] = psycopg_mod
        sys.modules["psycopg.errors"] = psycopg_errors
        sys.modules["psycopg.types"] = psycopg_types
        sys.modules["psycopg.types.json"] = psycopg_json

if "psycopg_pool" not in sys.modules:
    try:
        import psycopg_pool  # noqa: F401
    except ModuleNotFoundError:
        pool_mod = types.ModuleType("psycopg_pool")
        pool_mod.AsyncConnectionPool = MagicMock
        sys.modules["psycopg_pool"] = pool_mod

if "httpx" not in sys.modules:
    try:
        import httpx  # noqa: F401
    except ModuleNotFoundError:
        httpx_mod = types.ModuleType("httpx")
        httpx_mod.AsyncClient = MagicMock
        httpx_mod.HTTPError = Exception
        sys.modules["httpx"] = httpx_mod

if "aiohttp" not in sys.modules:
    try:
        import aiohttp  # noqa: F401
    except ModuleNotFoundError:
        aiohttp_mod = types.ModuleType("aiohttp")
        aiohttp_mod.ClientError = Exception
        aiohttp_mod.ContentTypeError = Exception
        aiohttp_mod.TCPConnector = MagicMock
        aiohttp_mod.ClientTimeout = MagicMock
        aiohttp_mod.ClientSession = MagicMock
        sys.modules["aiohttp"] = aiohttp_mod

if "numpy" not in sys.modules:
    try:
        import numpy  # noqa: F401
    except ModuleNotFoundError:
        np_mod = types.ModuleType("numpy")
        np_mod.percentile = lambda vals, p: sorted(vals)[min(len(vals) - 1, int(len(vals) * p / 100))]
        sys.modules["numpy"] = np_mod

import psycopg.errors  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import fallas as stub_fallas  # noqa: E402
from portal import config  # noqa: E402
from portal.integraciones.credito import CreditoNoDisponible  # noqa: E402
from portal.integraciones.resiliencia import (  # noqa: E402
    Bulkhead,
    CircuitBreaker,
    ejecutar_con_reintentos,
)
from portal.modulos.ordenes.interno import servicio as ordenes_servicio  # noqa: E402


def test_motor_fallas_combinadas_y_kill_switch(tmp_path, monkeypatch):
    """Verifica que el motor de fallas en proceso soporte fallas simultáneas (A1 + D2)
    y que el Kill Switch Global (enabled=false) revierta con 0 sobrecarga."""
    archivo_yaml = tmp_path / "faults.yaml"
    cfg = {
        "version": 1,
        "enabled": True,
        "semilla": 42,
        "fallas": [
            {
                "id": "A1",
                "enabled": True,
                "inyector": "proceso",
                "objetivo": {"servicio": "stub-credito", "porcentaje": 100},
                "parametros": {"latencia_ms": 5, "jitter_ms": 1},
            },
            {
                "id": "D2",
                "enabled": True,
                "inyector": "proceso",
                "objetivo": {"servicio": "stub-credito", "porcentaje": 100},
                "parametros": {"codigo_error": 503, "probabilidad": 100},
            },
        ],
    }
    archivo_yaml.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(stub_fallas, "RUTA_FALLAS_DEFECTO", str(archivo_yaml))
    stub_fallas._ultimo_mtime = -1.0

    with pytest.raises(HTTPException) as exc:
        asyncio.run(stub_fallas.aplicar_fallas_proceso(orden_id=101, proveedor_id=1, intento=1))
    assert exc.value.status_code == 503

    # Kill Switch Global: enabled = False -> 0 errores y retorno inmediato
    cfg["enabled"] = False
    archivo_yaml.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    stub_fallas._ultimo_mtime = -1.0
    asyncio.run(stub_fallas.aplicar_fallas_proceso(orden_id=101, proveedor_id=1, intento=1))


def test_circuit_breaker_no_oscila_en_50pct_con_umbral_70pct(monkeypatch):
    """Con umbral de apertura en 70%, una tasa de fallos del 50% (D2) mantiene el circuito cerrado,
    mientras que una tasa >= 70% lo abre."""
    monkeypatch.setattr(config, "BREAKER_ACTIVO", True)
    monkeypatch.setattr(config, "BREAKER_UMBRAL_FALLOS_PCT", 70.0)
    monkeypatch.setattr(config, "BREAKER_MIN_LLAMADAS", 10)
    monkeypatch.setattr(config, "BREAKER_VENTANA_S", 30.0)

    cb = CircuitBreaker()

    async def simular_50_pct():
        for i in range(10):
            await cb.antes_de_llamar()
            await cb.registrar_resultado(exito=(i % 2 == 0))

    asyncio.run(simular_50_pct())
    assert cb.estado == CircuitBreaker.ESTADO_CERRADO

    cb_alto = CircuitBreaker()

    async def simular_80_pct():
        for i in range(10):
            await cb_alto.antes_de_llamar()
            await cb_alto.registrar_resultado(exito=(i < 2))

    asyncio.run(simular_80_pct())
    assert cb_alto.estado == CircuitBreaker.ESTADO_ABIERTO
    with pytest.raises(CreditoNoDisponible, match="breaker_abierto"):
        asyncio.run(cb_alto.antes_de_llamar())


def test_bulkhead_y_reintentos(monkeypatch):
    """Verifica que el motor de reintentos recupere ante fallos transitorios y que el Bulkhead aísle concurrencia."""
    monkeypatch.setattr(config, "BREAKER_ACTIVO", False)
    monkeypatch.setattr(config, "BULKHEAD_ACTIVO", True)
    monkeypatch.setattr(config, "BULKHEAD_MAX_CONCURRENTES", 1)
    monkeypatch.setattr(config, "BULKHEAD_ESPERA_MS", 10)
    monkeypatch.setattr(config, "REINTENTOS_ACTIVO", True)
    monkeypatch.setattr(config, "REINTENTOS_MAX", 2)
    monkeypatch.setattr(config, "REINTENTOS_BASE_MS", 5)
    monkeypatch.setattr(config, "REINTENTOS_TOPE_MS", 10)
    monkeypatch.setattr(config, "REINTENTOS_PRESUPUESTO_MS", 1000)

    intentos_vistos = []

    async def operacion_flaky(intento: int):
        intentos_vistos.append(intento)
        if intento < 2:
            raise CreditoNoDisponible("http_503")
        return "OK"

    res = asyncio.run(ejecutar_con_reintentos(operacion_flaky, idempotency_key="k-test"))
    assert res == "OK"
    assert intentos_vistos == [1, 2]

    bh = Bulkhead()

    async def saturar_bulkhead():
        evento = asyncio.Event()

        async def lenta():
            await evento.wait()

        t1 = asyncio.create_task(bh.ejecutar(lenta))
        await asyncio.sleep(0.005)
        with pytest.raises(CreditoNoDisponible, match="bulkhead_agotado"):
            await bh.ejecutar(lenta)
        evento.set()
        await t1

    asyncio.run(saturar_bulkhead())


def test_lock_not_available_mapea_a_503_franja_bloqueada(monkeypatch):
    """Verifica que LockNotAvailable (B2 con lock_timeout) devuelva HTTP 503 franja_bloqueada con Retry-After."""
    monkeypatch.setattr(config, "DEGRADACION_ACTIVA", True)
    monkeypatch.setattr(config, "DEGRADACION_RETRY_AFTER_S", 2)

    conn_mock = AsyncMock()
    tx_cm = AsyncMock()
    tx_cm.__aenter__.return_value = None
    tx_cm.__aexit__.return_value = False
    conn_mock.transaction = MagicMock(return_value=tx_cm)

    pool_cm = AsyncMock()
    pool_cm.__aenter__.return_value = conn_mock
    pool_cm.__aexit__.return_value = False

    with (
        patch.object(ordenes_servicio.pool, "connection", return_value=pool_cm),
        patch.object(ordenes_servicio.repositorio, "idem_tomar", AsyncMock(return_value=True)),
        patch.object(ordenes_servicio.repositorio, "idem_borrar", AsyncMock()),
        patch.object(ordenes_servicio, "_confirmar", AsyncMock(side_effect=psycopg.errors.LockNotAvailable())),
    ):
        resp = asyncio.run(ordenes_servicio.confirmar_orden(91150, "idem-b2", "trace-b2"))

    assert resp.codigo_http == 503
    assert resp.cuerpo["causa"] == "franja_bloqueada"
    assert resp.cuerpo["estado"] == "EN_PROCESO"
    assert resp.cabeceras.get("Retry-After") == "2"


def test_variante_lote_activa_por_defecto_y_codigos_reintentables():
    """Verifica que benchmark_carga tenga VARIANTE_LOTE activa por defecto y generador reintente 409."""
    with patch.dict("sys.modules", {"db": MagicMock(conectar=MagicMock(), RAIZ=RAIZ)}):
        import benchmark_carga
        assert benchmark_carga.VARIANTE_LOTE is True

    import generador
    assert 409 in generador.CODIGOS_REINTENTABLES
