# Estado inicial (sin resiliencia) · combinación A1 + D2 + B2 en caliente

Inyección en inicio_s = 21.6 s · kill switch en 59.0 s · se descartan 2 s en cada transición. Latencias del cliente en ms; error = 5xx o sin respuesta.

| Ventana | s | Solicitudes | % error global | % error confirmar | p50 | p95 | p99 | máx | p99 confirmar | máx confirmar | breaker_abierto | franja_bloqueada |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| antes | 9,6 | 1935 | 0,00 | 0,00 | 7,6 | 41,8 | 54,3 | 106 | 63,6 | 106 | 0 | 0 |
| durante | 35,4 | 7209 | 13,75 | 27,49 | 9,0 | 774,9 | 1 066,8 | 34 833 | 1 117,3 | 34 833 | 0 | 0 |
| despues | 24,0 | 4824 | 0,00 | 0,00 | 17,9 | 74,3 | 94,3 | 155 | 105,4 | 155 | 0 | 0 |

Causas de error en confirmar durante la falla: `503 HTTP 503` × 991
