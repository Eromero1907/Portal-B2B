"""Trazas distribuidas (OpenTelemetry -> Jaeger) del Entregable 3, relevo 3.

APAGADO por defecto (OTEL_ACTIVO=false): `span()` es un no-op y la línea base queda idéntica. Se activa por
variable de entorno al levantar los contenedores (ver README, sección Observabilidad).

Diseño: spans manuales, sin librerías de auto-instrumentación. El `trace_id` que JJ ya generaba (W3C, 32 hex) y
propaga por cabeceras, logs y payload del outbox se reutiliza como trace id de OpenTelemetry. Así cada línea de
log JSON se corresponde con una traza en Jaeger, y los spans del publicador y del consumidor del outbox caen en
la MISMA traza que la solicitud HTTP que originó el evento.

  OTEL_ACTIVO                    true/false (defecto false)
  OTEL_EXPORTER_OTLP_ENDPOINT    defecto http://jaeger:4318
  OTEL_MUESTREO                  fracción de trazas a registrar (0..1, defecto 1.0). Decisión determinista por
                                 trace id: todos los servicios deciden igual.
"""
import os
import random
from contextlib import contextmanager

ACTIVO = os.environ.get("OTEL_ACTIVO", "false").lower() in ("1", "true", "si", "yes", "on")
_MUESTREO = float(os.environ.get("OTEL_MUESTREO", "1.0"))
_tracer = None


def iniciar(servicio: str) -> None:
    """Configura el exportador OTLP hacia Jaeger. No hace nada si OTEL_ACTIVO es falso."""
    global _tracer
    if not ACTIVO or _tracer is not None:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318").rstrip("/")
    proveedor = TracerProvider(resource=Resource.create(
        {"service.name": servicio, "service.instance.id": os.environ.get("INSTANCIA", "local")}))
    proveedor.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=base + "/v1/traces"),
        schedule_delay_millis=1000, max_queue_size=8192, max_export_batch_size=512))
    trace.set_tracer_provider(proveedor)
    _tracer = trace.get_tracer("portal-b2b")


def _limpiar(atributos: dict) -> dict:
    return {k: (v if isinstance(v, (str, int, float, bool)) else str(v))
            for k, v in atributos.items() if v is not None}


@contextmanager
def span(nombre: str, trace_id: str | None = None, **atributos):
    """Span hijo del contexto actual. Si no hay contexto y se da `trace_id`, abre la traza con ese id."""
    if _tracer is None:
        yield None
        return
    from opentelemetry import trace

    ctx = None
    if trace_id and not trace.get_current_span().get_span_context().is_valid:
        try:
            tid = int(trace_id, 16)
        except ValueError:
            tid = 0
        if tid:
            muestreado = (tid & 0x00FFFFFFFFFFFFFF) < _MUESTREO * (1 << 56)
            sc = trace.SpanContext(trace_id=tid, span_id=random.getrandbits(64) or 1, is_remote=True,
                                   trace_flags=trace.TraceFlags(1 if muestreado else 0))
            ctx = trace.set_span_in_context(trace.NonRecordingSpan(sc))
    with _tracer.start_as_current_span(nombre, context=ctx, attributes=_limpiar(atributos)) as s:
        yield s


@contextmanager
def span_entrante(nombre: str, cabeceras, **atributos):
    """Span de servidor que continúa la traza recibida en la cabecera `traceparent`."""
    if _tracer is None:
        yield None
        return
    from opentelemetry import trace
    from opentelemetry.propagate import extract

    with _tracer.start_as_current_span(nombre, context=extract(dict(cabeceras)), kind=trace.SpanKind.SERVER,
                                       attributes=_limpiar(atributos)) as s:
        yield s


def cabeceras() -> dict:
    """Cabeceras `traceparent` del span actual para propagarlas en una llamada saliente."""
    if _tracer is None:
        return {}
    from opentelemetry.propagate import inject
    h: dict = {}
    inject(h)
    return h
