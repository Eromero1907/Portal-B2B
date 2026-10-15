# Portal B2B de Proveedores de Retail
Proyecto integrador · Aplicaciones y Sistemas Escalables · Universidad EAFIT
Equipo: Esteban Jacob Romero Rios · Juan José Rodríguez Restrepo · Santiago Sabogal Lozano

Monolito modular con cuatro módulos de negocio (Órdenes, Proveedores, Catálogo, Logística), un esquema de PostgreSQL
por módulo y sin JOIN ni llaves foráneas entre esquemas. El caso crítico es
`POST /ordenes-compra/{id}/confirmacion`.

| Entregable | Qué hay en este repositorio |
|---|---|
| 2 · Escalabilidad de los datos | Generador determinista (3 145 251 filas, Zipf, estacionalidad, 8 casos borde), modelo físico, carga COPY, consultas Q1–Q5 y mediciones (`datos/`, `medicion/`, `reportes/`) |
| 3 · Resiliencia y observabilidad | Plataforma ejecutable (3 instancias + nginx + stub externo), línea base reproducible del E2, generador de carga, pruebas de aceptación, CI de fronteras (`app/`, `stub/`, `carga/`, `baseline/`, `infra/`) |

---

## Requisitos
Docker (Docker Desktop en Windows), `make`, bash (Git Bash en Windows) y Python 3. Nada más se instala en el equipo:
la base de datos, la aplicación y el generador de carga corren en contenedores. Para la línea base, las mediciones
del E2 se ejecutan desde el host como en el E2: `make venv` crea un entorno virtual con sus dependencias.

## Inicio rápido (Entregable 3)
```bash
make datos        # PostgreSQL + datos del E2 desde cero (--seed 42)            ~1 min
make plataforma   # esquema E3 + stub + app1..app3 + nginx → http://localhost:8080
make pruebas      # 14 pruebas de aceptación (reglas de negocio, idempotencia, último cupo)
make carga        # carga estable: 100 flujos/s = 200 solicitudes/s durante 300 s
make venv         # entorno del host para medicion/ y el CI de fronteras
make baseline     # Momento 1 completo (~25–35 min) → baseline/corridas/<equipo>-<fecha>/
make fronteras    # CI local: import-linter + un esquema por módulo
```
`make help` lista todos los comandos.

---

## Arquitectura de la plataforma (Entregable 3)
```
 generador de carga ─► nginx :8080 (least_conn, health check pasivo) ─► app1 · app2 · app3 :8000 (monolito modular)
                                                                          │  pool de conexiones │ adaptador de crédito
                                                                          ▼                     ▼
                                                              PostgreSQL :5433            stub-credito :9000
                                                   (proveedores · catalogo · logistica · ordenes · auditoria)
```

### Endpoints (vía nginx, `http://localhost:8080`)
| Método y ruta | Qué hace |
|---|---|
| `POST /ordenes-compra` | Crea una orden `EN_PROCESO` con sus líneas. Cabecera `Idempotency-Key` opcional (creación idempotente) |
| `POST /ordenes-compra/{id}/confirmacion` | Confirma la orden. **Cabecera `Idempotency-Key` obligatoria** (RN-13) |
| `GET /ordenes-compra/{id}` | Estado de la orden |
| `GET /salud` · `GET /salud/lista` | Vida del proceso · lista para atender (la BD responde) |
| `GET /metrics` | Métricas Prometheus (directo a cada instancia: `localhost:8001`, `:8002`, `:8003`; stub: `:9000`) |

Cada respuesta trae `x-trace-id` y `x-instancia`.

### Flujo de la confirmación
1. **Idempotencia:** toma la clave; si ya está completada devuelve la respuesta guardada, si está en curso responde 409.
2. **Transacción corta T1:** bloquea la orden; Proveedores valida proveedor ACTIVO y contrato vigente (RN-01/02);
   Catálogo valida que cada línea sea oferta vigente del proveedor al precio negociado (RN-03/04/05); Logística reserva
   un cupo con `UPDATE … WHERE capacidad_reservada < capacidad_total` y crea una reserva PENDIENTE con expiración
   (RN-07/08/09). Si una regla falla, la orden queda `RECHAZADA` con su causa.
3. **Llamada al stub de crédito/tributación fuera de toda transacción** (RN-10): no se retienen bloqueos mientras se espera al externo.
4. **Transacción T2:** aprobado → reserva CONFIRMADA + orden CONFIRMADA + evento `OrdenConfirmada` en `ordenes.outbox`, todo o nada (RN-15).
   Denegado → se devuelve el cupo y la orden queda `RECHAZADA`. Externo no disponible → se devuelve el cupo, la orden
   sigue `EN_PROCESO`, la clave se libera y se responde 503: **nunca se aprueba por defecto** (RN-11).
5. Un liberador en cada instancia devuelve los cupos de reservas PENDIENTE vencidas (RN-09); una clave abandonada se
   puede retomar pasados 30 s (recuperación, RF-10).

### Módulos y fronteras
`app/portal/modulos/<modulo>/__init__.py` es la interfaz pública; `interno/` contiene el SQL de su esquema.
`make fronteras` (y GitHub Actions, `.github/workflows/fronteras.yml`) falla si un módulo importa los internos de
otro (`.importlinter`) o si escribe SQL contra un esquema ajeno (`tests/test_fronteras.py`).

### Configuración (variables de entorno en `docker-compose.yml`)
| Variable | Valor línea base | Efecto |
|---|---|---|
| `BD_POOL_MIN` / `BD_POOL_MAX` / `BD_POOL_TIMEOUT_S` | 4 / 10 / 10 s | Pool de conexiones por instancia |
| `CREDITO_TIMEOUT_S` | 30 s | Timeout de la llamada al externo (sin reintentos, breaker ni bulkhead en la línea base) |
| `RESERVA_TTL_S` | 60 s | Vida de una reserva PENDIENTE |
| `FECHA_OPERACION` | 2026-09-17 | Fecha de las órdenes nuevas (día siguiente al pivote de los datos): validación de contratos reproducible |
| `LATENCIA_BASE_MS` (stub) | 20 ms | Latencia propia del externo en estado estable |
| `PORCENTAJE_SIN_CUPO` (stub) | 3 % | Proveedores a los que el externo niega cupo (regla determinista) |

### Métricas expuestas (contrato para el tablero)
`portal_http_solicitudes_total{metodo,ruta,codigo}`, `portal_http_duracion_segundos{metodo,ruta}` (histograma: p50/p95/p99),
`portal_confirmaciones_total{resultado,causa}`, `portal_credito_llamadas_total{resultado}`,
`portal_credito_duracion_segundos`, `portal_bd_pool_conexiones{estado}`, `portal_bd_pool_espera_ms_total`,
`portal_bd_pool_errores_total`, `portal_reservas_expiradas_total`, `portal_info`, `process_*`, `python_gc_*`;
stub: `stub_credito_solicitudes_total`, `stub_credito_duracion_segundos`; nginx: `/nginx_status`.
Logs JSON en la salida estándar de cada contenedor con `trace_id` (app, stub y nginx).

---

## Momento 1 · línea base (rúbrica del Entregable 3)
`make baseline` reconstruye desde cero el estado canónico del E2 y mide **sin fallas**, con el mismo protocolo del E2:
Q1–Q5 frío/caliente (3 corridas), Q3 concurrente 16/32/64 hilos (5 s de medición por hilo, como el E2), estrategias de inyección E1–E4,
la carga COPY y, además, la ruta de confirmación bajo carga estable. Deja en `baseline/corridas/<id>/` los CSV crudos,
`manifest.json` (semilla, conteos, PostgreSQL, imágenes, máquina, commit) y `comparacion_e2.csv`.

- **Referencia:** los valores del informe final del E2 (`baseline/referencia_e2.json`). `reportes/percentiles.csv` es
  una corrida posterior del mismo harness (commit `e988169`) y no se usa como referencia.
- **Objetivos:** `baseline/objetivos.csv` = 0,90 × cada métrica de tiempo del E2 (63 métricas de tiempo de respuesta).
- **Palancas de mejora:** `baseline/palancas.md`.
- **Máquina:** la comparación contra el E2 solo es válida en la máquina donde se midió el E2.
  Opciones: `CORRIDAS=3 COMPLETA=1 DURACION_Q3=5 FLUJOS=100 DURACION=300 ID=<nombre> NOTA="..." make baseline`;
  `make baseline-rapida` omite Q3 concurrente y E1–E4.

## Carga y pruebas
- `make carga [FLUJOS=100 DURACION=300 CALENTAMIENTO=30 SEMILLA=42 SALIDA=resultados/carga/x]`: parte siempre de
  `reset-estado`, corre el generador abierto (Poisson con semilla) dentro de la red de Docker contra nginx y muestrea
  `docker stats` cada 5 s. Deja `solicitudes.csv`, `resumen.json` (p50/p95/p99 por fase, throughput, errores, SLO
  RNF-10, retraso del generador) y `recursos.csv`. Si `generador.retraso_inicio_p99_s` supera 0,05 s, la corrida no es
  válida (el generador no sostuvo el ritmo).
- `make pruebas`: 14 pruebas de aceptación contra las 3 instancias, con verificación de cada efecto en la base;
  reporte en `resultados/pruebas/aceptacion.json`.
- `make reset-estado`: devuelve la base al estado inicial de la plataforma sin recargar los 3,1 M de filas.

---

## Entregable 2 (referencia)
`make datos` · `make verificar` · `make determinismo` · `make indices-off` / `make indices-on`. Detalle de tablas y
columnas en el contrato de datos del equipo; consultas en `datos/consultas.sql`; parámetros frío/caliente en
`datos/parametros.sql`; harness de medición en `medicion/`.
