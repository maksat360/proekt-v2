# -*- coding: utf-8 -*-
"""Ежедневная копия данных портала на Google Диск (запускает LaunchAgent kg.sharq.backup).

Кладёт в «Мой диск/Резерв портала»:
  портал_ГГГГММДД_ЧЧММ.sql.gz   — база PostgreSQL (склад, заказы, сотрудники, адреса)
  данные_ГГГГММДД_ЧЧММ.tar.gz   — папка data/ (пользователи, роли, цех, реестр склада, кабинеты WB)
Хранит последние KEEP копий каждого вида. Восстановление: gunzip -c файл.sql.gz | psql portal"""
from __future__ import annotations

import gzip
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402

DRIVE = Path.home() / "Library/CloudStorage/GoogleDrive-sharqtextile@gmail.com/Мой диск/Резерв портала"
KEEP = 30
# не копируем: старые локальные копии, голос, логи, сама папка дампов — они большие и пересоздаются
SKIP = {"склад_бэкапы", "voice", "backups", "sql"}
SKIP_SUFFIX = (".log",)


def _keep_last(prefix: str) -> None:
    files = sorted(DRIVE.glob(prefix + "_*"))
    for f in files[:-KEEP]:
        f.unlink(missing_ok=True)


def run() -> list[Path]:
    if not DRIVE.parent.exists():
        raise SystemExit(f"Google Диск не подключён: нет {DRIVE.parent}")
    DRIVE.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    made = []

    con = sqldb.connect()
    try:
        dump = sqldb.backup(con)  # pg_dump → data/sql/backups (там тоже хранится 30 штук)
    finally:
        con.close()
    out = DRIVE / f"портал_{stamp}{dump.suffix}.gz"
    with open(dump, "rb") as src, gzip.open(out, "wb") as dst:
        shutil.copyfileobj(src, dst)
    made.append(out)

    out = DRIVE / f"данные_{stamp}.tar.gz"
    data = BASE / "data"
    with tarfile.open(out, "w:gz") as tar:
        for p in sorted(data.iterdir()):
            if p.name in SKIP or p.name.endswith(SKIP_SUFFIX):
                continue
            tar.add(p, arcname=f"data/{p.name}",
                    filter=lambda ti: None if ti.name.endswith(SKIP_SUFFIX) else ti)
    made.append(out)

    _keep_last("портал")
    _keep_last("данные")
    return made


if __name__ == "__main__":
    for f in run():
        print(f"{f.name}  {f.stat().st_size / 1e6:.1f} МБ")
