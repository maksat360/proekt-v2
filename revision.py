# -*- coding: utf-8 -*-
"""Ревизия склада: пересчитываем товар, сверяем с базой, проводим разницу.

Остаток = размещено − отгружено. Проведение ревизии пишет разницу так же, как обычные операции:
излишек — размещение в ячейку «ревизия», недостача — отгрузка получателю «РЕВИЗИЯ».
Правятся только пересчитанные позиции; не тронутые в ревизии остаются как были."""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "sql"))
import db as sqldb  # noqa: E402

PLACE = "ревизия"   # ячейка для излишков
TARGET = "РЕВИЗИЯ"  # получатель для недостачи

_STOCK_SQL = """COALESCE((SELECT SUM(qty) FROM placements WHERE product_id = p.id), 0) -
                COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id = p.id), 0)"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:20]


def _con():
    con = sqldb.connect()
    con.execute("""CREATE TABLE IF NOT EXISTS revisions (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, created_by TEXT, scope TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'открыта', closed_at TEXT, closed_by TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS revision_items (
        revision_id TEXT NOT NULL, product_id TEXT NOT NULL, counted REAL NOT NULL, system REAL,
        updated_at TEXT, updated_by TEXT, PRIMARY KEY (revision_id, product_id))""")
    return con


def _open(con) -> dict | None:
    return con.execute("SELECT * FROM revisions WHERE status='открыта' ORDER BY created_at DESC LIMIT 1").fetchone()


def _reset_stock_cache() -> None:
    try:
        import fbs_stock
        fbs_stock._FACT["ts"] = 0
    except Exception:  # noqa: BLE001
        pass


def start(scope: str, actor: str) -> dict:
    """scope — категория («Постель») или пусто — весь склад."""
    con = _con()
    try:
        if _open(con):
            raise ValueError("Уже идёт ревизия — проведите или отмените её")
        rid = _id("rev", _now(), actor)
        con.execute("INSERT INTO revisions(id, created_at, created_by, scope) VALUES (?,?,?,?)",
                    (rid, _now(), actor, scope.strip()))
        return {"id": rid}
    finally:
        con.close()


def count(rev_id: str, name: str, actor: str, qty: float | None = None, add: float = 0) -> dict:
    """Факт по товару: qty — задать число (None — убрать из ревизии), add — прибавить (скан)."""
    con = _con()
    try:
        rev = con.execute("SELECT status FROM revisions WHERE id=?", (rev_id,)).fetchone()
        if not rev or rev["status"] != "открыта":
            raise ValueError("Ревизия уже закрыта")
        p = con.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
        if not p:
            raise ValueError(f"Товар не найден: {name}")
        have = con.execute("SELECT counted FROM revision_items WHERE revision_id=? AND product_id=?",
                           (rev_id, p["id"])).fetchone()
        if qty is None and not add:
            con.execute("DELETE FROM revision_items WHERE revision_id=? AND product_id=?", (rev_id, p["id"]))
            return {"наименование": name, "факт": None}
        value = (have["counted"] if have else 0) + add if add else qty
        if value < 0:
            raise ValueError("Факт не может быть меньше нуля")
        if have:
            con.execute("UPDATE revision_items SET counted=?, updated_at=?, updated_by=? "
                        "WHERE revision_id=? AND product_id=?", (value, _now(), actor, rev_id, p["id"]))
        else:
            con.execute("INSERT INTO revision_items(revision_id, product_id, counted, updated_at, updated_by) "
                        "VALUES (?,?,?,?,?)", (rev_id, p["id"], value, _now(), actor))
        return {"наименование": name, "факт": value}
    finally:
        con.close()


def current() -> dict | None:
    """Открытая ревизия: товары её категории (и всё уже пересчитанное) с остатком по базе."""
    con = _con()
    try:
        rev = _open(con)
        if not rev:
            return None
        like = (rev["scope"] + "/%") if rev["scope"] else "%"
        rows = con.execute(f"""
            SELECT p.name AS name, {_STOCK_SQL} AS sys, ri.counted AS counted
            FROM products p
            LEFT JOIN revision_items ri ON ri.product_id = p.id AND ri.revision_id = ?
            WHERE p.name LIKE ? OR ri.counted IS NOT NULL
            ORDER BY p.name""", (rev["id"], like)).fetchall()
        items = []
        for r in rows:
            sys_q = float(r["sys"] or 0)
            c = None if r["counted"] is None else float(r["counted"])
            if c is None and sys_q == 0:
                continue  # нулевые непересчитанные не показываем — их можно найти сканом
            items.append({"наименование": r["name"], "система": sys_q, "факт": c,
                          "разница": None if c is None else c - sys_q})
        return {"id": rev["id"], "категория": rev["scope"], "начата": rev["created_at"],
                "кто": rev["created_by"], "товары": items}
    finally:
        con.close()


def apply(rev_id: str, actor: str) -> dict:
    """Провести: по каждой пересчитанной позиции довести остаток в базе до факта."""
    con = _con()
    try:
        rev = con.execute("SELECT status FROM revisions WHERE id=?", (rev_id,)).fetchone()
        if not rev or rev["status"] != "открыта":
            raise ValueError("Ревизия уже закрыта")
        rows = con.execute(f"""
            SELECT ri.product_id AS pid, ri.counted AS counted, {_STOCK_SQL} AS sys
            FROM revision_items ri JOIN products p ON p.id = ri.product_id
            WHERE ri.revision_id = ?""", (rev_id,)).fetchall()
        ts = _now()
        plus = minus = 0.0
        for r in rows:
            sys_q = float(r["sys"] or 0)
            diff = float(r["counted"]) - sys_q
            ext = f"rev:{rev_id}:{r['pid']}"
            if diff > 0:
                con.execute("""INSERT INTO placements(id, ts, location_code, product_id, qty, external_uuid, source_sheet)
                               VALUES (?,?,?,?,?,?,?)""", (_id(ext), ts, PLACE, r["pid"], diff, ext, "ревизия"))
                plus += diff
            elif diff < 0:
                con.execute("""INSERT INTO shipments(id, ts, target, product_id, qty, order_ref, user,
                                   external_uuid, source_sheet)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (_id(ext), ts, TARGET, r["pid"], -diff, rev_id, actor, ext, "ревизия"))
                minus += -diff
            con.execute("UPDATE revision_items SET system=? WHERE revision_id=? AND product_id=?",
                        (sys_q, rev_id, r["pid"]))
        con.execute("UPDATE revisions SET status='проведена', closed_at=?, closed_by=? WHERE id=?",
                    (ts, actor, rev_id))
        sqldb.audit(con, actor, "revision_apply", "revision", rev_id,
                    {"позиций": len(rows), "излишек": plus, "недостача": minus})
    finally:
        con.close()
    _reset_stock_cache()
    return {"позиций": len(rows), "излишек": plus, "недостача": minus}


def cancel(rev_id: str, actor: str) -> dict:
    con = _con()
    try:
        con.execute("UPDATE revisions SET status='отменена', closed_at=?, closed_by=? "
                    "WHERE id=? AND status='открыта'", (_now(), actor, rev_id))
        return {"id": rev_id}
    finally:
        con.close()


def history(limit: int = 20) -> list[dict]:
    con = _con()
    try:
        revs = con.execute("SELECT * FROM revisions WHERE status!='открыта' ORDER BY created_at DESC LIMIT ?",
                           (limit,)).fetchall()
        out = []
        for r in revs:
            items = con.execute("""SELECT p.name AS name, ri.counted AS counted, ri.system AS system
                                   FROM revision_items ri JOIN products p ON p.id = ri.product_id
                                   WHERE ri.revision_id=? ORDER BY p.name""", (r["id"],)).fetchall()
            diffs = [{"наименование": i["name"], "система": i["system"], "факт": i["counted"],
                      "разница": (i["counted"] - i["system"]) if i["system"] is not None else None}
                     for i in items]
            out.append({"id": r["id"], "категория": r["scope"], "статус": r["status"],
                        "начата": r["created_at"], "закрыта": r["closed_at"],
                        "кто": r["closed_by"] or r["created_by"],
                        "позиций": len(items),
                        "излишек": sum(d["разница"] for d in diffs if (d["разница"] or 0) > 0),
                        "недостача": -sum(d["разница"] for d in diffs if (d["разница"] or 0) < 0),
                        "расхождения": [d for d in diffs if d["разница"]]})
        return out
    finally:
        con.close()
