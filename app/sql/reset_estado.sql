-- =====================================================================
-- reset_estado.sql — Devuelve la base al estado inicial conocido de la plataforma (sin recargar 3,1 M de filas)
-- Deshace TODO lo que la plataforma escribe: órdenes y líneas nuevas (id > máximo del E2), reservas,
-- cupos de franjas, idempotencia y outbox. Lo usan `make reset-estado`, `make carga` y `make pruebas`.
-- Script administrativo: es el único lugar donde se tocan varios esquemas a la vez (no es código de la app).
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

-- 1. Devolver los cupos que tengan reservas activas (también restaura la franja 91150 del caso borde 4 a 9/10)
UPDATE logistica.franjas_cedi f
   SET capacidad_reservada = f.capacidad_reservada - r.n
  FROM (SELECT franja_id, count(*) AS n
          FROM logistica.reservas
         WHERE estado IN ('PENDIENTE', 'CONFIRMADA')
         GROUP BY franja_id) r
 WHERE f.id = r.franja_id;

TRUNCATE logistica.reservas RESTART IDENTITY;

-- 2. Órdenes y líneas creadas por la plataforma (numero_orden 'OC-E3-…'; las del E2 son 'OC-2026-…')
DELETE FROM ordenes.lineas_orden l
 USING ordenes.ordenes_compra o
 WHERE l.orden_id = o.id AND o.numero_orden LIKE 'OC-E3-%';
DELETE FROM ordenes.ordenes_compra WHERE numero_orden LIKE 'OC-E3-%';

TRUNCATE ordenes.idempotencia;
TRUNCATE ordenes.outbox RESTART IDENTITY;

SELECT setval('ordenes.ordenes_compra_id_seq', (SELECT max(id) FROM ordenes.ordenes_compra));
SELECT setval('ordenes.lineas_orden_id_seq',   (SELECT max(id) FROM ordenes.lineas_orden));

COMMIT;

-- Comprobación: la invariante reservada <= total se cumple y no queda nada de la plataforma
SELECT (SELECT count(*) FROM ordenes.ordenes_compra WHERE numero_orden LIKE 'OC-E3-%')   AS ordenes_plataforma,
       (SELECT count(*) FROM logistica.reservas)                                        AS reservas,
       (SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = 91150)        AS franja_91150_reservada,
       (SELECT count(*) FROM logistica.franjas_cedi WHERE capacidad_reservada > capacidad_total) AS violaciones_invariante;
