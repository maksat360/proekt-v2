# -*- coding: utf-8 -*-
"""Ревизия склада: сканируем товар и вписываем поправку (+1 — лишняя штука, −2 — не хватает двух).

Остаток = размещено − отгружено. Проведение ревизии пишет разницу так же, как обычные операции:
излишек — размещение в ячейку «ревизия», недостача — отгрузка получателю «РЕВИЗИЯ».
Правятся только позиции с поправкой; остальные остаются как были.
Пока ревизия открыта, revision_items.counted хранит поправку; при проведении туда пишется итог
(остаток + поправка), а в system — остаток до ревизии, поэтому история читается как «было → стало»."""
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


def count(rev_id: str, name: str, actor: str, delta: float | None = None) -> dict:
    """Поправка по товару: +N — лишние, −N — не хватает; None или 0 — убрать из ревизии; без поправки — просто найти."""
    con = _con()
    try:
        rev = con.execute("SELECT status FROM revisions WHERE id=?", (rev_id,)).fetchone()
        if not rev or rev["status"] != "открыта":
            raise ValueError("Ревизия уже закрыта")
        p = con.execute(f"SELECT p.id AS id, {_STOCK_SQL} AS sys FROM products p WHERE p.name=?", (name,)).fetchone()
        if not p:
            raise ValueError(f"Товар не найден: {name}")
        sys_q = float(p["sys"] or 0)
        have = con.execute("SELECT counted FROM revision_items WHERE revision_id=? AND product_id=?",
                           (rev_id, p["id"])).fetchone()
        if delta is None and have is None:
            return {"наименование": name, "система": sys_q, "поправка": None}
        if not delta:
            con.execute("DELETE FROM revision_items WHERE revision_id=? AND product_id=?", (rev_id, p["id"]))
            return {"наименование": name, "система": sys_q, "поправка": None}
        if sys_q + delta < 0:
            raise ValueError(f"По базе всего {sys_q:g} шт — списать {-delta:g} нельзя")
        if have:
            con.execute("UPDATE revision_items SET counted=?, updated_at=?, updated_by=? "
                        "WHERE revision_id=? AND product_id=?", (delta, _now(), actor, rev_id, p["id"]))
        else:
            con.execute("INSERT INTO revision_items(revision_id, product_id, counted, updated_at, updated_by) "
                        "VALUES (?,?,?,?,?)", (rev_id, p["id"], delta, _now(), actor))
        return {"наименование": name, "система": sys_q, "поправка": delta}
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
            d = None if r["counted"] is None else float(r["counted"])
            if d is None and sys_q == 0:
                continue  # нулевые без поправки не показываем — их можно найти сканом
            items.append({"наименование": r["name"], "система": sys_q, "поправка": d,
                          "станет": None if d is None else sys_q + d})
        return {"id": rev["id"], "категория": rev["scope"], "начата": rev["created_at"],
                "кто": rev["created_by"], "товары": items}
    finally:
        con.close()


def apply(rev_id: str, actor: str) -> dict:
    """Провести: по каждой позиции с поправкой прибавить или списать её."""
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
        low = [r for r in rows if float(r["sys"] or 0) + float(r["counted"]) < 0]
        if low:  # остаток успел уменьшиться (отгрузка) — минуса не допускаем
            raise ValueError("Остаток изменился, поправка уведёт в минус — проверьте позиции и проведите снова")
        for r in rows:
            sys_q = float(r["sys"] or 0)
            diff = float(r["counted"])
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
            con.execute("UPDATE revision_items SET system=?, counted=? WHERE revision_id=? AND product_id=?",
                        (sys_q, sys_q + diff, rev_id, r["pid"]))
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


def undo(rev_id: str, actor: str) -> dict:
    """Откатить проведённую ревизию: убрать её излишки и недостачи, остаток — как до неё.
    Запись ревизии остаётся в истории со статусом «откатена»."""
    con = _con()
    try:
        rev = con.execute("SELECT status FROM revisions WHERE id=?", (rev_id,)).fetchone()
        if not rev or rev["status"] != "проведена":
            raise ValueError("Откатить можно только проведённую ревизию")
        like = f"rev:{rev_id}:%"
        back: dict[str, float] = {}  # товар → на сколько изменится остаток при откате
        for r in con.execute("SELECT product_id, qty FROM placements WHERE external_uuid LIKE ?", (like,)).fetchall():
            back[r["product_id"]] = back.get(r["product_id"], 0.0) - float(r["qty"])
        for r in con.execute("SELECT product_id, qty FROM shipments WHERE external_uuid LIKE ?", (like,)).fetchall():
            back[r["product_id"]] = back.get(r["product_id"], 0.0) + float(r["qty"])
        for pid, d in back.items():
            p = con.execute(f"SELECT p.name AS name, {_STOCK_SQL} AS sys FROM products p WHERE p.id=?", (pid,)).fetchone()
            if float(p["sys"] or 0) + d < 0:  # излишек уже отгрузили — откат увёл бы в минус
                raise ValueError(f"«{p['name']}»: излишек ревизии уже ушёл, остаток стал бы {float(p['sys'] or 0) + d:g}")
        con.execute("DELETE FROM placements WHERE external_uuid LIKE ?", (like,))
        con.execute("DELETE FROM shipments WHERE external_uuid LIKE ?", (like,))
        con.execute("UPDATE revisions SET status='откатена' WHERE id=?", (rev_id,))
        sqldb.audit(con, actor, "revision_undo", "revision", rev_id, {"позиций": len(back)})
    finally:
        con.close()
    _reset_stock_cache()
    return {"id": rev_id, "позиций": len(back)}


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
