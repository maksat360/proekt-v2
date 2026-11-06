# -*- coding: utf-8 -*-
"""Синхронизация FBS: новые заказы из WB → SQLite, подтверждение в сборку."""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

_BASE = Path(__file__).resolve().parent
_SQL = _BASE / "sql"
if str(_SQL) not in sys.path:
    sys.path.insert(0, str(_SQL))

import cabinets_store
import db as sqldb
import wb_api

STATUS_NEW = "new"
STATUS_PROCESSING = "processing"
STATUS_PICKING = "picking"
STATUS_PICKED = "picked"
STATUS_SHIPPED = "shipped"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

LABELS = {
    STATUS_NEW: "Новый",
    STATUS_PROCESSING: "В обработке",
    STATUS_PICKING: "Собирается",
    STATUS_PICKED: "Собран",
    STATUS_SHIPPED: "Отправлен",
    STATUS_DONE: "Завершён",
    STATUS_CANCELLED: "Отменён",
}


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _history(con, order_id: str, from_status: str | None, to_status: str,
             actor: str, comment: str = "") -> None:
    con.execute(
        "INSERT INTO order_status_history(order_id, from_status, to_status, actor, at, comment) "
        "VALUES (?,?,?,?,?,?)",
        (order_id, from_status, to_status, actor, _now(), comment))


def _resolve_product(con, cabinet_id: str, article: str, skus: list[str],
                     size: str = "") -> str | None:
    """Артикул продавца + размер → наше наименование (по листу «главный», колонки B и C)."""
    article = (article or "").strip()
    try:
        import warehouse
        name = warehouse.resolve_by_article(article, size)
        if name:
            row = con.execute("SELECT id FROM products WHERE lower(name)=lower(?)", (name,)).fetchone()
            if row:
                return row["id"]
            # товара ещё нет в базе — создаём по найденному наименованию
            _product_id(con, name)
            row = con.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
            if row:
                return row["id"]
    except Exception:
        pass
    if article:
        row = con.execute("SELECT id FROM products WHERE lower(name) = lower(?)",
                          (article,)).fetchone()
        if row:
            return row["id"]
        row = con.execute("SELECT product_id FROM wb_sku_map WHERE cabinet_id = ? AND external_sku = ?",
                          (cabinet_id, article)).fetchone()
        if row and row["product_id"]:
            return row["product_id"]
    for sku in skus or []:
        row = con.execute("SELECT product_id FROM wb_sku_map WHERE cabinet_id = ? AND external_sku = ?",
                          (cabinet_id, str(sku))).fetchone()
        if row and row["product_id"]:
            return row["product_id"]
    return None


def _upsert_order(con, cabinet: dict, order: dict) -> str:
    """Один заказ WB (rid) может содержать несколько позиций (id).

    Заказ = строка в orders с external_id = rid; каждая позиция = order_items.
    """
    cabinet_id = cabinet["id"]
    # номер задания — то, что видно в кабинете WB; rid только как ссылка
    item_id = str(order.get("id") or "").strip()
    rid = str(order.get("rid") or "").strip()
    if not item_id:
        return "skipped"

    existing = con.execute(
        "SELECT id FROM orders WHERE type='fbs' AND cabinet_id=? AND external_id=?",
        (cabinet_id, item_id)).fetchone()

    # заказы, созданные ошибочно по rid, подхватываем по позиции
    if not existing:
        legacy = con.execute(
            """SELECT o.id FROM orders o JOIN order_items i ON i.order_id = o.id
               WHERE o.type='fbs' AND o.cabinet_id=? AND i.external_id=?""",
            (cabinet_id, item_id)).fetchone()
        if legacy:
            con.execute("UPDATE orders SET external_id=?, external_number=?, external_uid=? WHERE id=?",
                        (item_id, item_id, rid, legacy["id"]))
            existing = {"id": legacy["id"]}

    article = str(order.get("article") or "").strip()
    skus = [str(x) for x in (order.get("skus") or [])]
    title = article or (skus[0] if skus else "") or f"WB {item_id}"
    price = float(order.get("convertedPrice") or order.get("price") or 0) / 100.0
    created = str(order.get("createdAt") or "")[:19].replace("T", " ") or _now()
    product_id = _resolve_product(con, cabinet_id, article, skus,
                                  str(order.get("sizeCode") or order.get("techSize") or ""))

    if existing:
        order_id = existing["id"]
        con.execute("UPDATE orders SET updated_at=?, amount=COALESCE(amount,0)+? WHERE id=?",
                    (_now(), price, order_id))
        outcome = "updated"
    else:
        order_id = _id("fbs", cabinet_id, item_id)
        con.execute(
            """INSERT INTO orders(id, ts, client, status, type, cabinet_id, external_id,
                                  external_number, external_uid, customer_name, source,
                                  updated_at, amount)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, created, cabinet.get("name", cabinet_id), STATUS_NEW, "fbs",
             cabinet_id, item_id, item_id, rid, cabinet.get("name", cabinet_id),
             "wb-api", _now(), price))
        _history(con, order_id, None, STATUS_NEW, "wb-api", "импорт из WB")
        outcome = "created"

    has_item = con.execute(
        "SELECT 1 FROM order_items WHERE order_id=? AND external_id=?",
        (order_id, item_id)).fetchone()
    if not has_item:
        con.execute(
            """INSERT INTO order_items(id, order_id, product_id, qty, shipped,
                                       external_sku, title, size, color, price, external_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_id("item", order_id, item_id), order_id, product_id, 1, 0,
             article or (skus[0] if skus else ""), title,
             str(order.get("sizeCode") or ""), str(order.get("colorCode") or ""),
             price, item_id))
    return outcome


def _rematch(con, cabinet_id: str) -> int:
    """Повторно сопоставляет старые заказы по новым правилам (артикул + размер)."""
    fixed = 0
    rows = con.execute(
        """SELECT i.id, i.external_sku, i.title, i.product_id
           FROM order_items i JOIN orders o ON o.id = i.order_id
           WHERE o.type='fbs' AND o.cabinet_id=?""", (cabinet_id,)).fetchall()
    for r in rows:
        if r["product_id"]:
            continue
        pid = _resolve_product(con, cabinet_id, r["external_sku"] or r["title"] or "", [])
        if pid:
            con.execute("UPDATE order_items SET product_id=? WHERE id=?", (pid, r["id"]))
            fixed += 1
    return fixed


def _older_than(stamp, hours: int = 24) -> bool:
    from datetime import datetime, timedelta
    if not stamp:
        return False
    try:
        dt = datetime.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
    return datetime.utcnow() - dt > timedelta(hours=hours)


def _stats_map(token: str) -> dict[str, dict]:
    """srid (orderUid) → запись статистики: отмена и дата изменения."""
    from datetime import datetime, timedelta
    date_from = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    try:
        rows = wb_api.statistics_orders(token, date_from)
    except Exception:
        return {}
    return {str(r.get("srid")): r for r in rows if r.get("srid")}


def reconcile(con, cabinet_id: str, fresh_ids: set[str], token: str,
              actor: str = "wb-api", uid_of: dict[str, str] | None = None) -> dict:
    """Точная сверка: что в поставке, что ещё собирается, что отменено.

    supplyId у заказа = он в поставке (собран/отгружен).
    Нет ни в «Новых», ни в списке заказов = отменён.
    """
    try:
        known = wb_api.all_orders(token)
    except wb_api.WbError:
        known = {}
    stats = _stats_map(token)
    uid_map = uid_of or {}
    try:
        result_stats = wb_api.statistics_state(token)
    except Exception:
        result_stats = {}

    rows = con.execute(
        """SELECT id, external_id, external_uid, status FROM orders
           WHERE type='fbs' AND cabinet_id=? AND status IN ('new','processing','picking')""",
        (cabinet_id,)).fetchall()

    result = {"отправлено": 0, "собирается": 0, "отменено": 0, "статистика": result_stats}
    for r in rows:
        ext = str(r["external_id"])
        wb = known.get(ext)
        st = stats.get(str(r["external_uid"] or uid_map.get(ext) or "")) or {}
        if st.get("isCancel"):
            target = STATUS_CANCELLED
            note = f"отменён клиентом в WB ({st.get('cancelDate') or 'дата неизвестна'})"
        elif ext in fresh_ids:
            target, note = STATUS_NEW, ""
        elif wb is None:
            target, note = STATUS_CANCELLED, "отменён в WB (нет в списке заказов кабинета)"
        elif wb.get("supplyId"):
            target, note = STATUS_SHIPPED, f"в поставке WB {wb.get('supplyId')}"
        elif _older_than(wb.get("createdAt"), hours=24):
            # старый заказ без поставки и не в «Новых» — отменён клиентом
            target, note = STATUS_CANCELLED, "отменён в WB (нет поставки)"
        else:
            target, note = STATUS_PROCESSING, "собран в кабинете, поставка ещё не создана"

        if target == r["status"]:
            continue
        con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                    (target, _now(), r["id"]))
        _history(con, r["id"], r["status"], target, actor, note)
        if target == STATUS_SHIPPED:
            result["отправлено"] += 1
        elif target == STATUS_PROCESSING:
            result["собирается"] += 1
        elif target == STATUS_CANCELLED:
            result["отменено"] += 1
    return result


def sync(cabinet_id: str | None = None, actor: str = "wb-api") -> dict:
    """Опрашивает WB по всем активным кабинетам с токеном."""
    con = sqldb.connect()
    result = {"кабинеты": [], "создано": 0, "обновлено": 0, "ошибки": []}
    try:
        for cab in cabinets_store.cabinets():
            if not cab["active"]:
                continue
            if cabinet_id and cab["id"] != cabinet_id:
                continue
            token = cabinets_store.token(cab["id"])
            if not token:
                result["кабинеты"].append({"id": cab["id"], "пропущен": "нет токена"})
                continue
            try:
                orders = wb_api.new_orders(token)
            except wb_api.WbError as exc:
                cabinets_store.mark_sync(cab["id"], str(exc))
                result["ошибки"].append({"кабинет": cab["id"], "ошибка": str(exc)})
                continue

            _rematch(con, cab["id"])
            created = updated = 0
            fresh_ids = {str(o.get("id") or "").strip() for o in orders}
            con.execute("BEGIN IMMEDIATE")
            try:
                for order in orders:
                    outcome = _upsert_order(con, cab, order)
                    created += outcome == "created"
                    updated += outcome == "updated"
                rec = reconcile(con, cab["id"], fresh_ids, token, actor)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

            con.execute(
                "INSERT INTO wb_sync_log(ts, cabinet_id, action, found, created, updated, errors, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_now(), cab["id"], "pull", len(orders), created, updated, 0, ""))
            cabinets_store.mark_sync(cab["id"], "")
            result["создано"] += created
            result["обновлено"] += updated
            result["кабинеты"].append({"id": cab["id"], "найдено": len(orders),
                                       "новых": created, "обновлено": updated,
                                       "отправлено": rec["отправлено"],
                                       "собирается": rec["собирается"],
                                       "отменено": rec["отменено"]})
            for key in ("отправлено", "собирается", "отменено"):
                result[key] = result.get(key, 0) + rec[key]
        sqldb.audit(con, actor, "wb_sync", "orders", "", result)
    finally:
        con.close()
    return result


def _stock_sql(con, product_id: str | None) -> float:
    """Остаток товара по данным SQL: размещено минус отгружено."""
    if not product_id:
        return 0.0
    row = con.execute(
        """SELECT
             COALESCE((SELECT SUM(qty) FROM placements WHERE product_id = ?), 0) -
             COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id = ?), 0) AS stock""",
        (product_id, product_id)).fetchone()
    return float(row["stock"] or 0)


def pickable() -> list[dict]:
    """Заказы FBS, которые ждут сборки: с остатком на складе и без него."""
    con = sqldb.connect()
    try:
        rows = con.execute(
            """SELECT o.id, o.external_id, o.cabinet_id, o.status, o.ts,
                      i.id AS item_id, i.product_id, i.title, i.external_sku,
                      p.name AS product_name
               FROM orders o
               JOIN order_items i ON i.order_id = o.id
               LEFT JOIN products p ON p.id = i.product_id
               WHERE o.type='fbs' AND o.status IN ('new', 'picking')
               ORDER BY CASE o.status WHEN 'picking' THEN 0 ELSE 1 END, o.ts""").fetchall()
        out = []
        for r in rows:
            name = r["product_name"] or ""
            have = _stock_sql(con, r["product_id"])
            out.append({
                "id": r["id"],
                "external_id": r["external_id"],
                "cabinet_id": r["cabinet_id"],
                "status": r["status"],
                "status_label": LABELS.get(r["status"], r["status"]),
                "ts": r["ts"],
                "title": r["title"] or "",
                "sku": r["external_sku"] or "",
                "product_id": r["product_id"],
                "product_name": name,
                "stock": round(have, 2),
                "can_pick": bool(r["product_id"]) and have >= 1,
                "picked": r["status"] == "picking",
            })
        return out
    finally:
        con.close()


def _deduct(con, order_id: str, actor: str = "") -> int:
    """Списывает со склада собранные позиции заказа (один раз)."""
    items = con.execute(
        "SELECT id, external_id, product_id, shipped FROM order_items WHERE order_id=?",
        (order_id,)).fetchall()
    done = 0
    for it in items:
        if not it["product_id"]:
            continue
        ext = f"fbs:{it['external_id'] or it['id']}"
        exists = con.execute("SELECT 1 FROM shipments WHERE external_uuid=?", (ext,)).fetchone()
        if exists:
            continue
        con.execute(
            """INSERT INTO shipments(id, ts, target, product_id, qty, order_ref, user,
                    external_uuid, source_sheet)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (_id("sh", ext), _now(), "WB", it["product_id"], 1, order_id,
             actor or "склад", ext, "FBS"))
        con.execute("UPDATE order_items SET shipped=1 WHERE id=?", (it["id"],))
        done += 1
    return done


def pick(order_id: str, actor: str = "") -> dict:
    """Отмечает заказ собранным (сканирование). Проверяет остаток."""
    con = sqldb.connect()
    try:
        row = con.execute(
            """SELECT o.id, o.status, i.product_id, p.name AS product_name
               FROM orders o JOIN order_items i ON i.order_id = o.id
               LEFT JOIN products p ON p.id = i.product_id
               WHERE o.id = ? AND o.type='fbs'""", (order_id,)).fetchone()
        if not row:
            raise ValueError("заказ не найден")
        if row["status"] == "picking":
            return {"id": order_id, "статус": "уже собран"}
        if row["status"] != "new":
            raise ValueError(f"заказ в статусе «{LABELS.get(row['status'], row['status'])}»")
        warn = ""
        if not row["product_id"]:
            warn = "товар не сопоставлен с каталогом"
        elif _stock_sql(con, row["product_id"]) < 1:
            warn = f"нет в наличии: {row['product_name']} — отправим на сборку без остатка"
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                        (STATUS_PICKING, _now(), order_id))
            _history(con, order_id, STATUS_NEW, STATUS_PICKING, actor or "склад",
                     "собран сканером" + (" (нет в наличии)" if warn else ""))
            _deduct(con, order_id, actor)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return {"id": order_id, "статус": "собран", "предупреждение": warn}
    finally:
        con.close()


def confirm(order_ids: list[str], actor: str = "") -> dict:
    """Подтверждение сборки: отправляет заказы в WB и меняет статус на «В обработке»."""
    con = sqldb.connect()
    done, errors = 0, []
    try:
        for oid in order_ids:
            row = con.execute("SELECT * FROM orders WHERE id=? AND type='fbs'", (oid,)).fetchone()
            if not row:
                errors.append({"id": oid, "ошибка": "заказ не найден"})
                continue
            if row["status"] not in (STATUS_NEW, STATUS_PICKING):
                errors.append({"id": oid, "ошибка": f"статус «{LABELS.get(row['status'], row['status'])}»"})
                continue
            cab = row["cabinet_id"]
            token = cabinets_store.token(cab)
            if not token:
                errors.append({"id": oid, "ошибка": f"у кабинета {cab} нет токена"})
                continue
            items = [r["external_id"] for r in con.execute(
                "SELECT external_id FROM order_items WHERE order_id=? AND external_id IS NOT NULL",
                (oid,))]
            if not items:
                # старые заказы: id позиции не сохранён, используем номер заказа
                items = [row["external_id"]]
            try:
                wb_api.confirm_orders(token, [int(i) for i in items])
            except wb_api.WbError as exc:
                errors.append({"id": oid, "ошибка": str(exc)})
                continue
            item = con.execute(
                "SELECT product_id FROM order_items WHERE order_id=? LIMIT 1", (oid,)).fetchone()
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                            (STATUS_PROCESSING, _now(), oid))
                _history(con, oid, STATUS_PICKING, STATUS_PROCESSING, actor or "склад",
                         "подтверждено, отправлено в сборку WB")
                _deduct(con, oid, actor)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            done += 1
        sqldb.audit(con, actor, "wb_confirm", "orders", "", {"ok": done, "errors": errors})
    finally:
        con.close()
    return {"подтверждено": done, "ошибки": errors}


def list_orders(status: str | None = None, cabinet_id: str | None = None,
                limit: int = 200) -> list[dict]:
    con = sqldb.connect()
    try:
        sql = """SELECT o.*, (SELECT COUNT(*) FROM order_items i WHERE i.order_id = o.id) AS items
                 FROM orders o WHERE o.type='fbs'"""
        args = []
        if status:
            sql += " AND o.status = ?"
            args.append(status)
        if cabinet_id:
            sql += " AND o.cabinet_id = ?"
            args.append(cabinet_id)
        sql += " ORDER BY o.ts DESC LIMIT ?"
        args.append(limit)
        rows = []
        for r in con.execute(sql, args):
            d = dict(r)
            d["status_label"] = LABELS.get(d["status"], d["status"])
            d["items_detail"] = [dict(i) for i in con.execute(
                "SELECT title, external_sku, size, color, price, product_id "
                "FROM order_items WHERE order_id = ?", (d["id"],))]
            rows.append(d)
        return rows
    finally:
        con.close()


def aggregate_order() -> dict | None:
    """Все новые FBS-позиции как ОДИН заказ — для массовой сборки сканером."""
    con = sqldb.connect()
    try:
        rows = con.execute(
            """SELECT o.id AS order_id, o.external_id AS wb_order, o.cabinet_id, o.ts,
                      i.id AS item_id, i.external_id AS wb_item, i.title, i.external_sku,
                      i.product_id, p.name AS product_name
               FROM orders o JOIN order_items i ON i.order_id = o.id
               LEFT JOIN products p ON p.id = i.product_id
               WHERE o.type='fbs' AND o.status IN ('new','picking')
               ORDER BY o.ts""").fetchall()
        if not rows:
            return None
        positions = [{
            "наименование": r["product_name"] or (r["title"] or r["external_sku"] or "—"),
            "количество": 1,
            "отгружено": 0,
            "в_каталоге": bool(r["product_id"]),
            "order_id": r["order_id"],
            "item_id": r["wb_item"] or r["item_id"],
            "кабинет": r["cabinet_id"],
            "номер_wb": r["wb_order"],
        } for r in rows]
        return {
            "id": "fbs-all",
            "агрегат": True,
            "fbs": True,
            "дата": rows[0]["ts"],
            "клиент": "Wildberries · FBS",
            "статус": "новый",
            "позиции": positions,
        }
    finally:
        con.close()


def confirm_items(item_ids: list[str], actor: str = "") -> dict:
    """Подтверждает в WB конкретные позиции (после массовой сборки)."""
    con = sqldb.connect()
    ok, errors = 0, []
    try:
        groups: dict[tuple[str, str], list[int]] = {}
        rows = []
        for item in item_ids:
            r = con.execute(
                """SELECT o.id AS order_id, o.cabinet_id, o.status,
                          i.external_id AS wb_item
                   FROM orders o JOIN order_items i ON i.order_id = o.id
                   WHERE (i.external_id = ? OR i.id = ?) AND o.type='fbs'""",
                (item, item)).fetchone()
            if not r:
                errors.append({"позиция": item, "ошибка": "позиция не найдена"})
                continue
            if not r["wb_item"]:
                errors.append({"позиция": item, "ошибка": "нет номера позиции WB"})
                continue
            groups.setdefault((r["cabinet_id"], r["order_id"]), []).append(int(r["wb_item"]))
            rows.append(r)

        for (cabinet_id, order_id), ids in groups.items():
            token = cabinets_store.token(cabinet_id)
            if not token:
                errors.append({"заказ": order_id, "ошибка": f"у кабинета {cabinet_id} нет токена"})
                continue
            try:
                wb_api.confirm_orders(token, ids)
            except wb_api.WbError as exc:
                errors.append({"заказ": order_id, "ошибка": str(exc)})
                continue
            con.execute("BEGIN IMMEDIATE")
            try:
                _deduct(con, order_id, actor)
                con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                            (STATUS_PROCESSING, _now(), order_id))
                _history(con, order_id, None, STATUS_PROCESSING, actor or "склад",
                         f"массовая сборка: позиции {', '.join(str(i) for i in ids)}")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            ok += len(ids)
        sqldb.audit(con, actor, "wb_confirm_items", "orders", "", {"ok": ok, "errors": errors})
    finally:
        con.close()
    return {"подтверждено": ok, "ошибки": errors}


def as_client_orders() -> list[dict]:
    """FBS-заказы в формате обычных заказов: один заказ — все его позиции."""
    con = sqldb.connect()
    try:
        orders = con.execute(
            """SELECT id, ts, cabinet_id, external_id, status
               FROM orders WHERE type='fbs' AND status IN ('new','picking')
               ORDER BY ts DESC""").fetchall()
        out = []
        for o in orders:
            items = con.execute(
                """SELECT i.title, i.qty, i.product_id, p.name AS product_name
                   FROM order_items i LEFT JOIN products p ON p.id = i.product_id
                   WHERE i.order_id = ?""", (o["id"],)).fetchall()
            out.append({
                "id": o["id"],
                "дата": o["ts"],
                "клиент": f"{o['cabinet_id'].upper()} · WB",
                "статус": "новый" if o["status"] == "new" else "собирается",
                "fbs": True,
                "cabinet_id": o["cabinet_id"],
                "external_id": o["external_id"],
                "позиции": [{
                    "наименование": it["product_name"] or (it["title"] or ""),
                    "количество": it["qty"],
                    "отгружено": 0,
                    "в_каталоге": bool(it["product_id"]),
                } for it in items],
            })
        return out
    finally:
        con.close()


def counts() -> dict:
    con = sqldb.connect()
    try:
        rows = con.execute("SELECT status, COUNT(*) c FROM orders WHERE type='fbs' GROUP BY status")
        out = {r["status"]: r["c"] for r in rows}
        return {"всего": sum(out.values()), "по_статусам": out}
    finally:
        con.close()
