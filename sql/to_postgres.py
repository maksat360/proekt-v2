# -*- coding: utf-8 -*-
"""Переезд на PostgreSQL: схема → копия всех таблиц из data/sql/portal.db →
остатки заново из книги (Google Диск) → сверка → config «db»: «postgres».

  python3 sql/to_postgres.py "<путь к цех_склад для apk.xlsm>"

SQLite-файл не меняется (остаётся резервом). Повторный запуск безопасен: таблицы в PG очищаются и заливаются заново.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as sqldb
import importer

# порядок — по внешним ключам
TABLES = ["meta", "products", "locations", "purchases", "placements", "shipments",
          "orders", "order_items", "order_status_history", "employees", "rates", "sales",
          "imports", "import_changes", "audit_log", "wb_sku_map", "wb_sync_log"]
SERIAL = ["imports", "import_changes", "audit_log", "order_status_history", "wb_sync_log"]


def stock(con) -> dict[str, float]:
    rows = con.execute(
        """SELECT p.name AS name,
                  COALESCE((SELECT SUM(qty) FROM placements WHERE product_id = p.id), 0) -
                  COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id = p.id), 0) AS q
           FROM products p""").fetchall()
    return {r["name"]: round(float(r["q"] or 0), 3) for r in rows}


def main(book: str) -> int:
    book_path = Path(book)
    if not book_path.exists():
        print("нет файла:", book_path)
        return 1
    src = sqldb.connect(sqldb.DB_PATH)
    print("1) резервная копия SQLite:", sqldb.backup(src).name)
    pg = sqldb.PgConnection(sqldb.pg_dsn())
    print("2) схема PostgreSQL, миграций:", sqldb.migrate(pg))
    pg.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    pg.execute("BEGIN")
    try:
        for t in reversed(TABLES):
            pg.execute(f"DELETE FROM {t}")
        for t in TABLES:
            rows = src.execute(f"SELECT * FROM {t}").fetchall()
            if not rows:
                continue
            cols = rows[0].keys()
            sql = (f"INSERT INTO {t}({', '.join(cols)}) "
                   f"VALUES ({', '.join('?' * len(cols))})")
            for r in rows:
                pg.execute(sql, tuple(r))
            print(f"   {t}: {len(rows)}")
        for t in SERIAL:
            pg.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                       f"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)")
        before = stock(pg)

        # 3) факт со склада — из книги: Excel-строки размещений/отгрузок заменяются, FBS-списания остаются
        pg.execute("DELETE FROM placements WHERE COALESCE(source_sheet, '') <> 'FBS'"
                   " AND COALESCE(external_uuid, '') NOT LIKE 'shadow:%'")
        pg.execute("DELETE FROM shipments WHERE COALESCE(source_sheet, '') <> 'FBS'"
                   " AND COALESCE(external_uuid, '') NOT LIKE 'shadow:%'")
        stats = importer.import_workbook(book_path, pg, actor="to_postgres")
        print("3) импорт книги:", book_path.name, stats)
        sqldb.set_meta(pg, "last_import", {"ts": sqldb.now(), "file": str(book_path), "stats": stats})
        pg.execute("COMMIT")
    except Exception:
        pg.execute("ROLLBACK")
        raise

    after = stock(pg)
    diff = {k: (before.get(k, 0), v) for k, v in after.items() if abs(before.get(k, 0) - v) > 1e-6}
    print(f"4) остаток всего: было {sum(before.values()):.0f} → стало {sum(after.values()):.0f}, "
          f"изменилось позиций: {len(diff)}")
    cfg = sqldb.load_config()
    cfg.update(db="postgres", pg_dsn=sqldb.pg_dsn(), shadow=True)
    sqldb.save_config(cfg)
    print("5) config.json: db=postgres, shadow=true (операции склада пишутся в PostgreSQL)")
    print("6) резервная копия PG:", sqldb.backup(pg).name)
    pg.close()
    src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
