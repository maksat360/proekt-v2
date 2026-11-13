# -*- coding: utf-8 -*-
"""Импорт с предпросмотром: dry-run сравнение выбранной книги с SQL.

Применение НЕ выполняется — только отчёт: сколько вставится, обновится,
не изменится и где конфликты.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compare
import db as sqldb


def preview(path: Path, con: sqlite3.Connection) -> dict:
    path = Path(path)
    excel = compare.excel_metrics(path)
    sql = compare.sql_metrics(con)
    rep = compare.compare(excel, sql)

    changes = []
    for name, e_stock in excel["stock"].items():
        s_stock = sql["stock"].get(name)
        if s_stock is None:
            changes.append({"тип": "insert", "товар": name, "excel": e_stock})
        elif abs(e_stock - s_stock) > 0.01:
            changes.append({"тип": "update", "товар": name,
                            "было_sql": s_stock, "станет_excel": e_stock})
    for name in sql["stock"]:
        if name not in excel["stock"]:
            changes.append({"тип": "missing_in_file", "товар": name,
                            "осталось_sql": sql["stock"][name]})
    return {
        "файл": path.name,
        "совпадает": rep["ok"],
        "расхождений": rep["всего_расхождений"],
        "изменения": changes[:200],
        "всего_изменений": len(changes),
        "проверки_структуры": _structure(path),
    }


def _structure(path: Path) -> dict:
    from openpyxl import load_workbook
    need = ["главный", "адрес", "приобритение"]
    wb = load_workbook(path, read_only=True)
    try:
        names = set(wb.sheetnames)
    finally:
        wb.close()
    return {"обязательные_листы": {n: (n in names) for n in need},
            "все_листы": sorted(names)}


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else sqldb.MASTER
    con = sqldb.connect()
    out = preview(target, con)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
    con.close()
