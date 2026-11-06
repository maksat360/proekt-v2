-- Черновик схемы v2: заказы FBS / FBO / магазин
-- Применять только после проверки на копии базы.

CREATE TABLE IF NOT EXISTS wb_cabinets (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    wb_name      TEXT,
    token_ref    TEXT,
    active       INTEGER DEFAULT 1,
    last_sync_at TEXT,
    last_error   TEXT
);

ALTER TABLE orders ADD COLUMN type TEXT NOT NULL DEFAULT 'shop';
ALTER TABLE orders ADD COLUMN cabinet_id TEXT REFERENCES wb_cabinets(id);
ALTER TABLE orders ADD COLUMN external_id TEXT;
ALTER TABLE orders ADD COLUMN external_number TEXT;
ALTER TABLE orders ADD COLUMN customer_id TEXT;
ALTER TABLE orders ADD COLUMN customer_name TEXT;
ALTER TABLE orders ADD COLUMN source TEXT DEFAULT 'app';
ALTER TABLE orders ADD COLUMN updated_at TEXT;
ALTER TABLE orders ADD COLUMN comment TEXT;

ALTER TABLE order_items ADD COLUMN external_sku TEXT;
ALTER TABLE order_items ADD COLUMN title TEXT;
ALTER TABLE order_items ADD COLUMN size TEXT;
ALTER TABLE order_items ADD COLUMN color TEXT;
ALTER TABLE order_items ADD COLUMN price REAL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_external
    ON orders(type, cabinet_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_orders_list ON orders(type, status, ts);

CREATE TABLE IF NOT EXISTS order_status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    actor       TEXT,
    at          TEXT NOT NULL,
    comment     TEXT
);
CREATE INDEX IF NOT EXISTS ix_history_order ON order_status_history(order_id, at);

CREATE TABLE IF NOT EXISTS wb_sku_map (
    cabinet_id   TEXT NOT NULL REFERENCES wb_cabinets(id),
    external_sku TEXT NOT NULL,
    product_id   TEXT REFERENCES products(id),
    PRIMARY KEY (cabinet_id, external_sku)
);
