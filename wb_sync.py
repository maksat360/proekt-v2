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
    STATUS_PROCESSING: "На сборке",
    STATUS_PICKING: "Собирается",
    STATUS_PICKED: "Собран",
    STATUS_SHIPPED: "В доставке",
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


def _resolve_product(con, cabinet_id: str, skus: list[str]) -> str | None:
    """Только по баркоду: баркод → (артикул + размер) → наименование из «главного»."""
    import warehouse
    for sku in skus or []:
        name = warehouse.resolve_by_barcode(sku)
        if name:
            row = con.execute("SELECT id FROM products WHERE lower(name)=lower(?)", (name,)).fetchone()
            if not row:  # товара ещё нет в базе — создаём по найденному наименованию
                _product_id(con, name)
                row = con.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
            if row:
                return row["id"]
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
    barcode = skus[0] if skus else ""
    product_id = _resolve_product(con, cabinet_id, skus)

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
    if has_item:  # ещё не собран — пересопоставить: баркод могли добавить в справочник
        con.execute("""UPDATE order_items SET product_id=?, external_sku=? WHERE order_id=? AND external_id=?
                       AND shipped=0 AND (SELECT status FROM orders WHERE id=?) = 'new'""",
                    (product_id, barcode or article, order_id, item_id, order_id))
    else:
        con.execute(
            """INSERT INTO order_items(id, order_id, product_id, qty, shipped,
                                       external_sku, title, size, color, price, external_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_id("item", order_id, item_id), order_id, product_id, 1, 0,
             barcode or article, title,
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
        pid = _resolve_product(con, cabinet_id, [r["external_sku"] or ""])
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


# этапы как во вкладках кабинета WB: Новые → На сборке → В доставке → Завершённые / Отменённые
WB_CANCEL = {"canceled", "canceled_by_client", "declined_by_client", "defect"}
ACTIVE = (STATUS_NEW, STATUS_PROCESSING, STATUS_PICKING, STATUS_PICKED, STATUS_SHIPPED)


def wb_target(st: dict) -> str | None:
    """Статус WB (supplierStatus, wbStatus) → наш этап; None — неизвестно, не трогаем."""
    sup, wbs = st.get("supplierStatus"), st.get("wbStatus")
    if sup == "cancel" or wbs in WB_CANCEL:
        return STATUS_CANCELLED
    if sup == "complete":  # поставка закрыта: едет на склад WB — «В доставке», принят складом — дальше дело WB
        return STATUS_SHIPPED if wbs in (None, "", "waiting") else STATUS_DONE
    if sup == "confirm":
        return STATUS_PROCESSING
    if sup == "new":
        return STATUS_NEW
    return None


def reconcile(con, cabinet_id: str, fresh_ids: set[str], token: str,
              actor: str = "wb-api", cabinet: dict | None = None) -> dict:
    """Сверка с WB по статусу каждого задания + подтягиваем те, что уже «На сборке» / «В доставке»,
    но система не застала их в «Новых» (подтвердили в кабинете WB раньше синхронизации)."""
    result = {"отправлено": 0, "собирается": 0, "отменено": 0, "завершено": 0, "подтянуто": 0}
    rows = {str(r["external_id"]): r for r in con.execute(
        f"""SELECT id, external_id, status FROM orders WHERE type='fbs' AND cabinet_id=?
            AND status IN ({",".join("?" * len(ACTIVE))})""", (cabinet_id, *ACTIVE)).fetchall()}
    known = {}
    if cabinet:
        try:
            known = wb_api.all_orders(token)
        except wb_api.WbError:
            known = {}
        have = {str(r[0]) for r in con.execute(
            "SELECT external_id FROM orders WHERE type='fbs' AND cabinet_id=?", (cabinet_id,))}
        missing = [i for i in known if i not in have]
    else:
        missing = []
    try:
        statuses = wb_api.order_statuses(token, list(rows) + missing)
    except wb_api.WbError:
        return result  # нет связи со статусами — ничего не меняем, чтобы не испортить этапы

    for ext in missing:  # только живые: на сборке или в доставке, как во вкладках WB
        target = wb_target(statuses.get(ext) or {})
        if target not in (STATUS_PROCESSING, STATUS_SHIPPED):
            continue
        _upsert_order(con, cabinet, known[ext])
        oid = con.execute("SELECT id FROM orders WHERE type='fbs' AND cabinet_id=? AND external_id=?",
                          (cabinet_id, ext)).fetchone()["id"]
        con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (target, _now(), oid))
        _history(con, oid, STATUS_NEW, target, actor, "подтянут из WB: уже был в работе")
        result["подтянуто"] += 1

    for ext, r in rows.items():
        target = STATUS_NEW if ext in fresh_ids else wb_target(statuses.get(ext) or {})
        if not target or target == r["status"]:
            continue
        if r["status"] in (STATUS_PICKING, STATUS_PICKED) and target == STATUS_PROCESSING:
            continue  # склад уже собирает — для WB это тоже «на сборке», свой этап не сбиваем
        if target == STATUS_NEW and r["status"] != STATUS_NEW:
            continue  # собрали и подтвердили у себя, в WB он ещё «новый» — назад не откатываем
        st = statuses.get(ext) or {}
        con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (target, _now(), r["id"]))
        _history(con, r["id"], r["status"], target, actor,
                 f"WB: {st.get('supplierStatus') or ''}/{st.get('wbStatus') or ''}".strip("/"))
        key = {STATUS_SHIPPED: "отправлено", STATUS_PROCESSING: "собирается",
               STATUS_CANCELLED: "отменено", STATUS_DONE: "завершено"}.get(target)
        if key:
            result[key] += 1
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
                rec = reconcile(con, cab["id"], fresh_ids, token, actor, cab)
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
                                       "отменено": rec["отменено"], "завершено": rec["завершено"],
                                       "подтянуто": rec["подтянуто"]})
            for key in ("отправлено", "собирается", "отменено", "завершено", "подтянуто"):
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


def _free_sql(con, product_id: str | None) -> float:
    """Свободный остаток: на складе минус собранное, но ещё не подтверждённое (резерв)."""
    if not product_id:
        return 0.0
    row = con.execute(
        """SELECT COUNT(*) c FROM order_items i JOIN orders o ON o.id = i.order_id
           WHERE i.product_id = ? AND o.type='fbs' AND o.status='picking'
             AND COALESCE(i.shipped, 0) = 0""", (product_id,)).fetchone()
    return _stock_sql(con, product_id) - float(row["c"] or 0)


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
            # собранный заказ уже держит свою единицу в резерве — ему показываем полный остаток
            have = (_stock_sql if r["status"] == "picking" else _free_sql)(con, r["product_id"])
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


def _deduct(con, order_id: str, actor: str = "", subs: dict | None = None,
            only: set[str] | None = None) -> int:
    """Списывает со склада собранные позиции заказа (один раз).
    subs: {id позиции WB: product_id} — отправлен другой товар (замена), списываем его."""
    items = con.execute(
        "SELECT id, external_id, product_id, shipped FROM order_items WHERE order_id=?",
        (order_id,)).fetchall()
    done = 0
    for it in items:
        if only is not None and str(it["external_id"]) not in only:
            continue  # позицию не подтверждали — не списываем
        pid = (subs or {}).get(str(it["external_id"])) or it["product_id"]
        if not pid:
            continue
        ext = f"fbs:{it['external_id'] or it['id']}"
        exists = con.execute("SELECT 1 FROM shipments WHERE external_uuid=?", (ext,)).fetchone()
        if exists:
            continue
        con.execute(
            """INSERT INTO shipments(id, ts, target, product_id, qty, order_ref, user,
                    external_uuid, source_sheet)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (_id("sh", ext), _now(), "WB", pid, 1, order_id,
             actor or "склад", ext, "FBS"))
        con.execute("UPDATE order_items SET shipped=1 WHERE id=?", (it["id"],))
        done += 1
    return done


def pick(order_id: str, actor: str = "") -> dict:
    """Отмечает заказ собранным (сканирование): резерв без списания. Проверяет свободный остаток."""
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
        elif _free_sql(con, row["product_id"]) < 1:
            warn = f"нет в наличии: {row['product_name']} — отправим на сборку без остатка"
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                        (STATUS_PICKING, _now(), order_id))
            _history(con, order_id, STATUS_NEW, STATUS_PICKING, actor or "склад",
                     "собран сканером" + (" (нет в наличии)" if warn else ""))
            # списание со склада — только при подтверждении (confirm / confirm_items)
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
            # подтверждение — только на нашем складе: в WB ничего не отправляем
            item = con.execute(
                "SELECT product_id FROM order_items WHERE order_id=? LIMIT 1", (oid,)).fetchone()
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                            (STATUS_PROCESSING, _now(), oid))
                _history(con, oid, STATUS_PICKING, STATUS_PROCESSING, actor or "склад",
                         "сборка подтверждена на складе, товар списан")
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


def aggregate_order(cabinet_id: str | None = None) -> dict | None:
    """Новые FBS-позиции кабинета как ОДИН заказ — для массовой сборки сканером.
    Каждый кабинет собирается отдельно: у него своя поставка в WB."""
    con = sqldb.connect()
    try:
        where, args = ("AND o.cabinet_id = ?", [cabinet_id]) if cabinet_id else ("", [])
        rows = con.execute(
            f"""SELECT o.id AS order_id, o.external_id AS wb_order, o.cabinet_id, o.ts,
                      i.id AS item_id, i.external_id AS wb_item, i.title, i.external_sku,
                      i.product_id, p.name AS product_name
               FROM orders o JOIN order_items i ON i.order_id = o.id
               LEFT JOIN products p ON p.id = i.product_id
               WHERE o.type='fbs' AND o.status IN ('new','picking') {where}
               ORDER BY o.ts""", args).fetchall()
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
        name = next((c["name"] for c in cabinets_store.cabinets() if c["id"] == cabinet_id), cabinet_id)
        return {
            "id": f"fbs-{cabinet_id}" if cabinet_id else "fbs-all",
            "агрегат": True,
            "fbs": True,
            "кабинет": cabinet_id or "",
            "дата": rows[0]["ts"],
            "клиент": f"Wildberries · FBS · {name}" if cabinet_id else "Wildberries · FBS",
            "статус": "новый",
            "позиции": positions,
        }
    finally:
        con.close()


def aggregates() -> list[dict]:
    """По одной сборке на каждый кабинет, где есть новые позиции (в порядке списка кабинетов)."""
    return [a for a in (aggregate_order(c["id"]) for c in cabinets_store.cabinets()) if a]


def confirm_items(item_ids: list[str], actor: str = "", subs: dict | None = None) -> dict:
    """Подтверждает собранные позиции на нашем складе (в WB ничего не отправляется):
    заказ уходит из «новых», товар списывается со склада.
    subs: {id позиции: наименование} — вместо заказанного отправлен другой товар, списываем его."""
    con = sqldb.connect()
    ok, errors = 0, []
    try:
        sub_pid: dict[str, str] = {}
        for item, name in (subs or {}).items():
            row = con.execute("SELECT id FROM products WHERE name=?", (str(name),)).fetchone()
            if not row:
                errors.append({"позиция": item, "ошибка": f"замена «{name}» не найдена в каталоге"})
                continue
            sub_pid[str(item)] = row["id"]
        ext_subs: dict[str, tuple[str, str]] = {}
        groups: dict[tuple[str, str], list[int]] = {}
        rows = []
        for item in item_ids:
            r = con.execute(
                """SELECT o.id AS order_id, o.cabinet_id, o.status,
                          i.external_id AS wb_item
                   FROM orders o JOIN order_items i ON i.order_id = o.id
                   WHERE (i.external_id = ? OR i.id = ?) AND o.type='fbs'""",
                (item, item)).fetchone()
            if str(item) in (subs or {}) and str(item) not in sub_pid:
                continue  # замена не найдена — позицию не отправляем, ошибка уже записана
            if not r:
                errors.append({"позиция": item, "ошибка": "позиция не найдена"})
                continue
            if not r["wb_item"]:
                errors.append({"позиция": item, "ошибка": "нет номера позиции WB"})
                continue
            groups.setdefault((r["cabinet_id"], r["order_id"]), []).append(int(r["wb_item"]))
            if str(item) in sub_pid:  # замена по id позиции WB
                ext_subs[str(r["wb_item"])] = (sub_pid[str(item)], subs[item])
            rows.append(r)

        for (cabinet_id, order_id), ids in groups.items():
            # подтверждение — только на нашем складе: в WB ничего не отправляем
            con.execute("BEGIN IMMEDIATE")
            try:
                # ключи замен — id позиции WB (как в order_items.external_id)
                o_subs = {str(i): ext_subs[str(i)] for i in ids if str(i) in ext_subs}
                _deduct(con, order_id, actor, {k: v[0] for k, v in o_subs.items()},
                        only={str(i) for i in ids})
                con.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?",
                            (STATUS_PROCESSING, _now(), order_id))
                note = f"массовая сборка: позиции {', '.join(str(i) for i in ids)}"
                if o_subs:
                    note += f"; отправлена замена: {', '.join(v[1] for v in o_subs.values())}"
                _history(con, order_id, None, STATUS_PROCESSING, actor or "склад", note)
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


def counts(cabinet_id: str | None = None) -> dict:
    """Счётчики по статусам (всего или одного кабинета) и сколько заказов у каждого кабинета."""
    con = sqldb.connect()
    try:
        where, args = ("AND cabinet_id = ?", [cabinet_id]) if cabinet_id else ("", [])
        rows = con.execute(f"SELECT status, COUNT(*) c FROM orders WHERE type='fbs' {where} GROUP BY status", args)
        out = {r["status"]: r["c"] for r in rows}
        cabs = {r["cabinet_id"]: {"всего": r["c"], "новых": r["n"]} for r in con.execute(
            "SELECT cabinet_id, COUNT(*) c, SUM(CASE WHEN status='new' THEN 1 ELSE 0 END) n FROM orders WHERE type='fbs' GROUP BY cabinet_id")}
        return {"всего": sum(out.values()), "по_статусам": out, "по_кабинетам": cabs}
    finally:
        con.close()


def _supply_rows(con) -> list:
    """Подтверждённые FBS-списания (одна строка — одна отправленная единица)."""
    return con.execute(
        """SELECT s.ts, s.qty, s.user, s.external_uuid, s.product_id, p.name AS sent_name,
                  o.id AS order_id, o.cabinet_id, o.external_id AS order_ext
           FROM shipments s JOIN orders o ON o.id = s.order_ref
           LEFT JOIN products p ON p.id = s.product_id
           WHERE s.source_sheet = 'FBS' ORDER BY s.ts""").fetchall()


def supplies() -> list[dict]:
    """Поставки FBS: по дню подтверждения и кабинету, новые сверху."""
    con = sqldb.connect()
    try:
        out: dict[tuple[str, str], dict] = {}
        for r in _supply_rows(con):
            key = (str(r["ts"])[:10], r["cabinet_id"])
            g = out.setdefault(key, {"дата": key[0], "кабинет": key[1], "штук": 0})
            g["штук"] += float(r["qty"] or 0)
        return sorted(out.values(), key=lambda g: (g["дата"], g["кабинет"]), reverse=True)
    finally:
        con.close()


def supply_lines(day: str, cabinet_id: str = "", names: dict | None = None) -> list[dict]:
    """Строки поставки: что отправили (с заменой) и что заказывал WB — для сверки."""
    names = names or {}
    con = sqldb.connect()
    try:
        rows = [r for r in _supply_rows(con)
                if str(r["ts"])[:10] == day and (not cabinet_id or r["cabinet_id"] == cabinet_id)]
        items = {}
        for oid in {r["order_id"] for r in rows}:
            for it in con.execute(
                    """SELECT i.external_id, i.title, p.name AS ordered_name
                       FROM order_items i LEFT JOIN products p ON p.id = i.product_id
                       WHERE i.order_id = ?""", (oid,)).fetchall():
                items[f"fbs:{it['external_id']}"] = it
    finally:
        con.close()
    out = []
    for r in rows:
        it = items.get(r["external_uuid"])
        out.append({
            "кабинет": names.get(r["cabinet_id"], r["cabinet_id"]),
            "заказ": str(r["order_ext"] or ""),
            "задание": str(r["external_uuid"]).removeprefix("fbs:"),
            "отправлено": r["sent_name"] or r["product_id"],
            "заказано": (it["ordered_name"] or it["title"] or "") if it else "",
            "кол-во": float(r["qty"] or 0),
            "время": str(r["ts"]),
            "кто": r["user"] or "",
        })
    return out


def product_names() -> list[str]:
    con = sqldb.connect()
    try:
        return [r[0] for r in con.execute("SELECT name FROM products ORDER BY name").fetchall()]
    finally:
        con.close()


def change_sent(changes: dict, actor: str = "") -> dict:
    """Исправление поставки: {задание: наименование} — что на самом деле отправили.
    Меняет товар списания, остатки пересчитываются сами (остаток = размещено − отгружено)."""
    con = sqldb.connect()
    done, errors = 0, []
    try:
        by_name = {}
        for r in con.execute("SELECT id, name FROM products").fetchall():
            by_name.setdefault(str(r["name"]).strip().casefold(), r["id"])
        con.execute("BEGIN IMMEDIATE")
        try:
            for task, name in changes.items():
                task, name = str(task).strip(), str(name or "").strip()
                pid = by_name.get(name.casefold())
                if not pid:
                    errors.append({"задание": task, "ошибка": f"«{name}» нет в каталоге"})
                    continue
                sh = con.execute(
                    """SELECT s.id, s.product_id, s.order_ref, p.name, o.status FROM shipments s
                       JOIN orders o ON o.id = s.order_ref
                       LEFT JOIN products p ON p.id = s.product_id
                       WHERE s.external_uuid = ? AND s.source_sheet = 'FBS'""",
                    (f"fbs:{task}",)).fetchone()
                if not sh:
                    errors.append({"задание": task, "ошибка": "в поставках нет такого задания"})
                    continue
                if sh["product_id"] == pid:
                    continue
                con.execute("UPDATE shipments SET product_id=? WHERE id=?", (pid, sh["id"]))
                _history(con, sh["order_ref"], None, sh["status"], actor or "склад",
                         f"исправлено в поставке: отправлено «{name}» вместо «{sh['name'] or sh['product_id']}»")
                done += 1
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        sqldb.audit(con, actor, "fbs_supply_edit", "shipments", "", {"ok": done, "errors": errors})
    finally:
        con.close()
    return {"изменено": done, "ошибки": errors}


def supply_import_xlsx(data: bytes, actor: str = "") -> dict:
    """Загрузка исправленного Excel поставки: берём колонки «Задание» и «Отправлено»."""
    import io
    from openpyxl import load_workbook
    try:
        ws = load_workbook(io.BytesIO(data), data_only=True)["Поставка"]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"это не файл поставки: {exc}") from exc
    head = [str(c or "").strip() for c in next(ws.iter_rows(min_row=3, max_row=3, values_only=True))]
    if "Задание" not in head or "Отправлено" not in head:
        raise ValueError("в файле нет колонок «Задание» и «Отправлено»")
    ti, si = head.index("Задание"), head.index("Отправлено")
    changes = {}
    for row in ws.iter_rows(min_row=4, values_only=True):
        task, sent = row[ti], row[si]
        if task in (None, "") or not sent:
            continue
        changes[str(task).strip().removesuffix(".0")] = str(sent).strip()
    if not changes:
        raise ValueError("в файле нет строк поставки")
    return change_sent(changes, actor)


def supply_xlsx(day: str, cabinet_id: str = "", names: dict | None = None) -> bytes:
    """Excel одной поставки (день + кабинет; без кабинета — все кабинеты за день).
    Колонку «Отправлено» можно исправить и загрузить файл обратно."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    names = names or {}
    lines = supply_lines(day, cabinet_id, names)
    if not lines:
        raise ValueError("за этот день поставок нет")
    wb = Workbook()
    ws = wb.active
    ws.title = "Поставка"
    cab_title = names.get(cabinet_id, cabinet_id) if cabinet_id else "все кабинеты"
    ws.append([f"Поставка FBS за {day} · {cab_title}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Исправьте «Отправлено», если ушёл другой товар, и загрузите файл обратно на сайт"])
    # главное — что фактически отправили (с заменой), заказ WB — только для сверки
    ws.append(["Кабинет", "Заказ WB", "Задание", "Отправлено", "Кол-во",
               "Вместо заказанного", "Подтверждено", "Кто"])
    total, by_name = 0.0, {}
    for x in lines:
        sent, qty = x["отправлено"], x["кол-во"]
        total += qty
        by_name[sent] = by_name.get(sent, 0) + qty
        ordered = x["заказано"]
        ws.append([x["кабинет"], x["заказ"], x["задание"], sent, qty,
                   ordered if ordered and ordered != sent else "", x["время"], x["кто"]])
    ws.append(["Итого", "", "", "", total])
    for c in ws[3] + ws[ws.max_row]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDEFGH", (10, 14, 16, 30, 8, 30, 19, 14)):
        ws.column_dimensions[col].width = w
    sm = wb.create_sheet("По товарам")
    sm.append(["Отправлено", "Кол-во"])
    for n, q in sorted(by_name.items()):
        sm.append([n, q])
    sm.append(["Итого", total])
    sm.column_dimensions["A"].width = 32
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
