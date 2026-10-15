# Palancas de mejora para la meta −10 % (Entregable 3)
**Autor:** JJ (relevo 1). **Las aplica y revalida:** Santiago (relevo 3), en el estado corregido y en la máquina del E2.
**Regla de la rúbrica:** la comparación conserva la misma consulta, escenario, métrica y condición de carga. Una palanca
es válida solo si **no cambia la condición de medición** (mismo cliente, misma máquina, mismos parámetros de entrada,
mismos datos). Objetivos de cada métrica: `baseline/objetivos.csv`. Comparación de una corrida:
`python baseline/objetivos.py comparar --corrida baseline/corridas/<id>`.

Cada palanca se aplica de a una, se re-mide con `make baseline` (o solo el paso afectado) y se registra en el informe
con su efecto y su costo. Ninguna es caché: el curso prohíbe “caché para tapar una consulta mal indexada sin decirlo”.

## 1. Primero: medir el ruido
Antes de atribuir una mejora, comparar las corridas repetidas de la línea base (`CORRIDAS=3` deja `q1q5_1..3`;
columna `rango_entre_corridas_pct` de `comparacion_e2.csv`). El propio E2 ya mostró que dos corridas del mismo
protocolo difieren hasta 0,87 ms en un p99 de Q3 (§3.2.1 del plan). **Una “mejora” más pequeña que el rango entre
corridas no es una mejora**: se declara “dentro del ruido”.

## 2. Palancas por métrica

| # | Métrica (objetivo E3) | Palanca | Por qué debería funcionar | Costo / riesgo a medir |
|---|---|---|---|---|
| P1 | **Q4 caliente** p95 10,053 ms · p99 10,332 ms | Índice covering de órdenes: `(proveedor_id, fecha_emision DESC, id DESC) INCLUDE (estado, fecha_compromiso, fecha_entrega)` | El plan del E2 hace Bitmap Heap Scan de las ~5 293 órdenes del proveedor 1 para leer estado y fechas; con las columnas en el índice pasa a Index Only Scan (sin visitas al heap). El p95 caliente (≈ 10× el p50) lo dominan justo los proveedores con más órdenes. Ojo: el E2 también mostró ~4 000 sondeos de `idx_lineas_orden` en Nested Loop; si ese es el costo dominante, P1 rinde poco y hay que decirlo | Índice más grande (tamaño a medir) y `estado` deja de permitir updates HOT en la confirmación (EN_PROCESO → CONFIRMADA): medir el costo en la ruta de confirmación |
| P2 | **Q4 frío y caliente** | `SET jit = off` para la sesión de medición o en el servidor | Con consultas de pocos ms, si el planificador activa JIT el tiempo de compilación pesa; verificar con `EXPLAIN (ANALYZE)` si aparece `JIT:` | Solo aplica si el plan muestra JIT; si no aparece, se descarta y se documenta |
| P3 | **Q5 OFFSET 5000** p95 2,403 ms | Que el planificador recorra el índice en orden en lugar de Bitmap + Sort de 5 293 filas (p. ej. ajustar `random_page_cost` a 1,1, adecuado para SSD/caché completa) | El E2 mostró que con Bitmap el OFFSET profundo paga un Sort completo; con Index Scan ordenado se salta las filas sin ordenar | Cambiar `random_page_cost` afecta todos los planes: re-medir Q1–Q5 completas para ver efectos colaterales |
| P4 | **Q2** p95 0,576/0,594 ms | Ya es Index Only Scan de 20 filas: no hay palanca de índice. Candidata: `VACUUM` previo garantizado (Heap Fetches = 0) | Las páginas all-visible evitan visitas al heap | Probablemente dentro del ruido: declararlo |
| P5 | **Q1, Q3, Q5 página 1 / keyset** (~0,5–0,8 ms) | Ninguna palanca de base de datos razonable: el tiempo lo domina la ida y vuelta cliente → Docker → PostgreSQL (~0,5 ms) | — | Declarar “no aplicable” con la evidencia del ruido (§1), como permite la rúbrica (“métricas aplicables”) |
| P6 | **Q3 concurrente** 16/32/64 hilos | `max_connections`/tamaño de pool y `shared_buffers` ya holgados; candidata: `effective_io_concurrency` y planes sin paralelismo para consultas cortas (`max_parallel_workers_per_gather = 0`) | Con 64 conexiones, lanzar workers paralelos para consultas de 1 ms compite por CPU | Medir throughput además de percentiles; ojo: el throughput de Q3 concurrente del E2 es un artefacto (ver `referencia_e2.json`, `nota_concurrencia_q3`) y no es objetivo |
| P7 | **Carga masiva** COPY ≤ 14,065 s · total ≤ 22,415 s | `\copy` de tablas independientes en paralelo (proveedores, catálogo, franjas, auditoría no dependen entre sí) y `maintenance_work_mem` alto solo durante la creación de índices | El COPY es secuencial tabla a tabla; las tablas sin FK entre sí se pueden cargar a la vez | Más CPU/IO concurrente; verificar que los conteos y `make verificar` siguen en PASA |
| P8 | **E4 ruta transaccional** ≤ 437,78 s (≥ 502 filas/s) | Validar todas las líneas de una orden en una sola consulta (`unnest` de arreglos, como hace la app del E3) en lugar de una consulta por línea | El E4 del E2 hace hasta 300 idas y vueltas por orden en la validación de catálogo | Cambia el código del benchmark: documentarlo como mejora de la ruta, no del motor |
| P9 | **E2/E3 lotes y fila a fila** | `synchronous_commit = off` **solo** si se declara la pérdida de durabilidad | Elimina la espera de flush del WAL por commit | Cambia la garantía de durabilidad: si se usa, debe quedar explícito que es otra condición; recomendación: **no usarla** para la meta |

## 3. Recomendación
Atacar primero **P1 (Q4 caliente)** y **P8 (E4)**: son las métricas donde la mejora puede superar con holgura el ruido.
P3 y P7 son las siguientes. Para P5 la conclusión honesta es “no aplicable”, sustentada con el ruido medido.
