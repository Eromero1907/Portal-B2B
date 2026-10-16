# Checklist del Entregable 3 (control interno)
Fuente de los criterios: `proyecto-integrador.md` (Entregable 3: mecanismos, observabilidad mínima, motor de fallas, método,
criterios duros). Estado a 2026-10-16. `[x]` hecho y con evidencia · `[~]` parcial, con la limitación dicha · `[ ]` pendiente.

## 1. Motor de fallas — las cinco condiciones
- [x] Sin redespliegue: `faults/faults.yaml` recargable en caliente + controlador (`faults/controlador_fallas.py`).
- [x] Parametrizada: probabilidad, latencia, jitter, distribución, duración, CPU, retención.
- [x] Focalizable: endpoint, porcentaje, contenedor, franja, instancia.
- [x] Reversible en segundos: kill switch (`enabled: false`); `experimento.sh` lo ejecuta con `trap` en cualquier salida.
- [x] Reproducible: semilla 42; mismos instantes de bloqueo en B2 en todas las corridas.
- [x] Catálogo: 4 familias × 2 fallas = 8 (A1, A2, B1, B2, C1, C2, D1, D2).

## 2. Método (experimento, no sabotaje)
- [x] Predicción numérica escrita **antes** de medir (fichas del 2026-10-14 22:55; no editadas).
- [x] Cada falla corrida **sin** y **con** resiliencia, ≥ 2 repeticiones válidas por configuración (`Entrega 3/evidencia/`).
- [x] Predicho vs observado por experimento: `<ID>_resultado.md` + tabla del informe §5.
- [x] Causa de cada desviación explicada (§5–§6 del informe).
- [x] Corrección y re-ejecución con predicción previa fechada: D2 (umbral 70 %), B2 (`lock0`, mapeo `LockNotAvailable`), C1 (0,10 CPU).
- [x] Corridas contaminadas descartadas y documentadas (13): `LEEME_descartadas.md`. [~] 4 corridas válidas con reserva (mediana previa 10–15 ms).
- [x] "Predecir mal y documentarlo": 3 de 8 predicciones fallaron de fondo y se reportan.

## 3. Mecanismos de resiliencia — cada uno demostrado activo bajo una falla
- [x] Timeouts explícitos en toda llamada de salida (A1: corta toda llamada > 200 ms).
- [x] Reintentos con backoff y jitter, presupuesto 1,5 s, siempre con la misma `Idempotency-Key` (A1, A2, D1).
- [x] Circuit breaker (umbral, ventana, semiabierto): activo en D2; se encontró y corrigió su umbral. [~] No probado con caída total del crédito.
- [~] Bulkhead: observado rechazando (`bulkhead_agotado`) solo en episodios transitorios (A2 `con_r1`: 72; B2 `con-lock0_r5`: 3); no hay un experimento que lo ejercite a propósito.
- [x] Degradación graciosa: 503 con `Retry-After`, orden EN_PROCESO, cupo devuelto, clave liberada (verificado en B2 y D2; en A1 por las causas de error); RN-11: nunca se aprueba sin crédito.
- [x] Idempotencia y outbox: `outbox_total` = CONFIRMADAS y 0 violaciones de `reservada ≤ total` en todas las corridas válidas (B1, C2, D1, D2).
- [~] Rate limiting / backpressure: implementado en nginx (`limit_req` 250 req/s) porque `RATE_LIMIT_*` no está conectado en la app; **no se activó** a 200 req/s (C1: 0 respuestas 503 por rate limit), así que no quedó demostrado bajo falla.
- [x] `lock_timeout` y timeout de pool: B2 (28,8 s → 2,0 s) y B1 (error a 10 s → 2 s).

## 4. Observabilidad mínima
- [x] RED por endpoint con p50 / p95 / p99 (no promedios): `solicitudes.csv`, `resumen.json`, tablero Grafana `portal-b2b`.
- [x] USE por recurso: cAdvisor (CPU/memoria), pool de BD, colas de RabbitMQ; `recursos.csv`, `salud.csv`, `lag.csv`.
- [x] Traza distribuida: `x-trace-id` en cada respuesta + Jaeger en el flujo principal.
- [x] Tablero único con el p99 en tiempo real. [ ] Capturas de Grafana por experimento (`Entrega 3/evidencia/<ID>/capturas/`).
- [x] SLO declarados con presupuesto de error (RNF-10: p95 < 400 ms, errores < 0,5 %), evaluados en cada experimento.
- [~] Métricas citadas en las fichas que no existían (`portal_bd_lock_timeouts_total`, `portal_degradaciones_total`); transiciones del breaker y `unacked` no archivadas por corrida. Declarado en el informe §4.

## 5. Criterios duros / anti-patrones
- [x] El sistema levanta con el comando documentado (`make datos && make plataforma`).
- [x] Datos con volumen y sesgo mínimos (3 145 251 filas, Zipf, semilla 42).
- [x] Mediciones con percentiles; ninguna gráfica sin unidades ni carga declarada (200 req/s, 300 s).
- [x] Sin try/catch genérico presentado como resiliencia; sin reintentos infinitos; sin caché para tapar consultas.
- [x] CI de fronteras (`make fronteras`, import-linter + un esquema por módulo).
- [x] Honestidad sobre lo no logrado: defectos abiertos en el informe §8 (50 mensajes sin ack en C2; 109 `breaker_abierto` en B1 `con_r3`; 409 no reintentable en D1).

## 6. Meta de mejora −10 %
- [x] Línea base oficial del E3 en la máquina del E2 (`baseline/corridas/oficial-e3`): p50 7,4 / p95 47,6 / p99 61,0 ms, 0 % errores.
- [x] Palancas P1–P3 con A/B alternado y rango de ruido: todas dentro del ruido (se reporta tal cual).
- [ ] Palanca P8 (E4): `make palanca-p8` y resultado en el informe §7 (`[[P8]]`).

## 7. Entrega
- [x] Informe ≤ 10 páginas, 8 secciones, sin anexos: `Entrega 3/informe.md` (convertir a PDF/Word y contar páginas). [ ] Figuras de Grafana insertadas.
- [x] README actualizado (sección "Entregable 3").
- [x] Un commit por experimento y por corrección (historial `E3 evidencia …`).
- [ ] `make empaquetar` con el equipo en reposo.
- [ ] `git push` **antes de las 23:00 (America/Bogota)**.
