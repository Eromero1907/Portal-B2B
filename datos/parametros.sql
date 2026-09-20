-- =====================================================================
-- parametros.sql — Conjuntos de parámetros REALES (frío / caliente) para medir Q1..Q5
-- Cada bloque es un SELECT independiente que devuelve el conjunto de parámetros. Todos los muestreos son
-- DETERMINISTAS (orden por md5(id || semilla)): misma semilla ⇒ mismos parámetros ⇒ mediciones reproducibles.
-- Ejecutar un bloque:  bash datos/psql.sh -d portal_b2b -At -F, -c "<SELECT>"    (o copiarlo a tu cliente)
--
-- DEFINICIONES (por qué así; ver también sando.md):
--   CALIENTE = proveedor del top 1 % por número de órdenes (pool P1: 1 000 proveedores; ≈ 45 órdenes en promedio,
--              hasta 5 293 el proveedor 1). Todos tienen contrato y 20 SKU.
--   FRÍO     = proveedor de la cola larga CON contrato: ids 9001..10000 (los proveedores con contrato son 1..10000
--              y el sesgo Zipf hace que los ids altos sean los menos activos): entre 1 y 20 órdenes, mediana 6.
--              NO usar proveedores con id > 10000 como "fríos" en Q1/Q2/Q4: no tienen contrato ni SKU, así que
--              esas consultas devolverían vacío (miden el camino de rechazo, no la cola larga). Solo sirven
--              para el escenario "sin contrato" (caso 5: proveedor 55555).
--   La diferencia frío/caliente en estos datos es de VOLUMEN por parámetro, no de caché: el conjunto (~0,5 GB)
--   cabe en shared_buffers. Para medir caché fría de verdad, reiniciar el contenedor antes de la tanda
--   (docker restart pg-portal-b2b) y declararlo.
-- =====================================================================

-- ---- Semilla del muestreo: cambiar aquí (y solo aquí) para otra muestra reproducible ----
--   Se escribe literal '42' en cada bloque para que sean copiables por separado.

-- P1 · Pool CALIENTE: top 1 % de proveedores por órdenes (1 000 filas)
SELECT proveedor_id, count(*) AS ordenes
  FROM ordenes.ordenes_compra
 GROUP BY proveedor_id
 ORDER BY ordenes DESC, proveedor_id
 LIMIT 1000;

-- P2 · Pool FRÍO: cola larga con contrato (ids 9001..10000 con al menos una orden; 998 filas)
SELECT proveedor_id, count(*) AS ordenes
  FROM ordenes.ordenes_compra
 WHERE proveedor_id BETWEEN 9001 AND 10000
 GROUP BY proveedor_id
 ORDER BY proveedor_id;

-- P3 · Q1 y Q4/Q5 CALIENTE: 200 pares (proveedor_id, fecha) tomados de órdenes reales de proveedores calientes
SELECT proveedor_id, (fecha_emision AT TIME ZONE 'UTC')::date AS fecha
  FROM ordenes.ordenes_compra
 WHERE proveedor_id IN (SELECT proveedor_id FROM ordenes.ordenes_compra
                         GROUP BY proveedor_id ORDER BY count(*) DESC, proveedor_id LIMIT 1000)   -- pool P1
 ORDER BY md5(id::text || '42')
 LIMIT 200;

-- P4 · Q1 y Q4/Q5 FRÍO: 200 pares (proveedor_id, fecha) de órdenes reales de la cola larga con contrato
--      (hay ~6 600 órdenes en ese tramo; 200 pares distintos alcanzan)
SELECT proveedor_id, (fecha_emision AT TIME ZONE 'UTC')::date AS fecha
  FROM ordenes.ordenes_compra
 WHERE proveedor_id BETWEEN 9001 AND 10000
 ORDER BY md5(id::text || '42')
 LIMIT 200;

-- P5 · Q2: los 20 SKU del proveedor (cada proveedor con contrato tiene exactamente 20 ofertas: p, p+10000, ...)
--      Sustituir :prov por el proveedor de cada ejecución.
SELECT array_agg(sku ORDER BY sku) AS skus_20
  FROM catalogo.sku_catalogo
 WHERE proveedor_id = 1;   -- <- :prov

-- P6 · Q3 CALIENTE: (cedi, fecha) de la última semana de los datos (2026-09-10..2026-09-16), donde se concentra la
--      operación reciente. La clave más caliente es el caso 4: (cedi 1, 2026-09-16), con la franja 91150 a UN cupo.
SELECT c.cedi_id, d::date AS fecha
  FROM generate_series(1, 5) AS c(cedi_id)
 CROSS JOIN generate_series(DATE '2026-09-10', DATE '2026-09-16', INTERVAL '1 day') AS d;

-- P7 · Q3 FRÍO: 200 pares (cedi, fecha) repartidos en los 24 meses
SELECT cedi_id, fecha
  FROM (SELECT DISTINCT cedi_id, fecha FROM logistica.franjas_cedi) x
 ORDER BY md5(cedi_id::text || fecha::text || '42')
 LIMIT 200;

-- P8 · Q5 profunda: (proveedor, OFFSET) por página — el proveedor 1 tiene 5 293 órdenes (~106 páginas de 50)
SELECT 1 AS proveedor_id, 50 * g AS offset_filas FROM generate_series(0, 105) g;

-- P9 · Ventana de Q4: 24 meses completos
SELECT DATE '2024-09-01' AS desde, DATE '2026-10-01' AS hasta_exclusivo;
