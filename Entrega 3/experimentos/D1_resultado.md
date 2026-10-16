# D1 · matar app2 — resultado (predicción vs medición)
**Evidencia:** `D1/sin_r{1,2}`, `D1/con_r{1,4}` (`con_r2`, `con_r3` descartadas). `con_r4` es válida con reserva: p50 previo a la falla = 9,7 ms (normal ≈ 7). **Veredicto: el aislamiento por nginx y el cero de pérdidas se cumplieron; el impacto en latencia se sobreestimó y la reincorporación de app2 fue más lenta que lo predicho.**

## Predicho vs observado (ventana [151, 211))
| Métrica | Predicho | Observado |
|---|---|---|
| Solicitudes perdidas con 502 "sin" | 2–8 | **2 y 2** (ambas a inicio_s 152,0 s; extremo bajo del rango) ✓ |
| Solicitudes perdidas "con" (reintentos de cliente) | 0 | `con_r1`: **0**; `con_r4`: 2 reintentos (1 recuperada → 201; 1 terminó en **409 `confirmacion_en_curso`**, no reintentable) ≈ ✓ |
| % errores global | 0,01–0,02 % "sin"; 0,003 % "con" | **0,003 %** "sin" (2 de 65 900); 0 % "con" ✓ |
| Reparto durante la falla | 50 / 0 / 50 % | **50,1 / 0 / 49,9 %** ✓ |
| p95 durante la falla | 110–140 ms | **44–49 ms** ✗ (sin cambio visible) |
| Tiempo hasta que nginx aísla app2 | < 50 ms | app2 sin tráfico desde inicio_s ≈ 160 ✓ |
| Reincorporación de app2 tras `docker start` (primera solicitud atendida) | ≤ 5 s | **4,6 / 5,5 / 11,0 / 14,9 s** (r4 / sin_r2 / con_r1 / sin_r1): cumple en 1 de 4 (5,5 s lo roza); hasta 3× el objetivo en las demás ✗ parcial |
| Órdenes duplicadas / sobreventa | 0 | **0 / 0** (`outbox_total` = CONFIRMADAS; 0 violaciones; franja 10/10) ✓ |
| ¿SLO? | sí | **sí** |

## Hallazgos no predichos
1. **Sondeo de nginx:** mientras app2 está caída, nginx la vuelve a probar cada ≈ 13 s (`fail_timeout` 10 s + `proxy_connect_timeout` 2 s). Cada sondeo cuesta ≈ **2,0 s a 1–2 solicitudes**: 10–12 solicitudes > 1 s durante los 60 s, todas ≈ 2,0 s. No mueve p95 pero sí el máximo. Corrección posible: bajar `proxy_connect_timeout` a 0,5 s o un `health_check` activo.
2. **Reincorporación variable (4,6–14,9 s):** depende de cuándo cae el siguiente sondeo de nginx dentro de su `fail_timeout` de 10 s (+ arranque de app2); el peor caso es ≈ `fail_timeout` + arranque.
3. **El reintento de cliente tiene un hueco:** el 409 `confirmacion_en_curso` aparece porque la app2 muerta dejó la clave EN_CURSO; el reintento a otra instancia ve la clave tomada y devuelve 409 (no está en `CODIGOS_REINTENTABLES`). La clave se recupera sola a los 30 s.

## Corrección / re-experimento
No se aplicó cambio de código. La propuesta (`proxy_connect_timeout` menor) queda documentada.

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
