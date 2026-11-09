# Estado final (perfil M + umbral 70 % + lock_timeout) · combinación A1 + D2 + B2 en caliente

Inyección en inicio_s = 21.5 s · kill switch en 58.7 s · se descartan 2 s en cada transición. Latencias del cliente en ms; error = 5xx o sin respuesta.

| Ventana | s | Solicitudes | % error global | % error confirmar | p50 | p95 | p99 | máx | p99 confirmar | máx confirmar | breaker_abierto | franja_bloqueada |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| antes | 9,5 | 1921 | 0,00 | 0,00 | 8,3 | 45,9 | 74,7 | 132 | 78,2 | 132 | 0 | 0 |
| durante | 35,2 | 7142 | 4,68 | 9,35 | 16,5 | 532,3 | 838,0 | 3 212 | 896,3 | 3 212 | 0 | 10 |
| despues | 24,3 | 4867 | 0,00 | 0,00 | 10,7 | 58,9 | 78,2 | 133 | 82,8 | 133 | 0 | 0 |

Causas de error en confirmar durante la falla: `503 HTTP 503` × 192, `503 TimeoutError: ` × 132, `503 franja_bloqueada` × 10
