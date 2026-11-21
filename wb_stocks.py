# -*- coding: utf-8 -*-
"""Остатки FBS в кабинетах WB = наш реальный остаток.

Раз в 10 минут: читаем остатки на складе продавца в каждом кабинете, сравниваем со свободным остатком
(как в магазине: склад − открытые заказы магазина − новые заказы FBS, ещё не списанные) и записываем
только те размеры, где цифры разошлись. Совпало — WB не трогаем.
Заказ уменьшает остаток сразу (WB сам вычитает его у себя, у нас он в резерве) — запись не нужна.
Один товар продаётся в нескольких кабинетах — в каждом виден весь наш остаток.
Пока выключено (файл data/wb_stocks.json, «вкл»: false) — только считает, что бы поменялось.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cabinets_store
import wb_api

BASE = Path(__file__).resolve().parent
STATE = BASE / "data" / "wb_stocks.json"
INTERVAL = 600
CARDS_TTL = 3600  # карточки меняются редко — перечитываем раз в час
_LOCK = threading.Lock()
_CARDS: dict[str, tuple[float, list]] = {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"вкл": False, "кабинеты": {}}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def set_on(on: bool) -> dict:
    with _LOCK:
        st = load()
        st["вкл"] = bool(on)
        _save(st)
        return st


def _name_of(size: dict, barcodes: dict, resolve) -> str | None:
    for b in size["barcodes"]:
        if b in barcodes:
            return barcodes[b]
    return resolve(size["article"], size["size"])


def plan(sizes: list[dict], have: dict[int, int], fact: dict[str, float], barcodes: dict, resolve) -> tuple[dict, list, int]:
    """→ ({chrtId: нужно}, [изменения для показа], сколько размеров без сопоставления).
    Товара нет у нас в базе — размер не трогаем (не обнуляем чужое)."""
    write, changes, unmapped, seen = {}, [], 0, set()
    for z in sizes:
        cid = z["chrtId"]
        if cid in seen:
            continue
        seen.add(cid)
        name = _name_of(z, barcodes, resolve)
        if not name or name not in fact:
            unmapped += 1
            continue
        want = max(0, int(fact[name]))
        was = int(have.get(cid, 0))
        if want != was:
            write[cid] = want
            changes.append({"товар": name, "в_wb": was, "у_нас": want})
    return write, changes, unmapped


def _sizes(cid: str, token: str) -> list:
    ts, data = _CARDS.get(cid, (0.0, []))
    if time.time() - ts > CARDS_TTL or not data:
        data = wb_api.card_sizes(token)
        _CARDS[cid] = (time.time(), data)
    return data


def warehouse_stocks(token: str, ids: list[int]) -> tuple:
    """→ (id склада, название, {chrtId: штук}). Складов несколько (у ЖСК пустой «Upsell») —
    берём тот, где остатки уже ведутся; все пустые — непонятно, куда писать."""
    whs = wb_api.warehouses(token)
    if not whs:
        raise wb_api.WbError("в кабинете нет склада продавца (FBS)")
    best = max(((w, wb_api.stocks(token, w["id"], ids)) for w in whs), key=lambda x: sum(x[1].values()))
    if len(whs) > 1 and not sum(best[1].values()):
        raise wb_api.WbError(f"складов FBS {len(whs)}, все пустые — непонятно, в какой писать")
    return best[0]["id"], str(best[0].get("name") or best[0]["id"]), best[1]


def sync_cabinet(cab: dict, fact: dict, barcodes: dict, resolve, on: bool) -> dict:
    token = cabinets_store.token(cab["id"])
    content = cabinets_store.analytics_token(cab["id"]) or token  # карточки читает ключ с «Контентом»
    res = {"имя": cab["name"], "когда": _now(), "размеров": 0, "расходится": 0, "записано": 0,
           "без_сопоставления": 0, "изменения": [], "ошибка": ""}
    try:
        sizes = _sizes(cab["id"], content)
        wid, res["склад"], have = warehouse_stocks(token, [z["chrtId"] for z in sizes])
        write, changes, unmapped = plan(sizes, have, fact, barcodes, resolve)
        res.update(размеров=len(sizes), расходится=len(write), без_сопоставления=unmapped, изменения=changes[:50])
        if on and write:
            wb_api.set_stocks(token, wid, write)
            res["записано"] = len(write)
    except Exception as exc:  # noqa: BLE001
        res["ошибка"] = str(exc)[:300]
    return res


def fbs_reserved() -> dict[str, float]:
    """Новые и собираемые заказы FBS, ещё не списанные со склада (списание — при подтверждении)."""
    import db as sqldb
    con = sqldb.connect()
    try:
        rows = con.execute(
            """SELECT p.name AS name, COUNT(*) AS c FROM order_items i
               JOIN orders o ON o.id = i.order_id JOIN products p ON p.id = i.product_id
               WHERE o.type='fbs' AND o.status IN ('new','picking') AND COALESCE(i.shipped, 0) = 0
               GROUP BY p.name""").fetchall()
        return {r["name"]: float(r["c"] or 0) for r in rows}
    finally:
        con.close()


def available() -> dict[str, float]:
    """Свободный остаток для WB: как в магазине, и ещё минус резерв FBS."""
    import warehouse
    import substitutes
    res = fbs_reserved()
    free = {n: max(0.0, q - res.get(n, 0.0)) for n, q in warehouse.available_for_order().items()}
    rules = substitutes.load()
    out = dict(free)
    for n, q in free.items():  # своего нет — показываем похожий (заказ уйдёт на него)
        sub = substitutes.for_name(n, rules) if q <= 0 else None
        if sub in free:
            out[n] = free[sub]
    return out


def pull_orders() -> dict[str, str]:
    """Сначала забрать новые заказы (как кнопка «Обновить из WB»), чтобы они ушли в резерв.
    → {кабинет: ошибка} — по этим кабинетам остатки не пишем."""
    import wb_sync
    try:
        res = wb_sync.sync(actor="wb-остатки")
    except Exception as exc:  # noqa: BLE001
        return {c["id"]: str(exc)[:120] for c in cabinets_store.cabinets()}
    return {e["кабинет"]: e["ошибка"][:120] for e in res.get("ошибки") or []}


def run() -> dict:
    """Один проход по всем активным кабинетам с токеном."""
    import fbs_stock
    import wb_report
    with _LOCK:
        st = load()
        failed = pull_orders()
        fact = available() if fbs_stock.fact_by_name() is not None else None
        if fact is None:
            st.update(когда=_now(), ошибка="нет остатков из базы — WB не трогаем")
            _save(st)
            return st
        barcodes, pairs, _, norm, sz = wb_report._catalog()
        resolve = lambda art, size: pairs.get((norm(art), sz(size)))  # noqa: E731
        st["ошибка"] = ""
        st["когда"] = _now()
        for cab in cabinets_store.cabinets():
            if cab["active"] and cab["token_set"]:
                # заказы кабинета не забрали — WB уже вычел их у себя, а у нас их нет в резерве: не пишем
                r = sync_cabinet(cab, fact, barcodes, resolve, bool(st.get("вкл")) and cab["id"] not in failed)
                if cab["id"] in failed:
                    r["ошибка"] = r["ошибка"] or f"заказы не обновились ({failed[cab['id']]}) — остатки не записаны"
                st.setdefault("кабинеты", {})[cab["id"]] = r
                if r["записано"]:
                    _audit(cab["id"], r)
        _save(st)
        return st


def _audit(cid: str, r: dict) -> None:
    try:
        import db as sqldb
        con = sqldb.connect()
        try:
            sqldb.audit(con, "система", "wb_stocks", "wb", cid, {"записано": r["записано"], "изменения": r["изменения"]})
            getattr(con, "commit", lambda: None)()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        print(f"wb_stocks: журнал: {exc}", file=sys.stderr, flush=True)


def loop() -> None:
    time.sleep(180)
    while True:
        try:
            run()
        except Exception as exc:  # noqa: BLE001
            print(f"wb_stocks: {exc}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL)
