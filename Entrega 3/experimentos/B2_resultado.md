# B2 · bloqueo FOR UPDATE de la franja 91150 — resultado (predicción vs medición, con dos correcciones)
**Cadena completa:** ficha original (2026-10-14) → falló el montaje → `B2_correccion_bloqueo_desde_t0.md` (2026-10-16 11:10) → la variante `lock0` descubrió un defecto de la aplicación → `B2_correccion_mapeo_lock_timeout.md` (2026-10-16 15:40, código corregido) → re-ejecución. **Veredicto: la ficha original falló por una suposición sobre el estado del sistema; el re-experimento sí ejercitó el bloqueo, confirmó el efecto de `lock_timeout` y destapó un 500 que ahora es un 503 controlado.**

## Ronda 1 — ficha original (`B2/{sin,con}_r1`, `sin_r2`)
Predicho: ≈ 12 confirmaciones bloqueadas, hasta 45 s. **Observado: 0.** Latencia máxima de `confirmar` 111–205 ms, 0 % de errores, con y sin `lock_timeout`. La sesión sí retuvo el bloqueo (verificación del controlador: `reteniendo bloqueo = 1`).
**Mecanismo:** la franja 91150 se llena a los 15,5 s del generador (durante el calentamiento); desde entonces `UPDATE … WHERE capacidad_reservada < capacidad_total` no encuentra fila candidata y PostgreSQL no espera el bloqueo de fila. El caso borde 4 (último cupo) quedó protegido (franja 10/10, 0 violaciones), pero la prueba no ejercitó el bloqueo.

## Ronda 2 — variante `lock0` (bloqueo desde el arranque, 60 s)
`sin-lock0_r{3,4}` y `con-lock0_r{3,4}` (antes del arreglo); `con-lock0_r{5,6}` (después). Se midieron 6 confirmaciones bloqueadas en la ventana (inicio_s ≥ 30) y 11 en total desde el arranque (5 cayeron durante el calentamiento).
| Métrica | Predicho | Observado |
|---|---|---|
| Confirmaciones bloqueadas medidas | "sin" ≈ 8 (3–14) | **6** (11 en total) ✓ |
| Latencia máxima "sin" | ≈ 25–30 s (primera tras el calentamiento) | **28,8 / 28,2 s** ✓ (máx. absoluto 46 s en el calentamiento) |
| Latencia de las bloqueadas "con M" | ≈ 2,1 s | **2,0–2,1 s** (9 de 11); 2 de ellas 2,9 y 3,2 s ✓/≈ (la segunda espera no se investigó) |
| Pool: `PoolTimeout` | no | **ninguno** ✓ |
| p95 / p99 global "sin" vs línea base | sin cambio | 47–49 / 62–75 ms ✓ |
| Invariante reservada ≤ total | 0 violaciones | **0** ✓; franja 10/10 |

## Ronda 3 — defecto descubierto y corregido
Con M, las 11 confirmaciones bloqueadas respondían **HTTP 500 `error_interno`** (r3 y r4), no el 503 `franja_bloqueada` que la ficha predecía: `LockNotAvailable` no estaba mapeada a la degradación. Corrección en `servicio.py` (captura `psycopg.errors.LockNotAvailable` → 503 `franja_bloqueada`, orden EN_PROCESO, clave liberada, `Retry-After`).
| Con M | Antes (r3 / r4) | Predicho después | Después (r6 / r5) |
|---|---|---|---|
| Respuestas bloqueadas | 11 × **500** | 503, 0 × 500 | **11 × 503 `franja_bloqueada`** / 12 × 503 ✓, 0 × 500 |
| % errores | 0,010 / 0,012 % | 0,010–0,012 % | **0,012 %** (r6) ✓ |
| `idempotencia_EN_CURSO` final | 0 | 0 | **0** ✓ |
| Violaciones / franja | 0 / 10/10 | 0 / 10/10 | **0 / 10/10** ✓ |
El generador cuenta 503 y 500 como error, así que el % no cambia: la mejora es de **calidad del error** (503 reintentable con `Retry-After`, orden recuperable, en lugar de un fallo interno).

## Resumen de lo que `lock_timeout` compra
Latencia de la peor confirmación bloqueada: **≈ 29 s (medida; 46 s total) → 2,0 s (−93 %)**, sin cambiar p95/p99 globales ni la corrección del inventario.

## Limitaciones
- `con-lock0_r5` tuvo un episodio ajeno a B2 entre inicio_s ≈ 120 y 200 (1 189 respuestas 503: 867 `breaker_abierto`, 307 `TimeoutError`, 3 `bulkhead_agotado`; EN_PROCESO = 1 189; p99 global 509 ms). La falla había terminado en t = 30 s. Se conserva como evidencia del arreglo (los 12 `franja_bloqueada` son del bloqueo) pero **no** se usa para métricas globales. `con-lock0_r6` es la corrida limpia (aunque su p50 previo es 11 ms: límite alto).
- Las métricas `portal_bd_lock_timeouts_total` y `portal_degradaciones_total{motivo="franja_bloqueada"}` de la ficha **no existían** en el código; el conteo sale de `solicitudes.csv` y de `portal_confirmaciones_total{causa="franja_bloqueada"}` (añadida con el arreglo).
- Las corridas `con-lock0_r{1,2}` y `sin-lock0_r{1,2}` se descartaron por equipo degradado (ver `LEEME_descartadas.md`).

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
