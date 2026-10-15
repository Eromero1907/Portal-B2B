"""Módulo Órdenes · interfaz publicada.

Dueño de órdenes, líneas, estado, Idempotency-Key y outbox. Orquesta la confirmación (ADR-002) llamando a las
interfaces de Proveedores, Catálogo y Logística y al adaptador de crédito; nunca a sus tablas.
"""
from portal.modulos.ordenes.interno.repositorio import (  # noqa: F401  (interfaz outbox para el publicador)
    outbox_contar_pendientes,
    outbox_marcar_publicados,
    outbox_obtener_pendientes,
)
from portal.modulos.ordenes.interno.servicio import (  # noqa: F401  (interfaz pública del módulo)
    CONFIRMADA, EN_PROCESO, RECHAZADA, Respuesta, confirmar_orden, consultar_orden, crear_orden,
)
