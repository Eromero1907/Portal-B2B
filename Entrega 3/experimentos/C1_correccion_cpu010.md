# C1 · Re-ejecución con una falla más intensa: app1 limitada a 0,10 CPU (predicción previa a la re-ejecución)
**Fecha de la predicción:** 2026-10-16 11:05 (-05:00), **antes** de ejecutar la variante. La ficha `C1.md` (2026-10-14) no se modifica.
**Config de la corrida:** `bash faults/experimento.sh C1 <sin|con>-cpu010 <rep>`: igual que C1 (t=60–360 s, 200 sol/s) pero `docker update --cpus 0.10 portal-app1` en lugar de 0,25.
"con" mantiene el perfil M + `limit_req` global de 250 req/s con ráfaga 100 en nginx.

## Qué falló en la predicción original (evidencia: `Entrega 3/evidencia/C1/{sin,con}_r1`, `sin_r2`)
| Métrica (ventana de falla) | Predicho "sin" | Observado "sin" (2 reps) | Observado "con" (r1) |
|---|---|---|---|
| Reparto app1 / app2 / app3 | 12 / 44 / 44 % | **26 / 37 / 37 %** | 26 / 37 / 37 % |
| p95 global | 380–480 ms | **51–59 ms** | 51 ms |
| p99 global | 1 200–1 600 ms | 125–167 ms | 122 ms |
| % errores | ≈ 0 % | 0 % | 0 % |
| p95 de la propia app1 | > 800 ms | **100–124 ms** | 99 ms |

Con 0,25 CPU, `app1` seguía atendiendo ≈ 26 % del tráfico (≈ 52 sol/s) con p95 de ≈ 100 ms: la CPU media de app1 fue ≈ 23 % de un núcleo (`recursos.csv`),
es decir, trabajaba pegada al tope pero **cada solicitud cuesta ≈ 4–5 ms de CPU** y 0,25 CPU alcanza para ≈ 55 sol/s. La predicción original sobreestimó el costo por solicitud.
El balanceador `least_conn` sí actuó (33 % → 26 %). El rate limit de 250 req/s no se activó (la carga es 200 sol/s): 0 respuestas 503, idéntico a "sin".
La falla no estresó el sistema porque la carga de la línea base es baja frente a su capacidad.

## Cambio propuesto
Reducir el tope a **0,10 CPU** (capacidad de app1 ≈ 22 sol/s) para estar de verdad por debajo de su cuota de tráfico (67 sol/s) y obligar a `least_conn` a desviar la mayor parte.

## Predicción numérica (ventana inicio_s 91–391)
| Métrica | Línea base | Sin (cpu 0,10) | Con (cpu 0,10 + rate limit) |
|---|---|---|---|
| Reparto app1 / app2 / app3 | 33 / 33 / 33 % | **≈ 11 / 44 / 44 %** (rango app1 8–15 %) | igual |
| p95 / p99 de app1 | 45 / 55 ms | **≈ 300 / 700 ms** (rango p95 150–600) | igual |
| p95 global | 43–55 ms | **≈ 100 ms** (rango 60–200) | ≈ 100 ms |
| p99 global | 55–80 ms | **≈ 450 ms** (rango 200–900) | ≈ 450 ms |
| % errores | 0 % | 0 % | **0 %**: el rate limit no se activa (200 < 250 req/s) |
| ¿SLO cumple? | sí | sí (p95 < 400 ms) | sí |
| Recuperación tras quitar el límite | — | ≤ 5 s | ≤ 5 s |

Criterio de fallo: si app1 sigue con > 20 % del tráfico, `least_conn` no equilibra por tasa sino por conexiones activas y la hipótesis del mecanismo es incorrecta.
Si el p95 global supera 400 ms, el desvío es insuficiente y la corrección sería sacar a app1 de la rotación con `max_fails`/`fail_timeout` ajustados.
