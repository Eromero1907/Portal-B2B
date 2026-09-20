#!/usr/bin/env bash
# db-reset.sh — Fase 0 · Esquema limpio
# Crea la base si no existe y recrea los esquemas (proveedores, catalogo, logistica, ordenes, auditoria)
# vacíos y sin índices secundarios, listos para COPY. La carga siempre parte de cero.
# Conexión: ver datos/_comun.sh
set -euo pipefail
source "$(dirname "$0")/_comun.sh"
verificar_conexion

# Se conecta a la BD de mantenimiento 'postgres' solo para crear la base objetivo
existe=$(sql -d postgres -At -c "SELECT 1 FROM pg_database WHERE datname = '$PGDATABASE'" || true)
if [ "$existe" != "1" ]; then
    echo "  · Creando base de datos '$PGDATABASE'..."
    sql -d postgres -c "CREATE DATABASE \"$PGDATABASE\" ENCODING 'UTF8' TEMPLATE template0"
fi

echo "  · Recreando los 5 esquemas vacíos en '$PGDATABASE' (solo tablas, sin índices secundarios)..."
sql -d "$PGDATABASE" -v tablas=true -v restricciones=false -v indices=false -f modelo-fisico.sql
echo "  ✓ Esquemas listos."
