#!/usr/bin/env bash
# cargar.sh — Fases 0 y 2 · Carga masiva con COPY, índices posteriores y ANALYZE
# Curso: Aplicaciones y Sistemas Escalables — Universidad EAFIT · Responsable: JJ (DBA)
#
# Secuencia (el orden importa):
#   0. db-reset            esquemas vacíos, sin índices secundarios
#   1. \copy por tabla     en orden de dependencias, cronometrado tabla a tabla
#   2. restricciones e     UNIQUE + FK, y luego los índices de rendimiento, DESPUÉS de cargar
#      índices             (modelo-fisico.sql, flags restricciones / indices), cada bloque cronometrado
#   3. ANALYZE             estadísticas para el planeador (sin esto las mediciones no valen)
#   4. VACUUM              marca las páginas como all-visible (habilita los Index Only Scan de Q1/Q2/Q4). Autovacuum
#                          lo haría solo en ~1 min; se fuerza para que el estado al terminar sea determinista
#
# Salida: tabla en consola + evidencia cruda en datos/resultados/:
#   carga_tiempos.csv   (fase,objeto,filas,segundos,filas_por_segundo)
#   entorno_bd.csv      (versión y parámetros del servidor bajo los que se midió)
#
# Variables: PSQL / PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE (ver datos/_comun.sh)
#            CSV_DIR (def. datos/csv) · SKIP_RESET=1 · SKIP_INDICES=1 (deja la base SIN índices de rendimiento,
#            para medir el "antes") · SKIP_VACUUM=1
set -euo pipefail
source "$(dirname "$0")/_comun.sh"

CSV_DIR="${CSV_DIR:-datos/csv}"
RESULTADOS="datos/resultados/carga_tiempos.csv"
ENTORNO="datos/resultados/entorno_bd.csv"

# tabla_destino | archivo CSV | columnas en el orden del encabezado del CSV
TABLAS=(
  "proveedores.proveedores|proveedores.csv|id,nit,razon_social,contacto_email,estado,created_at"
  "proveedores.contratos_suministro|contratos.csv|id,proveedor_id,numero_contrato,fecha_inicio,fecha_fin,estado,created_at"
  "catalogo.sku_catalogo|sku_catalogo.csv|id,sku,proveedor_id,nombre_producto,categoria,precio_negociado,vigencia_desde,vigencia_hasta,created_at"
  "logistica.franjas_cedi|franjas_cedi.csv|id,cedi_id,fecha,hora_inicio,hora_fin,capacidad_total,capacidad_reservada,created_at"
  "ordenes.ordenes_compra|ordenes_compra.csv|id,numero_orden,proveedor_id,franja_id,fecha_emision,estado,total_orden,idempotency_key,created_at,fecha_compromiso,fecha_entrega"
  "ordenes.lineas_orden|lineas_orden.csv|id,orden_id,sku_id,cantidad,precio_unitario,subtotal,cantidad_entregada"
  "auditoria.eventos_auditoria|eventos_auditoria.csv|id,fecha_evento,tipo_evento,modulo_origen,entidad_id,payload"
)

verificar_conexion
for entrada in "${TABLAS[@]}"; do
    IFS='|' read -r _ archivo _ <<< "$entrada"
    if [ ! -f "$CSV_DIR/$archivo" ]; then
        echo "ERROR: falta $CSV_DIR/$archivo. Ejecuta primero: make generar" >&2
        exit 1
    fi
done

mkdir -p "$(dirname "$RESULTADOS")"
echo "fase,objeto,filas,segundos,filas_por_segundo" > "$RESULTADOS"
registrar() { echo "$1,$2,$3,$4,$(tasa "$3" "$4")" >> "$RESULTADOS"; }

echo "====================================================================="
echo "CARGA MASIVA · base '$PGDATABASE' · $(sql -d postgres -At -c 'SHOW server_version' 2>/dev/null | head -1 | sed 's/^/PostgreSQL /')"
echo "====================================================================="
T_TOTAL_0=$(ahora)

# ---------------------------------------------------------------------
# Fase 0 · esquema limpio
# ---------------------------------------------------------------------
if [ "${SKIP_RESET:-0}" != "1" ]; then
    echo "[0] Esquema limpio"
    "$BASH" datos/db-reset.sh
fi

# ---------------------------------------------------------------------
# Fase 1 · COPY, una tabla a la vez, cronometrado
# ---------------------------------------------------------------------
echo "[1] COPY por tabla (sin índices secundarios)"
printf "  %-34s %12s %10s %14s\n" "tabla" "filas" "segundos" "filas/seg"
TOTAL_FILAS=0
T_COPY_0=$(ahora)
for entrada in "${TABLAS[@]}"; do
    IFS='|' read -r tabla archivo columnas <<< "$entrada"
    t0=$(ahora)
    sql -d "$PGDATABASE" -c "\copy $tabla ($columnas) FROM '$CSV_DIR/$archivo' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"
    t1=$(ahora)
    # filas cargadas = las que la tabla realmente tiene (no las que decía el CSV)
    filas=$(sql -d "$PGDATABASE" -qAt -c "SELECT count(*) FROM $tabla")
    seg=$(delta "$t0" "$t1")
    TOTAL_FILAS=$((TOTAL_FILAS + filas))
    printf "  %-34s %12s %10s %14s\n" "$tabla" "$filas" "$seg" "$(tasa "$filas" "$seg")"
    registrar "copy" "$tabla" "$filas" "$seg"
    esperado=$(( $(wc -l < "$CSV_DIR/$archivo") - 1 ))
    if [ "$filas" != "$esperado" ]; then
        echo "ERROR: $tabla tiene $filas filas y el CSV $esperado. Carga inconsistente." >&2
        exit 1
    fi
done
T_COPY_1=$(ahora)
seg_copy=$(delta "$T_COPY_0" "$T_COPY_1")
printf "  %-34s %12s %10s %14s\n" "TOTAL COPY" "$TOTAL_FILAS" "$seg_copy" "$(tasa "$TOTAL_FILAS" "$seg_copy")"
registrar "copy" "TOTAL" "$TOTAL_FILAS" "$seg_copy"

# ---------------------------------------------------------------------
# Fase 2 · restricciones (UNIQUE, FK) e índices de rendimiento, después de la carga
# ---------------------------------------------------------------------
echo "[2] Restricciones (UNIQUE + FK) e índices de rendimiento (post-carga)"
t0=$(ahora)
sql -d "$PGDATABASE" -v tablas=false -v restricciones=true -v indices=false -f modelo-fisico.sql
seg_res=$(delta "$t0" "$(ahora)")
echo "  restricciones UNIQUE + FK creadas en ${seg_res} s"
registrar "restricciones" "unique+fk" "$TOTAL_FILAS" "$seg_res"

seg_idx=0
if [ "${SKIP_INDICES:-0}" != "1" ]; then
    t0=$(ahora)
    sql -d "$PGDATABASE" -v tablas=false -v restricciones=false -v indices=true -f modelo-fisico.sql
    seg_idx=$(delta "$t0" "$(ahora)")
    echo "  índices de rendimiento creados en ${seg_idx} s"
    registrar "indices" "rendimiento" "$TOTAL_FILAS" "$seg_idx"
else
    echo "  SKIP_INDICES=1: la base queda SIN índices de rendimiento (estado 'antes')"
fi

# ---------------------------------------------------------------------
# Fase 3 · ANALYZE (obligatorio) y VACUUM (visibility map para Index Only Scan)
# ---------------------------------------------------------------------
echo "[3] ANALYZE"
t0=$(ahora)
sql -d "$PGDATABASE" -c "ANALYZE;"
seg_an=$(delta "$t0" "$(ahora)")
echo "  ANALYZE en ${seg_an} s"
registrar "analyze" "base_completa" "$TOTAL_FILAS" "$seg_an"

seg_vac=0
if [ "${SKIP_VACUUM:-0}" != "1" ]; then
    echo "[4] VACUUM"
    t0=$(ahora)
    sql -d "$PGDATABASE" -c "VACUUM;"
    seg_vac=$(delta "$t0" "$(ahora)")
    echo "  VACUUM en ${seg_vac} s"
    registrar "vacuum" "base_completa" "$TOTAL_FILAS" "$seg_vac"
fi

T_TOTAL_1=$(ahora)
seg_total=$(delta "$T_TOTAL_0" "$T_TOTAL_1")
registrar "total" "reset+copy+restricciones+indices+analyze+vacuum" "$TOTAL_FILAS" "$seg_total"

# ---------------------------------------------------------------------
# Entorno bajo el que se midió (el enunciado exige declarar el volumen y la carga)
# ---------------------------------------------------------------------
sql -d "$PGDATABASE" -At -F, -c "
    SELECT 'server_version', version()
    UNION ALL SELECT name, current_setting(name) FROM pg_settings
     WHERE name IN ('shared_buffers','work_mem','effective_cache_size','max_wal_size','synchronous_commit',
                    'fsync','random_page_cost','max_parallel_workers_per_gather','track_io_timing','TimeZone')
     ORDER BY 1" > "$ENTORNO.tmp"
{ echo "parametro,valor"; sed 's/^\([^,]*\),\(.*\)$/\1,"\2"/' "$ENTORNO.tmp"; } > "$ENTORNO"
rm -f "$ENTORNO.tmp"

# ---------------------------------------------------------------------
# Resumen: tamaños en disco (heap + índices) por tabla
# ---------------------------------------------------------------------
echo "---------------------------------------------------------------------"
echo "Tamaño en disco (tabla + índices + TOAST)"
sql -d "$PGDATABASE" -P footer=off -P format=aligned -c "
SELECT format('%s.%s', n.nspname, c.relname)                                   AS tabla,
       pg_size_pretty(sum(pg_table_size(t.relid))::bigint)                     AS tabla_heap,
       pg_size_pretty(sum(pg_indexes_size(t.relid))::bigint)                   AS indices,
       pg_size_pretty(sum(pg_total_relation_size(t.relid))::bigint)            AS total
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  CROSS JOIN LATERAL (SELECT relid FROM pg_partition_tree(c.oid) WHERE isleaf   -- particiones hoja
                      UNION ALL
                      SELECT c.oid WHERE c.relkind = 'r') t(relid)                -- tabla normal
 WHERE c.relkind IN ('r', 'p')
   AND NOT c.relispartition
   AND n.nspname IN ('proveedores','catalogo','logistica','ordenes','auditoria')
 GROUP BY n.nspname, c.relname
 ORDER BY sum(pg_total_relation_size(t.relid)) DESC"

echo "====================================================================="
echo "✓ CARGA COMPLETA · ${TOTAL_FILAS} filas en ${seg_total} s"
echo "  COPY ${seg_copy} s · restricciones ${seg_res} s · índices ${seg_idx} s · ANALYZE ${seg_an} s · VACUUM ${seg_vac} s"
echo "  Evidencia cruda: $RESULTADOS · $ENTORNO"
echo "====================================================================="
