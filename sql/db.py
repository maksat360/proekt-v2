# -*- coding: utf-8 -*-
"""SQL-слой: подключение, миграции, резервные копии, аудит.

SQLite выбран осознанно: одно устройство, 2–3 пользователя, доступ только
через backend. Файл БД лежит вне временных каталогов: data/sql/portal.db.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SQL_DIR = BASE / "data" / "sql"
DB_PATH = Path(os.environ.get("V2_DB", SQL_DIR / "portal.db"))
BACKUP_DIR = SQL_DIR / "backups"
MASTER = BASE / "master" / "цех_склад_master_2026-10-21.xlsm"
CONFIG = BASE / "config.json"

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "initial schema", [
        """CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            category TEXT, model TEXT, color TEXT, size TEXT,
            source_sheet TEXT, source_row INTEGER,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE,
            kind TEXT, note TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS purchases (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, supplier TEXT, batch TEXT,
            product_id TEXT NOT NULL REFERENCES products(id),
            qty REAL NOT NULL, defect REAL DEFAULT 0,
            status TEXT DEFAULT 'ok', source TEXT,
            external_uuid TEXT UNIQUE, source_sheet TEXT, source_row INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS placements (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL,
            location_code TEXT NOT NULL, product_id TEXT NOT NULL REFERENCES products(id),
            qty REAL NOT NULL, status TEXT DEFAULT 'ok',
            external_uuid TEXT UNIQUE, source_sheet TEXT, source_row INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS shipments (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, target TEXT NOT NULL,
            product_id TEXT NOT NULL REFERENCES products(id),
            qty REAL NOT NULL, order_ref TEXT, user TEXT,
            status TEXT DEFAULT 'ok', external_uuid TEXT UNIQUE,
            source_sheet TEXT, source_row INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL, client TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'новый', closed_at TEXT,
            cancelled_by TEXT, reason TEXT,
            external_uuid TEXT UNIQUE, source_sheet TEXT, source_row INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS order_items (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id TEXT NOT NULL REFERENCES products(id),
            qty REAL NOT NULL, shipped REAL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS employees (
            login TEXT PRIMARY KEY, name TEXT, role TEXT, workshop TEXT,
            rate_hour REAL DEFAULT 0, active INTEGER DEFAULT 1,
            password_state TEXT DEFAULT 'unknown'
        )""",
        """CREATE TABLE IF NOT EXISTS rates (
            code TEXT PRIMARY KEY, name TEXT, price REAL DEFAULT 0,
            sort_order INTEGER DEFAULT 0, required INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS sales (
            id TEXT PRIMARY KEY, ts TEXT NOT NULL,
            product_id TEXT REFERENCES products(id),
            qty REAL NOT NULL, price REAL, total REAL,
            buyer TEXT, user TEXT, status TEXT DEFAULT 'ok',
            external_uuid TEXT UNIQUE
        )""",
        """CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            file_name TEXT, file_sha256 TEXT, user TEXT, mode TEXT,
            summary_json TEXT, status TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS import_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
            entity TEXT, entity_id TEXT, change TEXT,
            before_json TEXT, after_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            actor TEXT, action TEXT, entity TEXT, entity_id TEXT,
            payload_json TEXT, outcome TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_placements_product ON placements(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_shipments_product ON shipments(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_purchases_product ON purchases(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)",
    ]),

    (2, "orders: types, cabinets, statuses, history", [
        "ALTER TABLE orders ADD COLUMN type TEXT NOT NULL DEFAULT 'shop'",
        "ALTER TABLE orders ADD COLUMN cabinet_id TEXT",
        "ALTER TABLE orders ADD COLUMN external_id TEXT",
        "ALTER TABLE orders ADD COLUMN external_number TEXT",
        "ALTER TABLE orders ADD COLUMN customer_id TEXT",
        "ALTER TABLE orders ADD COLUMN customer_name TEXT",
        "ALTER TABLE orders ADD COLUMN source TEXT DEFAULT 'app'",
        "ALTER TABLE orders ADD COLUMN updated_at TEXT",
        "ALTER TABLE orders ADD COLUMN comment TEXT",
        "ALTER TABLE orders ADD COLUMN amount REAL",
        "ALTER TABLE order_items ADD COLUMN external_sku TEXT",
        "ALTER TABLE order_items ADD COLUMN title TEXT",
        "ALTER TABLE order_items ADD COLUMN size TEXT",
        "ALTER TABLE order_items ADD COLUMN color TEXT",
        "ALTER TABLE order_items ADD COLUMN price REAL",
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_external
             ON orders(type, cabinet_id, external_id) WHERE external_id IS NOT NULL""",
        "CREATE INDEX IF NOT EXISTS ix_orders_list ON orders(type, status, ts)",
        """CREATE TABLE IF NOT EXISTS order_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            from_status TEXT, to_status TEXT NOT NULL,
            actor TEXT, at TEXT NOT NULL, comment TEXT)""",
        "CREATE INDEX IF NOT EXISTS ix_history_order ON order_status_history(order_id, at)",
        """CREATE TABLE IF NOT EXISTS wb_sku_map (
            cabinet_id TEXT NOT NULL, external_sku TEXT NOT NULL,
            product_id TEXT REFERENCES products(id),
            PRIMARY KEY (cabinet_id, external_sku))""",
        """CREATE TABLE IF NOT EXISTS wb_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            cabinet_id TEXT, action TEXT, found INTEGER, created INTEGER,
            updated INTEGER, errors INTEGER, note TEXT)""",
    ]),
    (3, "order_items: product_id может быть пустым (нетоварный артикул)", [
        """CREATE TABLE order_items_new (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id TEXT REFERENCES products(id),
            qty REAL NOT NULL, shipped REAL DEFAULT 0,
            external_sku TEXT, title TEXT, size TEXT, color TEXT, price REAL)""",
        """INSERT INTO order_items_new(id, order_id, product_id, qty, shipped,
               external_sku, title, size, color, price)
           SELECT id, order_id, product_id, qty, shipped,
                  external_sku, title, size, color, price FROM order_items""",
        "DROP TABLE order_items",
        "ALTER TABLE order_items_new RENAME TO order_items",
        "CREATE INDEX IF NOT EXISTS ix_items_order ON order_items(order_id)",
    ]),
    (4, "order_items: id позиции в WB", [
        "ALTER TABLE order_items ADD COLUMN external_id TEXT",
        "CREATE INDEX IF NOT EXISTS ix_items_external ON order_items(order_id, external_id)",
    ]),
    (5, "orders: внутренний rid отдельно от номера задания", [
        "ALTER TABLE orders ADD COLUMN external_uid TEXT",
        "CREATE INDEX IF NOT EXISTS ix_orders_uid ON orders(type, cabinet_id, external_uid)",
    ]),
    (6, "контрагенты: поставщики, покупатели, собственные компании и цеха", [
        """CREATE TABLE IF NOT EXISTS counterparties (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
            phone TEXT, note TEXT, created_at TEXT NOT NULL, updated_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS ix_counterparties_cat ON counterparties(category, name)",
    ]),
    (7, "адресное хранение: ячейки P/N, коробки K, мешки M и что в них лежит", [
        """CREATE TABLE IF NOT EXISTS wh_places (
            code TEXT PRIMARY KEY, kind TEXT NOT NULL, rack INTEGER, floor INTEGER, cell INTEGER,
            at TEXT, status TEXT NOT NULL DEFAULT 'active', replaced_by TEXT,
            created_at TEXT NOT NULL, updated_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS ix_wh_places_kind ON wh_places(kind, status)",
        """CREATE TABLE IF NOT EXISTS wh_contents (
            place TEXT NOT NULL, product TEXT NOT NULL, qty REAL NOT NULL, updated_at TEXT,
            PRIMARY KEY (place, product))""",
        "CREATE INDEX IF NOT EXISTS ix_wh_contents_product ON wh_contents(product)",
    ]),
]


# ---------------------------------------------------------------- PostgreSQL
# Рабочая база — PostgreSQL (config.json → "db": "postgres", "pg_dsn").
# SQLite остаётся для тестов и явного пути (connect(path) или V2_DB).
_PG_SUBS = [
    (re.compile(r"\bBEGIN IMMEDIATE\b"), "BEGIN"),
    (re.compile(r"\bINTEGER PRIMARY KEY AUTOINCREMENT\b"), "SERIAL PRIMARY KEY"),
    (re.compile(r"\bREAL\b"), "DOUBLE PRECISION"),
    (re.compile(r'(?<![\w"])user(?![\w"])'), '"user"'),  # user — зарезервированное слово в PG
]


def _pg_sql(sql: str) -> str:
    sql = sql.replace("%", "%%").replace("?", "%s")  # shortcut: «?» внутри строковых литералов не поддержан
    for rx, rep in _PG_SUBS:
        sql = rx.sub(rep, sql)
    return sql


class PgRow(dict):
    """Строка как sqlite3.Row: r["col"] и r[0]."""
    __slots__ = ("_v",)

    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._v = values

    def __getitem__(self, k):
        return self._v[k] if isinstance(k, int) else super().__getitem__(k)


def _pg_rows(cur):
    names = [c.name for c in cur.description] if cur.description else []
    return lambda values: PgRow(names, values)


class PgConnection:
    """Тонкая обёртка psycopg с интерфейсом sqlite3 (execute → курсор, «?» → %s)."""
    dialect = "postgres"

    def __init__(self, dsn: str):
        import psycopg
        from psycopg.adapt import Dumper

        class _LooseInt(Dumper):
            oid = 0  # unknown: PG выводит тип из контекста (текст = 123 не падает, как в SQLite)

            def dump(self, obj):
                return str(int(obj)).encode()

        self._c = psycopg.connect(dsn, autocommit=True, row_factory=_pg_rows)
        for t in (int, bool):  # bool → 1/0, как в SQLite (булевых столбцов в схеме нет)
            self._c.adapters.register_dumper(t, _LooseInt)

    def execute(self, sql: str, params=()):
        return self._c.execute(_pg_sql(sql), tuple(params or ()))

    def close(self) -> None:
        self._c.close()


def pg_dsn() -> str:
    return os.environ.get("V2_PG") or str(load_config().get("pg_dsn") or "dbname=portal")


def _testing() -> bool:
    """Запуск тестов (python -m unittest / pytest) — рабочую базу не трогаем."""
    import sys
    argv0 = os.path.basename(sys.argv[0] if sys.argv else "")
    return "unittest" in argv0 or "pytest" in argv0


def use_pg(path=None) -> bool:
    if path or os.environ.get("V2_DB"):
        return False
    if os.environ.get("V2_PG"):
        return True
    if _testing():
        return False
    return load_config().get("db") == "postgres"


def connect(path: Path | str | None = None):
    if use_pg(path):
        return PgConnection(pg_dsn())
    target = Path(path) if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(target), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def migrate(con: sqlite3.Connection) -> int:
    con.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, note TEXT)""")
    done = {r["version"] for r in con.execute("SELECT version FROM schema_version")}
    applied = 0
    for version, note, statements in MIGRATIONS:
        if version in done:
            continue
        con.execute("BEGIN IMMEDIATE")
        try:
            for sql in statements:
                con.execute(sql)
            con.execute("INSERT INTO schema_version(version, applied_at, note) VALUES (?,?,?)",
                        (version, now(), note))
            con.execute("COMMIT")
            applied += 1
        except Exception:
            con.execute("ROLLBACK")
            raise
    return applied


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pg_bin(name: str) -> str:
    for d in ("/opt/homebrew/opt/postgresql@17/bin", "/usr/local/opt/postgresql@17/bin"):
        if Path(d, name).exists():
            return str(Path(d, name))
    return shutil.which(name) or name


def backup(con: sqlite3.Connection, keep: int = 30) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    pg = isinstance(con, PgConnection)
    dest = BACKUP_DIR / f"portal_{datetime.now():%Y%m%d_%H%M%S}.{'sql' if pg else 'db'}"
    if pg:
        subprocess.run([_pg_bin("pg_dump"), "-f", str(dest), pg_dsn()], check=True)
    else:
        con.execute("VACUUM INTO ?", (str(dest),))
    old = sorted(BACKUP_DIR.glob(f"portal_*.{dest.suffix[1:]}"))
    for f in old[:-keep]:
        f.unlink(missing_ok=True)
    return dest


def audit(con: sqlite3.Connection, actor: str, action: str, entity: str = "",
          entity_id: str = "", payload: dict | None = None, outcome: str = "ok") -> None:
    con.execute(
        "INSERT INTO audit_log(ts, actor, action, entity, entity_id, payload_json, outcome) "
        "VALUES (?,?,?,?,?,?,?)",
        (now(), actor, action, entity, str(entity_id),
         json.dumps(payload or {}, ensure_ascii=False), outcome))


def set_meta(con: sqlite3.Connection, key: str, value) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta(key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))


def get_meta(con: sqlite3.Connection, key: str, default=None):
    try:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except Exception:  # нет таблицы meta (sqlite / postgres)
        return default
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"backend": "excel", "shadow": False}


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def shadow_enabled() -> bool:
    if os.environ.get("V2_SHADOW") == "1":
        return True
    return not _testing() and bool(load_config().get("shadow"))


def backend() -> str:
    return str(load_config().get("backend", "excel"))


def integrity(con: sqlite3.Connection) -> str:
    if isinstance(con, PgConnection):
        con.execute("SELECT 1")
        return "ok"
    return con.execute("PRAGMA integrity_check").fetchone()[0]


def archive_excel_data(keep: int = 10) -> Path | None:
    """Архив всех data/*.xlsx перед первой миграцией."""
    data = BASE / "data"
    files = sorted(p for p in data.glob("*.xlsx"))
    if not files:
        return None
    out_dir = data / "backups"
    out_dir.mkdir(exist_ok=True)
    dest = out_dir / f"data_{datetime.now():%Y%m%d_%H%M%S}.zip"
    import zipfile
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
    old = sorted(out_dir.glob("data_*.zip"))
    for f in old[:-keep]:
        f.unlink(missing_ok=True)
    return dest
