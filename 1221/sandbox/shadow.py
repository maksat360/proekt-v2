# -*- coding: utf-8 -*-
"""Теневой режим: зеркалит операции склада в SQL, не влияя на ответ пользователю.

Включается config.json → {"shadow": true} или V2_SHADOW=1.
Любая ошибка тени логируется и НИКОГДА не ломает основную операцию.
"""
from __future__ import annotations

import hashlib
import traceback

import db as sqldb


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _product(con, name: str) -> str:
    row = con.execute("SELECT id FROM products WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    parts = [p.strip() for p in name.split("/")]
    pid = _id("product", name)
    con.execute(
        "INSERT INTO products(id, name, category, model, color, size, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (pid, name, parts[0] if parts else "", parts[1] if len(parts) > 1 else "",
         parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else "", sqldb.now()))
    return pid


def mirror(kind: str, payload: dict, actor: str = "") -> dict | None:
    """kind: приход | адрес | отгрузка | заказ | отмена_заказа."""
    if not sqldb.shadow_enabled():
        return None
    if kind not in ("приход", "адрес", "отгрузка", "заказ", "отмена_заказа"):
        return {"mirrored": False, "error": f"неизвестный тип операции: {kind}"}
    con = sqldb.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        uid = str(payload.get("uuid") or _id(kind, sqldb.now(), repr(payload)))
        if kind == "приход":
            for pos in payload.get("позиции", []):
                name = str(pos.get("наименование") or "")
                qty = float(pos.get("количество") or 0)
                if not name or qty <= 0:
                    continue
                pid = _product(con, name)
                ext = f"shadow:приход:{uid}:{name}"
                con.execute(
                    """INSERT INTO purchases(id, ts, supplier, batch, product_id, qty, defect,
                            source, external_uuid)
                       VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(external_uuid) DO NOTHING""",
                    (_id("p", ext), sqldb.now(), str(payload.get("поставщик") or ""),
                     str(payload.get("партия") or ""), pid, qty,
                     float(payload.get("неликвид") or 0), "shadow", ext))
        elif kind == "адрес":
            name = str(payload.get("наименование") or "")
            qty = float(payload.get("количество") or 0)
            if name and qty > 0:
                pid = _product(con, name)
                box = str(payload.get("коробка") or "—")
                con.execute("INSERT INTO locations(id, code) VALUES (?,?) ON CONFLICT(code) DO NOTHING",
                            (_id("loc", box), box))
                ext = f"shadow:адрес:{uid}"
                con.execute(
                    """INSERT INTO placements(id, ts, location_code, product_id, qty, external_uuid)
                       VALUES (?,?,?,?,?,?) ON CONFLICT(external_uuid) DO NOTHING""",
                    (_id("pl", ext), sqldb.now(), box, pid, qty, ext))
        elif kind == "отгрузка":
            name = str(payload.get("наименование") or "")
            qty = float(payload.get("количество") or 0)
            if name and qty > 0:
                pid = _product(con, name)
                ext = f"shadow:отгрузка:{uid}"
                con.execute(
                    """INSERT INTO shipments(id, ts, target, product_id, qty, order_ref, user, external_uuid)
                       VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(external_uuid) DO NOTHING""",
                    (_id("sh", ext), sqldb.now(), str(payload.get("получатель") or ""),
                     pid, qty, str(payload.get("заказ") or ""), actor, ext))
        con.execute("COMMIT")
        sqldb.audit(con, actor, f"shadow_{kind}", "operation", uid, payload, "ok")
        return {"mirrored": True}
    except Exception as exc:  # noqa: BLE001
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        try:
            sqldb.audit(con, actor, f"shadow_{kind}", "operation", "", payload,
                        f"shadow_error: {exc}")
        except Exception:
            traceback.print_exc()
        return {"mirrored": False, "error": str(exc)}
    finally:
        con.close()
