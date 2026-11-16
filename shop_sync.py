#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Синхронизация каталога магазина с листом «главный» книги цеха (книга хранится в базе).

Правила:
  • книга только ЧИТАЕТСЯ, никогда не сохраняется;
  • количество берётся строго из колонки «ф.к» листа «главный» (фактическое количество);
  • лист «каробки» используется только для сверки и отчёта о расхождениях;
  • цены и фото, заданные в портале, при пересинхронизации сохраняются;
  • если книга в базе изменилась, данные пересобираются автоматически.

Использование:
    from shop_sync import sync_if_changed, sync_from_excel, status
    sync_if_changed()          # дешёвая проверка версии книги + синк при изменении
    sync_from_excel(force=True)
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
STATUS_FILE = DATA / "shop_status.json"

DEFAULT_PRICE = {
    "Брюки": 1800, "Худи": 1600, "Толстовка": 1600, "Лонгслив": 950,
    "Футболка": 750, "Футболка ХБ": 800, "Постель": 2600,
}
ICONS = {
    "Брюки": "pants", "Худи": "hoodie", "Толстовка": "hoodie",
    "Лонгслив": "longsleeve", "Футболка": "tshirt", "Футболка ХБ": "tshirt",
    "Постель": "bedding",
}

_LOCK = threading.Lock()


# ------------------------------------------------------------------ helpers
def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def as_num(value, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except Exception:
        return default


def _category(name: str) -> str:
    cat = name.split("/")[0].strip()
    if cat.lower().startswith("футболка") and "хб" in cat.lower():
        return "Футболка ХБ"
    return cat


def _price_for(cat: str, old: dict, name: str):
    value = old.get(name)
    try:
        if value is not None and str(value).strip() != "" and float(value) > 0:
            return float(value)
    except (TypeError, ValueError):
        pass
    return DEFAULT_PRICE.get(cat, 1000)


def status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_status(payload: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_FILE)


# ------------------------------------------------------------------- sync
def sync_from_excel(force: bool = False) -> dict:
    """Пересобирает таблицу products из листа «главный» книги цеха (в базе). Книга не изменяется."""
    import sheets
    from server import read_table, write_table  # импорт здесь, чтобы не было цикла

    with _LOCK:
        sig = sheets.version("цех")
        prev = status()
        if not force and prev.get("signature") == sig and STATUS_FILE.exists():
            products = read_table("products")
            if products:
                return prev

        wb = sheets.View("цех")
        rows = list(wb["главный"].iter_rows(values_only=True))

        # сверка с листом «каробки» (только для отчёта)
        boxes: dict[str, float] = defaultdict(float)
        if "каробки" in wb.sheetnames:
            for r in list(wb["каробки"].iter_rows(values_only=True))[1:]:
                if r and len(r) > 6 and r[5] and isinstance(r[6], (int, float)):
                    boxes[_clean(r[5])] += float(r[6])

        old = {(_clean(p.get("наименование"))): p for p in read_table("products")}

        sold: dict[str, float] = defaultdict(float)
        for sale in read_table("sales"):
            if str(sale.get("отменена", "0")) in ("1", "True", "true"):
                continue
            sold[_clean(sale.get("наименование"))] += float(as_num(sale.get("количество")))

        # приходы/поставки/корректировки, оформленные в портале
        adjust: dict[str, float] = defaultdict(float)
        for op in read_table("operations"):
            if str(op.get("отменена", "0")) in ("1", "True", "true"):
                continue
            name = _clean(op.get("наименование"))
            qty = float(as_num(op.get("количество")))
            kind = str(op.get("тип"))
            if kind == "приход":
                adjust[name] += qty
            elif kind == "поставка":
                adjust[name] -= qty
            elif kind == "корректировка":
                adjust[name] += qty

        # берём фактические остатки склада (адрес − отгрузки), чтобы магазин и склад совпадали
        wh_stock = {}
        try:
            import warehouse
            wh_stock = {i["наименование"]: i["остаток"] for i in warehouse.stock_items()}
        except Exception:
            wh_stock = {}

        catalog: dict[str, dict] = {}
        fk_sum = 0.0
        mismatch = 0
        for row in rows[4:]:
            if not row or not row[11]:
                continue
            name = _clean(row[11])
            if not name:
                continue
            parts = [p.strip() for p in name.split("/")]
            cat = _category(name)
            cached = float(row[17]) if isinstance(row[17], (int, float)) else 0.0
            qty = wh_stock.get(name, cached)
            fk_sum += qty
            old_item = old.get(name, {})
            price = _price_for(cat, {name: old_item.get("цена")}, name)
            if abs(qty - boxes.get(name, 0.0)) > 1e-9:
                mismatch += 1
            catalog[name] = {
                "категория": cat,
                "модель": (parts[1] if len(parts) > 1 else "") or _clean(row[12]),
                "цвет": parts[2] if len(parts) > 2 else "",
                "размер": (parts[3] if len(parts) > 3 else "") or _clean(row[14]),
                "код": _clean(row[4]),
                "количество": qty,
                "цена": price,
                "фото": _clean(old_item.get("фото")),
                "название": _clean(old_item.get("название")),
                "описание": _clean(old_item.get("описание")),
                "иконка": ICONS.get(cat, "tshirt"),
            }

        products = []
        for idx, (name, item) in enumerate(sorted(catalog.items()), start=1):
            fk = item["количество"]
            products.append({
                "id": idx,
                "артикул": item["код"] or item["модель"],
                "категория": item["категория"],
                "модель": item["модель"],
                "цвет": item["цвет"],
                "размер": item["размер"],
                "количество": max(0.0, fk - sold.get(name, 0.0) + adjust.get(name, 0.0)),
                "фк": fk,
                "цена": item["цена"],
                "наименование": name,
                "иконка": item["иконка"],
                "фото": item["фото"],
                "название": item["название"],
                "описание": item["описание"],
            })

        write_table("products", products)

        payload = {
            "source": "база данных",
            "source_name": "база данных",
            "signature": sig,
            "synced_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "позиций": len(products),
            "в_наличии": len([p for p in products if p["количество"] > 0]),
            "шт": round(sum(p["количество"] for p in products), 2),
            "fk_сумма": round(fk_sum, 2),
            "каробки_сумма": round(sum(boxes.values()), 2),
            "расхождений": mismatch,
            "error": "",
        }
        _write_status(payload)
        return payload


def sync_if_changed() -> dict:
    import sheets
    prev = status()
    if prev.get("signature") == sheets.version("цех") and prev.get("позиций"):
        return prev
    try:
        return sync_from_excel()
    except Exception as exc:  # noqa: BLE001
        payload = {**prev, "error": f"{type(exc).__name__}: {exc}",
                   "checked_at": datetime.now().strftime("%H:%M:%S")}
        _write_status(payload)
        return payload


def import_wb_photos_by_model(path: str | Path, aliases: dict | None = None) -> dict:
    """Фото из выгрузки WB, где артикул — модель, а цвет отдельно (ЖСК): первое фото — всем размерам
    той же модели и цвета. Только товарам без фото; уже заданные не трогаем.
    shortcut: храним ссылку на CDN WB, а не файл — если WB удалит фото, картинка пропадёт."""
    import warehouse  # noqa: WPS433
    from server import read_table, write_table  # noqa: WPS433

    photos = {}
    for r in warehouse.wb_rows(path):
        if r["фото"].startswith("http"):
            for k in warehouse.alias_keys(r["ключ"], aliases):  # цвет WB, названный в «главном» иначе
                photos.setdefault(k[:3], r["фото"])  # без размера: одно фото на модель и цвет
    with _LOCK:
        products = read_table("products")
        hit, cards = 0, set()
        for p in products:
            k = warehouse.name_key(_clean(p.get("наименование")))
            url = photos.get(k[:3]) if k else None
            if url and not _clean(p.get("фото")):
                p["фото"] = url
                hit += 1
                cards.add(url)
        if hit:
            write_table("products", products)
    return {"карточек_в_файле": len(photos), "товаров_с_фото": hit, "карточек_применено": len(cards)}


def import_wb_photos(path: str | Path, overwrite: bool = False) -> dict:
    """Фото из выгрузки WB «Общие характеристики» (лист «Товары»): B — артикул
    «Брюки/483/темно-синий/», H — ссылки через «;». Первое фото — всем размерам
    этого цвета. Фото, уже заданные в портале, не трогаем (overwrite=False).
    shortcut: храним ссылку на CDN WB, а не файл — если WB удалит фото, картинка пропадёт."""
    from server import read_table, write_table  # noqa: WPS433

    def key(v) -> str:
        return _clean(v).lower().replace("ё", "е").rstrip("/").strip()

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        photos = {}
        for r in wb["Товары"].iter_rows(min_row=5, values_only=True):
            if len(r) > 7 and r[1] and r[7]:
                first = str(r[7]).split(";")[0].strip()
                if first.startswith("http"):
                    photos.setdefault(key(r[1]), first)
    finally:
        wb.close()
    with _LOCK:
        products = read_table("products")
        hit = 0
        cards = set()
        for p in products:
            url = photos.get(key(_clean(p.get("наименование")).rsplit("/", 1)[0]))  # «Брюки/477/бежевый/42» → без размера
            if url and (overwrite or not _clean(p.get("фото"))):
                p["фото"] = url
                hit += 1
                cards.add(url)
        if hit:
            write_table("products", products)
    return {"карточек_в_файле": len(photos), "товаров_с_фото": hit, "карточек_применено": len(cards)}
