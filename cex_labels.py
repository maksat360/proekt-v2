# -*- coding: utf-8 -*-
"""Цех: этикетки изделий (DataMatrix) по упаковке партий.

Вынесено из cex_api.py. Общие данные и функции цеха — через cex_api (C.…):
так подмены в тестах и вызовы из других разделов идут через один модуль.
Импортировать этот модуль напрямую не нужно: cex_api сам отдаёт его функции."""
from __future__ import annotations

import re
from datetime import datetime

import cex_api as C


# -------------------------------------------------- этикетки изделий (DataMatrix)
# На каждое изделие — этикетка 40×30: DataMatrix + наименование
# «Категория/Модель/Цвет/Размер» (как в листе «главный»). В DataMatrix зашито
# то же наименование в кодировке Windows-1251 — так же, как делает BarTender.
# Технолог генерирует после кроя: количество = раскроено по цвету и размеру.


def item_name(category: str, model: str, color: str, size: str) -> str:
    return f"{category}/{model}/{color}/{C._norm_size(size)}"


def datamatrix_svg(text: str) -> str:
    """SVG-разметка DataMatrix (только <path>), квадрат в модулях."""
    if text in C._DM_CACHE:
        return C._DM_CACHE[text]
    import zxingcpp
    try:
        data = text.encode("cp1251")
    except UnicodeEncodeError:
        data = text.encode("utf-8")
    svg = zxingcpp.create_barcode(data, zxingcpp.BarcodeFormat.DataMatrix,
                                  forceSquare=True).to_svg()  # квадрат, как в BarTender
    svg = svg[svg.index("<svg"):]
    m = re.search(r'width="(\d+)" height="(\d+)"', svg)
    if m and "viewBox" not in svg[:200]:  # без viewBox картинка не масштабируется под этикетку
        svg = svg.replace("<svg ", f'<svg viewBox="0 0 {m.group(1)} {m.group(2)}" ', 1)
    if len(C._DM_CACHE) > 2000:
        C._DM_CACHE.clear()
    C._DM_CACHE[text] = svg
    return svg


def _catalog_names() -> dict[tuple, str]:
    """(модель, цвет, размер) → категория из каталога «главный»."""
    out = {}
    for r in C._catalog_rows():
        out[(r["модель"], r["цвет"].lower(), r["размер"])] = r["категория"]
    return out


def _label_rows_for(p: dict) -> list[dict]:
    cats = C._catalog_names()
    rows = []
    for r in p["строки"]:
        qty = C._int(r.get("раскроено"))
        if qty <= 0:
            continue
        cat = cats.get((p["модель"], r["цвет"].lower(), r["размер"])) or p["категория"]
        rows.append({"категория": cat, "модель": p["модель"], "цвет": r["цвет"], "размер": r["размер"],
                     "наименование": C.item_name(cat, p["модель"], r["цвет"], r["размер"]),
                     "количество": qty})
    return rows


def labels_state(num: str) -> dict:
    party = next((p for p in C.cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    saved = [r for r in C._rows(C.ITEM_LABELS) if C._norm_size(r.get("№ партии")) == num]
    fresh = C._label_rows_for(party)
    now_map = {x["наименование"]: x["количество"] for x in fresh}
    old_map = {C._s(r.get("наименование")): C._int(r.get("количество")) for r in saved}
    return {
        "партия": num, "модель": party["модель"], "клиент": party["клиент"],
        "раскроено": party["раскроено"], "план": party["план"], "крой_идёт": party["остаток"] > 0,
        "сгенерировано": bool(saved),
        "дата": C._s(saved[0].get("дата")) if saved else "",
        "кто": C._s(saved[0].get("сгенерировал")) if saved else "",
        "устарели": bool(saved) and now_map != old_map,
        "строки": [{"наименование": C._s(r.get("наименование")), "цвет": C._s(r.get("цвет")),
                    "размер": C._norm_size(r.get("размер")), "количество": C._int(r.get("количество"))}
                   for r in saved],
        "всего": sum(old_map.values()),
    }


def generate_labels(me: dict, body: dict) -> dict:
    num = C._s(body.get("партия"))
    party = next((p for p in C.cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    fresh = C._label_rows_for(party)
    if not fresh:
        raise ValueError("Партия ещё не раскроена — этикетки генерируются по факту кроя")
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    who = C._s(me.get("фио")) or C._s(me.get("логин"))
    rows = [r for r in C._rows(C.ITEM_LABELS) if C._norm_size(r.get("№ партии")) != num]
    rows += [{"№ партии": num, "наименование": x["наименование"], "категория": x["категория"],
              "модель": x["модель"], "цвет": x["цвет"], "размер": x["размер"],
              "количество": x["количество"], "сгенерировал": who, "дата": now} for x in fresh]
    C.store.write_sheets([(C.ITEM_LABELS[0], C.ITEM_LABELS[1], rows)])
    return {"партия": num, "строк": len(fresh), "этикеток": sum(x["количество"] for x in fresh)}


def item_labels_print(num: str) -> dict:
    st = C.labels_state(num)
    if not st["сгенерировано"]:
        raise ValueError("Этикетки этой партии ещё не сгенерированы")
    size = "40x30"
    try:
        for r in C.store.read_sheet("настройки"):
            if C._s(r.get("параметр")) in ("этикетка изделия", "этикетка мм"):
                size = C._s(r.get("значение")) or size
    except Exception:
        pass
    w, _, h = size.lower().replace("×", "x").partition("x")
    for r in st["строки"]:
        r["svg"] = C.datamatrix_svg(r["наименование"])
    st["мм"] = {"ш": C._int(w, 40) or 40, "в": C._int(h, 30) or 30}
    return st


def labels_data(party: str = "", box: str = "") -> dict:
    packed = C._rows(C.PACK)
    party_rows = C._rows(C.PARTIES)
    meta = {}
    for r in party_rows:
        meta.setdefault(C._s(r.get("№ партии")), {
            "модель": C._s(r.get("модель")), "категория": C._s(r.get("категория")),
            "клиент": C._s(r.get("клиент")),
        })
    brand = C._brand()
    labels = []
    for r in packed:
        num = C._s(r.get("партия"))
        if party and num != party:
            continue
        if box and C._s(r.get("коробка")) != box:
            continue
        m = meta.get(num, {})
        labels.append({
            "партия": num, "коробка": C._s(r.get("коробка")), "цвет": C._s(r.get("цвет")),
            "размер": C._norm_size(r.get("размер")), "количество": C._int(r.get("количество")),
            "модель": m.get("модель", ""), "категория": m.get("категория", ""),
            "клиент": m.get("клиент", ""), "дата": C._s(r.get("дата")),
            "бренд": brand["название"], "подзаголовок": brand["подзаголовок"],
        })
    labels.reverse()
    return {"этикетки": labels, "бренд": brand}
