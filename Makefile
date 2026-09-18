# Makefile — Portal B2B de Retail: Escalabilidad de los Datos
# Curso: Aplicaciones y Sistemas Escalables — Universidad EAFIT
# Integrantes: Esteban (Datos), JJ (Base de Datos), Sando (Profiling)

PYTHON ?= python3

.PHONY: all help datos generar cargar verificar db-reset

all: help

help:
	@echo "====================================================================="
	@echo "🛠️  COMANDOS DISPONIBLES — ENTREGABLE 2"
	@echo "====================================================================="
	@echo "  make datos       Ejecuta el pipeline completo (generar + cargar)"
	@echo "  make generar     Genera los CSVs deterministas con --seed 42 (Esteban)"
	@echo "  make verificar   Audita volúmenes, sesgo Zipf y 8 casos borde (Esteban)"
	@echo "  make cargar      Ejecuta la carga masiva COPY en PostgreSQL (JJ)"
	@echo "  make db-reset    Limpia y recrea los 4 esquemas desde cero (JJ)"
	@echo "====================================================================="

# -------------------------------------------------------------------
# FASE ESTEBAN: Generación y Validación
# -------------------------------------------------------------------
generar:
	@echo "⚙️  Generando datos deterministas..."
	$(PYTHON) datos/generar.py --seed 42 --scale min

verificar:
	@echo "📋 Auditando calidad, sesgo y casos borde de los datos..."
	$(PYTHON) datos/verificar.py

# -------------------------------------------------------------------
# FASE JJ: Carga en Base de Datos y Reset
# -------------------------------------------------------------------
cargar:
	@if [ -f datos/cargar.sh ]; then \
		echo "📥 Ejecutando carga masiva COPY..."; \
		bash datos/cargar.sh; \
	else \
		echo "⚠️  datos/cargar.sh no existe aún (Fase asignada a JJ)."; \
	fi

db-reset:
	@if [ -f datos/db-reset.sh ]; then \
		echo "🧹 Reiniciando base de datos..."; \
		bash datos/db-reset.sh; \
	elif [ -f modelo-fisico.sql ]; then \
		echo "🧹 Recreando esquemas con modelo-fisico.sql..."; \
		psql -d portal_b2b -f modelo-fisico.sql; \
	else \
		echo "⚠️  modelo-fisico.sql o db-reset.sh no existen aún (Fase asignada a JJ)."; \
	fi

# -------------------------------------------------------------------
# COMANDO MAESTRO EXIGIDO POR LA RÚBRICA
# (Levanta y carga todo con un solo comando)
# -------------------------------------------------------------------
datos: generar cargar
