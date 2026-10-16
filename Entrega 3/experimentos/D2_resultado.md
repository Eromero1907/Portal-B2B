# D2 · 5xx del crédito (breaker y degradación) — resultado (predicción vs medición, con corrección)
**Evidencia:** `D2/{sin,con}_r{1,2}` (umbral 50 %) y `D2/con-umbral70_r{3,4}`. `con-umbral70_r1/r2` se descartaron por equipo degradado; r3 y r4 son válidas **con reserva**: su p50 previo a la falla es 14,7–15,3 ms (≈ el doble de lo normal), por lo que las latencias absolutas están infladas y sólo se usa el % de errores como cifra robusta. **Veredicto: "sin" se cumplió exacto; "con M" (umbral 50 %) falló y el remedio empeoró el error; con umbral 70 % el error baja ≈ 87 %.**

## Ronda 1 — breaker con umbral 50 %
| Métrica | Predicho "sin" | Observado "sin" (r1 / r2) | Predicho "con M" | Observado "con M" (r1 / r2) |
|---|---|---|---|---|
| % errores 5xx ventana | ≈ 13,5 % | **13,4 / 13,4 %** ✓ | ≈ 13,5 % | **21,1 / 21,0 %** ✗ |
| Causa de los 503 | 100 % stub | 100 % `HTTP 503` del stub | rechazos rápidos | 12 642–12 817 `breaker_abierto`; sólo 187–190 del stub |
| Latencia del error | 20–30 ms | 36–43 ms | < 2 ms | 9–10 ms |
| p95 global | 85–110 ms | 43 / 55 ms | 50–70 ms | 39 / 35 ms |
| p99 global | — | 55 / 80 ms | 350 ms (ficha D2: no predicho) | 194 / 170 ms |
**Mecanismo:** la falla devuelve 503 con probabilidad 50 %, exactamente el umbral del breaker (50 %). La tasa observada en la ventana de 10 s oscila alrededor del umbral y el breaker se abre y se cierra continuamente; abierto, rechaza el 100 % de las llamadas aunque el stub respondería bien la mitad. Los reintentos quedan sin efecto porque el breaker corta antes. El remedio empeoró el error de 13,4 % a 21 %.

## Ronda 2 — umbral 70 % (`D2_correccion_umbral70.md`, predicción 2026-10-16 11:00)
| Métrica | Predicho | Observado r3 / r4 |
|---|---|---|
| % errores 5xx ventana | ≈ 1,7 % (1–3 %) | **2,72 % / 1,71 %** ✓ (−80 a −87 % frente a "sin", −87 a −92 % frente a umbral 50) |
| Respuestas `breaker_abierto` | ≈ 0 (< 100) | **523 / 0** (r3 ✗, r4 ✓) |
| Causa de los 503 | residuo del stub tras 4 intentos | 962 / 1 006 `HTTP 503` del stub ✓ + `TimeoutError` 142 / 14 |
| p95 global (ventana) | 60–120 ms | **210 / 259 ms** ✗ (host con p50 previo ≈ 15 ms, inflado) |
| p99 global (ventana) | 150–400 ms | **400 / 519 ms** ✗ (borde / sobre el rango; mismo sesgo del host) |
| ¿SLO? | NO por errores | **NO por errores** ✓ (1,7–2,7 % > 0,5 %); p95 de la corrida completa 162 / 202 ms < 400 ✓ |
| Negocio | RN-11 intacta | **0 aprobaciones sin crédito**: EN_PROCESO = 1 627 / 1 020 = errores; 0 violaciones; `outbox_total` = CONFIRMADAS (21 687 / 22 274) ✓ |

**Lectura.** Con 4 intentos por llamada y 50 % de fallos independientes, una llamada lógica falla con 0,5⁴ = 6,25 % y el error global esperado es 1,7 %: se observó 1,7 % (r4). En r3 el breaker abrió al menos una vez (523 rechazos) y el error subió a 2,7 %: **el umbral 70 % reduce la oscilación pero no la elimina** cuando el host es lento. Lo que la corrección no hace (y la ficha lo declara): cumplir el SLO de errores, ni proteger ante una caída total del crédito (no se probó con 100 % de fallos).

## Limitaciones
- r3/r4 se ejecutaron en un host más lento (p50 previo ≈ 15 ms). Las latencias absolutas de la ronda 2 no son comparables con las de la ronda 1.
- `portal_breaker_estado` y `portal_degradaciones_total` no se capturaron en archivo: la apertura del breaker se infiere de las respuestas `breaker_abierto`.

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
