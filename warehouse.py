#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Склад — работа с файлом «цех_склад для apk.xlsm».

Структура файла (как есть, не меняем):
  «главный»            — каталог + фактический остаток (колонка R «ф.к»)
  «Вспомогательный лист» — A наименование, B модель, C цвет, D размер,
                           G категория, I поставщики, J полный адрес
  «приобритение»       — строка 7 шапка: A дата, B поставщик, C товар, D модель,
                           E цвет, F размер, G неликвид, H количество, I партия
  «адрес»              — D дата, E ID коробки, F товар, G количество, H проверка, I категория
  «паставка ЖСК/ККМ/ААТ» — отгрузки

Остаток = «ф.к» + приходы − отгрузки (по операциям портала).
Операции пишутся и в Excel (для истории), и в локальный реестр data/склад_реестр.json.
Перед каждой записью делается резервная копия файла.
"""
from __future__ import annotations

import json
import os
import re
import time
import shutil
import threading
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from cex_store import BOOK_LOCK, guard as cex_guard  # общий с цехом замок записи; проверка «открыт в Excel»
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
BACKUP = DATA / "склад_бэкапы"
LEDGER = DATA / "склад_реестр.json"
SOURCE_HINT = DATA / "склад_источник.txt"

DEFAULT_SOURCE = Path("/Users/temp/швейный цех приложение/цех_склад для apk.xlsm")

TARGETS = ["ЖСК", "ККМ", "ААТ"]
SHIP_SHEET = {"ЖСК": "паставка ЖСК", "ККМ": "паставка ККМ", "ААТ": "паставка ААТ"}

_LOCK = threading.RLock()
_CACHE = {"sig": None, "data": None}
_STOCK = {"key": None, "ts": 0.0, "items": [], "index": {}, "names": []}
_LEDGER_CACHE = {"mtime": None, "data": None}
_FLUSH = {"running": False, "last": ""}
_SMALL = {}  # лёгкие выборки из книги (сотрудники, настройки): ключ → (подпись файла, данные)


def _cached_by_file(key: str, build):
    """Пересчитывает build() только когда файл книги изменился."""
    try:
        sig = _signature(source_path())
    except OSError:
        sig = None
    hit = _SMALL.get(key)
    if sig is not None and hit and hit[0] == sig:
        return hit[1]
    data = build()
    if sig is not None:
        _SMALL[key] = (sig, data)
    return data


# ---------------------------------------------------------------- служебное
def source_path() -> Path:
    if SOURCE_HINT.exists():
        raw = SOURCE_HINT.read_text(encoding="utf-8").strip()
        if raw:
            return Path(raw).expanduser()
    return DEFAULT_SOURCE


def set_source(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if str(p).startswith(("/tmp", "/private/tmp")) and os.environ.get("V2_ALLOW_TMP") != "1":
        raise ValueError("временный путь нельзя использовать как источник склада")
    DATA.mkdir(parents=True, exist_ok=True)
    SOURCE_HINT.write_text(str(p), encoding="utf-8")
    _CACHE["sig"] = None
    _SMALL.clear()
    _STOCK["key"] = None
    return p


def _op_key() -> str:
    import uuid as _uuid
    return _uuid.uuid4().hex


def _shadow(kind: str, payload: dict, actor: str = "") -> None:
    """Теневая запись в SQL. Включается только при shadow=true; ошибки не влияют."""
    try:
        import sql_bridge
        sql_bridge.shadow(kind, payload, actor)
    except Exception:
        pass


def _safe(v, limit: int = 200) -> str:
    """Убирает управляющие символы — openpyxl не умеет их писать."""
    text = "" if v is None else str(v)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text.strip()[:limit]


_ART_CACHE = {"key": None, "data": None}


def _norm(v) -> str:
    return " ".join(str(v or "").lower().replace("ё", "е").split())


def _size(v) -> str:
    """Размер для сравнения: «42.» = «42», «0» у WB = без размера (постель)."""
    s = _norm(v).rstrip(".").strip()
    return "" if s == "0" else s


BARCODE_COL = 20  # «главный», колонка T — баркоды WB (через «; », если их несколько)


def _barcode_text(v) -> list[str]:
    if isinstance(v, float) and v.is_integer():  # баркод, введённый как число
        v = int(v)
    return [b.strip() for b in str(v or "").replace(",", ";").split(";") if b.strip()]


def article_index() -> dict:
    """Лист «главный»: B — артикул, C — размер, L — наименование, T — баркоды WB.
    pairs: (артикул, размер) → наименование; barcodes: баркод → наименование."""
    key = _signature(source_path())
    if _ART_CACHE["key"] == key and _ART_CACHE["data"] is not None:
        return _ART_CACHE["data"]
    data = {"pairs": {}, "barcodes": {}}
    wb = load_workbook(source_path(), data_only=True, read_only=True)
    try:
        for row in list(wb["главный"].iter_rows(values_only=True))[4:]:
            if not row or len(row) < 12 or not _clean(row[11]):
                continue
            name = _clean(row[11])
            if _norm(row[1]):
                data["pairs"].setdefault((_norm(row[1]), _size(row[2])), name)
            for bc in _barcode_text(row[BARCODE_COL - 1] if len(row) >= BARCODE_COL else None):
                data["barcodes"].setdefault(bc, name)
    finally:
        wb.close()
    _ART_CACHE["key"] = key
    _ART_CACHE["data"] = data
    return data


def resolve_by_barcode(barcode: str) -> str | None:
    """Только по баркоду из колонки T листа «главный»."""
    return article_index()["barcodes"].get(str(barcode or "").strip())


def import_barcodes(path: str | Path) -> dict:
    """Выгрузка WB «Общие характеристики» (B — артикул продавца, L — баркод, M — размер) →
    баркоды в колонку T «главного», в строку с тем же артикулом (B) и размером (C)."""
    src = load_workbook(path, data_only=True, read_only=True)
    try:
        rows = list(src["Товары"].iter_rows(values_only=True))[4:]
    finally:
        src.close()
    want: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        if r and len(r) > 12 and _clean(r[1]) and _clean(r[11]):
            want.setdefault((_norm(r[1]), _size(r[12])), []).append(_clean(r[11]))
    p = source_path()
    with BOOK_LOCK:
        cex_guard(p)
        _backup(p)
        wb = load_workbook(p, keep_vba=True)
        ws = wb["главный"]
        ws.cell(row=4, column=BARCODE_COL, value="баркод WB")
        used, rows_done = set(), 0
        for r in range(5, ws.max_row + 1):
            k = (_norm(ws.cell(r, 2).value), _size(ws.cell(r, 3).value))
            if not k[0] or k not in want:
                continue
            have = _barcode_text(ws.cell(r, BARCODE_COL).value)
            merged = have + [b for b in want[k] if b not in have]
            ws.cell(r, BARCODE_COL, value="; ".join(merged))
            used.add(k)
            rows_done += 1
        _save_atomic(wb, p)
    _ART_CACHE["key"] = None
    miss = sorted((k, v) for k, v in want.items() if k not in used)
    return {"баркодов": sum(len(v) for v in want.values()), "строк_заполнено": rows_done,
            "нет_в_главном": [(a, s, ", ".join(b)) for (a, s), b in miss]}


# --- сопоставление с выгрузкой WB, где артикул — просто модель («477»), а цвет — отдельная колонка (ЖСК)
def _nn(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower().replace("ё", "е").replace("-", " "))


def _colors(v) -> frozenset:
    """«белый;синий» = «синий, белый» = «Синий, белый» — порядок и разделитель не важны."""
    return frozenset(x.strip() for x in re.split(r"[;,]", _nn(v)) if x.strip())


def name_key(name: str):
    """«Брюки/477/мята-пыльная/42» → ("", "477", {мята пыльная}, "42"); постель — со своей категорией."""
    p = str(name or "").split("/")
    if len(p) < 4:
        return None
    if _nn(p[0]) == "постель":  # у навычки та же модель — её не путаем с комплектом
        return _bed_key(p[1], p[3])
    return ("", _nn(p[1]), _colors(p[2]), _nn(_size(p[3])).replace(",", "."))


def wb_key(article, color, size, wb_category):
    """Строка выгрузки WB → тот же ключ. У постельного WB размера нет: «1,5 сп шахмат» → 1.5 сп, иначе 1 сп."""
    if _nn(wb_category).startswith("постельное"):
        return _bed_key(article, "")
    return ("", _nn(article), _colors(color), _nn(_size(size)))


def _bed_key(model, size) -> tuple:
    """Постель: рисунок + размер. «1,5 СП ШАХМАТ» → («шахмат», «1.5 сп»), без приставки — 1 сп.
    Цвет не сравниваем: он задан рисунком, а в карточках WB у полуторок стоит «черный;белый» для всех."""
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*сп\s+(.+)$", _nn(model))
    bed = m.group(2) if m else _nn(model)
    sz = (m.group(1).replace(",", ".") + " сп") if m else (_nn(size).replace(",", ".") or "1 сп")
    return ("постель", bed, frozenset(), sz)


def wb_rows(path) -> list[dict]:
    """Лист «Товары» выгрузки WB: B артикул, E категория, H фото, K цвет, L баркоды, M размер."""
    src = load_workbook(path, data_only=True, read_only=True)
    try:
        rows = list(src["Товары"].iter_rows(values_only=True))[3:]
    finally:
        src.close()
    out = []
    for r in rows:
        if r and len(r) > 12 and _clean(r[1]) and _clean(r[11]) and _clean(r[1]) != "Артикул продавца":
            out.append({"ключ": wb_key(r[1], r[10], r[12], r[4]), "баркоды": _barcode_text(r[11]),
                        "фото": str(r[7] or "").split(";")[0].strip(), "wb": f"{r[1]} / {r[10]} / {r[12] or '—'}"})
    return out


def alias_keys(key: tuple, aliases: dict | None) -> list[tuple]:
    """Ключ строки WB с учётом соответствий цветов: {(модель, «цвета WB»): [цвета «главного»]}."""
    cat, model, colors, size = key
    for (m, c), to in (aliases or {}).items():
        if _nn(m) == model and _colors(c) == colors:
            return [(cat, model, _colors(x), size) for x in to]
    return [key]


def aliases_from_template(path) -> dict:
    """Заполненный шаблон «Сопоставление цветов»: модель, цвет WB, цвет «главного» (несколько — через «+»)."""
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        out = {}
        for r in list(wb.worksheets[0].iter_rows(values_only=True))[1:]:
            if r and len(r) >= 4 and _clean(r[0]) and _clean(r[1]) and _clean(r[3]) \
                    and _nn(r[3]) not in ("нет", "нету", "-", "—", "пусто"):  # «нету» — цвета в «главном» нет
                out[(_clean(r[0]), _clean(r[1]))] = [x.strip() for x in _clean(r[3]).split("+") if x.strip()]
        return out
    finally:
        wb.close()


def import_barcodes_by_model(path, dry: bool = False, aliases: dict | None = None) -> dict:
    """Баркоды WB → колонка T «главного» там, где одновременно совпали модель, цвет(а) и размер.
    Уже записанные баркоды (другого кабинета) сохраняются, новые дописываются через «; ».
    aliases — цвет WB, названный в «главном» иначе: {(модель, «цвета WB»): [цвета в «главном»]}.
    Несколько цветов — комплект: его баркод получают все строки (поиск по баркоду найдёт первую)."""
    want: dict = {}
    labels: dict = {}
    for r in wb_rows(path):
        for k in alias_keys(r["ключ"], aliases):
            want.setdefault(k, []).extend(b for b in r["баркоды"] if b not in want.get(k, []))
            labels[k] = r["wb"]
    p = source_path()
    with BOOK_LOCK:
        if not dry:
            cex_guard(p)
            _backup(p)
        wb = load_workbook(p, keep_vba=not dry, read_only=dry, data_only=dry)
        try:
            ws = wb["главный"]
            used, rows_done, added = set(), 0, 0
            for r, row in enumerate(ws.iter_rows(min_row=5, values_only=True), start=5) if dry else \
                    ((r, [ws.cell(r, c).value for c in range(1, BARCODE_COL + 1)]) for r in range(5, ws.max_row + 1)):
                k = name_key(row[11] if len(row) > 11 else "")
                if not k or k not in want:
                    continue
                have = _barcode_text(row[BARCODE_COL - 1] if len(row) >= BARCODE_COL else None)
                new = [b for b in want[k] if b not in have]
                used.add(k)
                rows_done += 1
                added += len(new)
                if new and not dry:
                    ws.cell(r, BARCODE_COL, value="; ".join(have + new))
            if not dry:
                ws.cell(row=4, column=BARCODE_COL, value="баркод WB")
                _save_atomic(wb, p)
        finally:
            if dry:
                wb.close()
    _ART_CACHE["key"] = None
    return {"строк_в_выгрузке": len(want), "строк_совпало": rows_done, "баркодов_добавлено": added,
            "не_найдено": sorted(labels[k] for k in want if k not in used)}


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return default


def _signature(p: Path):
    st = p.stat()
    return (int(st.st_mtime), int(st.st_size))


def _backup(p: Path) -> None:
    try:
        BACKUP.mkdir(parents=True, exist_ok=True)
        dst = BACKUP / f"{datetime.now():%Y-%m-%d_%H%M%S}_{p.name}"
        shutil.copyfile(p, dst)
        old = sorted(BACKUP.glob("*.xlsm"))
        for f in old[:-12]:
            f.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print("резервная копия не создана:", exc)


# ------------------------------------------------------------------ реестр
def _ledger() -> dict:
    if not LEDGER.exists():
        return {"приход": [], "адрес": [], "отгрузки": [], "orders": []}
    try:
        mt = LEDGER.stat().st_mtime
    except OSError:
        mt = None
    if _LEDGER_CACHE["mtime"] == mt and _LEDGER_CACHE["data"] is not None:
        return _LEDGER_CACHE["data"]
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        data = {"приход": [], "адрес": [], "отгрузки": [], "orders": []}
    _LEDGER_CACHE["mtime"] = mt
    _LEDGER_CACHE["data"] = data
    return data


def _save_ledger(data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    # страховка: копия реестра перед перезаписью
    if LEDGER.exists():
        try:
            hist = DATA / "склад_реестр_история"
            hist.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copyfile(LEDGER, hist / f"{stamp}.json")
            for old in sorted(hist.glob("*.json"))[:-40]:
                old.unlink(missing_ok=True)
        except Exception:
            pass
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(LEDGER)
    _LEDGER_CACHE["data"] = data
    try:
        _LEDGER_CACHE["mtime"] = LEDGER.stat().st_mtime
    except OSError:
        _LEDGER_CACHE["mtime"] = None
    _STOCK["key"] = None


# ------------------------------------------------------------------ чтение
def load_master(force: bool = False) -> dict:
    p = source_path()
    sig = _signature(p)
    if not force and _CACHE["sig"] == sig and _CACHE["data"]:
        return _CACHE["data"]

    # read_only: читаем только нужные листы потоком (≈0,2 с вместо ≈6 с на всю книгу)
    wb = load_workbook(p, data_only=True, read_only=True)
    data = {"items": [], "suppliers": [], "addresses": [], "item_address": {},
            "barcodes": {}, "categories": [], "ship_sheets": {}}
    # листы отгрузок: «паставка ЖСК» → клиент «ЖСК»
    for name in wb.sheetnames:
        low = name.strip().lower()
        if low.startswith("паставка ") and not low[len("паставка "):].strip().isdigit():
            client = name.strip()[len("паставка "):].strip()
            if client:
                data["ship_sheets"][client.upper()] = name
    try:
        addr_qty = defaultdict(float)
        ship_qty = defaultdict(float)

        if "адрес" in wb.sheetnames:
            for row in list(wb["адрес"].iter_rows(values_only=True))[1:]:
                if row and len(row) > 6 and row[5]:
                    addr_qty[_clean(row[5])] += _num(row[6])

        # как формула ф.к на листе «главный»: адрес − все листы «паставка …» − «магазин».
        # Листы берём по имени из книги: список вроде «паставка ААТ» устаревал
        # (лист называется «паставка Алтын», и его отгрузки не вычитались).
        ship_sheets = [(n, 5, 6) for n in wb.sheetnames if n.strip().lower().startswith("паставка")]
        for sheet, name_col, qty_col in ship_sheets + [("магазин", 2, 3)]:
            if sheet not in wb.sheetnames:
                continue
            for row in list(wb[sheet].iter_rows(values_only=True))[1:]:
                if row and len(row) > max(name_col, qty_col) and row[name_col]:
                    ship_qty[_clean(row[name_col])] += _num(row[qty_col])

        bought = defaultdict(float)
        defect = defaultdict(float)
        if "приобритение" in wb.sheetnames:
            for row in list(wb["приобритение"].iter_rows(values_only=True))[7:]:
                if row and len(row) > 7 and row[2]:
                    name_key = _clean(row[2])
                    bought[name_key] += _num(row[7])
                    if len(row) > 6:
                        defect[name_key] += _num(row[6])

        # каталог и остатки
        ws = wb["главный"]
        seen = set()
        for row in list(ws.iter_rows(values_only=True))[4:]:
            if not row or len(row) < 18 or not row[11]:
                continue
            name = _clean(row[11])
            if not name or name in seen:
                continue
            seen.add(name)
            parts = [x.strip() for x in name.split("/")]
            cat = parts[0] if parts else ""
            if cat.lower().startswith("футболка") and "хб" in cat.lower():
                cat = "Футболка ХБ"
            data["items"].append({
                "наименование": name,
                "категория": cat,
                "модель": parts[1] if len(parts) > 1 else "",
                "цвет": parts[2] if len(parts) > 2 else "",
                "размер": parts[3] if len(parts) > 3 else "",
                "фк": round(addr_qty.get(name, 0.0) - ship_qty.get(name, 0.0), 2),
                "приобретено": round(bought.get(name, 0.0), 2),
                "неликвид": round(defect.get(name, 0.0), 2),
                "размещено": round(addr_qty.get(name, 0.0), 2),
            })

        # справочник: категории, поставщики, адреса
        if "Вспомогательный лист" in wb.sheetnames:
            ws = wb["Вспомогательный лист"]
            suppliers, addresses, cats = set(), set(), set()
            for row in list(ws.iter_rows(values_only=True))[1:]:
                if not row:
                    continue
                row = list(row) + [None] * (14 - len(row))
                name = _clean(row[0])
                if len(row) > 8 and row[8]:
                    suppliers.add(_clean(row[8]))
                if len(row) > 9 and row[9]:
                    addr = _clean(row[9])
                    addresses.add(addr)
                    if name:
                        data["item_address"][name] = addr
                if len(row) > 6 and row[6]:
                    cats.add(_clean(row[6]))
            data["suppliers"] = sorted(suppliers)
            data["addresses"] = sorted(addresses)
            data["categories"] = sorted(cats)

        # адреса из листа «адрес» (что уже размещено)
        if "адрес" in wb.sheetnames:
            ws = wb["адрес"]
            placed = defaultdict(float)
            for row in list(ws.iter_rows(values_only=True))[1:]:
                if not row or len(row) < 7:
                    continue
                name = _clean(row[5])
                box = _clean(row[4])
                qty = _num(row[6])
                if name and qty:
                    placed[(box, name)] += qty
            data["placed"] = {f"{k[0]}|{k[1]}": v for k, v in placed.items()}

        # коды из «Вспомогательного листа» (колонка F) → наименование
        if "Вспомогательный лист" in wb.sheetnames:
            codes = data.setdefault("codes", {})
            for row in list(wb["Вспомогательный лист"].iter_rows(values_only=True))[1:]:
                if not row or len(row) < 6:
                    continue
                name = _clean(row[0])
                code = _clean(row[5])
                if name and code and code not in codes:
                    codes[code.lower()] = name

        # штрихкоды: EAN → модель/цвет/размер
        for sheet in ("лист для штрих кодов и отчета",):
            if sheet not in wb.sheetnames:
                continue
            for row in list(wb[sheet].iter_rows(values_only=True))[3:]:
                if not row or len(row) < 7:
                    continue
                code, sku, color, size = _clean(row[6]), _clean(row[2]), _clean(row[4]), _clean(row[5])
                if re.fullmatch(r"\d{8,14}", code) and sku:
                    data["barcodes"][code] = {
                        "модель": sku.split("-")[0].strip(),
                        "цвет": color.lower(),
                        "размер": size,
                    }
    finally:
        wb.close()

    _CACHE["sig"] = sig
    _CACHE["data"] = data
    return data


# ------------------------------------------------------------------ расчёт
def _stock_key():
    try:
        st = source_path().stat()
        mt = (int(st.st_mtime), int(st.st_size))
    except OSError:
        mt = (0, 0)
    try:
        lm = int(LEDGER.stat().st_mtime) if LEDGER.exists() else 0
    except OSError:
        lm = 0
    return (mt, lm)


def _fbs_shipped() -> dict:
    try:
        import fbs_stock
        return fbs_stock.shipped_by_name()
    except Exception:
        return {}


def _sql_fact() -> dict | None:
    try:
        import fbs_stock
        return fbs_stock.fact_by_name()
    except Exception:
        return None


def stock_items() -> list[dict]:
    sql_fact = _sql_fact()
    key = (_stock_key(), tuple(sorted(_fbs_shipped().items())),
           tuple(sorted(sql_fact.items())) if sql_fact is not None else None)
    if _STOCK["key"] == key:
        return _STOCK["items"]
    data = load_master()
    led = _ledger()
    placed, shipped, bought = defaultdict(float), defaultdict(float), defaultdict(float)
    for r in led.get("адрес", []):
        placed[_clean(r.get("наименование"))] += _num(r.get("количество"))
    for r in led.get("отгрузки", []):
        shipped[_clean(r.get("наименование"))] += _num(r.get("количество"))
    for r in led.get("приход", []):
        bought[_clean(r.get("наименование"))] += _num(r.get("количество"))
    out = []
    items = list(data["items"])
    known = {it["наименование"] for it in items}
    for name in sorted(set(sql_fact or {}) - known):  # товары, заведённые в цехе (нет в «главном»)
        parts = [x.strip() for x in name.split("/")] + ["", "", "", ""]
        items.append({"наименование": name, "категория": parts[0], "модель": parts[1], "цвет": parts[2],
                      "размер": parts[3], "фк": 0.0, "приобретено": 0.0, "неликвид": 0.0, "размещено": 0.0})
    for it in items:
        name = it["наименование"]
        # «до KB»: куплено − размещено − неликвид (по листам) + ещё не выгруженные операции
        pend = (it.get("приобретено", 0.0) - it.get("размещено", 0.0) - it.get("неликвид", 0.0)
                + bought.get(name, 0.0) - placed.get(name, 0.0))
        fbs = _fbs_shipped().get(name, 0.0)
        if sql_fact is not None:  # PostgreSQL — источник истины (операции зеркалятся туда)
            fact = sql_fact.get(name, 0.0)
        else:
            fact = it["фк"] + placed.get(name, 0.0) - shipped.get(name, 0.0) - fbs
        out.append({
            **it,
            "остаток": round(fact, 2),
            "пересорт": round(max(0.0, -fact), 2),
            "ожидает": round(max(0.0, pend), 2),
            "приход": round(it.get("приобретено", 0.0), 2),
            "отгружено": round(shipped.get(name, 0.0) + fbs, 2),
            "фbs": round(fbs, 2),
            "адрес": data["item_address"].get(name, ""),
        })
    _STOCK.update(key=key, ts=time.time(), items=out,
                  index={i["наименование"].lower(): i for i in out},
                  names=[i["наименование"] for i in out])
    return out


def _size_key(v: str):
    m = re.match(r"(\d+(?:[.,]\d+)?)", str(v))
    return (0, float(m.group(1).replace(",", "."))) if m else (1, str(v))


def meta() -> dict:
    items = stock_items()
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for it in items:
        tree[it["категория"]][it["модель"]][it["цвет"]].add(it["размер"])
    data = load_master()
    return {
        "категории": sorted(tree.keys()),
        "дерево": {c: {m: {col: sorted(s, key=_size_key) for col, s in cols.items()}
                       for m, cols in models.items()} for c, models in tree.items()},
        "поставщики": data["suppliers"],
        "адреса": data["addresses"][:400],
        "получатели": sorted(data.get("ship_sheets") or {k: v for k, v in SHIP_SHEET.items()}),
        "позиций": len(items),
        "штук": round(sum(i["остаток"] for i in items), 2),
        "вес": "не задан в файле",
        "источник": source_path().name,
    }


def find_many(value: str, limit: int = 6) -> list[dict]:
    """Все подходящие варианты — для подсказок в интерфейсе."""
    v = (value or "").strip().lower()
    if not v:
        return []
    stock_items()
    exact = _STOCK["index"].get(v)
    if exact:
        return [exact]
    # штрихкод или код из «Вспомогательного листа»
    resolved = resolve_product(value.strip())
    if resolved:
        return [resolved]
    out = [i for i in _STOCK["items"] if v in i["наименование"].lower()]
    out.sort(key=lambda i: (len(i["наименование"]), -i["остаток"]))
    return out[:limit]


def resolve_product(value: str) -> dict | None:
    v = (value or "").strip()
    if not v:
        return None
    items = stock_items()
    if re.fullmatch(r"\d{8,14}", v):
        info = load_master()["barcodes"].get(v)
        if not info:
            return None
        model = info["модель"].lower()
        for it in items:
            if (it["модель"].lower() == model
                    and (not info["цвет"] or info["цвет"] in it["цвет"].lower())
                    and (not info["размер"] or info["размер"] == it["размер"])):
                return it
        return None
    low = v.lower()
    codes = (load_master().get("codes") or {})
    if low in codes:
        mapped = _STOCK["index"].get(codes[low].lower())
        if mapped:
            return mapped
    hit = _STOCK["index"].get(low)
    if hit:
        return hit
    best = None
    for name in _STOCK["names"]:
        ln = name.lower()
        if low in ln:
            if best is None or len(name) < len(best["наименование"]):
                best = _STOCK["index"][ln]
    return best


# ------------------------------------------------------------------ запись
def receive(supplier: str, name: str, qty: float, defect: float, batch: str) -> dict:
    item = resolve_product(name)
    if not item:
        raise ValueError("Товар не найден в справочнике")
    if qty <= 0:
        raise ValueError("Количество должно быть больше нуля")
    with _LOCK:
        led = _ledger()
        led.setdefault("приход", []).append({
            "key": _op_key(),
            "дата": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "наименование": item["наименование"], "количество": qty,
            "поставщик": supplier, "неликвид": defect, "партия": batch,
        })
        _save_ledger(led)
    flush_async()
    return {"остаток": round(item["остаток"], 2), "ожидает": round(item.get("ожидает", 0) + qty, 2)}


NO_ADDRESS = "без адреса"  # коробка для товара, принятого сразу на склад


def receive_multi(supplier: str, batch: str, defect: float, rows: list[dict],
                  direct: bool = False) -> dict:
    """Приход сразу по нескольким размерам: [{наименование, количество}, ...].
    direct — сразу на склад: размещаем в «без адреса», товар сразу в факте (пока нет адресного хранения)."""
    ok = 0
    total = 0.0
    placed = []
    with _LOCK:
        led = _ledger()
        for row in rows:
            name = _clean(row.get("наименование"))
            qty = _num(row.get("количество"))
            if not name or qty <= 0:
                continue
            item = resolve_product(name)
            if not item:
                continue
            led.setdefault("приход", []).append({
                "key": _op_key(),
                "дата": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "наименование": item["наименование"], "количество": qty,
                "поставщик": supplier, "неликвид": defect, "партия": batch,
            })
            if direct:
                led.setdefault("адрес", []).append({
                    "key": _op_key(),
                    "дата": datetime.now().strftime("%d.%m.%Y %H:%M"), "коробка": NO_ADDRESS,
                    "наименование": item["наименование"], "количество": qty,
                })
                placed.append((item["наименование"], qty))
            ok += 1
            total += qty
        _save_ledger(led)
    if not ok:
        raise ValueError("Не выбрано ни одного размера с количеством")
    flush_async()
    _shadow("приход", {"поставщик": supplier, "партия": batch, "неликвид": defect,
                       "позиции": rows})
    for name, qty in placed:
        _shadow("адрес", {"коробка": NO_ADDRESS, "наименование": name, "количество": qty})
    return {"строк": ok, "штук": total, "сразу_на_склад": bool(direct)}


def place(box: str, name: str, qty: float) -> dict:
    item = resolve_product(name)
    if not item:
        raise ValueError("Товар не найден")
    box = _safe(box or "")
    if not box:
        raise ValueError("Сначала отсканируйте адрес (коробку)")
    if not re.fullmatch(r"[A-Za-zА-Яа-я0-9/_.\- ]{2,40}", box):
        raise ValueError("Это не похоже на адрес. Адрес выглядит так: s/t1/e1/i1")
    if qty <= 0:
        raise ValueError("Количество должно быть больше нуля")
    pending = item.get("ожидает", 0.0)
    if pending <= 0:
        raise ValueError("По этому товару нет прихода для размещения — сначала оформите приход")
    if qty > pending:
        raise ValueError(f"Для размещения доступно {pending:g} шт (приход минус уже размещённое)")
    with _LOCK:
        led = _ledger()
        led.setdefault("адрес", []).append({
            "key": _op_key(),
            "дата": datetime.now().strftime("%d.%m.%Y %H:%M"), "коробка": box,
            "наименование": item["наименование"], "количество": qty,
        })
        _save_ledger(led)
    flush_async()
    _shadow("адрес", {"коробка": box, "наименование": item["наименование"], "количество": qty})
    return {"коробка": box, "товар": item["наименование"], "количество": qty}


def ship(target: str, name: str, qty: float, order: str = "", who: str = "",
         check: str = "Nice✅", any_target: bool = False) -> dict:
    """any_target: заказ сотрудника или FBO — листа «паставка …» нет, списание идёт в PostgreSQL,
    в книгу Excel такая отгрузка не пишется (выгрузка пропускает получателей без листа)."""
    sheets = load_master().get("ship_sheets") or {k.upper(): v for k, v in SHIP_SHEET.items()}
    target = _clean(target).upper()
    if target not in sheets and not any_target:
        raise ValueError(f"Нет листа отгрузки для «{target}» (нужен лист «паставка {target}»)")
    item = resolve_product(name)
    if not item:
        raise ValueError("Товар не найден")
    if qty <= 0:
        raise ValueError("Количество должно быть больше нуля")
    if item["остаток"] <= 0:
        raise ValueError(f"Нет свободного остатка: по товару пересорт {abs(item['остаток']):g} шт. Сначала разберитесь с размещением")
    if qty > item["остаток"]:
        raise ValueError(f"На складе всего {item['остаток']:g} шт")
    with _LOCK:
        led = _ledger()
        led.setdefault("отгрузки", []).append({
            "key": _op_key(),
            "дата": datetime.now().strftime("%d.%m.%Y %H:%M"), "получатель": target,
            "наименование": item["наименование"], "количество": qty,
            "заказ": order, "кто": who, "проверка": check,
        })
        _save_ledger(led)
    flush_async()
    _shadow("отгрузка", {"получатель": target, "наименование": item["наименование"],
                         "количество": qty, "заказ": order})
    return {"остаток": round(item["остаток"] - qty, 2)}


def _last_filled_row(ws, first_data_row: int = 2, ncols: int = 10) -> int:
    last = first_data_row - 1
    for r in range(first_data_row, ws.max_row + 1):
        if any(ws.cell(row=r, column=c).value not in (None, "") for c in range(1, ncols + 1)):
            last = r
    return last


def _compact_sheet(ws, first_data_row: int = 2, ncols: int = 10) -> int:
    """Убирает пустые строки: данные поднимаются вверх, без дырок.
    Возвращает номер последней заполненной строки."""
    last = ws.max_row
    rows = []
    for r in range(first_data_row, last + 1):
        vals = [ws.cell(row=r, column=c).value for c in range(1, ncols + 1)]
        if any(v not in (None, "") for v in vals):
            rows.append(vals)
    for r in range(first_data_row, last + 1):
        for c in range(1, ncols + 1):
            ws.cell(row=r, column=c).value = None
    for i, vals in enumerate(rows, start=first_data_row):
        for c, v in enumerate(vals, start=1):
            ws.cell(row=i, column=c).value = v
    return first_data_row + len(rows) - 1 if rows else first_data_row - 1


def _expand_tables(ws, last_row: int | None = None) -> None:
    """Растягивает таблицы Excel на добавленные строки: иначе новые записи
    остаются ниже таблицы и в Excel их «не видно»."""
    try:
        names = list(ws.tables.keys())
    except Exception:
        return
    last = last_row or ws.max_row
    for name in names:
        try:
            tbl = ws.tables[name]
        except Exception:
            continue
        ref = getattr(tbl, "ref", None)
        if not ref or ":" not in ref:
            continue
        try:
            start_cell, end_cell = ref.split(":")
            col_start = "".join(ch for ch in start_cell if ch.isalpha())
            col_end = "".join(ch for ch in end_cell if ch.isalpha())
            row_end = int("".join(ch for ch in end_cell if ch.isdigit()))
            if last != row_end:
                tbl.ref = f"{col_start}1:{col_end}{last}"
        except Exception:
            continue


ROLE_RU = {
    "admin": "Начальник", "manager": "Менеджер", "accountant": "Бухгалтер",
    "technologist": "Технолог", "storekeeper": "Складчик",
    "client": "Клиент",
}


def _sheet(wb, name: str, headers: list[str], widths: list[int]):
    if name in wb.sheetnames:
        ws = wb[name]
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)
    else:
        ws = wb.create_sheet(name)
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = widths[i - 1] if i <= len(widths) else 16
    ws.freeze_panes = "A2"
    return ws






def _save_atomic(wb, path: Path) -> None:
    """Сохраняет книгу во временный файл и подменяет исходный — защита от обрыва.

    Если процесс упадёт во время записи, рабочий файл останется целым.
    """
    tmp = path.with_name(path.stem + ".wh.tmp" + path.suffix)  # своё имя: у цеха другое
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

def _append_shipment_row(ws, date: str, name: str, qty: float) -> int:
    """Вставляет строку отгрузки в таблицу листа «паставка …».

    Пишем только E (дата), F (наименование), G (количество). Колонки H (проверка)
    и I (категория) — формулы Excel, их не трогаем: копируем формулу из первой
    строки данных, чтобы Excel посчитал сам.
    """
    hf = ws.cell(row=2, column=8).value
    i_f = ws.cell(row=2, column=9).value
    hf = hf if isinstance(hf, str) and hf.startswith("=") else None
    i_f = i_f if isinstance(i_f, str) and i_f.startswith("=") else None

    row = 2
    col_end = "I"
    tbl = list(ws.tables.values())[0] if ws.tables else None
    if tbl is not None and tbl.ref and ":" in tbl.ref:
        start_cell, end_cell = tbl.ref.split(":")
        col_end = "".join(ch for ch in end_cell if ch.isalpha()) or "I"
        row_end = int("".join(ch for ch in end_cell if ch.isdigit()))
        row = row_end + 1
    else:
        row = _last_filled_row(ws, 2, 10) + 1

    ws.cell(row=row, column=5, value=date)
    ws.cell(row=row, column=6, value=name)
    ws.cell(row=row, column=7, value=qty)
    if hf:
        ws.cell(row=row, column=8, value=hf)
    if i_f:
        ws.cell(row=row, column=9, value=i_f)
    if tbl is not None:
        tbl.ref = f"E1:{col_end}{row}"
    return row

def _write_orders_sheet(wb, led: dict, counts: dict) -> None:
    """Лист «заказы»: все заказы клиентов, включая отменённые и собранные."""
    headers = ["№", "дата", "клиент", "статус", "товар", "заказано", "собрано",
               "кто закрыл", "причина отмены", "дата закрытия"]
    ws = _sheet(wb, "заказы", headers, [7, 15, 11, 10, 34, 10, 9, 16, 22, 15])
    row = 2
    written = 0
    for o in led.get("orders", []):
        for pos in o.get("позиции", []):
            values = [o.get("id"), o.get("дата"), o.get("клиент"), o.get("статус"),
                      pos.get("наименование"), pos.get("количество"), pos.get("отгружено", 0),
                      o.get("отменил", ""), o.get("причина", ""), o.get("закрыт", "")]
            for c, v in enumerate(values, start=1):
                ws.cell(row=row, column=c, value=v)
            row += 1
            written += 1
    counts["заказы"] = written


def _write_staff_sheets(wb, counts: dict) -> None:
    """Листы «сотрудники» и «расценки».

    «сотрудники» — рабочий лист: если он уже заполнен, правки владельца не
    перезаписываем, только считаем строки. «расценки» обновляем всегда.
    """
    if "сотрудники" not in wb.sheetnames or wb["сотрудники"].max_row <= 1:
        _fill_staff_sheet(wb, counts)
    else:
        counts["сотрудники"] = max(0, wb["сотрудники"].max_row - 1)
    _fill_rates_sheet(wb, counts)


def _fill_staff_sheet(wb, counts: dict) -> None:
    import hashlib

    def hashpw(raw: str) -> str:
        return hashlib.sha256(("v2salt::" + raw).encode("utf-8")).hexdigest()

    default_hash = hashpw("123456")
    users_path = DATA / "users.xlsx"
    ws = _sheet(wb, "сотрудники",
                ["логин", "пароль", "ФИО", "роль", "должность", "цех",
                 "ставка за час", "активен"],
                [12, 12, 26, 14, 14, 8, 12, 9])
    n = 0
    if users_path.exists():
        src = load_workbook(users_path, data_only=True)
        try:
            sheet = src["users"] if "users" in src.sheetnames else src[src.sheetnames[0]]
            head = [str(c.value or "").strip() for c in sheet[1]]
            idx = {h: i for i, h in enumerate(head)}
            for raw in list(sheet.iter_rows(values_only=True))[1:]:
                if not raw or not raw[idx.get("логин", 0)]:
                    continue
                stored = str(raw[idx.get("пароль", 1)] or "")
                pw = "123456" if stored == default_hash else "изменён"
                role = str(raw[idx.get("роль", 3)] or "")
                values = [raw[idx.get("логин", 0)], pw, raw[idx.get("фио", 2)],
                          role, ROLE_RU.get(role, role), raw[idx.get("цех", 4)],
                          raw[idx.get("ставка_час", 5)] or 0,
                          "да" if str(raw[idx.get("активен", 6)]) in ("1", "True", "true") else "нет"]
                for c, v in enumerate(values, start=1):
                    ws.cell(row=n + 2, column=c, value=v)
                n += 1
        finally:
            src.close()
    counts["сотрудники"] = n


def _fill_rates_sheet(wb, counts: dict) -> None:
    proc_path = DATA / "processes.xlsx"
    ws = _sheet(wb, "расценки", ["код", "операция", "расценка за шт", "порядок", "обязательная", "отключён"],
                [12, 30, 15, 10, 13, 11])
    m = 0
    if proc_path.exists():
        src = load_workbook(proc_path, data_only=True)
        try:
            sheet = src["processes"] if "processes" in src.sheetnames else src[src.sheetnames[0]]
            head = [str(c.value or "").strip() for c in sheet[1]]
            idx = {h: i for i, h in enumerate(head)}
            for raw in list(sheet.iter_rows(values_only=True))[1:]:
                if not raw or not raw[idx.get("код", 0)]:
                    continue
                values = [raw[idx.get("код", 0)], raw[idx.get("название", 1)],
                          raw[idx.get("тариф", 3)] or 0, raw[idx.get("порядок", 2)] or 0,
                          "да" if str(raw[idx.get("обязательный", 5)]) in ("1", "True", "true") else "нет",
                          # отключённый в цехе этап — колонки может не быть в старом processes.xlsx
                          "да" if "отключён" in idx and str(raw[idx["отключён"]]) in ("1", "True", "true") else ""]
                for c, v in enumerate(values, start=1):
                    ws.cell(row=m + 2, column=c, value=v)
                m += 1
        finally:
            src.close()
    counts["расценки"] = m


def export_to_excel(who: str = "") -> dict:
    """Переносит операции портала в файл цеха (один раз, пачкой)."""
    with _EXPORT_LOCK, BOOK_LOCK:  # пока книга открыта и сохраняется, цех ждёт
        _FLUSH["running"] = True
        try:
            counts = _export_to_excel(who)
        finally:
            _FLUSH["running"] = False
    if sum(counts.get(k, 0) for k in ("приход", "адрес", "отгрузки", "заказы")):
        _FLUSH["last"] = (datetime.now().strftime("%H:%M:%S")
                          + f" · приход {counts['приход']}, адрес {counts['адрес']}, отгрузки {counts['отгрузки']}")
    return counts


def _export_to_excel(who: str = "") -> dict:
    led = _ledger()
    if not (led.get("приход") or led.get("адрес") or led.get("отгрузки") or led.get("orders")):
        return {"приход": 0, "адрес": 0, "отгрузки": 0, "заказы": 0,
                "сотрудники": 0, "расценки": 0}
    p = source_path()
    _backup(p)
    wb = load_workbook(p, keep_vba=True)
    counts = {"приход": 0, "адрес": 0, "отгрузки": 0, "заказы": 0, "сотрудники": 0, "расценки": 0}
    done = {"приход": set(), "адрес": set(), "отгрузки": set()}
    try:
        if led.get("приход") and "приобритение" in wb.sheetnames:
            ws = wb["приобритение"]
            for r in led["приход"]:
                it = resolve_product(r.get("наименование", "")) or {}
                ws.append([r.get("дата", "")[:10], r.get("поставщик", ""), r.get("наименование", ""),
                           it.get("модель", ""), it.get("цвет", ""), it.get("размер", ""),
                           r.get("неликвид", ""), r.get("количество", 0), r.get("партия", ""),
                           it.get("категория", ""), it.get("модель", ""), it.get("размер", "")])
                counts["приход"] += 1
                if r.get("key"):
                    done["приход"].add(r["key"])
        if led.get("адрес") and "адрес" in wb.sheetnames:
            ws = wb["адрес"]
            for r in led["адрес"]:
                it = resolve_product(r.get("наименование", "")) or {}
                target = _last_filled_row(ws, 2, 10) + 1
                vals = ["", "", "", r.get("дата", "")[:10], r.get("коробка", ""),
                        r.get("наименование", ""), r.get("количество", 0), "Nice✅",
                        it.get("категория", ""), ""]
                for c, v in enumerate(vals, start=1):
                    ws.cell(row=target, column=c).value = v
                counts["адрес"] += 1
                if r.get("key"):
                    done["адрес"].add(r["key"])
            last_row = _compact_sheet(ws, 2, 10)
            _expand_tables(ws, last_row)
        ship_map = {_clean(k).upper(): v for k, v in
                    (load_master().get("ship_sheets") or SHIP_SHEET).items()}
        targets = []
        for r in led.get("отгрузки", []):
            t = _clean(r.get("получатель")).upper()
            if t and t not in targets:
                targets.append(t)
        for target in targets:
            rows = [r for r in led.get("отгрузки", [])
                    if _clean(r.get("получатель")).upper() == target]
            sheet_name = ship_map.get(target)
            if not rows or not sheet_name or sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            for r in rows:
                name = _safe(r.get("наименование", ""))
                try:
                    _append_shipment_row(ws, _safe(r.get("дата", ""))[:10], name,
                                         r.get("количество", 0))
                    counts["отгрузки"] += 1
                    if r.get("key"):
                        done["отгрузки"].add(r["key"])
                    elif True:
                        pass
                except Exception:
                    counts["ошибок"] = counts.get("ошибок", 0) + 1
        _write_orders_sheet(wb, led, counts)
        _write_staff_sheets(wb, counts)
        _save_atomic(wb, p)
    finally:
        wb.close()
    _CACHE["sig"] = None
    _SMALL.clear()
    _STOCK["key"] = None
    # под блокировкой: иначе операция, пришедшая в этот момент, затрётся при сохранении реестра
    with _LOCK:
        fresh = _ledger()
        fresh["приход"] = [r for r in fresh.get("приход", []) if r.get("key") not in done["приход"]]
        fresh["адрес"] = [r for r in fresh.get("адрес", []) if r.get("key") not in done["адрес"]]
        fresh["отгрузки"] = [r for r in fresh.get("отгрузки", []) if r.get("key") not in done["отгрузки"]]
        _save_ledger(fresh)
    return counts


def addresses(limit: int = 200) -> list[dict]:
    led = _ledger()
    return list(reversed(led.get("адрес", [])))[:limit]


def shipments(target: str, limit: int = 200) -> list[dict]:
    led = _ledger()
    rows = [r for r in led.get("отгрузки", []) if r.get("получатель") == target]
    return list(reversed(rows))[:limit]


def purchases(limit: int = 200) -> list[dict]:
    return list(reversed(_ledger().get("приход", [])))[:limit]


_EXPORT_LOCK = threading.Lock()  # одна запись в книгу за раз: фоновая и кнопка «сейчас» не пересекаются
DEFAULT_FLUSH_MINUTES = 3.0


def _flush_delay() -> float:
    """Пауза перед записью пачки в Excel, сек (config.json → excel_flush_minutes)."""
    minutes = DEFAULT_FLUSH_MINUTES
    try:
        cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        minutes = float(cfg.get("excel_flush_minutes", minutes))
    except Exception:  # noqa: BLE001
        pass
    return max(1.5, min(minutes, 60.0) * 60)


def _has_pending(led: dict) -> bool:
    return bool(led.get("приход") or led.get("адрес") or led.get("отгрузки"))


def flush_async(delay: float | None = None) -> None:
    """Планирует запись накопленных операций в Excel одной пачкой.

    Запись книги занимает ≈15 с и нагружает сервер, поэтому пишем не после каждой
    операции, а раз в несколько минут. Повторные вызовы срок не сдвигают:
    первая операция серии задаёт время записи. Операции до записи лежат в реестре
    и уже учтены в остатках приложения.
    """
    with _LOCK:
        if _FLUSH.get("timer"):
            return
        wait = _flush_delay() if delay is None else delay
        _FLUSH["due"] = time.time() + wait
        timer = threading.Timer(wait, _flush_worker)
        timer.daemon = True
        _FLUSH["timer"] = timer
        timer.start()


def _flush_worker() -> None:
    with _LOCK:
        _FLUSH["timer"] = None
        _FLUSH["due"] = None
    failed = False
    try:
        export_to_excel()
    except Exception as exc:  # noqa: BLE001
        failed = True
        _FLUSH["last"] = "ошибка записи: " + str(exc)
    # книга была занята или за время записи пришли новые операции — следующая пачка
    if failed or _has_pending(_ledger()):
        flush_async()


def flush_pending() -> None:
    """При запуске сервера: дописать то, что осталось в реестре с прошлого раза."""
    if _has_pending(_ledger()):
        flush_async()


def flush_status() -> dict:
    led = _ledger()
    due = _FLUSH.get("due")
    return {"выполняется": _FLUSH["running"], "последняя": _FLUSH["last"],
            "в_очереди": len(led.get("приход", [])) + len(led.get("адрес", [])) + len(led.get("отгрузки", [])),
            "следующая": datetime.fromtimestamp(due).strftime("%H:%M") if due else "",
            "интервал_мин": round(_flush_delay() / 60, 1)}


# ------------------------------------------------------------------ заказы
def _next_order_id(led: dict) -> int:
    ids = [int(o.get("id", 0)) for o in led.get("orders", [])]
    return (max(ids) + 1) if ids else 1


def available_for_order() -> dict:
    """Сколько можно заказать: остаток минус уже заказанное в открытых заказах."""
    stock = {i["наименование"]: i["остаток"] for i in stock_items()}
    reserved = defaultdict(float)
    for o in orders():
        if (o.get("статус") or "новый") != "новый":
            continue
        for pos in o.get("позиции", []):
            left = _num(pos.get("количество")) - _num(pos.get("отгружено"))
            if left > 0:
                reserved[_clean(pos.get("наименование"))] += left
    return {name: max(0.0, qty - reserved.get(name, 0.0)) for name, qty in stock.items()}


def create_order(client: str, items: list[dict], author: str = "", kind: str = "свой",
                 cabinet: str = "") -> dict:
    """kind: «свой» — от своего имени, «FBO» — от имени кабинета WB (client = «FBO · ККМ»)."""
    clean = []
    for it in items:
        name = _clean(it.get("наименование"))
        qty = _num(it.get("количество"))
        if name and qty > 0:
            clean.append({"наименование": name, "количество": qty, "отгружено": 0})
    if not clean:
        raise ValueError("Корзина пуста")

    free = available_for_order()
    for it in clean:
        name = it["наименование"]
        left = free.get(name, 0.0)
        if it["количество"] > left + 0.001:
            raise ValueError(f"{name}: доступно {left:g} шт (остаток минус уже заказанное)")
    with _LOCK:
        led = _ledger()
        oid = _next_order_id(led)
        led.setdefault("orders", []).append({
            "id": oid,
            "дата": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "клиент": client,
            "автор": author or client,
            "тип": kind,
            "кабинет": cabinet,
            "статус": "новый",
            "позиции": clean,
        })
        _save_ledger(led)
    flush_async()
    return {"id": oid, "позиций": len(clean)}


def orders(client: str | None = None, status: str | None = None,
           author: str | None = None) -> list[dict]:
    led = _ledger()
    rows = list(led.get("orders", []))
    if author:  # старые заказы без «автор» — по клиенту
        rows = [o for o in rows if (o.get("автор") or o.get("клиент")) == author]
    if client:
        rows = [o for o in rows if o.get("клиент") == client]
    if status:
        rows = [o for o in rows if o.get("статус") == status]
    return list(reversed(rows))


def cancel_order(order_id: int, who: str, reason: str = "") -> dict:
    """Отмена заказа. Заказ не удаляется — остаётся в архиве со статусом «отменён»."""
    with _LOCK:
        led = _ledger()
        for o in led.get("orders", []):
            if int(o.get("id", 0)) == int(order_id):
                if o.get("статус") == "собран":
                    raise ValueError("Заказ уже собран — отменить нельзя")
                o["статус"] = "отменён"
                o["отменил"] = who
                o["причина"] = reason
                o["закрыт"] = datetime.now().strftime("%d.%m.%Y %H:%M")
                _save_ledger(led)
                flush_async()
                return {"id": order_id, "статус": "отменён"}
    raise ValueError("Заказ не найден")


def close_order(order_id: int) -> dict:
    with _LOCK:
        led = _ledger()
        for o in led.get("orders", []):
            if int(o.get("id", 0)) == int(order_id):
                o["статус"] = "собран"
                _save_ledger(led)
                return {"id": order_id, "статус": "собран"}
    raise ValueError("Заказ не найден")


def pick_order(order_id: int, items: list[dict], who: str = "") -> dict:
    """Сборка нескольких позиций заказа за один заход (штрихкод → количество)."""
    results, ok, total = [], 0, 0.0
    for pos in items or []:
        name = _clean(pos.get("наименование"))
        qty = _num(pos.get("количество"))
        if not name or qty <= 0:
            continue
        try:
            res = order_ship(order_id, name, qty, who, _clean(pos.get("проверка")) or "Nice✅")
            results.append({"наименование": name, "ok": True, "остаток": res.get("остаток")})
            ok += 1
            total += qty
        except ValueError as exc:
            results.append({"наименование": name, "ok": False, "error": str(exc)})
    if not ok:
        errs = "; ".join(r["error"] for r in results if not r["ok"]) or "нечего отгружать"
        raise ValueError(errs)
    return {"принято": ok, "штук": total, "результаты": results}


def order_ship(order_id: int, name: str, qty: float, who: str = "",
               check: str = "Nice✅") -> dict:
    """Отгружает позицию заказа: пишет в паставка и уменьшает остаток."""
    led = _ledger()
    order = next((o for o in led.get("orders", []) if int(o.get("id", 0)) == int(order_id)), None)
    if not order:
        raise ValueError("Заказ не найден")
    item = None
    for pos in order.get("позиции", []):
        if pos.get("наименование") == name:
            item = pos
            break
    if not item:
        raise ValueError("Позиции нет в заказе")
    left = _num(item.get("количество")) - _num(item.get("отгружено"))
    if qty <= 0 or qty > left:
        raise ValueError(f"Осталось собрать {left:g} шт")
    # заказ сотрудника («свой») и FBO списываются без листа отгрузки; заказы ЖСК/ККМ/Алтын — как раньше
    res = ship(order.get("клиент"), name, qty, str(order_id), who, check,
               any_target=order.get("тип") in ("свой", "FBO"))
    with _LOCK:
        led2 = _ledger()
        for o in led2.get("orders", []):
            if int(o.get("id", 0)) == int(order_id):
                for pos in o.get("позиции", []):
                    if pos.get("наименование") == name:
                        pos["отгружено"] = _num(pos.get("отгружено")) + qty
                if all(_num(p.get("отгружено")) >= _num(p.get("количество")) for p in o.get("позиции", [])):
                    o["статус"] = "собран"
                    o["закрыт"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        _save_ledger(led2)
    flush_async()
    return res


# ------------------------------------------------------------------ синхронизация
def _version() -> str:
    try:
        st = source_path().stat()
        file_part = f"{int(st.st_mtime)}-{int(st.st_size)}"
    except OSError:
        file_part = "0-0"
    try:
        led_part = str(int(LEDGER.stat().st_mtime)) if LEDGER.exists() else "0"
    except OSError:
        led_part = "0"
    return f"{file_part}-{led_part}"


def snapshot() -> dict:
    """Полный снимок склада для офлайн-работы на телефоне."""
    items = stock_items()
    data = load_master()
    open_orders = [o for o in orders() if (o.get("статус") or "новый") == "новый"]
    return {
        "version": _version(),
        "at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "items": [{
            "наименование": i["наименование"], "категория": i["категория"],
            "модель": i["модель"], "цвет": i["цвет"], "размер": i["размер"],
            "остаток": i["остаток"], "ожидает": i["ожидает"], "адрес": i["адрес"],
        } for i in items],
        "addresses": data["addresses"][:600],
        "suppliers": data["suppliers"],
        "orders": open_orders,
        "totals": {"позиций": len(items),
                   "штук": round(sum(i["остаток"] for i in items), 2),
                   "ожидает": round(sum(i["ожидает"] for i in items), 2)},
    }


def apply_ops(ops: list, who: str, base_version: str = "") -> dict:
    """Применяет пачку офлайн-операций. Каждая операция идемпотентна по uuid."""
    if not isinstance(ops, list):
        raise ValueError("ops должен быть списком")
    results = []
    applied_count = 0
    with _LOCK:
        led = _ledger()
        applied = led.setdefault("applied", [])

    for op in ops:
        uid = _clean(op.get("uuid"))
        kind = _clean(op.get("type"))
        payload = op.get("payload") or {}
        if not uid:
            results.append({"uuid": "", "ok": False, "error": "нет uuid операции"})
            continue
        if uid in applied:
            results.append({"uuid": uid, "ok": True, "дубль": True})
            continue
        try:
            if kind == "приход":
                res = receive_multi(_clean(payload.get("поставщик")),
                                    _clean(payload.get("партия")), 0,
                                    payload.get("позиции") or [])
            elif kind == "адрес":
                res = place(_clean(payload.get("коробка")),
                            _clean(payload.get("наименование")),
                            _num(payload.get("количество")))
            elif kind == "отгрузка":
                res = ship(_clean(payload.get("получатель")),
                           _clean(payload.get("наименование")),
                           _num(payload.get("количество")),
                           _clean(payload.get("заказ")), who)
            elif kind == "отгрузка_заказа":
                res = order_ship(int(_num(payload.get("id"))),
                                 _clean(payload.get("наименование")),
                                 _num(payload.get("количество")), who)
            elif kind == "отмена_заказа":
                res = cancel_order(int(_num(payload.get("id"))), who,
                                   _clean(payload.get("причина")))
            else:
                raise ValueError(f"неизвестный тип операции: {kind}")
        except ValueError as exc:
            results.append({"uuid": uid, "ok": False, "error": str(exc), "type": kind})
            continue
        except Exception as exc:  # noqa: BLE001
            results.append({"uuid": uid, "ok": False, "error": f"сбой: {exc}", "type": kind})
            continue

        with _LOCK:
            led = _ledger()
            # не обрезаем: иначе старая офлайн-очередь с телефона применится повторно
            led.setdefault("applied", []).append(uid)
            _save_ledger(led)
        applied_count += 1
        results.append({"uuid": uid, "ok": True, "type": kind, "результат": res})

    flush_async()
    rejected = [r for r in results if not r["ok"]]
    return {
        "результаты": results,
        "принято": applied_count,
        "отклонено": len(rejected),
        "версия": _version(),
        "base_version": base_version,
    }


# ------------------------------------------------------------------ сотрудники и настройки
def staff_rows(force: bool = False) -> list[dict]:
    """Пользователи из листа «сотрудники» рабочей книги (он — источник учёток)."""
    if force:
        _SMALL.pop("staff", None)
    return [dict(r) for r in _cached_by_file("staff", _read_staff_rows)]


def _read_staff_rows() -> list[dict]:
    try:
        p = source_path()
        wb = load_workbook(p, data_only=True, read_only=True)
        try:
            if "сотрудники" not in wb.sheetnames:
                return []
            ws = wb["сотрудники"]
            out = []
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            head = [str(c or "").strip().lower() for c in rows[0]]
            idx = {h: i for i, h in enumerate(head)}
            def val(r, *names, default=""):
                for n in names:
                    i = idx.get(n)
                    if i is not None and i < len(r) and r[i] not in (None, ""):
                        return str(r[i]).strip()
                return default
            for r in rows[1:]:
                if not r:
                    continue
                login = val(r, "логин", "login")
                if not login:
                    continue
                out.append({
                    "логин": login,
                    "пароль": val(r, "пароль", "password"),
                    "фио": val(r, "фио", "имя"),
                    "роль": val(r, "роль", "role"),
                    "цех": val(r, "цех", "workshop"),
                    "ставка_час": _num(val(r, "ставка за час", "ставка")),
                    "активен": 0 if val(r, "активен", "active").lower() in ("нет", "0", "false") else 1,
                })
            return out
        finally:
            wb.close()
    except Exception:
        return []


def ensure_settings_sheet(wb) -> None:
    """Создаёт лист «настройки», если его нет (название цеха, логотип)."""
    if "настройки" in wb.sheetnames:
        return
    ws = wb.create_sheet("настройки")
    rows = [
        ("параметр", "значение"),
        ("название", "Швейный цех"),
        ("подзаголовок", "Швейный цех №1"),
        ("логотип", ""),
    ]
    for r in rows:
        ws.append(list(r))
    for i, width in enumerate((22, 42), start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def brand() -> dict:
    """Название и логотип из листа «настройки»."""
    return dict(_cached_by_file("brand", _read_brand))


def _read_brand() -> dict:
    out = {"название": "Швейный цех", "подзаголовок": "", "логотип": ""}
    try:
        p = source_path()
        wb = load_workbook(p, data_only=True, read_only=True)
        try:
            if "настройки" not in wb.sheetnames:
                return out
            for r in list(wb["настройки"].iter_rows(values_only=True))[1:]:
                if not r or len(r) < 2:
                    continue
                key = _clean(r[0]).lower()
                value = _clean(r[1])
                if key in ("название", "подзаголовок", "логотип") and value:
                    out[key] = value
        finally:
            wb.close()
    except Exception:
        pass
    return out


def save_brand(data: dict) -> dict:
    """Записывает «настройки» в рабочую книгу (с резервной копией)."""
    with BOOK_LOCK:
        return _save_brand(data)


def _save_brand(data: dict) -> dict:
    p = source_path()
    _backup(p)
    wb = load_workbook(p, keep_vba=True)
    try:
        ensure_settings_sheet(wb)
        ws = wb["настройки"]
        wanted = {k: _safe(v) for k, v in data.items() if k in ("название", "подзаголовок", "логотип")}
        for row in range(2, ws.max_row + 1):
            key = _clean(ws.cell(row=row, column=1).value).lower()
            if key in wanted:
                ws.cell(row=row, column=2, value=wanted.pop(key))
        for key, value in wanted.items():
            ws.append([key, value])
        _save_atomic(wb, p)
    finally:
        wb.close()
    _CACHE["sig"] = None
    _SMALL.clear()
    return brand()


def negatives() -> list[dict]:
    """Позиции, где отгружено больше, чем размещено (остаток минус)."""
    out = []
    for i in stock_items():
        if i["остаток"] < -0.001:
            out.append({
                "наименование": i["наименование"],
                "остаток": i["остаток"],
                "пересорт": round(-i["остаток"], 2),
                "размещено": i.get("размещено", 0),
            })
    out.sort(key=lambda x: -x["пересорт"])
    return out


def add_products(category: str, model: str, colors: list[str], sizes: list[str]) -> int:
    """Завести позиции склада «Категория/модель/цвет/размер» в PostgreSQL. Возвращает, сколько новых."""
    import sys
    if str(BASE / "sql") not in sys.path:
        sys.path.insert(0, str(BASE / "sql"))
    import db as sqldb  # noqa: WPS433
    import hashlib
    con = sqldb.connect()
    added = 0
    try:
        for color in colors:
            for size in sizes:
                name = f"{category}/{model}/{color}/{size}"
                pid = hashlib.sha1(("product|" + name).encode()).hexdigest()[:20]
                cur = con.execute(
                    """INSERT INTO products(id, name, category, model, color, size, source_sheet, created_at)
                       VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                    (pid, name, category, model, color, str(size), "цех", sqldb.now()))
                added += max(getattr(cur, "rowcount", 0) or 0, 0)  # соединение в autocommit
    finally:
        con.close()
    try:
        import fbs_stock
        fbs_stock._FACT["ts"] = 0.0  # остатки перечитаются — новые позиции сразу видны в «Приходе»
    except Exception:  # noqa: BLE001
        pass
    return added


# ---------- Принятое: приёмки через портал (PostgreSQL, source='shadow') ----------
# shortcut: история из книги (source='excel') не показывается — там задвоенные строки; показать после переимпорта
ALL_SUPPLIERS = "*"


def _receipt_rows(day: str = "") -> list:
    import sys
    if str(BASE / "sql") not in sys.path:
        sys.path.insert(0, str(BASE / "sql"))
    import db as sqldb  # noqa: WPS433
    con = sqldb.connect()
    try:
        sql = """SELECT pu.ts, pu.supplier, pu.batch, pu.qty, p.name
                 FROM purchases pu LEFT JOIN products p ON p.id = pu.product_id
                 WHERE pu.source = 'shadow'"""
        args: tuple = ()
        if day:
            sql += " AND pu.ts LIKE ?"
            args = (day + "%",)
        return con.execute(sql + " ORDER BY pu.ts", args).fetchall()
    finally:
        con.close()


def receipts() -> list[dict]:
    """Приёмки по партиям (партия за несколько дней — одна строка), свежие сверху."""
    out: dict[tuple[str, str], dict] = {}
    for r in _receipt_rows():  # строки идут по времени — последняя дата в конце списка
        key = (str(r["supplier"] or ""), str(r["batch"] or ""))
        g = out.setdefault(key, {"поставщик": key[0], "партия": key[1], "даты": [], "штук": 0.0})
        g["штук"] += float(r["qty"] or 0)
        day = str(r["ts"])[:10]
        if day not in g["даты"]:
            g["даты"].append(day)
    return sorted(out.values(), key=lambda g: (g["даты"][-1], g["партия"]), reverse=True)


def receipt_lines(day: str = "", supplier: str = ALL_SUPPLIERS, batch: str = ALL_SUPPLIERS) -> list[dict]:
    return [{"время": str(r["ts"])[:16], "поставщик": r["supplier"] or "", "партия": r["batch"] or "",
             "товар": r["name"] or "", "кол-во": float(r["qty"] or 0)}
            for r in _receipt_rows(day)
            if (supplier == ALL_SUPPLIERS or (r["supplier"] or "") == supplier)
            and (batch == ALL_SUPPLIERS or (r["batch"] or "") == batch)]


def receipt_xlsx(day: str = "", supplier: str = ALL_SUPPLIERS, batch: str = ALL_SUPPLIERS) -> bytes:
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    lines = receipt_lines(day, supplier, batch)
    if not lines:
        raise ValueError("приёмок не найдено")
    wb = Workbook()
    ws = wb.active
    ws.title = "Принято"
    ws.append([f"Принято на склад{' ' + day if day else ''} · {'все поставщики' if supplier == ALL_SUPPLIERS else supplier or 'без поставщика'}"
               f"{'' if batch == ALL_SUPPLIERS else ' · партия ' + (batch or '—')}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Время", "Поставщик", "Партия", "Товар", "Кол-во"])
    for x in lines:
        ws.append([x["время"], x["поставщик"], x["партия"], x["товар"], x["кол-во"]])
    ws.append(["Итого", "", "", "", sum(x["кол-во"] for x in lines)])
    for c in ws[2] + ws[ws.max_row]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDE", (17, 20, 10, 34, 8)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def full_xlsx() -> bytes:
    """Весь склад одной книгой: остатки + приход, размещение и отгрузки из PostgreSQL."""
    import io
    import sys
    from openpyxl import Workbook
    from openpyxl.styles import Font
    if str(BASE / "sql") not in sys.path:
        sys.path.insert(0, str(BASE / "sql"))
    import db as sqldb  # noqa: WPS433
    wb = Workbook()

    def sheet(title, headers, rows, widths):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append(list(r))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w

    items = stock_items()
    sheet("Остатки", ["Наименование", "Категория", "Модель", "Цвет", "Размер", "Остаток", "Ждёт размещения",
                      "Приход", "Отгружено", "из них FBS", "Адрес"],
          ([i["наименование"], i["категория"], i["модель"], i["цвет"], i["размер"], i["остаток"], i["ожидает"],
            i["приход"], i["отгружено"], i["фbs"], i["адрес"]] for i in items),
          (34, 14, 10, 20, 8, 10, 12, 10, 10, 10, 16))
    con = sqldb.connect()
    try:
        q = lambda sql: con.execute(sql).fetchall()
        sheet("Приход", ["Дата", "Поставщик", "Партия", "Наименование", "Кол-во", "Неликвид", "Откуда"],
              ([r["ts"], r["supplier"], r["batch"], r["name"], r["qty"], r["defect"],
                "портал" if r["source"] == "shadow" else "книга Excel"] for r in q(
                  """SELECT pu.ts, pu.supplier, pu.batch, p.name, pu.qty, pu.defect, pu.source
                     FROM purchases pu LEFT JOIN products p ON p.id = pu.product_id ORDER BY pu.ts""")),
              (19, 18, 8, 34, 8, 9, 12))
        sheet("Размещение", ["Дата", "Коробка", "Наименование", "Кол-во"],
              ([r["ts"], r["location_code"], r["name"], r["qty"]] for r in q(
                  """SELECT pl.ts, pl.location_code, p.name, pl.qty
                     FROM placements pl LEFT JOIN products p ON p.id = pl.product_id ORDER BY pl.ts""")),
              (19, 14, 34, 8))
        sheet("Отгрузки", ["Дата", "Получатель", "Наименование", "Кол-во", "Кто", "Откуда"],
              ([r["ts"], r["target"], r["name"], r["qty"], r["user"], r["source_sheet"]] for r in q(
                  """SELECT s.ts, s.target, p.name, s.qty, s.user, s.source_sheet
                     FROM shipments s LEFT JOIN products p ON p.id = s.product_id ORDER BY s.ts""")),
              (19, 14, 34, 8, 14, 18))
    finally:
        con.close()
    wb.remove(wb.active)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
