# -*- coding: utf-8 -*-
"""
Листы цеха. Раньше — рабочая книга цех_склад для apk.xlsm, теперь — база (sheets.py, книга «цех»).
Интерфейс прежний: read_sheet / write_sheets / append_rows / ensure_sheets.
"""
from __future__ import annotations

import threading
from pathlib import Path

import sheets

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
BOOK = "цех"

LOCK = threading.RLock()
# Один писатель листов цеха на процесс: цех (здесь) и склад (warehouse.py) правят одну книгу.
BOOK_LOCK = threading.RLock()


class CexLocked(RuntimeError):
    """Книга занята (со времён Excel; база не блокируется — не возникает)."""


class CexSourceError(RuntimeError):
    pass


def source_path() -> Path:
    """Где лежал старый файл книги — только для разового переноса и старых скриптов."""
    hint = DATA / "цех_источник.txt"
    raw = hint.read_text(encoding="utf-8").strip() if hint.exists() else ""
    return Path(raw).expanduser() if raw else BASE / "цех_склад для apk.xlsm"


# --------------------------------------------------------------- чтение
def read_sheet(name: str) -> list[dict]:
    """Лист как список словарей по шапке первой строки."""
    data = sheets.rows(BOOK, name) or []
    if not data:
        return []
    first = data[0][1]
    width = max(first) if first else 0
    header = [str(first.get(i, "") or f"col{i}") for i in range(1, width + 1)]
    return [{header[i - 1]: cells.get(i, "") for i in range(1, width + 1)} for _, cells in data[1:]]


def first_row(name: str) -> list:
    """Первая строка листа как список значений по колонкам (шапка)."""
    data = sheets.rows(BOOK, name) or []
    if not data:
        return []
    first = data[0][1]
    return [first.get(i, "") for i in range(1, (max(first) if first else 0) + 1)]


def sheet_names() -> list[str]:
    return sheets.names(BOOK)


# --------------------------------------------------------------- запись
def write_sheets(items: list[tuple]) -> None:
    """items: [(имя листа, [колонки], [строки-словари или списки]), ...]"""
    with BOOK_LOCK, LOCK:
        have = set(sheet_names())
        for name, headers, rows in items:
            if name not in have:
                raise KeyError(f"нет листа «{name}» — сначала создайте его")
            sheets.put_table(BOOK, name, headers, rows)


def write_sheet(name: str, headers: list[str], rows) -> None:
    """Полная замена содержимого одного листа (шапка + строки)."""
    write_sheets([(name, headers, rows)])


def append_rows(name: str, headers: list[str], rows: list[dict]) -> None:
    with BOOK_LOCK, LOCK:
        write_sheet(name, headers, read_sheet(name) + rows)


def ensure_sheets(specs: list[tuple]) -> list[str]:
    """Создать отсутствующие листы. specs: [(имя, [колонки], [ширины]), ...]. Возвращает созданные."""
    with BOOK_LOCK, LOCK:
        lower = {n.lower() for n in sheet_names()}
        created = []
        for name, headers, _widths in specs:
            if name.lower() in lower:
                continue  # лист уже есть (в том числе под другим регистром) — не дублируем
            sheets.put_table(BOOK, name, headers, [])
            lower.add(name.lower())
            created.append(name)
        return created


def ensure_sheet(name: str, headers: list[str], widths: list[float]) -> bool:
    """Создать лист, если его нет. True — создали."""
    return bool(ensure_sheets([(name, headers, widths)]))
