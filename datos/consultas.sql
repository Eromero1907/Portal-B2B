-- =====================================================================
-- consultas.sql — Las cinco consultas que todos miden (Entregable 2, sección 4 del enunciado)
-- Definición ÚNICA de Q1..Q5 como sentencias preparadas: cualquier cliente (psql, Python, k6, Java)
-- las ejecuta con EXECUTE qN(...) y mide lo mismo. Cargar en cada sesión:
--     bash datos/psql.sh -d portal_b2b -f datos/consultas.sql
--
-- IMPORTANTE para medir: una sentencia preparada cambia a plan GENÉRICO tras 5 ejecuciones, y el plan genérico
-- puede ignorar el parámetro (frío o caliente) y ocultar justo la diferencia que se busca. Medir con:
--     SET plan_cache_mode = force_custom_plan;
-- Fecha de referencia ("hoy") de los datos: 2026-09-16 (datos/parametros_generacion.json).
-- =====================================================================

SET plan_cache_mode = force_custom_plan;

-- ---------------------------------------------------------------------
-- Q1 · Validar proveedor y contrato vigente por proveedor_id y fecha.  Punto. Debe estar por debajo de 10 ms.
--   RN-01 (proveedor elegible = estado ACTIVO) y RN-02 (contrato vigente en la fecha). El LEFT JOIN devuelve
--   el proveedor aun sin contrato (caso 5: 55555) con contrato_id NULL: ese es el camino de rechazo frecuente.
--   Frontera temporal: fecha_fin >= fecha (inclusive). Caso 2: contrato 2 venció ayer; caso 3: contrato 3 vence hoy.
--   Parámetros: $1 proveedor_id · $2 fecha
-- ---------------------------------------------------------------------
PREPARE q1 (int, date) AS
SELECT p.id            AS proveedor_id,
       p.estado        AS estado_proveedor,
       c.id            AS contrato_id,
       c.numero_contrato,
       c.fecha_fin
  FROM proveedores.proveedores p
  LEFT JOIN proveedores.contratos_suministro c
         ON c.proveedor_id = p.id
        AND c.estado = 'VIGENTE'
        AND c.fecha_inicio <= $2
        AND c.fecha_fin    >= $2
 WHERE p.id = $1;

-- ---------------------------------------------------------------------
-- Q2 · Verificar precio y vigencia de 20 SKU del catálogo negociado de un proveedor.  Lote pequeño.
--   RN-03/04/05: el SKU debe ser oferta de ESE proveedor y estar vigente en la fecha de la orden.
--   Un SKU que no devuelve fila es "fuera del catálogo negociado" (caso 6).
--   Parámetros: $1 proveedor_id · $2 arreglo de 20 códigos sku ('SKU-0000001', ...) · $3 fecha
-- ---------------------------------------------------------------------
PREPARE q2 (int, text[], date) AS
SELECT s.sku,
       s.precio_negociado,
       s.vigencia_desde,
       s.vigencia_hasta,
       (s.vigencia_desde <= $3 AND s.vigencia_hasta >= $3) AS vigente
  FROM catalogo.sku_catalogo s
 WHERE s.proveedor_id = $1
   AND s.sku = ANY ($2);

-- ---------------------------------------------------------------------
-- Q3 · Franjas disponibles de un CEDI para una fecha.  Recurso escaso, alta concurrencia.
--   Solo franjas con cupo. Caso 4: franja 91150 (CEDI 1, 2026-09-16) tiene UN solo cupo libre.
--   Parámetros: $1 cedi_id (1..5) · $2 fecha
-- ---------------------------------------------------------------------
PREPARE q3 (int, date) AS
SELECT f.id            AS franja_id,
       f.hora_inicio,
       f.hora_fin,
       f.capacidad_total - f.capacidad_reservada AS cupos_libres
  FROM logistica.franjas_cedi f
 WHERE f.cedi_id = $1
   AND f.fecha   = $2
   AND f.capacidad_reservada < f.capacidad_total
 ORDER BY f.hora_inicio;

-- ---------------------------------------------------------------------
-- Q4 · OTIF y fill rate de UN proveedor por mes, sobre una ventana de hasta 24 meses.  Analítica pesada.
--   Definiciones (glosario de la Entrega 1):
--     OTIF      = % de órdenes CONFIRMADAS y ya entregadas que llegaron a tiempo (fecha_entrega <= fecha_compromiso)
--                 Y completas (todas sus líneas con cantidad_entregada >= cantidad).
--     Fill rate = unidades surtidas / unidades pedidas (sin considerar el tiempo), sobre las mismas órdenes.
--   Las órdenes sin entrega (fecha_entrega NULL: EN_PROCESO, RECHAZADAS o aún no entregadas) no entran.
--   La serie mensual se completa con generate_series: un mes SIN órdenes (caso 8: proveedor 10, 2025-06) aparece con
--   0 órdenes y OTIF/fill NULL en vez de desaparecer o dividir por cero.
--   Parámetros: $1 proveedor_id · $2 desde (fecha, inclusive) · $3 hasta (fecha, exclusive)
--   Referencia de SLO (Entrega 1, RNF-11): p95 < 2 500 ms y p99 < 5 000 ms sobre 24 meses.
-- ---------------------------------------------------------------------
PREPARE q4 (int, date, date) AS
WITH meses AS (
    SELECT generate_series(date_trunc('month', $2::timestamp),
                           date_trunc('month', ($3 - 1)::timestamp),
                           interval '1 month')::date AS mes
), ord AS (
    SELECT o.id,
           date_trunc('month', o.fecha_emision AT TIME ZONE 'UTC')::date AS mes,
           o.fecha_compromiso,
           o.fecha_entrega
      FROM ordenes.ordenes_compra o
     WHERE o.proveedor_id = $1
       AND o.fecha_emision >= $2
       AND o.fecha_emision <  $3
       AND o.estado = 'CONFIRMADA'
       AND o.fecha_entrega IS NOT NULL
), lin AS (
    SELECT l.orden_id,
           sum(l.cantidad)                                   AS pedido,
           sum(least(l.cantidad_entregada, l.cantidad))      AS surtido,
           bool_and(l.cantidad_entregada >= l.cantidad)      AS completa
      FROM ordenes.lineas_orden l
     WHERE l.orden_id IN (SELECT id FROM ord)
     GROUP BY l.orden_id
), agg AS (
    SELECT o.mes,
           count(*)                                                                       AS ordenes_entregadas,
           count(*) FILTER (WHERE o.fecha_entrega <= o.fecha_compromiso AND l.completa)   AS ordenes_otif,
           sum(l.pedido)                                                                  AS unidades_pedidas,
           sum(l.surtido)                                                                 AS unidades_surtidas
      FROM ord o
      JOIN lin l ON l.orden_id = o.id
     GROUP BY o.mes
)
SELECT m.mes,
       COALESCE(a.ordenes_entregadas, 0)                                       AS ordenes_entregadas,
       round(100.0 * a.ordenes_otif      / NULLIF(a.ordenes_entregadas, 0), 2) AS otif_pct,
       round(100.0 * a.unidades_surtidas / NULLIF(a.unidades_pedidas, 0), 2)   AS fill_rate_pct
  FROM meses m
  LEFT JOIN agg a USING (mes)
 ORDER BY m.mes;

-- ---------------------------------------------------------------------
-- Q5 · Últimas 50 órdenes de un proveedor, paginadas.  Hot partition y paginación.
--   q5        : paginación por OFFSET (página n = OFFSET 50*(n-1)); degrada con páginas profundas.
--   q5_keyset : paginación por cursor (fecha_emision, id) de la última fila vista; costo constante.
--   Medir la página 1 y una página profunda (p. ej. OFFSET 5000 en un proveedor hot: proveedor 1 tiene 5 293 órdenes).
--   Parámetros q5: $1 proveedor_id · $2 offset       q5_keyset: $1 proveedor_id · $2 fecha_emision · $3 id
-- ---------------------------------------------------------------------
PREPARE q5 (int, int) AS
SELECT o.id, o.numero_orden, o.fecha_emision, o.estado, o.total_orden
  FROM ordenes.ordenes_compra o
 WHERE o.proveedor_id = $1
 ORDER BY o.fecha_emision DESC, o.id DESC
 LIMIT 50 OFFSET $2;

PREPARE q5_keyset (int, timestamptz, int) AS
SELECT o.id, o.numero_orden, o.fecha_emision, o.estado, o.total_orden
  FROM ordenes.ordenes_compra o
 WHERE o.proveedor_id = $1
   AND (o.fecha_emision, o.id) < ($2, $3)
 ORDER BY o.fecha_emision DESC, o.id DESC
 LIMIT 50;

-- Ejemplos (descomentar):
-- EXPLAIN (ANALYZE, BUFFERS) EXECUTE q1(1, '2026-09-16');
-- EXPLAIN (ANALYZE, BUFFERS) EXECUTE q4(1, '2024-09-01', '2026-10-01');
-- EXPLAIN (ANALYZE, BUFFERS) EXECUTE q5(1, 0);
