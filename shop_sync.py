#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Синхронизация каталога магазина с Excel-файлом цеха.

Правила:
  • файл-источник только ЧИТАЕТСЯ, никогда не сохраняется;
  • количество берётся строго из колонки «ф.к» листа «главный» (фактическое количество);
  • лист «каробки» используется только для сверки и отчёта о расхождениях;
  • цены и фото, заданные в портале, при пересинхронизации сохраняются;
  • если файл изменился (mtime/размер), данные пересобираются автоматически.

Использование:
    from shop_sync import sync_if_changed, sync_from_excel, status
    sync_if_changed()          # дешёвая проверка mtime + синк при изменении
    sync_from_excel(force=True)
"""
from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
SOURCE_FILE = DATA / "shop_source.txt"
STATUS_FILE = DATA / "shop_status.json"

DEFAULT_SOURCE = Path("/Users/temp/швейный цех приложение/цех_склад для apk.xlsm")

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
def source_path() -> Path:
    if SOURCE_FILE.exists():
        raw = SOURCE_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return Path(os.path.expanduser(raw))
    return DEFAULT_SOURCE


def set_source(path: str | Path) -> Path:
    p = Path(os.path.expanduser(str(path))).resolve()
    DATA.mkdir(parents=True, exist_ok=True)
    SOURCE_FILE.write_text(str(p), encoding="utf-8")
    return p


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


def _signature(path: Path) -> tuple:
    try:
        st = path.stat()
        return (int(st.st_mtime), int(st.st_size))
    except OSError:
        return (0, 0)


# ------------------------------------------------------------------- sync
def sync_from_excel(path: str | Path | None = None, force: bool = False) -> dict:
    """Пересобирает products.xlsx из Excel. Источник не изменяется."""
    from server import read_table, write_table  # импорт здесь, чтобы не было цикла

    src = Path(os.path.expanduser(str(path))) if path else source_path()
    with _LOCK:
        if not src.exists():
            payload = {**status(), "error": f"файл не найден: {src}",
                       "source": str(src), "synced_at": status().get("synced_at")}
            _write_status(payload)
            return payload

        sig = _signature(src)
        prev = status()
        if not force and prev.get("signature") == list(sig) and STATUS_FILE.exists():
            products = read_table("products")
            if products:
                return prev

        # читаем только для чтения: файл никогда не сохраняется
        wb = load_workbook(src, data_only=True)
        try:
            sheet = wb["главный"]
            rows = list(sheet.iter_rows(values_only=True))
        finally:
            wb.close()

        # сверка с листом «каробки» (только для отчёта)
        boxes: dict[str, float] = defaultdict(float)
        wb2 = load_workbook(src, data_only=True)
        try:
            if "каробки" in wb2.sheetnames:
                for r in list(wb2["каробки"].iter_rows(values_only=True))[1:]:
                    if r and r[5] and isinstance(r[6], (int, float)):
                        boxes[_clean(r[5])] += float(r[6])
        finally:
            wb2.close()

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
            })

        write_table("products", products)

        payload = {
            "source": str(src),
            "source_name": src.name,
            "signature": list(sig),
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
    src = source_path()
    sig = _signature(src)
    prev = status()
    if prev.get("signature") == list(sig) and prev.get("позиций"):
        return prev
    try:
        return sync_from_excel(src)
    except Exception as exc:  # noqa: BLE001 — файл занят Excel/OneDrive
        payload = {**prev, "error": f"{type(exc).__name__}: {exc}",
                   "checked_at": datetime.now().strftime("%H:%M:%S")}
        _write_status(payload)
        return payload
