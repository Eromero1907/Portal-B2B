"""Configuración de la instancia, leída de variables de entorno (docker-compose.yml las fija).

Todo parámetro que un experimento pueda querer cambiar vive aquí y se declara en el manifest de la corrida.
"""
import os


def _entero(nombre: str, defecto: int) -> int:
    return int(os.environ.get(nombre, defecto))


def _decimal(nombre: str, defecto: float) -> float:
    return float(os.environ.get(nombre, defecto))


INSTANCIA = os.environ.get("INSTANCIA", "local")
VERSION = "e3-relevo1"

# Base de datos (pool por instancia: 3 instancias × BD_POOL_MAX conexiones)
BD_DSN = os.environ.get("BD_DSN", "postgresql://postgres:portal@localhost:5433/portal_b2b")
BD_POOL_MIN = _entero("BD_POOL_MIN", 4)
BD_POOL_MAX = _entero("BD_POOL_MAX", 10)
BD_POOL_TIMEOUT_S = _decimal("BD_POOL_TIMEOUT_S", 10.0)

# Dependencia externa (stub de crédito/tributación).
# Timeout explícito pero ingenuo a propósito (30 s, como el cliente HTTP del ejemplo del curso): el relevo 2
# (resiliencia) lo ajusta y agrega reintentos, breaker y bulkhead en el único punto de llamada.
CREDITO_URL = os.environ.get("CREDITO_URL", "http://localhost:9000")
CREDITO_TIMEOUT_S = _decimal("CREDITO_TIMEOUT_S", 30.0)
CREDITO_MAX_CONEXIONES = _entero("CREDITO_MAX_CONEXIONES", 100)

# Reservas de franja (RN-09) e idempotencia (RN-13)
RESERVA_TTL_S = _entero("RESERVA_TTL_S", 60)
LIBERADOR_PERIODO_S = _decimal("LIBERADOR_PERIODO_S", 5.0)
IDEMPOTENCIA_ABANDONO_S = _entero("IDEMPOTENCIA_ABANDONO_S", 30)

# Fecha de operación por defecto para órdenes nuevas: el día siguiente al pivote del conjunto (2026-09-16).
# Fija para que la validación de contratos sea reproducible sin importar la fecha real del reloj.
FECHA_OPERACION = os.environ.get("FECHA_OPERACION", "2026-09-17")
