# -*- coding: utf-8 -*-
"""Сравнение Excel-расчётов и SQL (фаза 3). Ничего не исправляет."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent.parent
SHIP_SHEETS = ("паставка ЖСК", "паставка ККМ", "паставка ААТ",
               "паставка4", "паставка5", "паставка6")
SHOP_SHEET = "магазин"


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return 0.0


def excel_metrics(path: Path) -> dict:
    """Считает те же величины, что формулы книги, но напрямую по листам (read-only)."""
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        placed = defaultdict(float)
        purchased = defaultdict(float)
        defect = defaultdict(float)
        shipped = defaultdict(float)
        shop = defaultdict(float)
        catalog = set()

        if "главный" in wb.sheetnames:
            for row in list(wb["главный"].iter_rows(values_only=True))[4:]:
                if row and len(row) > 11 and row[11]:
                    catalog.add(_clean(row[11]))

        if "адрес" in wb.sheetnames:
            for row in list(wb["адрес"].iter_rows(values_only=True))[1:]:
                if row and len(row) > 6 and row[5]:
                    placed[_clean(row[5])] += _num(row[6])

        if "приобритение" in wb.sheetnames:
            for row in list(wb["приобритение"].iter_rows(values_only=True))[7:]:
                if row and len(row) > 7 and row[2]:
                    purchased[_clean(row[2])] += _num(row[7])
                    defect[_clean(row[2])] += _num(row[6])

        for sheet in SHIP_SHEETS:
            if sheet not in wb.sheetnames:
                continue
            for row in list(wb[sheet].iter_rows(values_only=True))[1:]:
                if row and len(row) > 6 and row[5]:
                    shipped[_clean(row[5])] += _num(row[6])

        if SHOP_SHEET in wb.sheetnames:
            for row in list(wb[SHOP_SHEET].iter_rows(values_only=True))[1:]:
                if row and len(row) > 3 and row[2]:
                    shop[_clean(row[2])] += _num(row[3])
    finally:
        wb.close()

    names = set(catalog) | set(placed) | set(shipped) | set(purchased)
    stock, pending = {}, {}
    for n in names:
        stock[n] = round(placed.get(n, 0.0) - shipped.get(n, 0.0) - shop.get(n, 0.0), 2)
        pending[n] = round(purchased.get(n, 0.0) - placed.get(n, 0.0) - defect.get(n, 0.0), 2)

    return {
        "products": len(catalog),
        "stock": stock,
        "pending": pending,
        "ship_total": round(sum(shipped.values()), 2),
        "shop_total": round(sum(shop.values()), 2),
        "placed_total": round(sum(placed.values()), 2),
        "purchased_total": round(sum(purchased.values()), 2),
    }


def sql_metrics(con: sqlite3.Connection) -> dict:
    stock, pending = {}, {}
    rows = con.execute("""
        SELECT p.name AS name,
               COALESCE((SELECT SUM(qty) FROM placements WHERE product_id = p.id), 0) AS placed,
               COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id = p.id AND target <> 'магазин'), 0) AS shipped,
               COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id = p.id AND target = 'магазин'), 0) AS shop,
               COALESCE((SELECT SUM(qty) FROM purchases WHERE product_id = p.id), 0) AS purchased,
               COALESCE((SELECT SUM(defect) FROM purchases WHERE product_id = p.id), 0) AS defect
        FROM products p
    """).fetchall()
    for r in rows:
        stock[r["name"]] = round(r["placed"] - r["shipped"] - r["shop"], 2)
        pending[r["name"]] = round(r["purchased"] - r["placed"] - r["defect"], 2)
    totals = con.execute("""
        SELECT (SELECT SUM(qty) FROM placements) AS placed,
               (SELECT SUM(qty) FROM purchases) AS purchased,
               (SELECT SUM(qty) FROM shipments WHERE target <> 'магазин') AS shipped,
               (SELECT SUM(qty) FROM shipments WHERE target = 'магазин') AS shop
    """).fetchone()
    return {
        "products": con.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        "stock": stock,
        "pending": pending,
        "ship_total": round(totals["shipped"] or 0, 2),
        "shop_total": round(totals["shop"] or 0, 2),
        "placed_total": round(totals["placed"] or 0, 2),
        "purchased_total": round(totals["purchased"] or 0, 2),
    }


def compare(excel: dict, sql: dict, limit: int = 40) -> dict:
    names = set(excel["stock"]) | set(sql["stock"])
    diffs = []
    for n in names:
        e_stock = excel["stock"].get(n, 0.0)
        s_stock = sql["stock"].get(n, 0.0)
        e_pend = excel["pending"].get(n, 0.0)
        s_pend = sql["pending"].get(n, 0.0)
        if abs(e_stock - s_stock) > 0.01 or abs(e_pend - s_pend) > 0.01:
            diffs.append({
                "товар": n,
                "остаток_excel": e_stock, "остаток_sql": s_stock,
                "ожидает_excel": e_pend, "ожидает_sql": s_pend,
                "разница": round(s_stock - e_stock, 2),
            })
    diffs.sort(key=lambda d: -abs(d["разница"]))
    dupes = []
    return {
        "excel": {k: v for k, v in excel.items() if not isinstance(v, dict)},
        "sql": {k: v for k, v in sql.items() if not isinstance(v, dict)},
        "товаров_excel": excel["products"],
        "товаров_sql": sql["products"],
        "расхождения": diffs[:limit],
        "всего_расхождений": len(diffs),
        "дубликаты": dupes,
        "ok": (excel["products"] == sql["products"]
               and abs(excel["placed_total"] - sql["placed_total"]) < 0.01
               and abs(excel["purchased_total"] - sql["purchased_total"]) < 0.01
               and abs(excel["ship_total"] - sql["ship_total"]) < 0.01
               and abs(excel["shop_total"] - sql["shop_total"]) < 0.01
               and not diffs),
    }


def to_markdown(report: dict) -> str:
    e, s = report["excel"], report["sql"]
    lines = [
        "# Отчёт сравнения Excel ↔ SQL",
        "",
        "| Показатель | Excel | SQL | Совпадает |",
        "|---|---:|---:|:---:|",
    ]
    labels = [
        ("products", "Товаров"),
        ("placed_total", "Размещено, шт"),
        ("purchased_total", "Закуплено, шт"),
        ("ship_total", "Отгружено, шт"),
        ("shop_total", "Списано магазином, шт"),
    ]
    for key, label in labels:
        ev, sv = e[key], s[key]
        same = "✅" if abs(float(ev) - float(sv)) < 0.01 else "❌"
        lines.append(f"| {label} | {ev} | {sv} | {same} |")
    lines += ["", f"**Расхождений по товарам:** {report['всего_расхождений']}", ""]
    if report["расхождения"]:
        lines += ["| Товар | Остаток Excel | Остаток SQL | Ожидает Excel | Ожидает SQL |",
                  "|---|---:|---:|---:|---:|"]
        for d in report["расхождения"][:25]:
            lines.append(f"| {d['товар']} | {d['остаток_excel']} | {d['остаток_sql']} "
                         f"| {d['ожидает_excel']} | {d['ожидает_sql']} |")
    lines += ["", f"Итог: {'✅ сходится' if report['ok'] else '⚠️ есть расхождения'}"]
    return "\n".join(lines)
