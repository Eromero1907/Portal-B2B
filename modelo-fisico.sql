-- =====================================================================
-- modelo-fisico.sql — Portal B2B de Retail · Entregable 2 (Escalabilidad de los datos)
-- Curso: Aplicaciones y Sistemas Escalables — Universidad EAFIT
-- Responsable: JJ (Base de Datos / DBA)
--
-- USO
--   psql -d portal_b2b -f modelo-fisico.sql                                 # todo: tablas + restricciones + índices
--   psql -d portal_b2b -v tablas=true  -v restricciones=false -v indices=false -f modelo-fisico.sql   # fase 0: tablas listas para COPY
--   psql -d portal_b2b -v tablas=false -v restricciones=true  -v indices=true  -f modelo-fisico.sql   # fase 2: DESPUÉS del COPY
--
--   Flags (por defecto true): tablas · restricciones (UNIQUE y FK) · indices (índices de rendimiento, idempotentes).
--   `make indices-off` / `make indices-on` quitan y devuelven SOLO los índices de rendimiento (medición "antes/después").
--
-- REGLAS DE DISEÑO
--   1. Un esquema por módulo: proveedores, catalogo, logistica, ordenes
--      + auditoria (transversal, append-only).
--   2. CERO llaves foráneas entre esquemas. La integridad entre módulos
--      (p. ej. ordenes.proveedor_id -> proveedores.id) es lógica de aplicación.
--      Solo hay FKs DENTRO de un mismo esquema (contratos->proveedores,
--      lineas_orden->ordenes_compra).
--   3. La carga masiva se hace SIN índices secundarios. Solo existen las PK
--      (el CSV de cada tabla debe traer ids únicos) y los CHECK. Los UNIQUE y las FK
--      (fase 'restricciones') y los índices de rendimiento (fase 'indices') se crean tras el COPY.
--   4. Cada índice de rendimiento nombra la consulta (Q1..Q5) que sirve. Si nadie lo usa, no existe.
-- =====================================================================

\set ON_ERROR_STOP on

\if :{?tablas}
\else
  \set tablas true
\endif
\if :{?restricciones}
\else
  \set restricciones true
\endif
\if :{?indices}
\else
  \set indices true
\endif

-- =====================================================================
-- FASE 0 · ESQUEMAS Y TABLAS (sin índices secundarios)
-- =====================================================================
\if :tablas

DROP SCHEMA IF EXISTS auditoria   CASCADE;
DROP SCHEMA IF EXISTS ordenes     CASCADE;
DROP SCHEMA IF EXISTS logistica   CASCADE;
DROP SCHEMA IF EXISTS catalogo    CASCADE;
DROP SCHEMA IF EXISTS proveedores CASCADE;

CREATE SCHEMA proveedores;
CREATE SCHEMA catalogo;
CREATE SCHEMA logistica;
CREATE SCHEMA ordenes;
CREATE SCHEMA auditoria;

COMMENT ON SCHEMA proveedores IS 'Módulo Proveedores: maestro de proveedores y contratos de suministro.';
COMMENT ON SCHEMA catalogo    IS 'Módulo Catálogo: SKU negociados por proveedor (precio y vigencia).';
COMMENT ON SCHEMA logistica   IS 'Módulo Logística: franjas de descargue por CEDI (recurso escaso).';
COMMENT ON SCHEMA ordenes     IS 'Módulo Órdenes: cabecera y líneas de órdenes de compra.';
COMMENT ON SCHEMA auditoria   IS 'Transversal: eventos de auditoría append-only, particionados por mes.';

-- ---------------------------------------------------------------------
-- proveedores.proveedores  (~100 000 filas)
-- ---------------------------------------------------------------------
CREATE TABLE proveedores.proveedores (
    id              INT           PRIMARY KEY,
    nit             VARCHAR(20)   NOT NULL,
    razon_social    VARCHAR(150)  NOT NULL,
    contacto_email  VARCHAR(100)  NOT NULL,
    estado          VARCHAR(20)   NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL,
    CONSTRAINT ck_proveedores_estado CHECK (estado IN ('ACTIVO', 'INACTIVO', 'SUSPENDIDO'))
);
COMMENT ON TABLE  proveedores.proveedores IS 'Maestro de proveedores. INT basta: 100 000 filas, techo de 2 147 M.';
COMMENT ON COLUMN proveedores.proveedores.nit IS 'Único (uq_proveedores_nit, creado tras la carga).';

-- ---------------------------------------------------------------------
-- proveedores.contratos_suministro  (~10 000 - 15 000 filas)
-- ---------------------------------------------------------------------
CREATE TABLE proveedores.contratos_suministro (
    id               INT          PRIMARY KEY,
    proveedor_id     INT          NOT NULL,   -- FK a proveedores.proveedores(id) (mismo esquema, se añade tras la carga)
    numero_contrato  VARCHAR(50)  NOT NULL,
    fecha_inicio     DATE         NOT NULL,   -- DATE (4 B): la vigencia se compara por día, no por instante
    fecha_fin        DATE         NOT NULL,
    estado           VARCHAR(20)  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL,
    CONSTRAINT ck_contratos_estado   CHECK (estado IN ('VIGENTE', 'VENCIDO', 'CANCELADO')),
    CONSTRAINT ck_contratos_vigencia CHECK (fecha_fin >= fecha_inicio)
);
COMMENT ON TABLE proveedores.contratos_suministro IS
  'Solo ~12 % de los proveedores tiene contrato: el desfase es intencional (camino de rechazo más frecuente).';

-- ---------------------------------------------------------------------
-- catalogo.sku_catalogo  (200 000 - 400 000 filas)
-- ---------------------------------------------------------------------
CREATE TABLE catalogo.sku_catalogo (
    id                INT            PRIMARY KEY,
    sku               VARCHAR(50)    NOT NULL,
    proveedor_id      INT            NOT NULL,   -- lógica: proveedores.proveedores(id), sin FK (otro esquema)
    nombre_producto   VARCHAR(150)   NOT NULL,
    categoria         VARCHAR(50)    NOT NULL,
    precio_negociado  NUMERIC(12,2)  NOT NULL,
    vigencia_desde    DATE           NOT NULL,
    vigencia_hasta    DATE           NOT NULL,
    created_at        TIMESTAMPTZ    NOT NULL,
    CONSTRAINT ck_sku_precio   CHECK (precio_negociado > 0),
    CONSTRAINT ck_sku_vigencia CHECK (vigencia_hasta >= vigencia_desde)
);
COMMENT ON TABLE catalogo.sku_catalogo IS
  'Oferta SKU-proveedor: un mismo SKU comercial puede ser ofrecido por varios proveedores; el precio es de la relación.';

-- ---------------------------------------------------------------------
-- logistica.franjas_cedi  (90 000 - 150 000 filas)
-- ---------------------------------------------------------------------
CREATE TABLE logistica.franjas_cedi (
    id                   INT          PRIMARY KEY,
    cedi_id              SMALLINT     NOT NULL,   -- 5 CEDI: SMALLINT (2 B)
    fecha                DATE         NOT NULL,
    hora_inicio          TIME         NOT NULL,
    hora_fin             TIME         NOT NULL,
    capacidad_total      SMALLINT     NOT NULL,
    capacidad_reservada  SMALLINT     NOT NULL,   -- ÚNICA columna caliente: se actualiza en cada reserva
    created_at           TIMESTAMPTZ  NOT NULL,
    CONSTRAINT ck_franjas_horas     CHECK (hora_fin > hora_inicio),
    CONSTRAINT ck_franjas_capacidad CHECK (capacidad_reservada >= 0 AND capacidad_reservada <= capacidad_total)
) WITH (fillfactor = 80);
COMMENT ON TABLE logistica.franjas_cedi IS
  'Recurso escaso y concurrente. fillfactor=80 deja espacio en la página para updates HOT de capacidad_reservada; '
  'el CHECK es la última barrera de la invariante reservada <= total (la autoridad es el UPDATE condicional del módulo).';

-- ---------------------------------------------------------------------
-- ordenes.ordenes_compra  (300 000 - 500 000 filas)
-- Columnas ordenadas por alineación (anchas de ancho fijo primero) para minimizar padding por fila.
-- El CSV trae otro orden; \copy usa lista explícita de columnas, así que no importa.
-- ---------------------------------------------------------------------
CREATE TABLE ordenes.ordenes_compra (
    id                INT            PRIMARY KEY,
    proveedor_id      INT            NOT NULL,   -- lógica: proveedores.proveedores(id)
    franja_id         INT            NOT NULL,   -- lógica: logistica.franjas_cedi(id)
    fecha_compromiso  DATE           NOT NULL,   -- snapshot de la fecha de la franja reservada: OTIF sin JOIN entre esquemas
    fecha_entrega     DATE,                      -- NULL: orden no confirmada o aún sin entregar (ck_ordenes_entrega)
    fecha_emision     TIMESTAMPTZ    NOT NULL,
    created_at        TIMESTAMPTZ    NOT NULL,
    total_orden       NUMERIC(14,2)  NOT NULL,
    numero_orden      VARCHAR(50)    NOT NULL,
    estado            VARCHAR(30)    NOT NULL,
    idempotency_key   VARCHAR(36)    NOT NULL,   -- el generador emite 'idemp-<id>-<nnnn>' (no es UUID): VARCHAR(36) del contrato
    CONSTRAINT ck_ordenes_estado  CHECK (estado IN ('CONFIRMADA', 'RECHAZADA', 'EN_PROCESO')),
    CONSTRAINT ck_ordenes_total   CHECK (total_orden >= 0),
    CONSTRAINT ck_ordenes_entrega CHECK (fecha_entrega IS NULL OR estado = 'CONFIRMADA')
) WITH (fillfactor = 90);
COMMENT ON TABLE ordenes.ordenes_compra IS
  'Cabecera de orden. fillfactor=90: estado pasa de EN_PROCESO a CONFIRMADA/RECHAZADA (UPDATE). '
  'Sin partición: Q1/Q5 acceden por proveedor_id y Q4 barre 24 meses de un proveedor, así que particionar por mes no podaría nada útil.';
COMMENT ON COLUMN ordenes.ordenes_compra.fecha_compromiso IS
  'Fecha de la franja reservada, copiada a la orden (snapshot). OTIF = fecha_entrega <= fecha_compromiso y orden completa.';

-- ---------------------------------------------------------------------
-- ordenes.lineas_orden  (1 500 000 - 3 000 000 filas)
-- ---------------------------------------------------------------------
CREATE TABLE ordenes.lineas_orden (
    id                  BIGINT         PRIMARY KEY,   -- BIGINT: la tabla crece más rápido que cualquier otra
    orden_id            INT            NOT NULL,      -- FK a ordenes.ordenes_compra(id) (mismo esquema, tras la carga)
    sku_id              INT            NOT NULL,      -- lógica: catalogo.sku_catalogo(id), sin FK (otro esquema)
    cantidad            INT            NOT NULL,
    precio_unitario     NUMERIC(12,2)  NOT NULL,
    subtotal            NUMERIC(14,2)  NOT NULL,
    cantidad_entregada  INT,                          -- NULL hasta la entrega; insumo del fill rate (Q4)
    CONSTRAINT ck_lineas_cantidad  CHECK (cantidad > 0),
    CONSTRAINT ck_lineas_subtotal  CHECK (subtotal = cantidad * precio_unitario),
    CONSTRAINT ck_lineas_entregada CHECK (cantidad_entregada IS NULL OR (cantidad_entregada >= 0 AND cantidad_entregada <= cantidad))
);
COMMENT ON TABLE ordenes.lineas_orden IS
  'Promedio 5 líneas/orden con cola larga hasta 300. Precio y subtotal se copian al momento de la orden (snapshot, RN-05).';

-- ---------------------------------------------------------------------
-- auditoria.eventos_auditoria  (500 000 - 800 000 filas, append-only)
-- Partición RANGE mensual por fecha_evento. En una tabla particionada la PK debe incluir la
-- columna de partición: PK (id, fecha_evento). El id sigue siendo consecutivo pero su unicidad
-- global no la impone el motor (solo se inserta, nunca se actualiza).
-- ---------------------------------------------------------------------
CREATE TABLE auditoria.eventos_auditoria (
    id             BIGINT       NOT NULL,
    fecha_evento   TIMESTAMPTZ  NOT NULL,
    entidad_id     INT          NOT NULL,   -- lógica: id del registro afectado (sin FK: apunta a varios módulos)
    tipo_evento    VARCHAR(50)  NOT NULL,
    modulo_origen  VARCHAR(30)  NOT NULL,
    payload        TEXT         NOT NULL,   -- TEXT y no JSONB: se escribe una vez y no se consulta por contenido
    PRIMARY KEY (id, fecha_evento),
    CONSTRAINT ck_eventos_modulo CHECK (modulo_origen IN ('ordenes', 'logistica', 'proveedores'))
) PARTITION BY RANGE (fecha_evento);

COMMENT ON TABLE auditoria.eventos_auditoria IS
  'Append-only, particionada por mes: DROP/DETACH de un mes viejo es O(1) y las escrituras se concentran en la partición caliente.';

-- 2024-09 .. 2026-12 (los datos van de 2024-09-17 a 2026-09-16) + DEFAULT para no perder eventos fuera de rango
DO $$
DECLARE
    mes DATE := DATE '2024-09-01';
BEGIN
    WHILE mes < DATE '2027-01-01' LOOP
        EXECUTE format(
            'CREATE TABLE auditoria.eventos_auditoria_%s PARTITION OF auditoria.eventos_auditoria '
            'FOR VALUES FROM (%L) TO (%L)',
            to_char(mes, 'YYYY_MM'), mes, (mes + INTERVAL '1 month')::DATE);
        mes := (mes + INTERVAL '1 month')::DATE;
    END LOOP;
END $$;

CREATE TABLE auditoria.eventos_auditoria_default PARTITION OF auditoria.eventos_auditoria DEFAULT;

\endif

-- =====================================================================
-- FASE 2a · RESTRICCIONES (UNIQUE y FK intra-esquema, DESPUÉS del COPY)
-- =====================================================================
\if :restricciones

ALTER TABLE proveedores.proveedores
    ADD CONSTRAINT uq_proveedores_nit UNIQUE (nit);

ALTER TABLE proveedores.contratos_suministro
    ADD CONSTRAINT uq_contratos_numero UNIQUE (numero_contrato);

ALTER TABLE ordenes.ordenes_compra
    ADD CONSTRAINT uq_ordenes_numero UNIQUE (numero_orden);

-- Idempotencia de extremo a extremo (RN-13): reintentar la misma confirmación no crea otra orden.
ALTER TABLE ordenes.ordenes_compra
    ADD CONSTRAINT uq_ordenes_idempotency UNIQUE (idempotency_key);

-- FKs intra-esquema (NUNCA entre esquemas). Validarlas tras la carga también audita la integridad del generador.
ALTER TABLE proveedores.contratos_suministro
    ADD CONSTRAINT fk_contratos_proveedor FOREIGN KEY (proveedor_id) REFERENCES proveedores.proveedores (id);

ALTER TABLE ordenes.lineas_orden
    ADD CONSTRAINT fk_lineas_orden FOREIGN KEY (orden_id) REFERENCES ordenes.ordenes_compra (id);

\endif

-- =====================================================================
-- FASE 2b · ÍNDICES DE RENDIMIENTO (DESPUÉS del COPY; IF NOT EXISTS: se reponen con `make indices-on`)
-- =====================================================================
\if :indices

-- ---------------------------------------------------------------------
-- Q1 · Validar proveedor y contrato vigente por proveedor_id y fecha (punto, < 10 ms)
--   LEFT JOIN contratos c ON c.proveedor_id = p.id AND c.estado = 'VIGENTE' AND c.fecha_inicio <= $f AND c.fecha_fin >= $f
--   Cada proveedor tiene 0..pocos contratos: (proveedor_id, fecha_fin) los acota. Los INCLUDE dejan
--   la validación "¿hay contrato vigente?" como Index Only Scan; si además lee id o numero_contrato,
--   pasa a Index Scan (1 visita al heap por contrato: sigue siendo puntual).
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_contratos_prov_vigencia
    ON proveedores.contratos_suministro (proveedor_id, fecha_fin)
    INCLUDE (fecha_inicio, estado);

-- ---------------------------------------------------------------------
-- Q2 · Precio y vigencia de 20 SKU del catálogo negociado de un proveedor (lote pequeño)
--   Único por (proveedor_id, sku): una oferta por par SKU-proveedor (RN-06, no solo rendimiento).
--   INCLUDE con precio y vigencia => Index Only Scan (requiere páginas all-visible: cargar.sh ejecuta VACUUM
--   para que no dependa de autovacuum, que tarda ~1 min en llegar a las tablas recién cargadas).
-- ---------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_sku_proveedor_sku
    ON catalogo.sku_catalogo (proveedor_id, sku)
    INCLUDE (id, precio_negociado, vigencia_desde, vigencia_hasta);

-- ---------------------------------------------------------------------
-- Q3 · Franjas disponibles de un CEDI para una fecha (recurso escaso, alta concurrencia)
--   WHERE cedi_id = $1 AND fecha = $2 AND capacidad_reservada < capacidad_total ORDER BY hora_inicio
--   Deliberadamente SIN capacidad_reservada en el índice ni en INCLUDE: es la columna que se actualiza
--   en cada reserva y, si estuviera indexada, cada UPDATE dejaría de ser HOT y escribiría en el índice.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_franjas_cedi_fecha
    ON logistica.franjas_cedi (cedi_id, fecha, hora_inicio);

-- ---------------------------------------------------------------------
-- Q5 y Q4 · Órdenes de un proveedor por fecha
--   Q5: WHERE proveedor_id = $1 ORDER BY fecha_emision DESC, id DESC LIMIT 50 (OFFSET o keyset)
--   Q4: WHERE proveedor_id = $1 AND fecha_emision >= $2 AND fecha_emision < $3  (24 meses de un proveedor)
--   El orden del índice (con id como desempate) evita el Sort y permite keyset pagination por (fecha_emision, id).
--   Sin INCLUDE de estado/fechas de entrega: estado se actualiza en la confirmación (EN_PROCESO -> CONFIRMADA)
--   y meterla en el índice impediría updates HOT. Variante covering: alternativa a medir en Q4.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_ordenes_proveedor_fecha
    ON ordenes.ordenes_compra (proveedor_id, fecha_emision DESC, id DESC);

-- ---------------------------------------------------------------------
-- Q4 · Líneas de una orden (agregación de fill rate y "orden completa" por orden)
--   INCLUDE (cantidad, cantidad_entregada): las líneas son casi inmutables (cantidad_entregada se fija una
--   vez al entregar), así que cubrir esas dos columnas es barato y deja la agregación como Index Only Scan.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_lineas_orden
    ON ordenes.lineas_orden (orden_id)
    INCLUDE (cantidad, cantidad_entregada);

-- auditoria.eventos_auditoria: sin índices secundarios a propósito. Es append-only y ninguna de
-- Q1..Q5 la consulta; cada índice adicional encarecería la ruta de escritura. La poda de particiones
-- por fecha_evento cubre las consultas temporales. Si aparece "eventos de una entidad", añadir
-- (modulo_origen, entidad_id) sobre la tabla padre (se propaga a las particiones).

\endif
