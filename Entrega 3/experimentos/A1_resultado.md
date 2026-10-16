# A1 · tributaria-lenta — resultado (predicción vs medición)
**Evidencia:** `Entrega 3/evidencia/A1/{sin,con}_r{1,2}` · 2 repeticiones válidas por configuración, resultados casi idénticos (misma semilla). **Veredicto: la predicción se cumplió.**

## Predicho vs observado (ventana de falla [91, 391))
| Métrica | Predicho "sin" | Observado "sin" (r1 / r2) | Predicho "con M" | Observado "con M" (r1 / r2) |
|---|---|---|---|---|
| p95 global | ≈ 770 ms (650–900) | **765 / 762 ms** | ≈ 300 ms (250–350) | **269 / 268 ms** |
| p99 global | ≈ 1 070 ms | **1 066 / 1 065 ms** | ≈ 545 ms | **552 / 552 ms** |
| p95 confirmar | ≈ 950 ms (800–1 050) | **955 / 954 ms** | ≈ 350 ms (300–550) | **304 / 301 ms** |
| p99 confirmar | ≈ 1 100 ms | **1 105 / 1 104 ms** | ≈ 875 ms | **788 / 797 ms** |
| p95 crear (control: la falla debe quedar focalizada) | sin cambio | 11 / 11 ms | sin cambio | 10 / 9 ms |
| % errores 5xx | ≈ 0 % | **0 %** | ≈ 0,22 % | **0,21 %** (125 / 124 de 59 582; todos 503 `TimeoutError` a ≈ 1,0 s) |
| ¿Cumple SLO (p95 < 400 ms, errores < 0,5 %)? | NO | **NO** (p95 765 ms) | sí, por poco | **SÍ** (p95 268 ms; 0,21 %) |
| Breaker | apagado | — | no abre | **no abrió**: 0 respuestas `breaker_abierto` |

## Mecanismo confirmado
Solo ≈ 27 % de las solicitudes llega al stub y el 30 % de ellas se vuelve lenta (+500–1 100 ms), es decir ≈ 8 % de todo el tráfico: por encima del 5 % del p95, la cola lenta entra al percentil. Con M, el timeout de 200 ms por intento corta toda llamada lenta (el extra mínimo es 500 ms) y el reintento sale rápido con probabilidad 0,7: el p95 baja 765 → 268 ms (−65 %). El precio son los 503 de las llamadas que agotan 4 intentos (0,3⁴ ≈ 0,8 % de las llamadas lógicas ⇒ 0,21 % de las solicitudes).

## Desviaciones
- Ninguna fuera de rango. La única diferencia relevante: el p99 de confirmar con M quedó algo mejor que lo predicho (790 vs 875 ms).
- La métrica de reintentos (`portal_credito_reintentos_total`) no se capturó en archivo; el mecanismo se infiere de la distribución de latencias y de las causas de error.
- Sin corrección ni re-experimento: no hizo falta.

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
