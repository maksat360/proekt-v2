# -*- coding: utf-8 -*-
"""
Мост к рабочей книге цеха (цех_склад для apk.xlsm).

Чтение — только нужного листа, без загрузки всей книги.
Запись — замена XML одного листа внутри архива: остальные части книги
(VBA, формулы, оформление, склад) остаются байт в байт.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
BACKUP_DIR = BASE / "backups" / "cex"
SRC_FILE = DATA / "цех_источник.txt"
STATE_FILE = DATA / "cex_state.json"
DEFAULT_SRC = Path("/Users/temp/швейный цех приложение/цех_склад для apk.xlsm")

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SHEET_CT = ("application/vnd.openxmlformats-officedocument."
            "spreadsheetml.worksheet+xml")

LOCK = threading.RLock()
# Один писатель рабочей книги на весь процесс: цех (здесь) и склад (warehouse.py) пишут
# один и тот же файл. Без общей блокировки выгрузка склада (≈15 с: открыть → сохранить)
# затирала записи цеха, а одновременная запись портила zip книги.
BOOK_LOCK = threading.RLock()
_CACHE: dict[tuple, list] = {}
_CACHE_MAX = 8


class CexLocked(RuntimeError):
    """Файл открыт в Excel."""


class CexSourceError(RuntimeError):
    pass


# ------------------------------------------------------------------ пути
def source_path() -> Path:
    if SRC_FILE.exists():
        raw = SRC_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return Path(raw).expanduser()
    return DEFAULT_SRC


def set_source(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise CexSourceError(f"файл не найден: {p}")
    SRC_FILE.parent.mkdir(parents=True, exist_ok=True)
    SRC_FILE.write_text(str(p), encoding="utf-8")
    return p


def _state() -> dict:
    try:
        return dict(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _save_state(data: dict) -> None:
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------ служебное
def _col_letter(idx: int) -> str:
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _col_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n


def _num_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value) if isinstance(value, float) else str(value)


def _bytes(xml) -> bytes:
    return etree.tostring(xml, xml_declaration=True, encoding="UTF-8", standalone=True)


# --------------------------------------------------------------- чтение
def _sheet_map(zf: zipfile.ZipFile) -> dict[str, str]:
    wb = etree.fromstring(zf.read("xl/workbook.xml"))
    rels = etree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {}
    for rel in rels:
        t = rel.get("Target") or ""
        if t.startswith("/"):
            t = t[1:]
        elif not t.startswith("xl/"):
            t = "xl/" + t
        targets[rel.get("Id")] = t
    out = {}
    sheets = wb.find(f"{{{NS}}}sheets")
    if sheets is None:
        return out
    for s in sheets:
        rid = s.get(f"{{{RNS}}}id")
        if rid in targets:
            out[s.get("name")] = targets[rid]
    return out


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = etree.fromstring(raw)
    out = []
    for si in root:
        out.append("".join(t.text or "" for t in si.iter(f"{{{NS}}}t")))
    return out


def _cells_to_values(sheet_xml: bytes, shared: list[str]) -> list[dict[int, object]]:
    root = etree.fromstring(sheet_xml)
    data = root.find(f"{{{NS}}}sheetData")
    rows: list[dict[int, object]] = []
    if data is None:
        return rows
    for row in data:
        if row.tag != f"{{{NS}}}row":
            continue
        cells: dict[int, object] = {}
        for c in row:
            if c.tag != f"{{{NS}}}c":
                continue
            ref = c.get("r") or ""
            col = _col_index(ref)
            t = c.get("t")
            value = None
            if t == "inlineStr":
                node = c.find(f"{{{NS}}}is")
                if node is not None:
                    value = "".join(x.text or "" for x in node.iter(f"{{{NS}}}t"))
            elif t == "s":
                v = c.find(f"{{{NS}}}v")
                if v is not None and (v.text or "").isdigit():
                    idx = int(v.text)
                    if idx < len(shared):
                        value = shared[idx]
            elif t in ("str", "e"):
                v = c.find(f"{{{NS}}}v")
                value = v.text if v is not None else None
            elif t == "b":
                v = c.find(f"{{{NS}}}v")
                value = (v is not None and v.text == "1")
            else:
                v = c.find(f"{{{NS}}}v")
                if v is not None and v.text not in (None, ""):
                    raw = v.text
                    try:
                        num = float(raw)
                        value = int(num) if num.is_integer() else num
                    except ValueError:
                        value = raw
            if value not in (None, ""):
                cells[col] = value
        if cells:
            rows.append(cells)
        else:
            rows.append({})
    return rows


def read_sheet(name: str) -> list[dict]:
    """Лист как список словарей по шапке первой строки."""
    path = source_path()
    if not path.is_file():
        raise CexSourceError(f"нет файла: {path}")
    st = path.stat()
    key = (str(path), name, st.st_mtime_ns, st.st_size)
    with LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return [dict(r) for r in cached]
    with zipfile.ZipFile(path) as zf:
        smap = _sheet_map(zf)
        target = smap.get(name)
        if not target:
            return []
        rows = _cells_to_values(zf.read(target), _shared_strings(zf))
    if not rows:
        return []
    # шапка: первая строка целиком по максимальному номеру колонки
    first = rows[0]
    width = max(first) if first else 0
    header = [str(first.get(i, "") or f"col{i}") for i in range(1, width + 1)]
    out = []
    for raw in rows[1:]:
        if not raw or all(v in (None, "") for v in raw.values()):
            continue
        out.append({header[i - 1]: raw.get(i, "") for i in range(1, width + 1)})
    with LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = out
    return [dict(r) for r in out]


def first_row(name: str) -> list:
    """Первая строка листа как список значений по колонкам (шапка)."""
    path = source_path()
    with zipfile.ZipFile(path) as zf:
        target = _sheet_map(zf).get(name)
        if not target:
            return []
        rows = _cells_to_values(zf.read(target), _shared_strings(zf))
    if not rows:
        return []
    first = rows[0]
    width = max(first) if first else 0
    return [first.get(i, "") for i in range(1, width + 1)]


def sheet_names() -> list[str]:
    with zipfile.ZipFile(source_path()) as zf:
        return list(_sheet_map(zf))


# -------------------------------------------------------- защита файла
def _lock_file(path: Path) -> Path:
    return path.parent / ("~$" + path.name)


STALE_LOCK_HOURS = 12


def _lock_active(path: Path) -> bool:
    """Замок «~$книга» есть и свежий. Старый замок — след аварийно закрытого Excel."""
    lock = _lock_file(path)
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return False
    return age < STALE_LOCK_HOURS * 3600


def guard(path: Path) -> None:
    if _lock_active(path):
        raise CexLocked(
            "Файл открыт в Excel. Закройте книгу и повторите — иначе правки потеряются.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    last = None
    for f in BACKUP_DIR.glob("*.xlsm"):
        if last is None or f.stat().st_mtime > last.stat().st_mtime:
            last = f
    if last is None or time.time() - last.stat().st_mtime > 600:
        dst = BACKUP_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsm"
        shutil.copy2(path, dst)
        backups = sorted(BACKUP_DIR.glob("*.xlsm"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-12]:
            try:
                old.unlink()
            except OSError:
                pass


def _rewrite(path: Path, replace: dict[str, bytes], add: dict[str, bytes] | None = None) -> None:
    tmp = path.with_name(path.stem + ".cex.tmp" + path.suffix)  # своё имя: у склада другое
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, replace.get(item.filename, zin.read(item.filename)))
        for name, data in (add or {}).items():
            zout.writestr(name, data)
    with zipfile.ZipFile(tmp) as z:
        bad = z.testzip()
        if bad:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"книга повреждена при записи: {bad}")
        for name in ("xl/workbook.xml", "[Content_Types].xml"):
            etree.fromstring(z.read(name))
        for name in list(replace) + list((add or {})):
            if name.endswith(".xml"):
                etree.fromstring(z.read(name))
    os.replace(tmp, path)


# --------------------------------------------------------------- запись
def _row_xml(r: int, values: list, style: str | None = None) -> str:
    cells = []
    for ci, value in enumerate(values, start=1):
        if value is None or value == "":
            continue
        ref = f"{_col_letter(ci)}{r}"
        s = f' s="{style}"' if style else ""
        if isinstance(value, bool):
            cells.append(f'<c r="{ref}"{s} t="b"><v>{1 if value else 0}</v></c>')
        elif isinstance(value, (int, float)):
            cells.append(f'<c r="{ref}"{s}><v>{_num_text(value)}</v></c>')
        else:
            text = escape(str(value))
            cells.append(
                f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
    body = "".join(cells)
    return f'<row r="{r}">{body}</row>'


def _part_bytes(zf: zipfile.ZipFile, name: str, headers: list[str], rows) -> tuple[str, bytes]:
    smap = _sheet_map(zf)
    target = smap.get(name)
    if not target:
        raise KeyError(f"нет листа «{name}» — сначала создайте его")
    root = etree.fromstring(zf.read(target))
    data = root.find(f"{{{NS}}}sheetData")
    if data is None:
        data = etree.SubElement(root, f"{{{NS}}}sheetData")
    style = None
    for c in data.iter(f"{{{NS}}}c"):
        if c.get("s"):
            style = c.get("s")
            break
    if style is None:
        style = _state().get("header_style")
    for child in list(data):
        data.remove(child)
    n = 1
    data.append(etree.fromstring(_row_xml(n, headers, style)))
    for row in rows:
        n += 1
        values = [row.get(h, "") for h in headers] if isinstance(row, dict) else list(row)
        data.append(etree.fromstring(_row_xml(n, values)))
    dim = root.find(f"{{{NS}}}dimension")
    ref = f"A1:{_col_letter(max(1, len(headers)))}{n}"
    if dim is None:
        dim = etree.Element(f"{{{NS}}}dimension")
        root.insert(1, dim)
    dim.set("ref", ref)
    return target, _bytes(root)


def write_sheets(items: list[tuple]) -> None:
    """Записать несколько листов за один проход по архиву.

    items: [(имя листа, [колонки], [строки-словари]), ...]
    """
    path = source_path()
    if not path.is_file():
        raise CexSourceError(f"нет файла: {path}")
    with BOOK_LOCK, LOCK:
        guard(path)
        with zipfile.ZipFile(path) as zf:
            replace: dict[str, bytes] = {}
            for name, headers, rows in items:
                target, data = _part_bytes(zf, name, headers, rows)
                replace[target] = data
        _rewrite(path, replace)
        _CACHE.clear()


def write_sheet(name: str, headers: list[str], rows) -> None:
    """Полная замена содержимого одного листа (шапка + строки)."""
    write_sheets([(name, headers, rows)])


def append_rows(name: str, headers: list[str], rows: list[dict]) -> None:
    current = read_sheet(name)
    write_sheet(name, headers, current + rows)


# --------------------------------------------------------- создание листов
def _ensure_header_style(parts: dict[str, bytes]) -> int | None:
    root = etree.fromstring(parts["xl/styles.xml"])
    fonts = root.find(f"{{{NS}}}fonts")
    fills = root.find(f"{{{NS}}}fills")
    cellxfs = root.find(f"{{{NS}}}cellXfs")
    bold_id = None
    for i, f in enumerate(fonts):
        if f.find(f"{{{NS}}}b") is not None and (f.find(f"{{{NS}}}sz") is not None):
            sz = f.find(f"{{{NS}}}sz").get("val")
            if sz in ("11", "11.0"):
                bold_id = i
                break
    if bold_id is None:
        font = etree.SubElement(fonts, f"{{{NS}}}font")
        etree.SubElement(font, f"{{{NS}}}sz").set("val", "11")
        etree.SubElement(font, f"{{{NS}}}b")
        etree.SubElement(font, f"{{{NS}}}name").set("val", "Aptos Narrow")
        bold_id = len(fonts) - 1
        fonts.set("count", str(len(fonts)))
    fill_id = None
    for i, f in enumerate(fills):
        pf = f.find(f"{{{NS}}}patternFill")
        if pf is not None and pf.get("patternType") == "solid":
            fg = pf.find(f"{{{NS}}}fgColor")
            if fg is not None and (fg.get("rgb") or "").upper() == "FFF2F4F7":
                fill_id = i
                break
    if fill_id is None:
        fill = etree.SubElement(fills, f"{{{NS}}}fill")
        pf = etree.SubElement(fill, f"{{{NS}}}patternFill")
        pf.set("patternType", "solid")
        etree.SubElement(pf, f"{{{NS}}}fgColor").set("rgb", "FFF2F4F7")
        etree.SubElement(pf, f"{{{NS}}}bgColor").set("indexed", "64")
        fill_id = len(fills) - 1
        fills.set("count", str(len(fills)))
    xf = etree.SubElement(cellxfs, f"{{{NS}}}xf")
    xf.set("numFmtId", "0")
    xf.set("fontId", str(bold_id))
    xf.set("fillId", str(fill_id))
    xf.set("borderId", "0")
    xf.set("xfId", "0")
    xf.set("applyFont", "1")
    xf.set("applyFill", "1")
    idx = len(cellxfs) - 1
    cellxfs.set("count", str(len(cellxfs)))
    parts["xl/styles.xml"] = _bytes(root)
    return idx


def _new_sheet_xml(headers: list[str], widths: list[float], style: str | None) -> bytes:
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths, start=1)
    )
    header = _row_xml(1, headers, style)
    last = f"{_col_letter(max(1, len(headers)))}1"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{NS}" xmlns:r="{RNS}">'
        f'<dimension ref="A1:{last}"/><sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="16"/>'
        f'<cols>{cols}</cols><sheetData>{header}</sheetData></worksheet>'
    ).encode("utf-8")


def ensure_sheets(specs: list[tuple]) -> list[str]:
    """Создать отсутствующие листы одним проходом.

    specs: [(имя, [колонки], [ширины]), ...]. Возвращает список созданных.
    """
    path = source_path()
    if not path.is_file():
        raise CexSourceError(f"нет файла: {path}")
    with BOOK_LOCK, LOCK:
        with zipfile.ZipFile(path) as zf:
            names = set(_sheet_map(zf))
            lower = {n.lower(): n for n in names}
            existing = set(zf.namelist())
            missing = []
            for sp in specs:
                if sp[0] in names:
                    continue
                if sp[0].lower() in lower:
                    continue  # лист уже есть под другим регистром — не дублируем
                missing.append(sp)
            if not missing:
                return []
            parts = {
                "xl/workbook.xml": zf.read("xl/workbook.xml"),
                "xl/_rels/workbook.xml.rels": zf.read("xl/_rels/workbook.xml.rels"),
                "[Content_Types].xml": zf.read("[Content_Types].xml"),
                "xl/styles.xml": zf.read("xl/styles.xml"),
            }
        guard(path)
        style_idx = _ensure_header_style(parts)
        style = str(style_idx) if style_idx is not None else None

        used_sheets = [int(n.split("sheet")[-1].split(".")[0]) for n in existing
                       if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
        num = max(used_sheets or [0])
        rels_xml = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
        used_rids = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels_xml)]
        rid = max(used_rids or [0])
        wb_xml = parts["xl/workbook.xml"].decode("utf-8")
        ct_xml = parts["[Content_Types].xml"].decode("utf-8")
        additions: dict[str, bytes] = {}
        created = []
        for name, headers, widths in missing:
            num += 1
            rid += 1
            wb_xml = wb_xml.replace(
                "</sheets>",
                f'<sheet xmlns:r="{RNS}" name="{escape(name)}" sheetId="{num}" state="visible"'
                f' r:id="rId{rid}"/></sheets>',
                1,
            )
            rels_xml = rels_xml.replace(
                "</Relationships>",
                '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/'
                f'2006/relationships/worksheet" Target="/xl/worksheets/sheet{num}.xml"'
                f' Id="rId{rid}"/></Relationships>',
                1,
            )
            ct_xml = ct_xml.replace(
                "</Types>",
                f'<Override PartName="/xl/worksheets/sheet{num}.xml"'
                f' ContentType="{SHEET_CT}"/></Types>',
                1,
            )
            additions[f"xl/worksheets/sheet{num}.xml"] = _new_sheet_xml(headers, widths, style)
            created.append(name)

        replace = {
            "xl/workbook.xml": wb_xml.encode("utf-8"),
            "xl/_rels/workbook.xml.rels": rels_xml.encode("utf-8"),
            "[Content_Types].xml": ct_xml.encode("utf-8"),
            "xl/styles.xml": parts["xl/styles.xml"],
        }
        _rewrite(path, replace, additions)
        state = _state()
        state["header_style"] = style or ""
        _save_state(state)
        _CACHE.clear()
        return created


def ensure_sheet(name: str, headers: list[str], widths: list[float]) -> bool:
    """Создать лист, если его нет. True — создали."""
    return bool(ensure_sheets([(name, headers, widths)]))
