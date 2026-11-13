# -*- coding: utf-8 -*-
"""Импорт данных из Excel-книги и data/*.xlsx в SQL.

Книга открывается ТОЛЬКО для чтения. Ничего не сохраняется.
Импорт идемпотентен: повторный запуск обновляет записи, а не создаёт дубли.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import db as sqldb

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def _id(*parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return default


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _product_id(con: sqlite3.Connection, name: str, extra: dict | None = None) -> str:
    row = con.execute("SELECT id FROM products WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    pid = _id("product", name)
    parts = [p.strip() for p in name.split("/")]
    con.execute(
        "INSERT INTO products(id, name, category, model, color, size, source_sheet, source_row, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, name, (extra or {}).get("category") or (parts[0] if parts else ""),
         (extra or {}).get("model") or (parts[1] if len(parts) > 1 else ""),
         (extra or {}).get("color") or (parts[2] if len(parts) > 2 else ""),
         (extra or {}).get("size") or (parts[3] if len(parts) > 3 else ""),
         (extra or {}).get("sheet"), (extra or {}).get("row"), sqldb.now()))
    return pid


def import_workbook(path: Path, con: sqlite3.Connection, actor: str = "importer") -> dict:
    """Читает книгу и наполняет SQL. Возвращает статистику."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    stats = Counter()
    started = sqldb.now()

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        # ---------- товары: главный
        ws = wb["главный"]
        rows = list(ws.iter_rows(values_only=True))
        for i, row in enumerate(rows[4:], start=5):
            if not row or len(row) < 12 or not row[11]:
                continue
            name = _clean(row[11])
            if not name:
                continue
            parts = [p.strip() for p in name.split("/")]
            con.execute(
                """INSERT INTO products(id, name, category, model, color, size, source_sheet, source_row, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                     category=excluded.category, model=excluded.model, color=excluded.color,
                     size=excluded.size, source_sheet=excluded.source_sheet, source_row=excluded.source_row""",
                (_id("product", name), name, parts[0] if parts else "",
                 parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "",
                 parts[3] if len(parts) > 3 else "", "главный", i, started))
            stats["products"] += 1

        # ---------- приход: приобритение (шапка в строке 7)
        ws = wb["приобритение"]
        seen = Counter()
        for i, row in enumerate(list(ws.iter_rows(values_only=True))[7:], start=8):
            if not row or len(row) < 8 or not row[2]:
                continue
            name = _clean(row[2])
            qty = _num(row[7])
            if not name or qty == 0:
                continue
            pid = _product_id(con, name)
            ts = _clean(row[0]) or started[:10]
            sup = _clean(row[1])
            seen[(ts, name, qty, sup)] += 1
            ext = f"приобритение:{ts}:{name}:{qty}:{seen[(ts, name, qty, sup)]}"
            con.execute(
                """INSERT INTO purchases(id, ts, supplier, batch, product_id, qty, defect,
                        source, external_uuid, source_sheet, source_row)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(external_uuid) DO UPDATE SET qty=excluded.qty, batch=excluded.batch""",
                (_id("purchase", ext), ts, sup, _clean(row[8]), pid, qty, _num(row[6]),
                 "excel", ext, "приобритение", i))
            stats["purchases"] += 1

        # ---------- размещение: адрес
        ws = wb["адрес"]
        seen = Counter()
        for i, row in enumerate(list(ws.iter_rows(values_only=True))[1:], start=2):
            if not row or len(row) < 7 or not row[5]:
                continue
            name = _clean(row[5])
            qty = _num(row[6])
            box = _clean(row[4])
            if not name or qty == 0:
                continue
            pid = _product_id(con, name)
            ts = _clean(row[3]) or started[:10]
            seen[(ts, box, name, qty)] += 1
            ext = f"адрес:{ts}:{box}:{name}:{qty}:{seen[(ts, box, name, qty)]}"
            con.execute(
                """INSERT INTO placements(id, ts, location_code, product_id, qty, external_uuid,
                        source_sheet, source_row)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(external_uuid) DO UPDATE SET qty=excluded.qty""",
                (_id("place", ext), ts, box or "—", pid, qty, ext, "адрес", i))
            if box:
                con.execute("INSERT INTO locations(id, code) VALUES (?,?) ON CONFLICT(code) DO NOTHING",
                            (_id("loc", box), box))
            stats["placements"] += 1

        # ---------- отгрузки
        for sheet, target in (("паставка ЖСК", "ЖСК"), ("паставка ККМ", "ККМ"),
                              ("паставка ААТ", "ААТ"), ("паставка4", "4"),
                              ("паставка5", "5"), ("паставка6", "6")):
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            seen = Counter()
            for i, row in enumerate(list(ws.iter_rows(values_only=True))[1:], start=2):
                if not row or len(row) < 7 or not row[5]:
                    continue
                name = _clean(row[5])
                qty = _num(row[6])
                if not name or qty <= 0:
                    continue
                pid = _product_id(con, name)
                ts = _clean(row[4]) or _clean(row[0]) or started[:10]
                seen[(ts, name, qty)] += 1
                ext = f"{sheet}:{ts}:{name}:{qty}:{seen[(ts, name, qty)]}"
                con.execute(
                    """INSERT INTO shipments(id, ts, target, product_id, qty, order_ref, user,
                            external_uuid, source_sheet, source_row)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(external_uuid) DO UPDATE SET qty=excluded.qty""",
                    (_id("ship", ext), ts, target, pid, qty, _clean(row[3]) if len(row) > 3 else "",
                     _clean(row[4]) if len(row) > 4 else "", ext, sheet, i))
                stats["shipments"] += 1

        # ---------- магазин (списания витрины)
        if "магазин" in wb.sheetnames:
            ws = wb["магазин"]
            seen = Counter()
            for i, row in enumerate(list(ws.iter_rows(values_only=True))[1:], start=2):
                if not row or len(row) < 4 or not row[2]:
                    continue
                name = _clean(row[2])
                qty = _num(row[3])
                if not name or qty <= 0:
                    continue
                pid = _product_id(con, name)
                seen[(name, qty)] += 1
                ext = f"магазин:{name}:{qty}:{seen[(name, qty)]}"
                con.execute(
                    """INSERT INTO shipments(id, ts, target, product_id, qty, external_uuid,
                            source_sheet, source_row)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(external_uuid) DO UPDATE SET qty=excluded.qty""",
                    (_id("mship", ext), started[:10], "магазин", pid, qty, ext, "магазин", i))
                stats["shop_writes"] += 1

        # ---------- заказы клиентов (лист приложения)
        if "заказы" in wb.sheetnames:
            ws = wb["заказы"]
            for i, row in enumerate(list(ws.iter_rows(values_only=True))[1:], start=2):
                if not row or not row[0]:
                    continue
                oid = _clean(row[0])
                client = _clean(row[2]) or "—"
                status = _clean(row[3]) or "новый"
                ext = f"orders:{oid}"
                con.execute(
                    """INSERT INTO orders(id, ts, client, status, closed_at, cancelled_by, reason,
                            external_uuid, source_sheet, source_row)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(external_uuid) DO UPDATE SET
                         status=excluded.status, cancelled_by=excluded.cancelled_by, reason=excluded.reason""",
                    (_id("order", ext), _clean(row[1]) or started, client, status,
                     _clean(row[9]), _clean(row[7]), _clean(row[8]), ext, "заказы", i))
                name = _clean(row[4])
                qty = _num(row[5])
                if name and qty > 0:
                    pid = _product_id(con, name)
                    item_id = _id("order_item", ext, name)
                    con.execute(
                        """INSERT INTO order_items(id, order_id, product_id, qty, shipped)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(id) DO UPDATE SET qty=excluded.qty, shipped=excluded.shipped""",
                        (item_id, _id("order", ext), pid, qty, _num(row[6])))
                stats["orders"] += 1

        # ---------- сотрудники
        if "сотрудники" in wb.sheetnames:
            ws = wb["сотрудники"]
            for row in list(ws.iter_rows(values_only=True))[1:]:
                if not row or not row[0]:
                    continue
                login = _clean(row[0])
                con.execute(
                    """INSERT INTO employees(login, name, role, workshop, rate_hour, active, password_state)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(login) DO UPDATE SET
                         name=excluded.name, role=excluded.role, workshop=excluded.workshop,
                         rate_hour=excluded.rate_hour, active=excluded.active,
                         password_state=excluded.password_state""",
                    (login, _clean(row[2]), _clean(row[3]), _clean(row[5]), _num(row[6]),
                     1 if _clean(row[7]) == "да" else 0,
                     "default" if _clean(row[1]) == "123456" else "changed"))
                stats["employees"] += 1

        # ---------- расценки
        if "расценки" in wb.sheetnames:
            ws = wb["расценки"]
            for row in list(ws.iter_rows(values_only=True))[1:]:
                if not row or not row[0]:
                    continue
                con.execute(
                    """INSERT INTO rates(code, name, price, sort_order, required)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(code) DO UPDATE SET name=excluded.name, price=excluded.price,
                         sort_order=excluded.sort_order, required=excluded.required""",
                    (_clean(row[0]), _clean(row[1]), _num(row[2]), int(_num(row[3])),
                     1 if _clean(row[4]) == "да" else 0))
                stats["rates"] += 1
    finally:
        wb.close()

    # ---------- продажи магазина из data/sales.xlsx
    sales_path = DATA / "sales.xlsx"
    if sales_path.exists():
        ws = load_workbook(sales_path, data_only=True, read_only=True)
        try:
            sheet = ws[ws.sheetnames[0]]
            head = [str(c.value or "").strip() for c in next(sheet.iter_rows(min_row=1, max_row=1))]
            idx = {h: n for n, h in enumerate(head)}
            for row in list(sheet.iter_rows(values_only=True))[1:]:
                if not row or not row[idx.get("id", 0)]:
                    continue
                name = _clean(row[idx.get("наименование", 3)])
                pid = _product_id(con, name) if name else None
                ext = f"sales:{row[idx['id']]}"
                con.execute(
                    """INSERT INTO sales(id, ts, product_id, qty, price, total, buyer, user, status, external_uuid)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(external_uuid) DO UPDATE SET status=excluded.status""",
                    (_id("sale", ext), _clean(row[idx.get("дата", 1)]), pid,
                     _num(row[idx.get("количество", 4)]), _num(row[idx.get("цена", 5)]),
                     _num(row[idx.get("сумма", 6)]), _clean(row[idx.get("покупатель", 7)]),
                     _clean(row[idx.get("кто", 8)]),
                     "cancelled" if _clean(row[idx.get("отменена", 9)]) in ("1", "True", "true") else "ok",
                     ext))
                stats["sales"] += 1
        finally:
            ws.close()

    con.execute("INSERT INTO imports(ts, file_name, file_sha256, user, mode, summary_json, status) "
                "VALUES (?,?,?,?,?,?,?)",
                (started, path.name, _file_sha(path), actor, "full",
                 json.dumps(dict(stats), ensure_ascii=False), "ok"))
    sqldb.audit(con, actor, "import", "workbook", path.name, dict(stats))
    return dict(stats)


def integrity_report(con: sqlite3.Connection) -> dict:
    counts = {}
    for table in ("products", "locations", "purchases", "placements", "shipments",
                  "orders", "order_items", "employees", "rates", "sales"):
        counts[table] = con.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
    return counts
