# Protocolo común de las fichas de predicción · Relevo 2

**Fecha de redacción:** 2026-10-14 22:55 (-05:00), **antes de cualquier medición con fallas**. No existe todavía ni el
motor de fallas ni los mecanismos: estas predicciones se hacen sobre el diseño acordado en la Fase 0.
**Autor:** Esteban (relevo 2) · **Commit base de la plataforma:** `bfa5b45` (relevo 1, JJ). El commit exacto de cada
corrida se registra en el manifest de la evidencia (`Entrega 3/evidencia/<ID>/`, relevo 3).

Regla de método: si la medición contradice una ficha, **la ficha no se edita**. La diferencia se anota aparte
(`<ID>_resultado.md` o en el informe) y se explica.

---

## 1. Línea base de referencia (máquina de JJ, NO oficial)

| Métrica (200 solicitudes/s, 300 s) | crear | confirmar | global |
|---|---:|---:|---:|
| p50 | 12,8 ms | 42,3 ms | 21,8 ms |
| p95 | 301 ms | 298 ms | 299 ms |
| p99 | 836 ms | 981 ms | 890 ms |
| Errores (5xx o sin respuesta) | | | 0,003 % |

- El p95 global de 299 ms lo infla el episodio H5 (~90 s). **Fuera de H5 el p95 global es de 65–88 ms.** Las
  predicciones "durante la falla" se comparan contra la línea base **fuera de H5**. Si H5 se superpone con la ventana
  de falla, se debe declarar y repetir la corrida.
- La línea base oficial la mide Santiago en la máquina del E2. Los valores absolutos pueden cambiar entre 1,6× y 3× (H2).
  Por eso se predicen también **diferencias y proporciones**, que son más transferibles entre máquinas.

**Fracción que llega al externo:** 16 038 de 29 933 confirmaciones (54 %), es decir **≈ 27 % de todas las solicitudes
≈ 53,5 llamadas/s** (≈ 17,8 por instancia). Las demás confirmaciones se rechazan antes (contrato, proveedor, SKU, cupo).
**Eventos `OrdenConfirmada`:** ≈ 52/s (15 596 en 300 s).

## 2. Carga (igual en los 8 experimentos salvo que la ficha diga otra cosa)

`make carga FLUJOS=100 DURACION=<D> CALENTAMIENTO=30 SEMILLA=42`: 100 flujos/s = **200 solicitudes/s**, Poisson,
timeout de cliente de 60 s, sin reintentos de cliente (`--reintentos-cliente 0`, valor por defecto). Siempre se ejecuta
`make reset-estado` antes. Cada experimento se corre **≥ 2 veces** con la misma semilla.

**Ventanas de análisis:** t = 0 es el fin del calentamiento. Las predicciones se dan para la **ventana de falla**, salvo
que la ficha diga otra cosa, y se calculan sobre `solicitudes.csv` filtrando por tiempo. El resumen global del
generador, que mezcla ventanas, se reporta aparte.

## 3. Dos configuraciones por experimento

- **Sin mecanismos:** valores por defecto de `docker-compose.yml`, idénticos a la línea base de hoy (timeout de
  crédito de 30 s, sin reintentos, sin breaker, sin bulkhead, sin rate limit, sin publicador activo, pool con timeout
  de 10 s y sin `lock_timeout`).
- **Con mecanismos, perfil M** (variables de entorno, recreando las apps sin rebuild):

| Variable | Valor M | Comentario |
|---|---|---|
| `CREDITO_TIMEOUT_S` | 5 | techo absoluto por llamada lógica |
| `CREDITO_TIMEOUT_INTENTO_MS` | 200 | ≈ 10× la latencia base del stub (20 ms) |
| `REINTENTOS_ACTIVO` / `_MAX` | true / 3 | hasta 4 intentos en total |
| `REINTENTOS_BASE_MS` / `_TOPE_MS` | 50 / 400 | backoff exponencial con *full jitter*: espera ~U(0, min(tope, base·2ⁿ)) |
| `REINTENTOS_PRESUPUESTO_MS` | 1500 | no se lanza un intento que no quepa en el presupuesto; muy por debajo del TTL de 60 s |
| `BREAKER_ACTIVO` | true | un breaker por instancia |
| `BREAKER_UMBRAL_FALLOS_PCT` | 50 | abre si fallos/intentos ≥ 50 % en la ventana… |
| `BREAKER_VENTANA_S` / `_MIN_LLAMADAS` | 10 / 20 | …móvil de 10 s y con ≥ 20 intentos |
| `BREAKER_ESPERA_ABIERTO_S` | 5 | luego pasa a semiabierto |
| `BREAKER_PRUEBAS_SEMIABIERTO` | 5 | cierra si fallan < 50 % de las 5 pruebas (≤ 2); si no, vuelve a abrir. La ventana se reinicia al cerrar |
| `BULKHEAD_ACTIVO` / `_MAX_CONCURRENTES` / `_ESPERA_MS` | true / 20 / 50 | semáforo por instancia para el stub |
| `DEGRADACION_ACTIVA` / `_RETRY_AFTER_S` | true / 5 | 503 con causa distinguible y `Retry-After`; orden EN_PROCESO, cupo liberado, clave libre. **Nunca aprueba** (RN-11) |
| `DB_LOCK_TIMEOUT_MS` | 2000 | `SET lock_timeout` en la transacción T1 |
| `BD_POOL_TIMEOUT_S` | 2 | falla rápido si no hay conexión (ya existe; hoy vale 10) |
| `OUTBOX_PUBLICADOR_ACTIVO` / `_LOTE` / `_INTERVALO_MS` | true / 100 / 200 | `FOR UPDATE SKIP LOCKED`, confirmaciones del publicador de RabbitMQ |
| `CONSUMIDOR_DEDUPLICAR` | true | `INSERT … ON CONFLICT (evento_id) DO NOTHING` + efecto en la misma transacción; ack después del commit |
| `RATE_LIMIT_ACTIVO` / `_RPS` / `_RAFAGA` | true / 250 / 100 | nginx `limit_req`, rechazo con **503** (cuenta como error en el SLO) |

**Semántica que condiciona las predicciones:**
- El breaker cuenta **intentos**, no llamadas lógicas. Son fallos: timeout, 5xx y error de conexión. `denegado` (cupo
  insuficiente) es un éxito técnico.
- Solo se reintentan fallas técnicas, siempre con la `Idempotency-Key` de la confirmación reenviada al stub.
- **Reproducibilidad con semilla 42:** que un intento quede afectado se decide con un hash determinista de
  `(seed, orden_id, n.º de intento)`, y la magnitud con un `Random` sembrado con ese mismo hash. Un reintento es un
  sorteo **independiente** del anterior: la misma orden en el mismo intento recibe siempre la misma falla.

## 4. SLO (RNF-10)
p95 global < 400 ms **y** errores (5xx o sin respuesta) < 0,5 %. El presupuesto de error en 300 s a 200 solicitudes/s es
de ≈ 300 solicitudes.
