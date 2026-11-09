# Demo en vivo · estado inicial vs estado final (misma combinación A1 + D2 + B2, misma carga y semilla)

Ventana DURANTE la falla. La comparación válida es esta: el estado final se comporta mejor *mientras* la falla está activa. Que ambos vuelvan a la línea base después del kill switch es recuperación, no corrección.

| Métrica (durante la falla) | Estado inicial | Estado final | Cambio |
|---|---:|---:|---:|
| % error global | 13,75 | 4,68 | -66 % |
| % error confirmar | 27,49 | 9,35 | -66 % |
| p95 global (ms) | 774,9 | 532,3 | -31 % |
| p99 global (ms) | 1 066,8 | 838,0 | -21 % |
| p99 confirmar (ms) | 1 117,3 | 896,3 | -20 % |
| máx confirmar (ms) | 34 833 | 3 212 | -91 % |
| respuestas breaker_abierto | 0 | 0 | — |
| 503 franja_bloqueada (lock_timeout) | 0 | 10 | — |

| Línea base (antes de inyectar) | Estado inicial | Estado final |
|---|---:|---:|
| % error global | 0,00 | 0,00 |
| % error confirmar | 0,00 | 0,00 |
| p95 global (ms) | 41,8 | 45,9 |
| p99 global (ms) | 54,3 | 74,7 |

SLO RNF-10 (p95 < 400 ms y error < 0,5 %) durante la falla: inicial NO cumple, final NO cumple.
