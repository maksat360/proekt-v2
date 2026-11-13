# -*- coding: utf-8 -*-
"""Перенос на единую систему ролей: этапы → производственные роли, «Швея» убирается.

Запускать при ОСТАНОВЛЕННОМ портале (книгу пишет только один процесс).
  python3 migrate_roles.py --проверка                 — только показать, что будет
  python3 migrate_roles.py --выдать seam2=ОВЕРЛ ...   — роли для «Швей» без этапов
Перед записью копирует книгу цеха, permissions.json, processes.xlsx и users.xlsx в backups/роли_<время>/.
Повторный запуск ничего не меняет.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import cex_api  # noqa: E402
import cex_store  # noqa: E402
import perms  # noqa: E402


def backup() -> Path:
    dst = BASE / "backups" / f"роли_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    dst.mkdir(parents=True, exist_ok=True)
    for src in (cex_store.source_path(), perms.FILE, BASE / "data" / "processes.xlsx",
                BASE / "data" / "users.xlsx"):
        if src.exists():
            shutil.copy2(src, dst / src.name)
    return dst


def main(argv: list[str]) -> int:
    dry = "--проверка" in argv
    assign: dict[str, list[str]] = {}
    for i, a in enumerate(argv):
        if a == "--выдать":
            for pair in argv[i + 1:]:
                if pair.startswith("--"):
                    break
                login, _, codes = pair.partition("=")
                assign[login] = [c for c in codes.split(",") if c]
    if not dry:
        print("Копия перед переносом:", backup())
    report = cex_api.migrate_roles(assign, dry=dry)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if report["без_ролей"]:
        print("\nНе перенесено: у этих «Швей» нет ни одной производственной роли —",
              ", ".join(report["без_ролей"]), "\nУкажите: --выдать логин=КОД[,КОД]")
        return 1
    print("\nГотово." if report["готово"] else "\nПроверка: данные не менялись.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
