# Corridas descartadas (`*_descartada`)

Se conservan como evidencia, pero **no entran en ninguna comparación ni en el informe como resultado**.
Criterio: en la ventana *previa* a la falla (inicio_s 31–90 s, antes de inyectar nada) el p50 supera ~12 ms, cuando en las corridas sanas es de ~7 ms.
Es decir, el equipo ya estaba degradado antes de la falla, por lo que no se puede atribuir el efecto observado a la falla.

| Carpeta | p50 previo a la falla | Observación |
|---|---|---|
| D1/con_r2, B2/con_r2, C2/con_r2, B1/con_r2, C1/con_r2 | 16–20 ms | corridas consecutivas desde las 10:14 UTC-5; causa no identificada |
| D1/con_r3 | 16,5 ms (p95 414 ms) | portátil sin enchufar y expuesto al calor (reconocido por el operador) |
| B2/{sin,con}-lock0_r{1,2} | 14–70 ms | ídem |
| D2/con-umbral70_r{1,2} | 46–55 ms; r2 llegó a p95 de 13,7 s y retraso del generador de 1,2 s | ídem |

Las repeticiones válidas llevan los números siguientes (r3/r4 según el caso) y se corrieron con el equipo enchufado en modo de alto rendimiento.
Causa de la degradación: no demostrada. Con las dos últimas tandas coincide con el equipo sin enchufar y al sol.
| C1/sin-cpu010_r2 | 15,4 ms (p95 346 ms) | arranque degradado antes de la falla; cpu010 sin queda con 1 sola corrida válida (r1) |
