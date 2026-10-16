# Makefile - Portal B2B de Retail
# Curso: Aplicaciones y Sistemas Escalables - Universidad EAFIT
# Integrantes: Esteban (Datos), JJ (Base de Datos), Sando (Profiling)
#
# REQUISITOS (maquina limpia): Docker, make, bash (Git Bash en Windows) y python3.
#   make datos       -> Entregable 2: levanta PostgreSQL (Docker), genera los CSV y los carga, todo desde cero
#   make plataforma  -> Entregable 3: esquema E3 + 3 instancias de la app + nginx + stub de credito
#   make baseline    -> Entregable 3: Momento 1, linea base reproducible del E2 + ruta de confirmacion
#
# Para usar un PostgreSQL propio en lugar del contenedor:
#   make datos PSQL=/ruta/a/psql PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=...
# En Windows se detecta solo el bash de Git; para forzar otro: make datos BASH=/ruta/a/bash
# Ver datos/_comun.sh para el detalle de las variables de conexion.

PYTHON ?= python3

# En Windows, 'bash' del PATH suele ser el lanzador de WSL (sin distribucion): se prefiere el bash de Git.
# (Desde Git Bash la variable BASH ya viene del entorno y se respeta.)
ifeq ($(origin BASH),undefined)
  ifeq ($(OS),Windows_NT)
    BASH := $(if $(wildcard C:/Progra~1/Git/bin/bash.exe),C:/Progra~1/Git/bin/bash.exe,bash)
  else
    BASH := bash
  endif
endif

# Entorno virtual del host para medicion/ (psycopg, numpy) y para el CI de fronteras (import-linter, pytest)
ifeq ($(OS),Windows_NT)
  VENV_BIN := .venv/Scripts
else
  VENV_BIN := .venv/bin
endif

# Servicios de la plataforma del Entregable 3
PLATAFORMA := rabbitmq stub-credito app1 app2 app3 publicador-outbox consumidor-eventos nginx


# Parametros de la carga (make carga FLUJOS=100 DURACION=300 CALENTAMIENTO=30 SALIDA=resultados/carga/x)
FLUJOS ?= 100
DURACION ?= 300
CALENTAMIENTO ?= 30
SEMILLA ?= 42

.PHONY: all help datos generar cargar verificar determinismo db-up db-down db-reset indices-on indices-off \
        cargar-sin-indices venv plataforma plataforma-down esquema-e3 reset-estado pruebas carga \
        baseline baseline-rapida objetivos fronteras

all: help

help:
	@echo "====================================================================="
	@echo " COMANDOS DISPONIBLES"
	@echo "====================================================================="
	@echo " ENTREGABLE 2 - datos"
	@echo "  make datos              TODO desde cero: db-up + generar + cargar (COPY + indices + ANALYZE)"
	@echo "  make db-up              Levanta solo PostgreSQL en Docker (localhost:5433, usuario postgres, clave portal)"
	@echo "  make db-down            Detiene todos los contenedores (conserva los datos cargados)"
	@echo "  make generar            Genera los CSV deterministas con --seed 42 (Esteban)"
	@echo "  make verificar          Audita volumen, sesgo, estacionalidad, casos borde e integridad"
	@echo "  make determinismo       Genera dos veces con --seed 42 y compara checksums SHA-256"
	@echo "  make cargar             db-reset + COPY + indices + ANALYZE + VACUUM, cronometrado (JJ)"
	@echo "  make db-reset           Recrea los 5 esquemas vacios, sin indices (JJ)"
	@echo "  make indices-off / -on  Quita / repone los indices de rendimiento (EXPLAIN antes/despues)"
	@echo "  make cargar-sin-indices Carga completa dejando la base SIN indices de rendimiento"
	@echo " ENTREGABLE 3 - plataforma, linea base y experimentos"
	@echo "  make venv               Crea .venv del host (medicion + CI de fronteras)"
	@echo "  make plataforma         Esquema E3 + estado limpio + stub + app1..app3 + nginx (http://localhost:8080)"
	@echo "  make plataforma-down    Detiene la plataforma (la BD sigue arriba)"
	@echo "  make reset-estado       Borra lo que escribio la plataforma (ordenes E3, reservas, outbox, idempotencia)"
	@echo "  make pruebas            Pruebas de aceptacion: reglas de negocio, idempotencia, ultimo cupo"
	@echo "  make carga              Carga estable de la ruta de confirmacion (FLUJOS=100 -> 200 rps, DURACION=300)"
	@echo "  make baseline           Momento 1 completo: datos E2 + Q1-Q5 x3 + Q3 concurrente + E1-E4 + ruta + manifest"
	@echo "  make baseline-rapida    Linea base sin Q3 concurrente ni E1-E4 (para probar el procedimiento)"
	@echo "  make objetivos          Regenera baseline/objetivos.csv (0,90 x valores del informe E2)"
	@echo "  make fronteras          CI local: import-linter + prueba de esquemas por modulo"
	@echo "====================================================================="

# -------------------------------------------------------------------
# COMANDO MAESTRO DEL ENTREGABLE 2 (levanta y carga todo desde cero)
# Si se define PSQL (servidor propio) no se intenta levantar Docker.
# -------------------------------------------------------------------
datos: $(if $(PSQL),,db-up) generar cargar

# -------------------------------------------------------------------
# Infraestructura: PostgreSQL en Docker (docker-compose.yml)
# -------------------------------------------------------------------
db-up:
	@echo "Levantando PostgreSQL en Docker..."
	docker compose up -d --wait db

db-down:
	docker compose stop

# -------------------------------------------------------------------
# FASE ESTEBAN: Generacion y Validacion
# -------------------------------------------------------------------
generar:
	@echo "Generando datos deterministas (--seed 42)..."
	$(PYTHON) datos/generar.py --seed 42 --scale min

verificar:
	@echo "Auditando calidad, sesgo, casos borde e integridad de los datos..."
	$(PYTHON) datos/verificar.py

determinismo:
	$(PYTHON) datos/verificar.py --determinismo

# -------------------------------------------------------------------
# FASE JJ: Esquema limpio, carga masiva, indices posteriores y ANALYZE
# -------------------------------------------------------------------
# cargar.sh parte SIEMPRE de un esquema limpio (llama a db-reset.sh):
# no existe el "ya lo tenia cargado de ayer".
cargar:
	@echo "Carga masiva COPY -> restricciones -> indices -> ANALYZE..."
	$(BASH) datos/cargar.sh

cargar-sin-indices: export SKIP_INDICES := 1
cargar-sin-indices:
	$(BASH) datos/cargar.sh

db-reset:
	@echo "Recreando esquemas vacios desde modelo-fisico.sql..."
	$(BASH) datos/db-reset.sh

indices-off:
	$(BASH) datos/indices.sh off

indices-on:
	$(BASH) datos/indices.sh on

# -------------------------------------------------------------------
# ENTREGABLE 3 · Relevo 1 (JJ): plataforma, carga y linea base
# -------------------------------------------------------------------
venv:
	$(PYTHON) -m venv .venv
	$(VENV_BIN)/python -m pip install --quiet --upgrade pip
	$(VENV_BIN)/python -m pip install --quiet -r medicion/requirements.txt -r requirements-dev.txt

esquema-e3:
	$(BASH) datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/esquema_e3.sql

reset-estado:
	$(BASH) datos/psql.sh -X -q -v ON_ERROR_STOP=1 -d portal_b2b -f app/sql/reset_estado.sql

plataforma: db-up esquema-e3 reset-estado
	docker compose up -d --build --wait $(PLATAFORMA)
	@echo "Plataforma lista: http://localhost:8080  (metricas: localhost:8001-8003/metrics, stub: localhost:9000/metrics)"

plataforma-down:
	docker compose stop $(PLATAFORMA)

pruebas:
	$(BASH) carga/correr_pruebas.sh

carga:
	$(BASH) carga/correr_carga.sh --flujos-por-s $(FLUJOS) --duracion $(DURACION) --calentamiento $(CALENTAMIENTO) \
	  --semilla $(SEMILLA) $(if $(SALIDA),--salida $(SALIDA),)

baseline:
	$(BASH) baseline/correr_baseline.sh

baseline-rapida: export COMPLETA := 0
baseline-rapida: export CORRIDAS := 1
baseline-rapida:
	$(BASH) baseline/correr_baseline.sh

objetivos:
	$(PYTHON) baseline/objetivos.py generar

fronteras: export PYTHONPATH := app
fronteras:
	$(VENV_BIN)/lint-imports
	$(VENV_BIN)/python -m pytest -q tests

humo:
	$(VENV_BIN)/python faults/probar_humo.py

fallas-estado:
	$(VENV_BIN)/python faults/controlador_fallas.py estado

kill-switch:
	$(VENV_BIN)/python faults/controlador_fallas.py kill-switch on

# --- Observabilidad (Relevo 3): Prometheus, Grafana, cAdvisor, exporters y Jaeger ---
OBS_COMPOSE = -f docker-compose.yml -f docker-compose.observabilidad.yml
OBS_SERVICIOS = prometheus grafana cadvisor postgres-exporter nginx-exporter jaeger

obs-up:
	docker compose $(OBS_COMPOSE) up -d $(OBS_SERVICIOS)
	@echo "Grafana: http://localhost:3000 | Prometheus: http://localhost:9090/targets | Jaeger: http://localhost:16686"

obs-down:
	docker compose $(OBS_COMPOSE) stop $(OBS_SERVICIOS)

experimento:
	$(BASH) faults/experimento.sh $(ID) $(CFG) $(REP)

cola:
	$(BASH) faults/cola.sh

palanca:
	$(BASH) baseline/palanca.sh $(P) $(N)

empaquetar:
	$(BASH) faults/empaquetar_evidencia.sh

palanca-p8:
	$(BASH) baseline/palanca_p8.sh
