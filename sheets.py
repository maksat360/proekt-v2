# -*- coding: utf-8 -*-
"""Листы в базе вместо Excel-файлов.

Книга «цех» — бывшая рабочая книга цех_склад для apk.xlsm (листы цеха и справочники склада).
Книга «data» — бывшие таблицы data/*.xlsx (пользователи, товары магазина, продажи…), лист = таблица.

Лист хранится как список заполненных строк [номер строки, {номер колонки: значение}],
поэтому чтение «по колонкам и строкам» работает так же, как с файлом.
Excel остаётся только для выгрузок (to_xlsx)."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402

if sqldb._testing():  # тесты не трогают ни рабочую базу, ни data/
    DATA = Path(tempfile.mkdtemp(prefix="v2-sheets-"))

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SKIP_SHEETS = {"номера"}  # shortcut: служебная нумерация на 1 млн строк, код её не читает

_LOCK = threading.RLock()
_READY: set = set()
_CACHE: dict = {}  # (база, книга, лист) → (updated_at, строки)


_LOCAL = threading.local()


class _Shared:
    """Одно подключение к PostgreSQL на поток: страница цеха читает листы сотни раз,
    а новое подключение стоит ~2 мс. close() ничего не закрывает."""

    def __init__(self, con):
        self._c = con

    def execute(self, sql, params=()):
        return self._c.execute(sql, params)

    def close(self) -> None:
        pass


def _pg():
    con = getattr(_LOCAL, "pg", None)
    now = time.monotonic()
    if con is not None:
        try:
            if now - getattr(_LOCAL, "used", 0) > 30:  # долго молчало — проверим, живо ли
                con.execute("SELECT 1")
            _LOCAL.used = now
            return con
        except Exception:  # noqa: BLE001 — оборвалось (перезапуск базы) — подключаемся заново
            try:
                con._c.close()
            except Exception:  # noqa: BLE001
                pass
    _LOCAL.pg, _LOCAL.used = _Shared(sqldb.connect()), now
    return _LOCAL.pg


def _con(where: Path | None = None):
    """Рабочая база; в тестах (без PostgreSQL) — sqlite-файл рядом с данными теста."""
    if sqldb.use_pg():
        con, key = _pg(), "pg"
    else:
        where = Path(where or DATA)
        if sqldb._testing() and where == BASE / "data":
            where = DATA
        path = where / "sheets.sqlite"
        con, key = sqldb.connect(path), str(path)
    if key not in _READY:  # sqlite-файл теста может быть пересоздан — для него проверяем всегда
        con.execute("""CREATE TABLE IF NOT EXISTS sheets (
            book TEXT NOT NULL, name TEXT NOT NULL, pos INTEGER NOT NULL DEFAULT 0,
            rows TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (book, name))""")
        if key == "pg":
            _READY.add(key)
    return con, key


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _value(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, (int, float, bool, str)) or v is None:
        return v
    return str(v)  # дата и прочее — текстом


def _encode(rows) -> str:
    out = []
    for r, cells in rows:
        cells = {str(c): _value(v) for c, v in cells.items() if v not in (None, "")}
        if cells:
            out.append([r, cells])
    return json.dumps(out, ensure_ascii=False)


def _decode(raw: str) -> list[tuple[int, dict[int, object]]]:
    return [(r, {int(c): v for c, v in cells.items()}) for r, cells in json.loads(raw)]


# ------------------------------------------------------------------ чтение
def names(book: str, where: Path | None = None) -> list[str]:
    con, _ = _con(where)
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sheets WHERE book=? ORDER BY pos, name", (book,)).fetchall()]
    finally:
        con.close()


def version(book: str, where: Path | None = None) -> str:
    """Меняется при любой записи в книгу — для кэшей."""
    con, _ = _con(where)
    try:
        row = con.execute("SELECT MAX(updated_at), COUNT(*) FROM sheets WHERE book=?", (book,)).fetchone()
        return f"{row[0] or ''}|{row[1]}"
    finally:
        con.close()


def rows(book: str, name: str, where: Path | None = None) -> list[tuple[int, dict]] | None:
    """Заполненные строки листа: [(номер строки, {колонка: значение})]; None — листа нет."""
    con, key = _con(where)
    try:
        hit = con.execute("SELECT updated_at FROM sheets WHERE book=? AND name=?", (book, name)).fetchone()
        if not hit:
            return None
        ck = (key, book, name)
        cached = _CACHE.get(ck)
        if cached and cached[0] == hit[0]:
            return cached[1]
        raw = con.execute("SELECT rows FROM sheets WHERE book=? AND name=?", (book, name)).fetchone()[0]
    finally:
        con.close()
    data = _decode(raw)
    _CACHE[ck] = (hit[0], data)
    return data


def grid(book: str, name: str, where: Path | None = None) -> list[tuple]:
    """Лист как в openpyxl iter_rows(values_only=True): строки с 1-й, пустые — None."""
    data = rows(book, name, where) or []
    if not data:
        return []
    width = max(max(c) for _, c in data)
    out = [(None,) * width for _ in range(data[-1][0])]
    for r, cells in data:
        out[r - 1] = tuple(cells.get(c) for c in range(1, width + 1))
    return out


class _Sheet:
    def __init__(self, book, name, where):
        self._g = grid(book, name, where)
        self.max_row = len(self._g)

    def iter_rows(self, min_row: int = 1, values_only: bool = True):
        return iter(self._g[min_row - 1:])


class View:
    """Только чтение, интерфейс как у openpyxl load_workbook(read_only=True)."""

    def __init__(self, book: str, where: Path | None = None):
        self.book, self.where = book, where
        self.sheetnames = names(book, where)

    def __getitem__(self, name: str) -> _Sheet:
        if name not in self.sheetnames:
            raise KeyError(name)
        return _Sheet(self.book, name, self.where)

    def close(self) -> None:
        pass


# ------------------------------------------------------------------ запись
def put(book: str, name: str, data, where: Path | None = None) -> None:
    """Заменить лист целиком; data — [(номер строки, {колонка: значение})]."""
    raw = _encode(data)
    con, key = _con(where)
    try:
        with _LOCK:
            have = con.execute("SELECT rows FROM sheets WHERE book=? AND name=?", (book, name)).fetchone()
            if have and have[0] == raw:
                return
            stamp = _now()
            if have:
                con.execute("UPDATE sheets SET rows=?, updated_at=? WHERE book=? AND name=?",
                            (raw, stamp, book, name))
            else:
                pos = con.execute("SELECT COALESCE(MAX(pos), 0) + 1 FROM sheets WHERE book=?", (book,)).fetchone()[0]
                con.execute("INSERT INTO sheets(book, name, pos, rows, updated_at) VALUES (?,?,?,?,?)",
                            (book, name, pos, raw, stamp))
            _CACHE[(key, book, name)] = (stamp, _decode(raw))
    finally:
        con.close()


def put_table(book: str, name: str, headers: list, values, where: Path | None = None) -> None:
    """Шапка в 1-й строке, дальше строки (словари по шапке или списки)."""
    data = [(1, dict(enumerate(headers, start=1)))]
    for i, row in enumerate(values, start=2):
        vals = [row.get(h, "") for h in headers] if isinstance(row, dict) else list(row)
        data.append((i, dict(enumerate(vals, start=1))))
    put(book, name, data, where)


def workbook(book: str, where: Path | None = None):
    """Книга целиком как openpyxl.Workbook — для старого кода, который правит ячейки."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name in names(book, where):
        ws = wb.create_sheet(name)
        for r, cells in rows(book, name, where) or []:
            for c, v in cells.items():
                ws.cell(row=r, column=c, value=v)
    return wb


def save(book: str, wb, where: Path | None = None) -> None:
    """Записать изменённые листы openpyxl-книги обратно в базу."""
    for ws in wb.worksheets:
        data = [(r, dict(enumerate(vals, start=1)))
                for r, vals in enumerate(ws.iter_rows(values_only=True), start=1)]
        put(book, ws.title, data, where)


def to_xlsx(book: str, where: Path | None = None) -> bytes:
    buf = io.BytesIO()
    wb = workbook(book, where)
    if not wb.worksheets:
        wb.create_sheet("пусто")
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ перенос из файлов
def _xlsx_sheets(path: Path):
    """Листы файла .xlsx/.xlsm как есть (значения формул — последние посчитанные Excel)."""
    from lxml import etree

    def col(ref: str) -> int:
        n = 0
        for ch in ref:
            if ch.isalpha():
                n = n * 26 + (ord(ch.upper()) - 64)
        return n

    with zipfile.ZipFile(path) as zf:
        wbx = etree.fromstring(zf.read("xl/workbook.xml"))
        rels = {}
        for rel in etree.fromstring(zf.read("xl/_rels/workbook.xml.rels")):
            t = rel.get("Target") or ""
            rels[rel.get("Id")] = t[1:] if t.startswith("/") else (t if t.startswith("xl/") else "xl/" + t)
        try:
            shared = ["".join(t.text or "" for t in si.iter(f"{{{NS}}}t"))
                      for si in etree.fromstring(zf.read("xl/sharedStrings.xml"))]
        except KeyError:
            shared = []
        for s in wbx.find(f"{{{NS}}}sheets"):
            name, target = s.get("name"), rels.get(s.get(f"{{{RNS}}}id"))
            if not target or name in SKIP_SHEETS:
                continue
            out = []
            data = etree.fromstring(zf.read(target)).find(f"{{{NS}}}sheetData")
            for i, row in enumerate(data if data is not None else [], start=1):
                r = int(row.get("r") or i)
                cells = {}
                for c in row.iter(f"{{{NS}}}c"):
                    t, v = c.get("t"), c.find(f"{{{NS}}}v")
                    if t == "inlineStr":
                        value = "".join(x.text or "" for x in c.iter(f"{{{NS}}}t"))
                    elif v is None or v.text in (None, ""):
                        continue
                    elif t == "s":
                        value = shared[int(v.text)] if v.text.isdigit() and int(v.text) < len(shared) else None
                    elif t in ("str", "e"):
                        value = v.text
                    elif t == "b":
                        value = v.text == "1"
                    else:
                        try:
                            num = float(v.text)
                            value = int(num) if num.is_integer() else num
                        except ValueError:
                            value = v.text
                    if value not in (None, ""):
                        cells[col(c.get("r") or "")] = value
                if cells:
                    out.append((r, cells))
            yield name, out


def import_file(book: str, path: Path, sheet: str | None = None, where: Path | None = None) -> int:
    """Перенести файл в книгу. sheet — взять только первый лист под этим именем (таблицы data/)."""
    n = 0
    for name, data in _xlsx_sheets(Path(path)):
        put(book, sheet or name, data, where)
        n += 1
        if sheet:
            break
    return n


if __name__ == "__main__":
    # python3 sheets.py "<книга цеха.xlsm>" — разовый перенос книги и data/*.xlsx в базу
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "цех_склад для apk.xlsm"
    print("книга цеха:", import_file("цех", src), "листов")
    for f in sorted((BASE / "data").glob("*.xlsx")):
        import_file("data", f, sheet=f.stem)
        print("таблица", f.stem)
