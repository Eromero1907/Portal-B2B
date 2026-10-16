# B1 · db-caida — resultado (predicción vs medición)
**Evidencia:** `B1/sin_r{1,2}`, `B1/con_r{1,3}` (la `con_r2` se descartó por equipo degradado). **Veredicto: acertamos la forma de la falla (latencia de los errores, cero pérdida de eventos), pero erramos dos números grandes: el total de errores y el tiempo de recuperación.**

## Predicho vs observado
| Métrica | Predicho "sin" | Observado "sin" (r1 / r2) | Predicho "con M" | Observado "con M" (r1 / r3) |
|---|---|---|---|---|
| % errores en la ventana de la falla | ≈ 100 % | **84 % / 80 %** (3 926 / 3 720 de 4 690 / 4 669) | ≈ 100 % | **93 % / 88 %** |
| % errores en la corrida completa | **18–25 %** | **7,0 % / 6,6 %** ✗ | 17–25 % | **8,5 % / 8,1 %** ✗ |
| Solicitudes con error | 11 000–15 000 | **3 934 / 3 720** ✗ | 10 000–15 000 | 4 667 / 4 490 ✗ |
| Latencia típica del error | p50 ≈ 10 s | **10,0 s** ✓ | p50 ≈ 2 s | **2,0 s** ✓ |
| p95 / p99 global (corrida completa) | ≈ 10 s / 10–12 s | **10,0 s / 10,0 s** ✓ | ≈ 2 s / 2–2,5 s | **2,0 s / 2,0 s** ✓ |
| Recuperación tras `docker start` (`/salud/lista` 200 en las 3 instancias) | **10–35 s** | **9 s** (6 s app2/app3, 9 s app1) ✗ | 10–35 s | **4–5 s** ✗ |
| Eventos perdidos (`outbox_total` = CONFIRMADAS) | 0 | **0** (15 036 = 15 036; 15 145 = 15 145) ✓ | 0 | **0** (14 670 = 14 670; 14 717 = 14 717) ✓ |
| Órdenes EN_PROCESO | 3–10 | **3 y 4** ✓ | similar | 1 y **112** (r3) |
| Violaciones reservada ≤ total | 0 | **0** ✓ | 0 | **0** ✓ |
| ¿SLO? | NO | **NO** | NO (errores) | **NO** |

## Por qué fallaron los dos números
1. **Errores 3–4 veces menos que lo predicho.** La ficha contó 200 solicitudes/s × 45 s. Pero un flujo es secuencial (`crear` → `confirmar`): cuando `crear` falla el flujo termina y **nunca envía la confirmación**. Durante la caída la tasa de solicitudes real fue ≈ 104/s (4 690 en 45 s), no 200/s. El error estaba en la hipótesis de carga, no en la del sistema.
2. **Recuperación en 4–9 s, no 10–35 s.** La hipótesis del backoff exponencial del pool (1, 2, 4, 8, 16, 32 s) no se materializó: PostgreSQL aceptó conexiones 0–1 s tras `docker start` y las instancias volvieron a `/salud/lista` 200 entre +4 y +9 s. Con M (`BD_POOL_TIMEOUT_S=2`) fue la más rápida (+4–5 s). Tras la recuperación, "sin" arrastra una cola: en los siguientes 60 s p95 = 2,9–3,2 s y p99 = 4,6–5,2 s (drenado de las solicitudes que esperaban el pool); "con M" tiene p95 246–342 ms y 2,3–2,6 % de errores residuales.
3. **Con M no se evita el error, se acorta la espera**: el pool devuelve el error a los 2 s en lugar de 10 s (−80 % de latencia del error) a cambio de más errores totales (8,3 % vs 6,8 %): al fallar rápido, los clientes consumen más solicitudes por segundo. Es un intercambio espera↔error, no una mejora neta.

## Hallazgos adicionales
- `con_r3`: 109 respuestas 503 `breaker_abierto` y 112 órdenes EN_PROCESO en torno a la caída (en `con_r1`: 0 y 1). Causa **no investigada** (no se sabe si el breaker contó errores de BD como fallos del crédito); se informa como hallazgo abierto.
- Las claves de idempotencia EN_CURSO que quedan abandonadas (1–3 al final) coinciden con la predicción de la ficha (se retoman a los 30 s).
- No se midieron duplicados del outbox (la predicción "0–100 duplicados detectados" queda sin verificar: la métrica del consumidor no se capturó).

## Corrección / re-experimento
Ninguna aplicada. Por la ficha, la corrección prevista (ajustar `reconnect_timeout`/backoff) **ya no es necesaria**: la recuperación medida (≤ 9 s) es mejor que el umbral de 10 s que la ficha fijó como disparador.

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
