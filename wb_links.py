# -*- coding: utf-8 -*-
"""Связи товаров: карточку WB, которую сайт не узнал, привязать к нашему товару (баркоды → «главный»),
отметить «не наше», и замены «нет своего — отправить похожий» (substitutes.json)."""
from __future__ import annotations

import json
from pathlib import Path

import cabinets_store
import substitutes
import warehouse
import wb_api
import wb_stocks

IGNORED = Path(__file__).resolve().parent / "data" / "wb_ignored.json"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _audit(actor: str, action: str, entity_id: str, payload: dict) -> None:
    import db as sqldb
    con = sqldb.connect()
    try:
        sqldb.audit(con, actor, action, "wb_links", entity_id, payload)
        getattr(con, "commit", lambda: None)()
    finally:
        con.close()


def prefixes() -> list[str]:
    """«Худи/263/шоколад» — категория/модель/цвет всех наших товаров, для выбора."""
    return sorted({"/".join(n.split("/")[:3]) for n in warehouse.product_names() if n.count("/") >= 3})


def _cards(cid: str) -> list[dict]:
    """Размеры карточек кабинета, сгруппированные по артикулу, с нашим наименованием (или None)."""
    token = cabinets_store.token(cid)
    sizes = wb_stocks._sizes(cid, cabinets_store.analytics_token(cid) or token)
    idx = warehouse.article_index()
    by: dict[str, list] = {}
    for z in {z["chrtId"]: z for z in sizes}.values():
        name = next((idx["barcodes"][b] for b in z["barcodes"] if b in idx["barcodes"]), None) \
            or idx["pairs"].get((warehouse._norm(z["article"]), warehouse._size(z["size"])))
        by.setdefault(z["article"], []).append({**z, "name": name})
    return [{"артикул": a, "размеры": v} for a, v in sorted(by.items())]


def unmatched(cid: str) -> dict:
    """Карточки кабинета, где хоть один размер не связан с нашим товаром."""
    token = cabinets_store.token(cid)
    ign = set(_read(IGNORED, {}).get(cid, []))
    cards = [c for c in _cards(cid) if any(not z["name"] for z in c["размеры"])]
    ids = [z["chrtId"] for c in cards for z in c["размеры"]]
    try:
        have = wb_stocks.warehouse_stocks(token, ids)[2] if ids else {}
    except wb_api.WbError:  # остатки только для подсказки: пустые склады — значит, везде 0
        have = {}
    out, hidden = [], []
    for c in cards:
        row = {"артикул": c["артикул"],
               "размеры": [{"размер": z["size"], "в_wb": have.get(z["chrtId"], 0), "связан": z["name"] or ""}
                           for z in sorted(c["размеры"], key=lambda z: z["size"])]}
        row["в_wb"] = sum(z["в_wb"] for z in row["размеры"])
        (hidden if c["артикул"] in ign else out).append(row)
    return {"карточки": out, "не_наше": hidden}


def link(cid: str, article: str, prefix: str, actor: str) -> dict:
    """Все размеры карточки → «prefix/размер»; баркоды дописываются в «главный». Названия не меняются."""
    prefix = str(prefix or "").strip().strip("/")
    card = next((c for c in _cards(cid) if c["артикул"] == article), None)
    if not card:
        raise ValueError(f"Карточка «{article}» не найдена в кабинете")
    ours = {warehouse._size(n.split("/")[3]): n for n in warehouse.product_names()
            if n.count("/") >= 3 and "/".join(n.split("/")[:3]) == prefix}
    if not ours:
        raise ValueError(f"У нас нет товара «{prefix}»")
    links, missing = {}, []
    for z in card["размеры"]:
        name = ours.get(warehouse._size(z["size"]))
        if name:
            links.setdefault(name, []).extend(z["barcodes"])
        else:
            missing.append(z["size"])
    if not links:
        raise ValueError(f"Ни один размер карточки не совпал с размерами «{prefix}»")
    done = warehouse.link_barcodes(links)
    _audit(actor, "wb_link", f"{cid}:{article}", {"товар": prefix, "размеры": done, "нет_размера": missing})
    return {"связано": len(done), "нет_размера": missing}


def ignore(cid: str, article: str, on: bool, actor: str) -> None:
    data = _read(IGNORED, {})
    arts = [a for a in data.get(cid, []) if a != article] + ([article] if on else [])
    data[cid] = arts
    _write(IGNORED, data)
    _audit(actor, "wb_link_ignore", f"{cid}:{article}", {"не_наше": bool(on)})


def set_sub(src: str, dst: str, actor: str) -> dict:
    """Замена src → dst (категория/модель/цвет); пустой dst — убрать замену."""
    src, dst = str(src or "").strip().strip("/"), str(dst or "").strip().strip("/")
    known = set(prefixes())
    rules = substitutes.load()
    if dst:
        if src not in known or dst not in known:
            raise ValueError("Выберите оба товара из списка")
        if src == dst:
            raise ValueError("Товар не может заменять сам себя")
        rules[src] = dst
    else:
        rules.pop(src, None)
    _write(substitutes.PATH, rules)
    _audit(actor, "wb_substitute", src, {"замена": dst})
    return rules
