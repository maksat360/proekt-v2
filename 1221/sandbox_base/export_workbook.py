# -*- coding: utf-8 -*-
"""Копии рабочей книги для скачивания: свежая и из резервных.

Рабочая книга только читается (shutil.copy2). Ничего не изменяется.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
EXPORTS = BASE / "exports"
BACKUPS = BASE / "data" / "склад_бэкапы"
SOURCE = Path("/Users/temp/швейный цех приложение/цех_склад для apk.xlsm")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot() -> dict:
    """Свежая копия рабочей книги в exports/ (с датой и временем)."""
    if not SOURCE.exists():
        raise FileNotFoundError("рабочая книга не найдена")
    EXPORTS.mkdir(parents=True, exist_ok=True)
    dest = EXPORTS / f"книга_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsm"
    shutil.copy2(SOURCE, dest)
    src_size = SOURCE.stat().st_size
    if dest.stat().st_size != src_size:
        raise RuntimeError("размер копии не совпал с оригиналом")
    if _sha(dest) != _sha(SOURCE):
        raise RuntimeError("контрольная сумма копии не совпала")
    return {"путь": str(dest), "размер": dest.stat().st_size,
            "создана": datetime.now().strftime("%d.%m.%Y %H:%M")}


def list_backups(limit: int = 15) -> list[dict]:
    if not BACKUPS.exists():
        return []
    files = sorted(BACKUPS.glob("*.xlsm"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:limit]:
        st = p.stat()
        out.append({
            "имя": p.name,
            "размер": st.st_size,
            "дата": datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M"),
        })
    return out


def backup_path(name: str) -> Path:
    name = Path(name).name
    target = (BACKUPS / name).resolve()
    if BACKUPS.resolve() not in target.parents:
        raise ValueError("недопустимое имя файла")
    if not target.is_file():
        raise ValueError("копия не найдена")
    return target
