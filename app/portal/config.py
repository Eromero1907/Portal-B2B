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
def _booleano(nombre: str, defecto: bool) -> bool:
    v = os.environ.get(nombre, "").lower()
    if not v:
        return defecto
    return v in ("1", "true", "si", "yes", "on")


BD_DSN = os.environ.get("BD_DSN", "postgresql://postgres:portal@localhost:5433/portal_b2b")
BD_POOL_MIN = _entero("BD_POOL_MIN", 4)
BD_POOL_MAX = _entero("BD_POOL_MAX", 10)
BD_POOL_TIMEOUT_S = _decimal("BD_POOL_TIMEOUT_S", 10.0)

# Dependencia externa (stub de crédito/tributación).
CREDITO_URL = os.environ.get("CREDITO_URL", "http://localhost:9000")
CREDITO_TIMEOUT_S = _decimal("CREDITO_TIMEOUT_S", 30.0)
CREDITO_TIMEOUT_INTENTO_MS = _entero("CREDITO_TIMEOUT_INTENTO_MS", 0)  # 0 = usa CREDITO_TIMEOUT_S
CREDITO_MAX_CONEXIONES = _entero("CREDITO_MAX_CONEXIONES", 100)

# Mecanismos de resiliencia (Relevo 2): por defecto desactivados para mantener la línea base
REINTENTOS_ACTIVO = _booleano("REINTENTOS_ACTIVO", False)
REINTENTOS_MAX = _entero("REINTENTOS_MAX", 0)
REINTENTOS_BASE_MS = _entero("REINTENTOS_BASE_MS", 50)
REINTENTOS_TOPE_MS = _entero("REINTENTOS_TOPE_MS", 400)
REINTENTOS_PRESUPUESTO_MS = _entero("REINTENTOS_PRESUPUESTO_MS", 1500)

BREAKER_ACTIVO = _booleano("BREAKER_ACTIVO", False)
BREAKER_UMBRAL_FALLOS_PCT = _entero("BREAKER_UMBRAL_FALLOS_PCT", 50)
BREAKER_VENTANA_S = _entero("BREAKER_VENTANA_S", 10)
BREAKER_MIN_LLAMADAS = _entero("BREAKER_MIN_LLAMADAS", 20)
BREAKER_ESPERA_ABIERTO_S = _decimal("BREAKER_ESPERA_ABIERTO_S", 5.0)
BREAKER_PRUEBAS_SEMIABIERTO = _entero("BREAKER_PRUEBAS_SEMIABIERTO", 5)

BULKHEAD_ACTIVO = _booleano("BULKHEAD_ACTIVO", False)
BULKHEAD_MAX_CONCURRENTES = _entero("BULKHEAD_MAX_CONCURRENTES", 20)
BULKHEAD_ESPERA_MS = _entero("BULKHEAD_ESPERA_MS", 50)

DEGRADACION_ACTIVA = _booleano("DEGRADACION_ACTIVA", False)
DEGRADACION_RETRY_AFTER_S = _entero("DEGRADACION_RETRY_AFTER_S", 5)

DB_LOCK_TIMEOUT_MS = _entero("DB_LOCK_TIMEOUT_MS", 0)

# Reservas de franja (RN-09) e idempotencia (RN-13)
RESERVA_TTL_S = _entero("RESERVA_TTL_S", 60)
LIBERADOR_PERIODO_S = _decimal("LIBERADOR_PERIODO_S", 5.0)
IDEMPOTENCIA_ABANDONO_S = _entero("IDEMPOTENCIA_ABANDONO_S", 30)

# Fecha de operación por defecto para órdenes nuevas: el día siguiente al pivote del conjunto (2026-09-16).
# Fija para que la validación de contratos sea reproducible sin importar la fecha real del reloj.
FECHA_OPERACION = os.environ.get("FECHA_OPERACION", "2026-09-17")

