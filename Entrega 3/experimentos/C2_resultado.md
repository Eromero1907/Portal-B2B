# C2 · consumidor pausado — resultado (predicción vs medición)
**Evidencia:** `C2/sin_r{1,2}`, `C2/con_r{1,3}` (`con_r2` descartada). **Veredicto: la independencia síncrona/asíncrona y la ausencia de pérdidas se cumplieron; el drenado fue más lento que lo predicho y quedó un hallazgo abierto (50 mensajes retenidos).**

## Predicho vs observado
| Métrica | Predicho | Observado |
|---|---|---|
| p95 / p99 HTTP durante la pausa | igual a la línea base | **45–49 / 56–63 ms** ✓ (sin impacto) |
| % errores HTTP | ≈ 0,003 % | 0 % (un 502 aislado en 2 de 4 corridas) ✓ |
| Lag en RabbitMQ al final de la pausa | crece lineal hasta ≈ 15 600 | **15 285–15 405** ✓ (pendiente ≈ 51/s) |
| Lag en `ordenes.outbox` | < 100 | **máx. 19–37** ✓ |
| Eventos perdidos | 0 | **0**: `outbox_total` = `CONFIRMADAS` = 23 269 (23 268 en 1 corrida) ✓ |
| Drenado tras reanudar | a 0 en 15–30 s | **74 s** en `con_r1` (≈ 210 msg/s) ✗ |
| Impacto en HTTP tras reanudar | ninguno | p50 sube de 7 a **10,6–16,5 ms** en los 60 s siguientes (el consumidor compite por la BD) ✗ leve |
| Eventos procesados = CONFIRMADAS (con dedupe) | igual | `con_r1`: 23 269 ✓; **`con_r3`: 23 219 (faltan 50)** ✗ |

## Hallazgo abierto: 50 mensajes que no se confirman
En 3 de 4 corridas, al terminar el muestreo (≈ 600 s después de reanudar) la cola conserva exactamente **50 mensajes** (= `prefetch` del consumidor): en `con_r3` y `sin_r1` quedaron como `ready = 50` al cierre y se vieron `unacked = 50` durante cientos de segundos antes; en `sin_r2` `unacked = 50`. Sólo `con_r1` drenó a 0/0. No se perdió ningún evento (siguen en la cola), pero el consumidor se queda con un lote sin confirmar. **Causa no diagnosticada** (hipótesis: tras `docker unpause` el consumidor conserva un lote en vuelo sin ack; no se descartó una carrera con la conexión AMQP). Queda como defecto pendiente y se informa en el reporte.

## "sin" vs "con"
"sin" no registra `eventos_procesados` (no hay tabla de deduplicación), así que `eventos_procesados_total` queda constante y la comparación de procesados sólo es posible en "con". En ambos, el lag de RabbitMQ se comporta igual: el perfil M no afecta la ruta HTTP, como predijo la ficha.

## Corrección / re-experimento
No se re-ejecutó. Corrección propuesta: revisar la confirmación (`ack`) del consumidor tras reanudar y exponer `rabbitmq_queue_messages_unacked` en un panel, para distinguir lote retenido de lote en proceso.

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
