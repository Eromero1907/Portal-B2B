# Makefile - Portal B2B de Retail: Escalabilidad de los Datos
# Curso: Aplicaciones y Sistemas Escalables - Universidad EAFIT
# Integrantes: Esteban (Datos), JJ (Base de Datos), Sando (Profiling)
#
# REQUISITOS (maquina limpia): Docker, make, bash (Git Bash en Windows) y python3.
#   make datos      -> levanta PostgreSQL (Docker), genera los CSV y los carga, todo desde cero
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

.PHONY: all help datos generar cargar verificar determinismo db-up db-down db-reset indices-on indices-off cargar-sin-indices

all: help

help:
	@echo "====================================================================="
	@echo " COMANDOS DISPONIBLES - ENTREGABLE 2"
	@echo "====================================================================="
	@echo "  make datos              TODO desde cero: db-up + generar + cargar (COPY + indices + ANALYZE)"
	@echo "  make db-up              Levanta PostgreSQL en Docker (localhost:5433, usuario postgres, clave portal)"
	@echo "  make db-down            Detiene el contenedor (conserva los datos cargados)"
	@echo "  make generar            Genera los CSV deterministas con --seed 42 (Esteban)"
	@echo "  make verificar          Audita volumen, sesgo, estacionalidad, casos borde e integridad (Esteban/JJ)"
	@echo "  make determinismo       Genera dos veces con --seed 42 y compara checksums SHA-256"
	@echo "  make cargar             db-reset + COPY + indices + ANALYZE + VACUUM, cronometrado (JJ)"
	@echo "  make db-reset           Recrea los 5 esquemas vacios, sin indices (JJ)"
	@echo "  make indices-off        Quita solo los indices de rendimiento (estado 'antes' para EXPLAIN)"
	@echo "  make indices-on         Repone los indices de rendimiento + ANALYZE + VACUUM (estado 'despues')"
	@echo "  make cargar-sin-indices Carga completa dejando la base SIN indices de rendimiento"
	@echo "====================================================================="

# -------------------------------------------------------------------
# COMANDO MAESTRO EXIGIDO POR LA RUBRICA (levanta y carga todo desde cero)
# Si se define PSQL (servidor propio) no se intenta levantar Docker.
# -------------------------------------------------------------------
datos: $(if $(PSQL),,db-up) generar cargar

# -------------------------------------------------------------------
# Infraestructura: PostgreSQL en Docker (docker-compose.yml)
# -------------------------------------------------------------------
db-up:
	@echo "Levantando PostgreSQL en Docker..."
	docker compose up -d --wait

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
