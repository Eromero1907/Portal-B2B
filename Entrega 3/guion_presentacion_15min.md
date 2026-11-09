# Guion de la sustentación final (15 min) · lunes 9 de noviembre de 2026

**Presentación:** [`presentacion_15min.html`](./presentacion_15min.html) (flechas ← →, botón "Iniciar reloj"). **Secuencia de la rúbrica:** estado inicial → inyección de la combinación en vivo → diagnóstico → aprendizajes → estado final → tabla E2–E3.
**Reparto propuesto:** Esteban (criterios 1 y 2), Santiago (criterio 3 y estado final), JJ (apertura, tabla E2–E3 y cierre). Todos hablan; cámbienlo si prefieren otro orden, pero cada uno debe poder responder preguntas de cualquier bloque.

Todas las cifras de este guion salen de archivos del repositorio; al lado de cada una está su fuente. **No decir cifras que no estén aquí.**

---

## Antes de entrar (15 min antes, en el computador con Docker)

```bash
make plataforma
make observabilidad
make humo            # debe terminar en "8 pruebas de humo y el Kill Switch Global pasaron"; ~30 s
```

1. **Validar la línea base** (aprendizaje nuestro): con la plataforma quieta, en Grafana el p50 debe estar cerca de 7 ms. Si el equipo está lento (sin cargador, otras apps, OneDrive sincronizando), la demo da cifras falsas: una corrida en un equipo saturado dio 24 % de error con el breaker abierto antes de inyectar. **Conectar el cargador y cerrar todo lo demás.**
2. Pestañas abiertas: la presentación, Grafana (`http://localhost:3000`, tablero `portal-b2b`, refresco 5 s, últimos 5 min) y Jaeger (`http://localhost:16686`).
3. Terminal en la carpeta del repo, con letra grande.
4. Plan B si algo falla en vivo: mostrar `resultados/demo_comparacion.md` y `resultados/demo_*/ventanas.md` (corrida del 8 de noviembre, misma máquina) y decirlo explícitamente: "esta es la corrida de ayer; la de hoy falló por X".

---

## 00:00 – 01:00 · Apertura (diapositiva 1) — JJ
"Presentamos el estado inicial, inyectamos en vivo una combinación de fallas, diagnosticamos con la observabilidad, mostramos el estado final con la misma combinación y cerramos con la tabla E2–E3 por consulta, escenario y percentil. Todo se reproduce con un comando."

## 01:00 – 02:15 · Las 8 fallas y la observabilidad (diapositiva 2) — Esteban
- Dos fallas por familia (A latencia, B base de datos, C recursos, D disponibilidad). El motor cumple las cinco condiciones: sin redespliegue (`faults/faults.yaml` en caliente), parametrizable, focalizable, reversible (kill switch medido hoy en 272 ms con `make humo`) y reproducible (semilla 42).
- Leer dos o tres filas de la tabla, no las ocho. Recomendado: A1 (p95 765 → 268 ms), B2 (28,8 → 2,0 s) y D2 (13,4 → 21,0 → 1,7–2,7 %). Fuente: `Entrega 3/informe.md` §5.
- Observabilidad: RED por endpoint e instancia con p50/p95/p99 (nunca promedios), USE por recurso (cAdvisor, pool de BD, RabbitMQ) y trazas con `x-trace-id` en Jaeger.

## 02:15 – 03:30 · La combinación y la predicción (diapositiva 3) — Esteban
- A1 y D2 atacan la misma dependencia (crédito) y las dos cuentan en la ventana del breaker: con timeout de 200 ms por intento, un intento falla con probabilidad 1 − 0,7 × 0,5 = 65 %, justo debajo del umbral corregido (70 %).
- B2 ataca la base de datos: la confirmación de la franja 91150 espera el lock dentro de la transacción.
- **Predicción antes de correr:** estado inicial ≈ 27 % de confirmaciones con error (0,5 × 54 % que llega al crédito); estado final ≈ 9,6 % (0,65⁴ = 17,9 % de llamadas que agotan los 4 intentos × 54 %); peor espera de B2 ≈ 30 s → 2 s. El SLO de errores no se puede cumplir sin violar RN-11 y lo decimos antes de medir.

## 03:30 – 06:00 · Estado inicial en vivo (diapositiva 4) — Esteban
```bash
bash faults/demo_vivo.sh sin
```
(≈ 2 min: recrea las instancias sin mecanismos, carga de 200 req/s, inyecta en t≈25 s, kill switch en t≈60 s y al final imprime la tabla por ventana.)

Mientras corre, en Grafana: línea base plana → al inyectar suben los 503 (causa `HTTP 503`) y el p95/p99 de confirmar → una confirmación queda colgada en el lock (se ve en el máximo) → kill switch y vuelta a la línea base. **Decir:** "volver a la línea base es recuperación, no corrección".

Resultado de referencia (corrida del 8 nov, ventana durante la falla; `resultados/demo_estado_inicial_sin_resiliencia/ventanas.md`): error global 13,7 %, error en confirmar 27,5 % (predicho ≈ 27 %), p95 775 ms, p99 1 067 ms, peor confirmación 34,8 s.

## 06:00 – 07:30 · Diagnóstico (diapositiva 5) — Santiago
- Orden fijo: qué métrica cambió (errores por **causa**), dónde está el tiempo (traza de la peor solicitud en Jaeger: span de BD, no del crédito) y qué recurso está ocupado (CPU plana, conexiones retenidas: contención, no saturación).
- Si da el tiempo, abrir Jaeger con el `trace_id` de la peor solicitud (columna `trace_id` de `solicitudes.csv`).
- Las tres predicciones del E3 que fallaron: D2 (breaker 50 % empeora 13,4 → 21 %), B2 (0 bloqueadas porque la franja se llenaba a los 15,5 s; destapó un 500 sin mapear), C1 (0,25 CPU no saturaba).

## 07:30 – 09:00 · Aprendizajes (diapositiva 6) — Santiago
Leer los seis puntos en una frase cada uno. Énfasis en los dos nuevos de la entrega final: validar la línea base antes de inyectar (la corrida saturada del 24 %) y no atribuir mejoras sin A/B (COPY "mejoró" 15 % sin tocar nada).

## 09:00 – 11:30 · Estado final en vivo (diapositiva 7) — Santiago
```bash
bash faults/demo_vivo.sh con
```
Al terminar imprime `ventanas.md` y la comparación `resultados/demo_comparacion.md`.

Resultado de referencia (ventana durante la falla, misma carga y semilla): error global **13,7 % → 4,7 %** (−66 %), error en confirmar 27,5 % → 9,4 % (predicho 9,6 %), p95 775 → 532 ms (−31 %), p99 1 067 → 838 ms (−21 %), peor confirmación 34,8 s → 3,2 s (−91 %), 0 respuestas `breaker_abierto`, 10 × 503 `franja_bloqueada` cortadas a 2 s. Línea base previa igual en los dos estados (p95 42 vs 46 ms).

**Decir explícitamente:** no cumple el SLO (p95 < 400 ms y error < 0,5 %). El residuo es el predicho; bajarlo exigiría aprobar sin crédito (RN-11) o más reintentos, que suben el p95.

## 11:30 – 13:15 · Tabla E2–E3 (diapositiva 9) — JJ
- Cómo se midió: estados E2 (consultas del commit `a1b9141` + índice del E2) y E3 en la misma máquina, 5 rondas intercaladas, mismo cliente del E2 (`medicion/medir.py`), plataforma detenida, semilla 42. Atribuible = E3 ≤ 0,9 × E2 de hoy y sin solape entre rondas. Q4 nueva idéntica a la del E2 en 286 comparaciones.
- Cifras (`baseline/corridas/ab-e2-e3-maquina-jj/tabla_e2_e3.md`): Q4 caliente p95 15,70 → 2,76 ms (−82 %), p99 18,04 → 3,08 ms (−83 %); Q5 OFFSET 5000 p95 7,83 → 1,98 ms (−75 %), p99 9,51 → 2,13 ms (−78 %). Servidor: Q4 19,9 → 2,0 ms, Q5 5,0 → 0,67 ms.
- Qué cambió: L4 modelo de lectura de entregas (triggers de sentencia) y L5 índice cubriente.

## 13:15 – 14:30 · Lo no cumplido y los costos (diapositiva 10) — JJ
- No aplicable: Q1, Q2, Q3, Q5 página 1 / keyset. El servidor ejecuta en ≈ 0,05 ms; el cliente ve 0,7–1,5 ms. El mismo estado E2 mide hoy 0,76–1,70 ms frente a 0,52–1,89 ms del informe: es la máquina.
- No cumplido: Q4 caliente p50 (1,17 vs meta 1,04 ms). 9 de 33 cumplen la meta frente al informe; 6 tienen mejora atribuible.
- Costos: +3,3 s en la carga, un `UPDATE` por sentencia que escribe líneas, índice 12 → 30 MB, sin HOT al confirmar.
- E4 (complemento): P8 bajó la ruta transaccional de 437,6 a 298,9 s; es código de la ruta, no Q1–Q5. Retiramos del informe el COPY y la carga total porque cambiaron sin tocar nada.

## 14:30 – 15:00 · Cierre (diapositiva 11) — JJ
"Lo que mejoró lo medimos contra el mismo estado anterior; lo que no se cumple lo explicamos con el mismo cálculo que predijo el resultado. Quedamos atentos."

---

## Preguntas probables (respuestas cortas)
- **¿Por qué no cumplen el SLO en el estado final?** 65 % de fallos por intento en el crédito; con 4 intentos queda 0,65⁴ ≈ 18 % de llamadas sin respuesta válida. RN-11 prohíbe aprobar sin crédito. Lo predijimos antes de medir.
- **¿Por qué no subieron los reintentos?** Cada intento fallido por A1 cuesta 200 ms + backoff; con más intentos el p95 (ya 532 ms) empeora. Es un intercambio error ↔ latencia, como en B1.
- **¿El modelo de lectura no es una caché?** No: es desnormalización controlada dentro de la misma transacción (triggers de sentencia), sin expiración ni lecturas obsoletas; la fuente de verdad sigue siendo `lineas_orden` y la equivalencia se verifica (286 comparaciones idénticas).
- **¿Por qué la tabla E2–E3 es de la máquina de JJ y no la del E2?** La atribución compara E2 y E3 medidos juntos, así que no depende de la máquina. Para la columna "E2 informe", la misma prueba se corre en la máquina del E2 con `RONDAS=5 ID=ab-e2-e3-oficial make comparar-e2`.
- **¿Por qué la corrida del compañero daba 24 % y la de hoy 4,7 %?** Esa corrida tenía la mediana previa en segundos (equipo saturado): el breaker se abría antes de inyectar. Por eso validamos la línea base antes de la demo.
