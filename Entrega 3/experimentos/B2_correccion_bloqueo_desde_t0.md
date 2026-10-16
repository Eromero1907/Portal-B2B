# B2 · Corrección del montaje: el bloqueo debe caer cuando la franja 91150 aún tiene cupo (predicción previa a la re-ejecución)
**Fecha de la predicción:** 2026-10-16 11:10 (-05:00), **antes** de ejecutar la variante. La ficha `B2.md` (2026-10-14) no se modifica.
**Config de la corrida:** `bash faults/experimento.sh B2 <sin|con>-lock0 <rep>`: igual que B2, pero el bloqueo `FOR UPDATE` sobre `logistica.franjas_cedi` id=91150 se toma en
el instante en que arranca la carga (t = −30 s de la ficha) y se retiene 60 s (hasta ≈ t = +30 s de la ficha, es decir 30 s dentro de la ventana medida).

## Qué falló en la predicción original (evidencia: `Entrega 3/evidencia/B2/{sin,con}_r{1,2}`)
La ficha predijo ≈ 12 confirmaciones bloqueadas con latencias de hasta 45 s. **Observado: cero.** Máximo de latencia de `confirmar` de 111–205 ms en las 4 corridas, 0 solicitudes > 500 ms,
p99,9 de 74–79 ms y 0 % de errores, tanto sin como con `lock_timeout`. La verificación del controlador confirmó que la sesión sí retuvo el bloqueo (`reteniendo bloqueo = 1`).

**Mecanismo.** La ficha supuso que la franja seguía en 9/10 en t=60 s. Pero el 0,5 % de los flujos que usa la franja 91150 (≈ 0,27 confirmaciones/s) la llena en los primeros segundos de la carga:
la primera confirmación aprobada toma el último cupo (10/10). **Medido:** esa confirmación ocurre a los 15,5 s del generador (durante el calentamiento) y la primera `sin_cupo_franja` a los 25,0 s, idéntico en las 4 corridas (misma semilla). Desde entonces el `UPDATE … WHERE capacidad_reservada < capacidad_total` no encuentra ninguna fila que cumpla el predicado
y devuelve 0 filas **sin esperar el bloqueo de fila**, porque PostgreSQL solo espera cuando una fila *candidata* está bloqueada. Las ≈ 80 confirmaciones restantes salen `sin_cupo_franja`
(RECHAZADA), idéntico con y sin bloqueo. Verificación final: franja 10/10 y 0 violaciones de la invariante. El caso borde 4 (último cupo) quedó **correctamente protegido**, pero B2 no ejercitó el bloqueo.

**Lección para el informe:** una predicción puede fallar por una suposición sobre el *estado* del sistema y no solo sobre su comportamiento. El montaje exigía reproducir el estado (franja con cupo) en el instante de la falla.

## Cambio propuesto
Inyectar el bloqueo antes de que la franja se llene: `INICIO_S=-30` (activación en el arranque de la carga) y `DURACION_FALLA_S=60`. Con la semilla 42 la primera confirmación sobre la franja llega a los 15,5 s: desde ahí hasta el desbloqueo (≈ 62 s del generador) llegan ≈ 12 confirmaciones; las ≈ 4 del calentamiento no se miden pero
ocupan conexiones del pool. Los que llegan entre t=0 y el desbloqueo (≈ 30 s) son medidos.

## Predicción numérica (variante `lock0`)
| Métrica | Línea base | Sin mecanismos | Con M (`lock_timeout` 2 s) |
|---|---|---|---|
| Confirmaciones bloqueadas medidas | 0 | **≈ 8** (rango 3–14) | ≈ 8 respuestas 503 `franja_bloqueada` (mismo rango) |
| Latencia máxima de `confirmar` | ~130 ms | **≈ 25–30 s** (la primera en llegar tras el calentamiento) | **≈ 2,1 s** |
| p95 / p99 global | 43–55 / 55–80 ms | sin cambio (< +10 ms): 8 solicitudes de ~59 000 | sin cambio |
| p99,9 de `confirmar` | ~80 ms | **sube a > 1 s** (8/30 000 = 0,027 % > 0,01 %) | ≈ 2 s |
| % errores 5xx | 0 % | ≈ 0 % (ninguna supera el timeout de 60 s del cliente) | ≈ 0,014 % (8 de ~59 000) |
| ¿SLO cumple? | sí | sí | sí |
| Pool de BD | ~2 conexiones/instancia | pico de ≈ 12 conexiones retenidas en total (≈ 4 por instancia de 10); `en_espera` ≈ 0 | ≤ 1 retenida |
| Tras liberar el bloqueo | — | la primera de la cola toma el último cupo; el resto sale `sin_cupo_franja` (RECHAZADA); franja 10/10 | la franja se llena con la siguiente confirmación posterior |
| Invariante reservada ≤ total | 0 violaciones | **0 violaciones** | **0 violaciones** |

Si el pico de conexiones retenidas supera 8 por instancia (de 10, muy por encima de lo previsto), aparece `PoolTimeout` y la predicción falla: ahí la corrección obligatoria es `lock_timeout`, como indica la ficha.
