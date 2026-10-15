-- =====================================================================
-- esquema_e3.sql — Extensiones del modelo físico para la plataforma del Entregable 3
-- Se aplica DESPUÉS de `make datos` (que recrea los esquemas del E2). Es idempotente.
-- Respeta las reglas del E2: cada tabla vive en el esquema de su módulo dueño y no hay FK entre esquemas.
--
--   ordenes.idempotencia      RN-13 · una misma Idempotency-Key nunca produce dos efectos
--   ordenes.outbox            RN-15 / ADR-005 · el evento OrdenConfirmada se escribe en la misma transacción
--   logistica.reservas        RN-07..09 · reserva con expiración; una sola reserva activa por orden
--   secuencias                ids de las órdenes y líneas nuevas (las del E2 llegan con id desde el CSV)
--   franjas futuras           capacidad para la operación simulada desde 2026-09-17 (día siguiente al pivote)
-- =====================================================================
\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------
-- ordenes.idempotencia
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ordenes.idempotencia (
    clave           VARCHAR(64)   PRIMARY KEY,
    orden_id        INT           NOT NULL,
    estado          VARCHAR(12)   NOT NULL,
    codigo_http     SMALLINT,
    respuesta       JSONB,
    creado_en       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_idempotencia_estado CHECK (estado IN ('EN_CURSO', 'COMPLETADA'))
);
COMMENT ON TABLE ordenes.idempotencia IS
  'RN-13: respuesta almacenada por Idempotency-Key de la confirmación. EN_CURSO abandonada (> N s) puede retomarse.';

-- ---------------------------------------------------------------------
-- ordenes.outbox  (Transactional Outbox, ADR-005)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ordenes.outbox (
    id             BIGSERIAL     PRIMARY KEY,
    evento_id      UUID          NOT NULL UNIQUE,
    tipo           VARCHAR(50)   NOT NULL,
    agregado_id    INT           NOT NULL,
    payload        JSONB         NOT NULL,
    creado_en      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    publicado_en   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_outbox_pendientes ON ordenes.outbox (id) WHERE publicado_en IS NULL;
COMMENT ON TABLE ordenes.outbox IS
  'Eventos persistidos en la misma transacción que confirma la orden. publicado_en NULL = pendiente de publicar.';

-- ---------------------------------------------------------------------
-- logistica.reservas
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS logistica.reservas (
    id              BIGSERIAL     PRIMARY KEY,
    franja_id       INT           NOT NULL,   -- FK intra-esquema a logistica.franjas_cedi
    orden_id        INT           NOT NULL,   -- lógica: ordenes.ordenes_compra(id), sin FK (otro esquema)
    estado          VARCHAR(12)   NOT NULL,
    creado_en       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    expira_en       TIMESTAMPTZ   NOT NULL,
    actualizado_en  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_reservas_estado CHECK (estado IN ('PENDIENTE', 'CONFIRMADA', 'LIBERADA', 'EXPIRADA')),
    CONSTRAINT fk_reservas_franja FOREIGN KEY (franja_id) REFERENCES logistica.franjas_cedi (id)
);
-- Una sola reserva activa por orden: dos confirmaciones concurrentes de la misma orden no pueden reservar dos cupos
CREATE UNIQUE INDEX IF NOT EXISTS uq_reservas_orden_activa
    ON logistica.reservas (orden_id) WHERE estado IN ('PENDIENTE', 'CONFIRMADA');
CREATE INDEX IF NOT EXISTS idx_reservas_pendientes_expira
    ON logistica.reservas (expira_en) WHERE estado = 'PENDIENTE';
COMMENT ON TABLE logistica.reservas IS
  'RN-09: una reserva PENDIENTE no confirmada antes de expira_en se libera (EXPIRADA) y devuelve el cupo.';

-- ---------------------------------------------------------------------
-- Secuencias para órdenes y líneas creadas por la plataforma (ids > los del E2)
-- ---------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS ordenes.ordenes_compra_id_seq AS INT;
CREATE SEQUENCE IF NOT EXISTS ordenes.lineas_orden_id_seq AS BIGINT;
SELECT setval('ordenes.ordenes_compra_id_seq', (SELECT max(id) FROM ordenes.ordenes_compra));
SELECT setval('ordenes.lineas_orden_id_seq',   (SELECT max(id) FROM ordenes.lineas_orden));

-- ---------------------------------------------------------------------
-- Franjas futuras: 2026-09-17 .. 2026-12-15 (90 días) · 5 CEDI · 25 franjas/día · capacidad 10 · 0 reservadas
-- Mismo patrón horario que el generador del E2 (06:00 + slot % 16). Solo se insertan si no existen.
-- ---------------------------------------------------------------------
INSERT INTO logistica.franjas_cedi (id, cedi_id, fecha, hora_inicio, hora_fin, capacidad_total, capacidad_reservada, created_at)
SELECT 91250 + row_number() OVER (ORDER BY d, c, s),
       c, d::date,
       make_time(6 + (s % 16), 0, 0),
       make_time(7 + (s % 16), 0, 0),
       10, 0, TIMESTAMPTZ '2026-09-16 00:00:00+00'
  FROM generate_series(DATE '2026-09-17', DATE '2026-12-15', INTERVAL '1 day') AS d,
       generate_series(1, 5) AS c,
       generate_series(0, 24) AS s
 WHERE NOT EXISTS (SELECT 1 FROM logistica.franjas_cedi WHERE fecha >= DATE '2026-09-17');

ANALYZE ordenes.idempotencia;
ANALYZE ordenes.outbox;
ANALYZE logistica.reservas;
ANALYZE logistica.franjas_cedi;
