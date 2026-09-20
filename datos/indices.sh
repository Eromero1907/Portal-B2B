#!/usr/bin/env bash
# indices.sh on|off — quita o repone SOLO los índices de rendimiento (Q1..Q5) sobre una base ya cargada.
# Sirve para medir "antes" y "después" (EXPLAIN (ANALYZE, BUFFERS)) sin recargar los datos.
#   off  → DROP de idx_contratos_prov_vigencia, uq_sku_proveedor_sku, idx_franjas_cedi_fecha,
#          idx_ordenes_proveedor_fecha, idx_lineas_orden. Se conservan PK, UNIQUE de negocio y FK.
#   on   → los recrea (modelo-fisico.sql, flag indices) y ejecuta ANALYZE.
# Conexión: ver datos/_comun.sh
set -euo pipefail
source "$(dirname "$0")/_comun.sh"
verificar_conexion

modo="${1:-}"
case "$modo" in
    off)
        sql -d "$PGDATABASE" -c "
            DROP INDEX IF EXISTS proveedores.idx_contratos_prov_vigencia;
            DROP INDEX IF EXISTS catalogo.uq_sku_proveedor_sku;
            DROP INDEX IF EXISTS logistica.idx_franjas_cedi_fecha;
            DROP INDEX IF EXISTS ordenes.idx_ordenes_proveedor_fecha;
            DROP INDEX IF EXISTS ordenes.idx_lineas_orden;
            ANALYZE;"
        echo "✓ Índices de rendimiento eliminados (quedan PK, UNIQUE de negocio y FK). Estado: SIN índices."
        ;;
    on)
        t0=$(ahora)
        sql -d "$PGDATABASE" -v tablas=false -v restricciones=false -v indices=true -f modelo-fisico.sql
        sql -d "$PGDATABASE" -c "ANALYZE;" -c "VACUUM;"
        echo "✓ Índices de rendimiento creados + ANALYZE + VACUUM en $(delta "$t0" "$(ahora)") s. Estado: CON índices."
        ;;
    *)
        echo "Uso: bash datos/indices.sh on|off" >&2
        exit 2
        ;;
esac
