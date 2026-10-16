# D2 · Corrección: umbral del Circuit Breaker de 50 % a 70 % (predicción previa a la re-ejecución)
**Fecha de la predicción:** 2026-10-16 11:00 (-05:00; escrita a las 10:58), **antes** de ejecutar la corrección. La ficha original `D2.md` (2026-10-14) no se modifica.
**Config de la corrida:** `bash faults/experimento.sh D2 con-umbral70 <rep>` = perfil M (`docker-compose.resiliencia.yml`) + `docker-compose.var-umbral70.yml`
(único cambio: `BREAKER_UMBRAL_FALLOS_PCT=70`). Misma carga, semilla y falla que D2 (503 con probabilidad 50 %, t=60–360 s).

## Qué falló en la predicción original (evidencia: `Entrega 3/evidencia/D2/{sin,con}_r{1,2}`)
| Métrica (ventana de falla) | Predicho "con M" | Observado "con M" (2 reps) | Observado "sin" (2 reps) |
|---|---|---|---|
| % errores 5xx | ≈ 13,5 % (igual que sin) | **21,0 %** (12 549 y 12 505 de 59 582) | 13,4 % |
| Causa de los 503 | rechazos rápidos | 12 642–12 817 por `breaker_abierto`; solo 187–190 por 503 real del stub | 100 % por el 503 del stub |
| p95 global | 50–70 ms | 35–39 ms | 43–55 ms |
| p99 global | no predicho | **170–194 ms** | 55–80 ms |

**Mecanismo.** La falla inyectada devuelve 503 con probabilidad 50 %, **exactamente el umbral** del breaker (50 %). La tasa de fallos observada en la ventana de 10 s
oscila alrededor del umbral por puro ruido estadístico, así que el breaker se abre una y otra vez. Mientras está abierto, el 100 % de las llamadas al crédito se
rechaza sin intentarlo, aunque el stub respondería bien la mitad de las veces. La falla era *intermitente* (recuperable con un reintento) y el breaker la trató como una
caída total: el remedio empeoró el error de 13,4 % a 21 %. Los reintentos del perfil M quedaron sin efecto, porque el breaker abierto corta antes de reintentar.

## Cambio propuesto
Subir `BREAKER_UMBRAL_FALLOS_PCT` a **70 %**. Una falla intermitente del 50 % no debe abrir el breaker; una caída real del crédito (≈ 100 % de fallos, caso del que el breaker
sí debe protegernos) sigue superando el 70 %. Así los reintentos (`REINTENTOS_MAX=3`, backoff 50–400 ms, presupuesto 1 500 ms) absorben el 50 % intermitente.

## Hipótesis
1. El breaker **no se abre** durante la falla (la tasa de fallos por intento ronda 50 %, bastante por debajo de 70 % incluso con ruido en ventanas de 10 s con ≥ 20 llamadas): 0 transiciones
   `cerrado→abierto` (esperadas ≤ 2 por ruido en las 6 instancias-minuto; si aparece más de una por instancia, la hipótesis falla).
2. Cada llamada lógica al crédito hace hasta 4 intentos (`max_intentos = 1 + REINTENTOS_MAX`, `resiliencia.py:183`) con backoff de full jitter (techo 50, 100, 200 ms) y el breaker
   registra **cada intento**, no cada llamada lógica. Con 50 % de fallos independientes, una llamada lógica falla con probabilidad 0,5^4 = **6,25 %**. El 54 % de las confirmaciones
   (≈ 27 % de las solicitudes) llega al crédito, así que el error global esperado es 0,0625 × 27 % ≈ **1,7 %**.
3. Costo: los reintentos agregan espera (backoff 50, 100, 200… ms más el reintento) a las llamadas que fallan al primer intento (≈ 13,5 % de todas las solicitudes).
   Eso sube el p95 y sobre todo el p99 frente a la línea base.

## Predicción numérica (ventana de falla, inicio_s 91–391)
| Métrica | D2 sin | D2 con (umbral 50, observado) | **D2 con umbral 70 (predicción)** |
|---|---|---|---|
| % errores 5xx global | 13,4 % | 21,0 % | **≈ 1,7 %** (rango 1–3 %) |
| Respuestas `breaker_abierto` | 0 | ≈ 12 700 | **≈ 0** (< 100 en total) |
| Transiciones del breaker a abierto (suma de 3 instancias) | — | decenas | **0–3** |
| p50 global | 6,4 ms | 6,0 ms | ≈ 6–8 ms |
| p95 global | 43–55 ms | 35–39 ms | **≈ 60–120 ms** (sube por los reintentos) |
| p99 global | 55–80 ms | 170–194 ms | **≈ 150–400 ms** |
| ¿SLO RNF-10 (p95 < 400 ms y errores < 0,5 %)? | NO (errores) | NO (errores) | **NO por errores** (≈ 1,7 % > 0,5 %); p95 sí cumple |
| Negocio | 0 aprobaciones sin crédito (RN-11) | ídem | ídem; las órdenes con crédito fallido quedan EN_PROCESO con la reserva liberada |

**Lo que NO esperamos lograr:** cumplir el SLO de errores. Con 50 % de fallas y 3 reintentos queda un residuo de 6,25 % de las llamadas al crédito, es decir ≈ 1,7 % de las solicitudes. Cumplirlo exigiría
más reintentos o una respuesta degradada aceptable (p. ej. aprobar con crédito en cola), que viola RN-11 y no se propone.

## Cómo se evalúa
- Comparar con `D2/con_r1`, `D2/con_r2` y `D2/sin_r*` sobre la misma ventana. Criterio de éxito: errores < 21 % (peor que "sin" sería un fracaso) y `breaker_abierto` ≈ 0.
- Si el p99 > 400 ms: bajar `REINTENTOS_PRESUPUESTO_MS` o `REINTENTOS_TOPE_MS`.
- Si el breaker sigue abriéndose con 70 %: la tasa por intento supera 70 %, o la ventana cuenta fallos por llamada lógica y no por intento. Se revisaría `app/portal/resiliencia/` antes de cambiar números.
- Prueba de que el breaker **sigue protegiendo** ante caída real: no se repite D2 con 100 % de fallos (fuera del alcance de las 8 fallas); se anota como límite de la corrección.
