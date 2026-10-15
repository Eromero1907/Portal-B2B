"""Consumidor idempotente de eventos de órdenes desde RabbitMQ (Relevo 2).

Consume eventos de la cola `ordenes_eventos`, procesa las notificaciones y
garantiza idempotencia estricta mediante inserción atómica en:
`notificaciones.eventos_procesados (evento_id PK)` con `ON CONFLICT DO NOTHING`.

El ACK a RabbitMQ solo se envía tras el commit exitoso en PostgreSQL.
Expone `/metrics` en el puerto 8005 para observabilidad del throughput y deduplicación.
"""
import asyncio
import json
import logging
import os
import sys

import aio_pika
import psycopg
from prometheus_client import start_http_server

from portal import config
from portal.observabilidad import CONSUMIDOR_PROCESADOS

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","servicio":"consumidor-eventos","nivel":"%(levelname)s","evento":"%(message)s"}',
)
logger = logging.getLogger("consumidor-eventos")

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://portal:portal@rabbitmq:5672/")
OUTBOX_COLA = os.environ.get("OUTBOX_COLA", "ordenes_eventos")
PUERTO_METRICAS = int(os.environ.get("PUERTO_METRICAS", "8005"))
CONSUMIDOR_PREFETCH = int(os.environ.get("CONSUMIDOR_PREFETCH", "50"))
CONSUMIDOR_DEDUPLICAR = os.environ.get("CONSUMIDOR_DEDUPLICAR", "true").lower() in ("1", "true", "si", "yes")


async def procesar_mensaje(message: aio_pika.IncomingMessage, pg_conn: psycopg.AsyncConnection) -> None:
    """Procesa un mensaje de evento aplicando deduplicación idempotente."""
    try:
        cuerpo = json.loads(message.body.decode("utf-8"))
        evento_id = cuerpo.get("evento_id") or message.message_id
        tipo = cuerpo.get("tipo") or message.type or "OrdenConfirmada"
        orden_id = cuerpo.get("orden_id") or message.headers.get("agregado_id")

        if not evento_id:
            logger.warning("Mensaje recibido sin evento_id. Descartando con ACK.")
            await message.ack()
            return

        if CONSUMIDOR_DEDUPLICAR:
            async with pg_conn.transaction():
                async with pg_conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO notificaciones.eventos_procesados (evento_id, tipo, agregado_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (evento_id) DO NOTHING
                        RETURNING evento_id
                        """,
                        (evento_id, tipo, orden_id),
                    )
                    insertado = await cur.fetchone()

            if insertado:
                CONSUMIDOR_PROCESADOS.labels("nuevo").inc()
                logger.info(f"Evento procesado: id={evento_id} tipo={tipo} orden_id={orden_id}")
            else:
                CONSUMIDOR_PROCESADOS.labels("duplicado").inc()
                logger.warning(f"Evento duplicado ignorado (idempotencia): id={evento_id}")
        else:
            # Modo sin deduplicación (para medir 'sin mecanismos' en C2 si aplica)
            CONSUMIDOR_PROCESADOS.labels("nuevo").inc()
            logger.info(f"Evento procesado sin deduplicar: id={evento_id}")

        # Solo enviamos el ack tras persistir de forma segura en Postgres
        await message.ack()

    except Exception as e:
        logger.error(f"Falla procesando mensaje: {e}. Rechazando sin requeue.")
        await message.reject(requeue=True)


async def main():
    logger.info("Iniciando servicio de Consumidor Idempotente de Eventos...")
    start_http_server(PUERTO_METRICAS)
    logger.info(f"Servidor de métricas expuesto en http://0.0.0.0:{PUERTO_METRICAS}/metrics")

    while True:
        try:
            logger.info(f"Conectando a RabbitMQ en {RABBITMQ_URL}...")
            rmq_conn = await aio_pika.connect_robust(RABBITMQ_URL)
            channel = await rmq_conn.channel()
            await channel.set_qos(prefetch_count=CONSUMIDOR_PREFETCH)
            queue = await channel.declare_queue(OUTBOX_COLA, durable=True)
            logger.info(f"Escuchando cola '{OUTBOX_COLA}' con prefetch={CONSUMIDOR_PREFETCH}")

            logger.info("Conectando a PostgreSQL...")
            async with await psycopg.AsyncConnection.connect(config.BD_DSN, autocommit=True) as pg_conn:
                logger.info("Conexión a PostgreSQL establecida")
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        await procesar_mensaje(message, pg_conn)

        except (aio_pika.exceptions.AMQPError, psycopg.Error, OSError) as e:
            logger.warning(f"Error de conexión en consumidor: {e}. Reintentando en 3s...")
            await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            logger.info("Consumidor de eventos cancelado.")
            break
        except Exception as e:
            logger.error(f"Falla inesperada en consumidor: {e}. Reintentando en 3s...")
            await asyncio.sleep(3.0)


if __name__ == "__main__":
    asyncio.run(main())
