# B2 · Corrección de código: `LockNotAvailable` debe degradarse a 503 controlado (predicción previa a la re-ejecución)
**Fecha de la predicción:** 2026-10-16 16:05 (-05:00), **antes** de ejecutar la corrección. Las fichas `B2.md` y `B2_correccion_bloqueo_desde_t0.md` no se modifican.
**Config de la corrida:** `bash faults/experimento.sh B2 con-lock0 <rep>` (perfil M, bloqueo de la franja 91150 desde el arranque durante 60 s) con la imagen reconstruida con el cambio.

## Qué falló (evidencia: `Entrega 3/evidencia/B2/con-lock0_r3`, `con-lock0_r4`)
La ficha B2 predijo, para "con M": *"cada UPDATE bloqueado aborta a los 2 s (`LockNotAvailable`). La degradación lo traduce a un 503 controlado (`causa: franja_bloqueada`, orden EN_PROCESO, clave libre, `Retry-After`)"*
y, como corrección prevista: *"Si con M aparece un 500 en lugar de un 503: falta mapear `LockNotAvailable` a la degradación."* **Es exactamente lo que ocurrió:**
las 6 confirmaciones bloqueadas (en r3 y en r4) terminaron a los ≈ 2,0–2,9 s con **HTTP 500 `error_interno`**, no 503. El `lock_timeout` sí funcionó (de 28 s sin M a 2 s con M), pero el error
no estaba mapeado: solo `CreditoNoDisponible` tenía degradación. Las métricas `portal_bd_lock_timeouts_total` y `portal_degradaciones_total` citadas en la ficha **no existían** en el código.

## Cambio
`servicio.py::confirmar` captura `psycopg.errors.LockNotAvailable` y responde 503 `{"error":"franja_bloqueada","causa":"franja_bloqueada","estado":"EN_PROCESO"}` con `Retry-After`, libera la clave de
idempotencia y cuenta `portal_confirmaciones_total{resultado="no_disponible",causa="franja_bloqueada"}`. La reserva no se crea (T1 hace ROLLBACK), así que no hay efectos que deshacer.

## Predicción numérica (con M, variante lock0, ventana medida)
| Métrica | Antes de la corrección (r3, r4) | **Después (predicción)** |
|---|---|---|
| Confirmaciones bloqueadas medidas | 6 y 6 | **6 ± 3** (mismo plan de carga y semilla: probablemente 6) |
| Código de esas respuestas | 500 `error_interno` | **503 `franja_bloqueada`** con `Retry-After: 5` |
| Latencia de esas respuestas | 2,0–2,9 s | 2,0–2,9 s (igual: la causa es el `lock_timeout`) |
| Respuestas 500 de la corrida | 6–7 | **0** (salvo un 502 espurio de nginx como el de r4, que no depende del cambio) |
| % de errores 5xx medido por el generador | 0,010–0,012 % | **0,010–0,012 %** (el generador cuenta 503 como error igual que 500; el cambio es de *calidad* del error, no de cantidad) |
| p95 / p99 global | 46–62 / 58–182 ms | sin cambio |
| `idempotencia_EN_CURSO` al final | 0 | 0 (la clave se libera) |
| Invariante reservada ≤ total | 0 violaciones | 0 violaciones |
| Franja 91150 al final | 10/10 | 10/10 |

Criterio de fallo: si siguen apareciendo 500, el error no es `LockNotAvailable` directo (p. ej. envuelto por el pool); se revisaría el tipo en el cuerpo del 500 (`tipo`) antes de seguir.
