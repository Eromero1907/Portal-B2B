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

## 4. Entrega final: lo que se aplicó y lo que se midió (A/B intercalado, `make comparar-e2`)
P1 solo bajaba el tiempo en el servidor (1,93 → 1,46 ms) y quedaba dentro del ruido en el cliente, porque el costo dominante de Q4
no era el heap de órdenes sino los ~4 000 sondeos a `lineas_orden` por proveedor caliente. Para la entrega final se atacó esa causa:

| # | Métrica | Palanca aplicada | Resultado (máquina del E2, `ab-e2-e3-oficial`, 5 rondas E2→E3 intercaladas; réplica en la de JJ) | Costo medido |
|---|---|---|---|---|
| L4 | **Q4 caliente y frío** | Modelo de lectura de entregas: `unidades_pedidas`, `unidades_surtidas`, `entrega_completa` en `ordenes_compra`, mantenidas por triggers de sentencia con tablas de transición sobre `lineas_orden` (`modelo-fisico.sql`, fase `modelo_lectura`); Q4 ya no toca `lineas_orden` | p95 caliente 18,68 → **2,68 ms** (−86 %), p99 20,57 → **2,80 ms** (−86 %), p50 1,51 → 0,91 ms (−40 %), frío p50 1,00 → 0,79 ms (−21 %); sin solape entre rondas. Servidor: 23,1 → 2,5 ms. Réplica en la máquina de JJ: p95 15,70 → 2,76 ms (−82 %). Resultado **idéntico** al de la Q4 del E2 en 286 comparaciones (`equivalencia_q4.txt`) | +3,3 s en `make datos` (relleno); un `UPDATE` de la orden por cada sentencia que inserta/actualiza/borra líneas (la app inserta las líneas en una sola sentencia: 1 `UPDATE` por orden creada); pruebas 14/14 siguen en PASA |
| L5 | **Q5 OFFSET 5000** | El índice de L4 incluye también `numero_orden` y `total_orden` (`INCLUDE`): Q5 pasa de Bitmap Heap Scan + Sort a Index Only Scan ordenado | p50 4,98 → **1,31 ms** (−74 %), p95 6,57 → **1,77 ms** (−73 %), p99 7,29 → **2,63 ms** (−64 %); servidor 5,5 → 0,83 ms. Réplica (JJ): p95 7,83 → 1,98 ms (−75 %) | `idx_ordenes_proveedor_fecha` 12 → 30 MB; `estado` en el índice impide HOT en la confirmación (ya ocurría con P1) |
| — | Q1, Q2, Q3, Q5 página 1 / keyset | Ninguna (P5) | Dentro del ruido: el servidor ejecuta en ~0,05 ms y el cliente ve 0,7–1,5 ms (ida y vuelta + planificación) | Declaradas **no aplicables** con esta evidencia |

Tabla completa: `baseline/corridas/ab-e2-e3-oficial/tabla_e2_e3.md` (máquina del E2) y `ab-e2-e3-maquina-jj` (réplica) · figura: `Entrega 3/evidencia/resumen_graficas/e2_vs_e3_consultas.png`.
