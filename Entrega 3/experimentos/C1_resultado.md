# C1 · saturación de CPU en app1 — resultado (predicción vs medición, con re-experimento)
**Evidencia:** `C1/{sin_r1,sin_r2,con_r1,con_r3}` (0,25 CPU) y `C1/{sin-cpu010_r1,con-cpu010_r1,con-cpu010_r2}` (0,10 CPU). **Veredicto: la ficha original falló por subestimar la capacidad de app1; con 0,10 CPU el mecanismo se confirma, pero el perfil M no aporta nada.**

## Ronda 1 — 0,25 CPU (ficha original)
| Métrica | Predicho "sin" | Observado "sin" (r1 / r2) | Observado "con" (r1 / r3) |
|---|---|---|---|
| Reparto app1 / app2 / app3 | 12 / 44 / 44 % | **26 / 37 / 37 %** ✗ | 26 / 37 / 37 % |
| p95 global | 380–480 ms | **51 / 59 ms** ✗ | 51 / 57 ms |
| p99 global | 1 200–1 600 ms | **125 / 167 ms** ✗ | 122 / 145 ms |
| p95 de app1 | > 800 ms | **100 / 125 ms** ✗ | 99 / 115 ms |
| % errores | ≈ 0 % | 0 % ✓ | 0 % ✓ |
Mecanismo del error: cada solicitud cuesta ≈ 4–5 ms de CPU, así que 0,25 CPU atiende ≈ 55 req/s, cercano a la cuota de app1 (67 req/s): `least_conn` la descargó solo a 26 %.

## Ronda 2 — 0,10 CPU (`C1_correccion_cpu010.md`, predicción previa 2026-10-16 11:05)
| Métrica | Predicho | Observado "sin" (r1) | Observado "con" (r1 / r2) |
|---|---|---|---|
| Reparto app1 | ≈ 11 % (8–15 %) | **11,6 %** ✓ | **10,4 / 10,8 %** ✓ |
| p95 / p99 de app1 | ≈ 300 / 700 ms (p95 150–600) | **394 / 603 ms** ✓ | **544 / 937** y **601 / 1 051 ms** (peor) |
| p95 global | ≈ 100 ms (60–200) | **98 ms** ✓ | **108 / 132 ms** ✓ |
| p99 global | ≈ 450 ms (200–900) | **300 ms** ✓ | **401 / 466 ms** ✓ |
| % errores | 0 % | 0,000 % (1 × 502) ✓ | 0 % ✓ |
| Rate limit (503 por `limit_req`) | no se activa | — | **0** ✓ |
| ¿SLO? | sí | **sí** | **sí** |
| Recuperación tras quitar el límite | ≤ 5 s | p95 aún 172–331 ms durante 60 s ✗ | p95 139–394 ms durante 60 s ✗ |

## Conclusiones
1. `least_conn` **sí** reparte por carga efectiva (33 → 26 → 11 %); no hace falta sacar a app1 de la rotación para mantener el SLO con la carga de 200 req/s.
2. **El perfil M no mejora C1**: el `limit_req` de 250 req/s nunca se activa (carga 200 req/s) y su única contribución es ruido; app1 con M queda peor en cola (p95 544–601 vs 394 ms) aunque con n=1 para "sin" no es concluyente.
3. La recuperación tarda ≈ 60 s en volver a p95 < 60 ms (la cola de app1 se drena), no ≤ 5 s.

## Limitaciones
- `sin-cpu010_r2` descartada (equipo degradado): "sin 0,10" tiene **una sola repetición válida**, por lo que la comparación con/sin a 0,10 CPU es indicativa, no concluyente.
- `RATE_LIMIT_*` no estaba conectado en la aplicación: se implementó en nginx (`docker-compose.ratelimit.yml`, `infra/nginx/nginx.ratelimit.conf`) y la "ficha" se evalúa con esa implementación.

## Validez de las corridas (común a los 8 experimentos)
- Ventanas en `inicio_s` del generador (= t de la ficha + 30 s de calentamiento + ≈ 1 s). Ventana de falla de 300 s = [91, 391).
- Criterio de validez: mediana (p50) de la ventana previa a la falla (inicio_s 31–90) ≈ 7 ms. Las corridas con p50 previo ≥ ≈ 12–15 ms (equipo con throttling) se renombraron `*_descartada` y se repitieron; la lista y el motivo están en `Entrega 3/evidencia/LEEME_descartadas.md`.
- Reloj: el reloj monotónico del contenedor avanza ≈ 4 % más rápido que el de pared. El script programa las fallas con `docker exec … date/sleep`, así que el inicio/fin real de la falla puede desviarse unos segundos respecto de la ficha.
- Las fichas `<ID>.md` (2026-10-14) no se editaron. Todo lo que cambió después está en este archivo o en los `<ID>_correccion_*.md` con fecha y hora de predicción previa a la re-ejecución.
- Cada corrida válida: `Entrega 3/evidencia/<ID>/<config>_r<n>/` (solicitudes.csv, resumen.json, eventos.log, manifest.txt, recursos.csv, verificacion.txt).
