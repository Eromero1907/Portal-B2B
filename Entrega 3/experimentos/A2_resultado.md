# A2 · cola-larga-lognormal — resultado (predicción vs medición)
**Evidencia:** `A2/sin_r{1,2}`, `A2/con_r{2,3}` (válidas). `A2/con_r1` se conserva pero **no se usa en las comparaciones**: tuvo un episodio transitorio ajeno a la falla (522 errores: 334 `breaker_abierto`, 36 HTTP 500 `error_interno`, 5 HTTP 502; ver Limitaciones). **Veredicto: "sin" se cumplió casi exacto; "con M" mejora la cola (p99 de confirmar) pero cuesta p95 global, y el p99 global quedó por encima de lo predicho.**

## Predicho vs observado (ventana [91, 391))
| Métrica | Predicho "sin" | Observado "sin" (r1 / r2) | Predicho "con M" | Observado "con M" (r2 / r3) |
|---|---|---|---|---|
| p95 global | ≈ 260 ms (200–320) | **228 / 231 ms** | ≈ 240 ms | **263 / 261 ms** |
| p99 global | ≈ 800 ms (600–1 000) | **746 / 755 ms** | ≈ 350 ms | **513 / 510 ms** (✗ por encima) |
| p95 confirmar | ≈ 430 ms (350–520) | **400 / 404 ms** | ≈ 300 ms | **325 / 328 ms** |
| p99 confirmar | ≈ 1 200 ms (0,9–1,6 s) | **1 171 / 1 183 ms** | ≈ 560 ms | **586 / 585 ms** |
| Latencia máxima | hasta ≈ 20 s (tope de la distribución) | **20,0 s** (20 036 / 20 041 ms) | — | 1,1 s |
| % errores | ≈ 0 % | **0 %** | ≈ 0,04 % | **0,05 %** (31 / 29 de 59 582, todos 503 `TimeoutError` a ≈ 1,0 s) |
| ¿SLO global? | sí, por poco | **sí** (p95 228 ms) | sí | **sí** (p95 262 ms; 0,05 %) |
| Breaker | — | — | no abre | no abrió en r2/r3 (0 `breaker_abierto`) |

## Lo que sí enseñó (y no estaba en la ficha)
1. **Los reintentos intercambian p95 por p99.** Con M el p99 de confirmar baja 1 180 → 585 ms (−50 %) y desaparecen los rezagados de 20 s, pero el p95 global **sube** 230 → 262 ms (+14 %): el 20 % de las llamadas con intento > 200 ms ahora paga timeout + backoff + reintento (≈ 300 ms) en lugar de su latencia natural (< 177 ms al p80). La ficha predijo que M mejoraría ambos; solo mejoró la cola.
2. El p99 **global** con M (≈ 512 ms) fue peor que lo predicho (350 ms): la ficha subestimó el costo de las llamadas que necesitan 2–3 intentos.
3. Sin M, el SLO global se cumple aunque la fase de confirmar lo rompa (p95 confirmar ≈ 400 ms ≈ límite): coincide con la "predicción no obvia" de la ficha.

## Corrección / re-experimento
No se re-ejecutó. Corrección prevista en la ficha (bajar el timeout por intento a 150 ms o *hedging*) quedaría como trabajo futuro: reduciría el p99 global pero aumentaría la carga sobre el stub (+24 % ya medido en la ficha).

## Limitaciones
- `con_r1` es un episodio de la plataforma no explicado (ráfaga de 500/502 y apertura del breaker); se documentó pero se excluyó de las cifras. Las dos repeticiones restantes coinciden entre sí.
- La métrica `stub_credito_idempotentes_total` (respuestas servidas desde caché) no se capturó, así que la predicción "30–60 % de reintentos servidos desde caché" **no se verificó**. Sí se verificó el invariante de negocio en el reset (ver `verificacion.txt` donde existe).

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
