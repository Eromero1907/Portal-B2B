"""Instrumentación mínima: métricas Prometheus (RED + pool), logs JSON y propagación de trace_id.

Contrato para el relevo 3 (Prometheus/Grafana/Jaeger): los nombres de métricas de este archivo son estables.
  portal_http_solicitudes_total{metodo,ruta,codigo}          contador  (Rate y Errors de RED)
  portal_http_duracion_segundos{metodo,ruta}                 histograma (Duration de RED: p50/p95/p99)
  portal_confirmaciones_total{resultado,causa}               contador  (resultado de negocio)
  portal_credito_llamadas_total{resultado}                   contador  (aprobado/denegado/error)
  portal_credito_duracion_segundos                           histograma
  portal_bd_pool_conexiones{estado=tamano|disponibles|en_espera|maximo}  gauge (USE del pool)
  portal_bd_pool_espera_ms_total / portal_bd_pool_errores_total          contadores
  portal_reservas_expiradas_total                            contador
  portal_info{instancia,version}                             gauge = 1
  process_* y python_gc_*                                    CPU, memoria y GC del proceso (USE)
"""
import json
import logging
import secrets
import sys
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest, REGISTRY,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from portal import config

# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
BUCKETS_HTTP = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.75,
                1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 30.0, 60.0)

SOLICITUDES = Counter("portal_http_solicitudes_total", "Solicitudes HTTP atendidas",
                      ["metodo", "ruta", "codigo"])
DURACION = Histogram("portal_http_duracion_segundos", "Duración de las solicitudes HTTP",
                     ["metodo", "ruta"], buckets=BUCKETS_HTTP)
CONFIRMACIONES = Counter("portal_confirmaciones_total", "Resultado de negocio de las confirmaciones",
                         ["resultado", "causa"])
CREDITO_LLAMADAS = Counter("portal_credito_llamadas_total", "Llamadas al servicio de crédito/tributación",
                           ["resultado"])
CREDITO_DURACION = Histogram("portal_credito_duracion_segundos", "Duración de la llamada de crédito",
                             buckets=BUCKETS_HTTP)
RESERVAS_EXPIRADAS = Counter("portal_reservas_expiradas_total", "Reservas PENDIENTE liberadas por expiración")
INFO = Gauge("portal_info", "Instancia y versión", ["instancia", "version"])
INFO.labels(config.INSTANCIA, config.VERSION).set(1)


class _ColectorPool:
    """Lee el estado del pool en cada scrape (no hay que actualizarlo a mano)."""

    def collect(self):
        from portal.bd import estadisticas_pool
        est = estadisticas_pool()
        g = GaugeMetricFamily("portal_bd_pool_conexiones", "Conexiones del pool por estado", labels=["estado"])
        for estado in ("tamano", "disponibles", "en_espera", "maximo"):
            g.add_metric([estado], est[estado])
        yield g
        yield CounterMetricFamily("portal_bd_pool_espera_ms", "Tiempo total esperando conexión del pool (ms)",
                                  value=est["tiempo_espera_ms_total"])
        yield CounterMetricFamily("portal_bd_pool_errores", "Solicitudes al pool que fallaron (p. ej. timeout)",
                                  value=est["errores"])


REGISTRY.register(_ColectorPool())


def exportar_metricas() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Logs JSON (una línea por evento; docker logs / Loki los pueden leer tal cual)
# ---------------------------------------------------------------------------
class _FormatoJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "nivel": record.levelname,
            "instancia": config.INSTANCIA,
            "evento": record.getMessage(),
        }
        extra = getattr(record, "campos", None)
        if extra:
            datos.update(extra)
        if record.exc_info:
            datos["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


def configurar_logs() -> logging.Logger:
    log = logging.getLogger("portal")
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(_FormatoJSON())
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


log = configurar_logs()


def registrar(evento: str, nivel: int = logging.INFO, **campos) -> None:
    log.log(nivel, evento, extra={"campos": campos})


# ---------------------------------------------------------------------------
# trace_id (W3C traceparent: 00-<trace 32 hex>-<span 16 hex>-01)
# ---------------------------------------------------------------------------
def extraer_o_crear_trace_id(cabeceras: dict[str, str]) -> str:
    tp = cabeceras.get("traceparent", "")
    partes = tp.split("-")
    if len(partes) == 4 and len(partes[1]) == 32:
        return partes[1]
    propio = cabeceras.get("x-trace-id", "")
    if len(propio) == 32 and all(c in "0123456789abcdef" for c in propio):
        return propio
    return secrets.token_hex(16)


def traceparent(trace_id: str) -> str:
    return f"00-{trace_id}-{secrets.token_hex(8)}-01"


class MiddlewareObservabilidad:
    """Middleware ASGI: mide cada solicitud (RED), asigna trace_id y escribe una línea de log de acceso."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cabeceras = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        trace_id = extraer_o_crear_trace_id(cabeceras)
        scope.setdefault("state", {})["trace_id"] = trace_id
        estado = {"codigo": 500}
        inicio = time.perf_counter()

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                estado["codigo"] = mensaje["status"]
                h = list(mensaje.get("headers", []))
                h.append((b"x-trace-id", trace_id.encode()))
                h.append((b"x-instancia", config.INSTANCIA.encode()))
                mensaje["headers"] = h
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        finally:
            duracion = time.perf_counter() - inicio
            ruta_obj = scope.get("route")
            ruta = getattr(ruta_obj, "path", None) or "sin_ruta"
            metodo = scope.get("method", "")
            if ruta != "/metrics":
                SOLICITUDES.labels(metodo, ruta, str(estado["codigo"])).inc()
                DURACION.labels(metodo, ruta).observe(duracion)
                registrar("http", metodo=metodo, ruta=ruta, path=scope.get("path"), codigo=estado["codigo"],
                          duracion_ms=round(duracion * 1000, 2), trace_id=trace_id)
