# Guion Minuto a Minuto — Sustentación Entrega 3 (15 Minutos)

**Fecha de presentación**: Lunes 9 de noviembre  
**Duración total**: 15 minutos exactos  
**Presentación interactiva**: [`Entrega 3/presentacion_15min.html`](./presentacion_15min.html)

---

## Preparación Previa (5 minutos antes de pasar al frente, en el computador con Docker)

Ejecutar en una terminal lista antes de iniciar los 15 minutos:

```bash
# 1. Asegurar que la plataforma y observabilidad estén arriba
make plataforma
make observabilidad

# 2. Tener abiertas 3 pestañas en el navegador:
#    - Pestaña 1: Entrega 3/presentacion_15min.html (Presionar "Iniciar Reloj 15m" al empezar)
#    - Pestaña 2: Grafana (http://localhost:3000 -> Dashboard "Portal B2B - Observabilidad")
#    - Pestaña 3: Jaeger (http://localhost:16686)
```

---

## Bloque 1 (00:00 – 03:30) · Las 8 Fallas, su Combinación y Comportamiento con Observabilidad
*(Diapositivas 1, 2 y 3)*

1. **Qué mostrar**:
   - Diapositiva 2: Tabla de las 8 fallas (`A1`, `A2`, `B1`, `B2`, `C1`, `C2`, `D1`, `D2`) distribuidas en las 4 familias (Red/Stubs, Base de Datos, Recursos/Colas e Instancias/5xx) y su reflejo inmediato en Grafana (RED + USE) y Jaeger (`trace_id` correlacionado en logs JSON).
   - Diapositiva 3: **Explicación explícita de las combinaciones de fallas**:
     - **A1 + D2 (Stubs simultáneos)**: Sin aislamiento, una petición que sobrevive a `credito` tras esperar reintentos se topa con `tributaria` bloqueada 2.5 s, agotando los workers. Con nuestro diseño, cada dependencia tiene su propio `Bulkhead(8)`, `Timeout(0.8s)` y `CircuitBreaker(70%)` independiente.
     - **B2 + A1/A2 (Lock SQL + Latencia de red)**: Las llamadas HTTP a los stubs ocurren **antes** de abrir la transacción en PostgreSQL; nunca se retiene un `SELECT ... FOR UPDATE` en `franja_entrega` esperando red, y el lock tiene `SET LOCAL lock_timeout = '2000ms'`.
     - **D1 + C1 + C2 (Falla de infraestructura combinada)**: Mientras `app2` muere con `SIGKILL` (D1) y `app1` sufre throttling a 0.10 CPU (C1), Nginx `least_conn` enruta hacia `app3` y el patrón **Transactional Outbox** absorbe la pausa de RabbitMQ (C2) con 0 ms de impacto en el `POST /ordenes/{id}/confirmar`.

---

## Bloque 2 (03:30 – 06:30) · Reproducción de Fallas en Vivo — Estado Inicial ("Sin" Resiliencia)
*(Diapositiva 4 + Terminal en vivo)*

1. **Qué ejecutar en vivo**:
   ```bash
   make demo-vivo
   ```
   *(O si desean mostrar la prueba de humo completa de las 8 fallas: `make humo`)*
2. **Qué narrar mientras corre la Fase 1 (Estado Inicial — `sin` resiliencia)**:
   - Mostrar cómo con `docker-compose.sin-resiliencia.yml` (timeouts de 30 s, 0 reintentos, sin bulkhead ni circuit breaker), al activar la combinación `A1 + D2 + B2`:
     - En **A1**, la latencia p95 sube de **72 ms a 2,566 ms** y el throughput cae un **44%** (de 21.7 a 12.1 req/s).
     - En **B2**, las transacciones sobre la franja `91150` se quedan colgadas en `pg_locks` durante **28.83 segundos**.
     - En **D2**, el 50% de error en el stub de crédito se traduce en **13.4% de errores HTTP 502** directos al cliente.

---

## Bloque 3 (06:30 – 09:30) · Análisis de Resultados y Aprendizaje
*(Diapositivas 5 y 6)*

1. **Qué ocurrió y qué corregimos (los 3 hallazgos experimentales clave)**:
   - **Hallazgo 1 — D2 (Circuit Breaker Flapping)**: Sin resiliencia el error era `13.4%`. Con el Perfil M inicial (umbral del breaker en 50%), el error **empeoró a `21.0%`** porque la falla inyectada era de 50%, haciendo oscilar el breaker (`12,817` rechazos por `breaker_abierto`). **Corrección**: Subimos `BREAKER_UMBRAL_FALLOS_PCT=70` (`docker-compose.var-umbral70.yml`), permitiendo que los 2 reintentos con *exponential backoff + full jitter* absorbieran las fallas transitorias y bajando el error a **`1.71%–2.72%`** (−87%).
   - **Hallazgo 2 — B2 (Agotamiento en warmup + Bug HTTP 500)**: Al disparar el lock a $t=60\text{ s}$, hubo `0` bloqueos porque la franja `91150` tenía 9/10 cupos ocupados y se llenó a los $15.5\text{ s}$. Al mover el lock a $t=0\text{ s}$ (`lock0`), el `lock_timeout = 2000ms` bajó la espera de `28.8 s` a `2.0 s`, pero destapó un bug: `psycopg.errors.LockNotAvailable` no se capturaba y devolvía **11 × HTTP 500**. **Corrección en código**: Capturamos `LockNotAvailable` en `app/portal/modulos/ordenes/interno/servicio.py` y devolvemos **HTTP 503 `franja_bloqueada`** con `Retry-After: 5` (**0 HTTP 500** en `r5/r6`).
   - **Hallazgo 3 — C1 (Holgura de CPU y `least_conn`)**: `0.25 CPU` no saturaba `app1` (~4.5 ms CPU/req). Al bajar a `0.10 CPU` (`cpu010`), el p95 de `app1` subió a `394 ms` y comprobamos cómo Nginx `least_conn` desvió el tráfico (`10.4%` a `app1` vs `44.8%` a `app2/app3`), manteniendo el p95 global en `98–132 ms`.

2. **Qué sabemos ahora que NO volveríamos a hacer (5 lecciones)**:
   1. **Nunca** configurar el umbral de un Circuit Breaker igual o inferior a la tasa de falla transitoria que los reintentos pueden recuperar.
   2. **Nunca** activar un timeout en base de datos (`lock_timeout` / `statement_timeout`) sin mapear su excepción en la capa de servicio a un código HTTP 503 reintentable con `Retry-After`.
   3. **Nunca** programar la inyección de contención sobre un recurso con cupo finito sin calcular antes su tiempo de agotamiento ($T_{\text{agotamiento}}$) bajo la tasa de llegada del generador.
   4. **Nunca** elegir un límite de CPU de caos sin medir primero el costo real de CPU por request (`cpu_seconds / req`).
   5. **Nunca** dejar desalineados los códigos transitorios del servidor (`409 confirmacion_en_curso`, `503`) respecto a la tupla `CODIGOS_REINTENTABLES` del cliente.

---

## Bloque 4 (09:30 – 12:30) · Corrección, Reexperimentación y Comunicación (Estado Final)
*(Diapositiva 7 + Fase 2 de `make demo-vivo`)*

1. **Qué mostrar**:
   - Las **30 corridas (`r1..r6`)** con predicciones fechadas en Git antes de medir (`Entrega 3/predicciones.md`).
   - La tabla y gráfica del Estado Inicial vs Intermedio vs Estado Final Corregido:
     - **A1**: p95 cae **−64%** (`2,566 ms` → `931 ms`), throughput sube **+45%** (`12.1` → `17.5 req/s`).
     - **A2**: p99 cae **−27%** (`1,416 ms` → `1,037 ms`), cortando colas de hasta 12 s en ~800 ms.
     - **B2**: espera máxima cae **−93%** (`28.83 s` → `2.04 s`) y **0 errores HTTP 500**.
     - **D2**: tasa de error global cae **−87%** (`13.4%` → `1.71%`).
     - **Invariantes**: `0` órdenes confirmadas sin evento outbox y `0` sobre-asignaciones de cupo en las 30 corridas.

---

## Bloque 5 (12:30 – 15:00) · Evidencias de la Disminución de Tiempos E2 → E3
*(Diapositivas 8 y 9)*

1. **Qué mostrar (`baseline/corridas/oficial-e3/comparacion_e2.csv` y gráfica comparativa)**:
   - Mejoramos el sistema (no acortamos las pruebas) aplicando validación por lotes (`ANY(%s)`), inserción batch (`executemany`), sentencias preparadas (`prepare=True`), índice cubriente `INCLUDE` + `CROSS JOIN LATERAL` en Q4 y publicación paralela en el outbox:
     - **E4 (Ruta transaccional completa, 50,000 órdenes / 219,704 filas)**: **`486.42 s` (E2) → `298.94 s` (E3)** = **−187.48 s (−38.5% tiempo / +62.6% throughput)**.
     - **E4 A/B intercalado (10,000 órdenes × 3 pares)**: **`134.83 s` → `68.33 s`** = **−66.50 s (−49.3% tiempo)**.
     - **E3 (Inserción fila por fila autocommit, 5,000 órdenes)**: **`56.63 s` → `43.42 s`** = **−13.21 s (−23.3% tiempo)**.
     - **E1 (`COPY` masivo total)**: **`15.63 s` → `13.27 s`** = **−2.36 s (−15.1% tiempo)**.
     - **Carga total de BD (`make datos`)**: **`24.91 s` → `21.64 s`** = **−3.27 s (−13.1% tiempo)**.
     - **Q4 en el motor PostgreSQL (`EXPLAIN ANALYZE`)**: **`1.932 ms` (Bitmap Heap Scan, 136 bloques) → `1.458 ms` (Index Only Scan, `Heap Fetches: 0`)** = **−24.5% tiempo en servidor**.
