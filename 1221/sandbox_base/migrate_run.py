# -*- coding: utf-8 -*-
"""Разовая миграция: архив Excel-данных → схема SQL → импорт мастер-копии → сравнение."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compare
import db as sqldb
import importer


def main() -> int:
    print("1) архив data/*.xlsx …")
    archive = sqldb.archive_excel_data()
    print("   ", archive.name if archive else "нет файлов")

    print("2) база:", sqldb.DB_PATH)
    con = sqldb.connect()
    applied = sqldb.migrate(con)
    print("   миграций применено:", applied)

    print("3) импорт мастер-копии:", sqldb.MASTER.name)
    stats = importer.import_workbook(sqldb.MASTER, con, actor="migration")
    print("   ", stats)

    print("4) резервная копия БД …")
    bak = sqldb.backup(con)
    print("   ", bak.name, f"{bak.stat().st_size/1024:.0f} КБ")

    print("5) сравнение Excel ↔ SQL …")
    excel = compare.excel_metrics(sqldb.MASTER)
    sql = compare.sql_metrics(con)
    report = compare.compare(excel, sql)
    print("   товаров:", report["товаров_excel"], "vs", report["товаров_sql"],
          "| расхождений:", report["всего_расхождений"], "| ok:", report["ok"])

    out = Path(__file__).resolve().parent.parent / "docs" / "SHADOW_REPORT.md"
    out.write_text(compare.to_markdown(report), encoding="utf-8")
    print("6) отчёт:", out.relative_to(out.parents[2]))

    sqldb.set_meta(con, "last_import", {"ts": sqldb.now(), "file": sqldb.MASTER.name,
                                        "stats": stats})
    sqldb.set_meta(con, "compare", {"ok": report["ok"], "diffs": report["всего_расхождений"]})
    print("7) integrity:", sqldb.integrity(con))
    con.close()
    return 0 if report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
