"""Publicador asincrono del Transactional Outbox hacia RabbitMQ (Relevo 2).

Consume eventos pendientes a traves de la interfaz del modulo de ordenes,
los publica de forma persistente con confirmacion en RabbitMQ y marca su publicacion.

Expone endpoint de observabilidad en el puerto 8004 para metricas de lag y throughput.
"""
import asyncio
import json
import logging
import os
import signal
import sys
import time

import aio_pika
import psycopg
from prometheus_client import start_http_server

from portal import config
from portal.modulos.ordenes import (
    outbox_contar_pendientes,
    outbox_marcar_publicados,
    outbox_obtener_pendientes,
)
from portal.observabilidad import OUTBOX_PENDIENTES, OUTBOX_PUBLICADOS

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","servicio":"publicador-outbox","nivel":"%(levelname)s","evento":"%(message)s"}',
)
logger = logging.getLogger("publicador-outbox")

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://portal:portal@rabbitmq:5672/")
OUTBOX_COLA = os.environ.get("OUTBOX_COLA", "ordenes_eventos")
PUERTO_METRICAS = int(os.environ.get("PUERTO_METRICAS", "8004"))

OUTBOX_PUBLICADOR_ACTIVO = os.environ.get("OUTBOX_PUBLICADOR_ACTIVO", "false").lower() in ("1", "true", "si", "yes")
OUTBOX_LOTE = int(os.environ.get("OUTBOX_LOTE", "100"))
OUTBOX_INTERVALO_MS = int(os.environ.get("OUTBOX_INTERVALO_MS", "200"))


async def _actualizar_metricas_lag(conn) -> int:
    """Mide cuantos eventos siguen pendientes usando la interfaz del modulo."""
    try:
        pendientes = await outbox_contar_pendientes(conn)
        OUTBOX_PENDIENTES.set(pendientes)
        return pendientes
    except Exception as e:
        logger.warning(f"Error midiendo lag de outbox: {e}")
        return 0


async def publicar_lote(conn, channel: aio_pika.RobustChannel) -> int:
    """Lee y publica un lote de eventos pendientes con confirmacion garantizada."""
    async with conn.transaction():
        filas = await outbox_obtener_pendientes(conn, OUTBOX_LOTE)
        if not filas:
            return 0

        ids_publicados = []
        for item in filas:
            id_fila = item["id"]
            evento_id = item["evento_id"]
            tipo = item["tipo"]
            agregado_id = item["agregado_id"]
            payload = item["payload"]

            if isinstance(payload, str):
                cuerpo_bytes = payload.encode("utf-8")
            else:
                cuerpo_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            mensaje = aio_pika.Message(
                body=cuerpo_bytes,
                message_id=str(evento_id),
                type=tipo,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                headers={"agregado_id": agregado_id, "tipo": tipo},
            )
            await channel.default_exchange.publish(mensaje, routing_key=OUTBOX_COLA)
            ids_publicados.append(id_fila)

        await outbox_marcar_publicados(conn, ids_publicados)
        cantidad = len(ids_publicados)
        OUTBOX_PUBLICADOS.labels(config.INSTANCIA).inc(cantidad)
        logger.info(f"Lote publicado: {cantidad} eventos enviados a RabbitMQ")
        return cantidad


async def main():
    logger.info("Iniciando servicio de Publicador Outbox...")
    start_http_server(PUERTO_METRICAS)
    logger.info(f"Servidor de métricas expuesto en http://0.0.0.0:{PUERTO_METRICAS}/metrics")

    # Bucle de reconexión y publicación
    while True:
        try:
            logger.info(f"Conectando a RabbitMQ en {RABBITMQ_URL}...")
            rmq_conn = await aio_pika.connect_robust(RABBITMQ_URL)
            channel = await rmq_conn.channel(publisher_confirms=True)
            await channel.declare_queue(OUTBOX_COLA, durable=True)
            logger.info(f"Cola '{OUTBOX_COLA}' declarada duradera en RabbitMQ")

            logger.info("Conectando a PostgreSQL...")
            async with await psycopg.AsyncConnection.connect(config.BD_DSN, autocommit=True) as pg_conn:
                logger.info("Conexión a PostgreSQL establecida")
                while True:
                    # Si el publicador está inactivo por configuración, solo monitorea lag
                    activo = os.environ.get("OUTBOX_PUBLICADOR_ACTIVO", "false").lower() in ("1", "true", "si", "yes")
                    if activo:
                        n = await publicar_lote(pg_conn, channel)
                        await _actualizar_metricas_lag(pg_conn)
                        if n == 0:
                            await asyncio.sleep(OUTBOX_INTERVALO_MS / 1000.0)
                    else:
                        await _actualizar_metricas_lag(pg_conn)
                        await asyncio.sleep(1.0)

        except (aio_pika.exceptions.AMQPError, psycopg.Error, OSError) as e:
            logger.warning(f"Error de conexión en publicador outbox: {e}. Reintentando en 3s...")
            await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            logger.info("Publicador outbox cancelado.")
            break
        except Exception as e:
            logger.error(f"Falla inesperada en publicador outbox: {e}. Reintentando en 3s...")
            await asyncio.sleep(3.0)


if __name__ == "__main__":
    asyncio.run(main())
