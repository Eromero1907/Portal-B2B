-- P1 · Índice covering de órdenes para Q4 (Index Only Scan en lugar de Bitmap Heap Scan)
CREATE INDEX IF NOT EXISTS idx_ordenes_proveedor_fecha_cubriente
    ON ordenes.ordenes_compra (proveedor_id, fecha_emision DESC, id DESC)
    INCLUDE (estado, fecha_compromiso, fecha_entrega);
VACUUM (ANALYZE) ordenes.ordenes_compra;
