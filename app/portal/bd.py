"""Pool de conexiones a PostgreSQL (uno por instancia de la aplicación).

Las conexiones van en autocommit: cada unidad de trabajo abre su transacción explícita con
`async with conn.transaction():`, así se ve en el código exactamente qué queda dentro de cada transacción.
"""
from psycopg_pool import AsyncConnectionPool

from portal import config

pool = AsyncConnectionPool(
    conninfo=config.BD_DSN,
    min_size=config.BD_POOL_MIN,
    max_size=config.BD_POOL_MAX,
    timeout=config.BD_POOL_TIMEOUT_S,
    kwargs={"autocommit": True, "application_name": f"portal-{config.INSTANCIA}"},
    name=f"pool-{config.INSTANCIA}",
    open=False,
)


def estadisticas_pool() -> dict:
    """Tamaño, conexiones libres y solicitudes esperando una conexión (para /metrics)."""
    est = pool.get_stats()
    return {
        "tamano": est.get("pool_size", 0),
        "disponibles": est.get("pool_available", 0),
        "en_espera": est.get("requests_waiting", 0),
        "tiempo_espera_ms_total": est.get("requests_wait_ms", 0),
        "errores": est.get("requests_errors", 0),
        "maximo": config.BD_POOL_MAX,
    }
