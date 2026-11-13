# -*- coding: utf-8 -*-
"""Безопасный экспорт SQL → новый файл на основе мастер-копии.

Правила:
  • шаблон — только master/*.xlsm (рабочая книга не используется и не меняется);
  • результат — всегда новый файл в exports/;
  • пишутся только листы, которыми владеет приложение и в которых нет формул:
    «заказы», «сотрудники», «расценки»;
  • VBA и формулы остаются нетронутыми, макросы не запускаются.
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import db as sqldb

BASE = Path(__file__).resolve().parent.parent
EXPORT_DIR = BASE / "exports"

APP_SHEETS = ("заказы", "сотрудники", "расценки")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _formula_count(path: Path, sheets: list[str] | None = None) -> dict[str, int]:
    wb = load_workbook(path, data_only=False, read_only=True)
    try:
        out = {}
        for name in (sheets or wb.sheetnames):
            if name not in wb.sheetnames:
                continue
            ws = wb[name]
            n = 0
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, str) and v.startswith("="):
                        n += 1
            out[name] = n
        return out
    finally:
        wb.close()


def _write_rows(ws, headers: list[str], rows: list[list]) -> None:
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    for r, values in enumerate(rows, start=2):
        for c, v in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=v)
    if ws.max_row > len(rows) + 1:
        ws.delete_rows(len(rows) + 2, ws.max_row - (len(rows) + 1))


def export_from_sql(con: sqlite3.Connection, template: Path | None = None,
                    out_dir: Path | None = None, actor: str = "export") -> dict:
    template = Path(template or sqldb.MASTER)
    out_dir = Path(out_dir or EXPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not template.exists():
        raise FileNotFoundError(f"нет мастер-копии: {template}")
    before_sha = _sha(template)

    dest = out_dir / f"цех_склад_{datetime.now():%Y-%m-%d_%H%M%S}.xlsm"
    shutil.copyfile(template, dest)
    dest.chmod(0o644)

    formulas_before = _formula_count(template)
    vba_before = "xl/vbaProject.bin" in zipfile.ZipFile(template).namelist()
    wb_ref = load_workbook(template, read_only=True)
    names_before = sorted(wb_ref.defined_names.keys()) if hasattr(wb_ref.defined_names, "keys") else []
    wb_ref.close()

    wb = load_workbook(dest, keep_vba=True)
    try:
        # заказы
        ws = wb["заказы"] if "заказы" in wb.sheetnames else wb.create_sheet("заказы")
        rows = []
        for o in con.execute("""SELECT id, ts, client, status, closed_at, cancelled_by
                                FROM orders ORDER BY CAST(id AS INTEGER), id"""):
            for it in con.execute("""SELECT p.name, oi.qty, oi.shipped FROM order_items oi
                                     JOIN products p ON p.id = oi.product_id
                                     WHERE oi.order_id = ?""", (o["id"],)):
                rows.append([o["id"], o["ts"], o["client"], o["status"], it["name"],
                             it["qty"], it["shipped"], o["cancelled_by"] or "",
                             o["closed_at"] or ""])
        _write_rows(ws, ["№", "дата", "клиент", "статус", "товар", "заказано", "собрано",
                         "кто закрыл", "дата закрытия"], rows)

        # сотрудники
        ws = wb["сотрудники"] if "сотрудники" in wb.sheetnames else wb.create_sheet("сотрудники")
        rows = [["", "", "", ""]]
        rows = []
        for e in con.execute("SELECT login, name, role, workshop, rate_hour, active, password_state FROM employees ORDER BY login"):
            rows.append([e["login"], "123456" if e["password_state"] == "default" else "изменён",
                         e["name"], e["role"], e["role"], e["workshop"], e["rate_hour"],
                         "да" if e["active"] else "нет"])
        _write_rows(ws, ["логин", "пароль", "ФИО", "роль", "должность", "цех",
                         "ставка за час", "активен"], rows)

        # расценки
        ws = wb["расценки"] if "расценки" in wb.sheetnames else wb.create_sheet("расценки")
        rows = [[r["code"], r["name"], r["price"], r["sort_order"],
                 "да" if r["required"] else "нет"]
                for r in con.execute("SELECT * FROM rates ORDER BY sort_order")]
        _write_rows(ws, ["код", "операция", "расценка за шт", "порядок", "обязательная"], rows)

        # пометка о происхождении + пересчёт при открытии
        wb.properties.description = (
            f"Сгенерировано из SQL · {datetime.now():%d.%m.%Y %H:%M} · "
            f"база: {sqldb.DB_PATH.name} · строк: {len(rows)}")
        try:
            wb.calculation.fullCalcOnLoad = True
        except Exception:
            pass
        wb.save(dest)
    finally:
        wb.close()

    # ---------- проверка результата
    formulas_after = _formula_count(dest)
    vba_after = "xl/vbaProject.bin" in zipfile.ZipFile(dest).namelist()
    wb2 = load_workbook(dest, read_only=True)
    names_after = sorted(wb2.defined_names.keys()) if hasattr(wb2.defined_names, "keys") else []
    sheets_after = list(wb2.sheetnames)
    wb2.close()
    template_sha_after = _sha(template)

    checks = {
        "файл_создан": dest.exists() and dest.stat().st_size > 0,
        "формат_xlsm": dest.suffix == ".xlsm",
        "все_листы_на_месте": set(sheets_after) >= set(formulas_before.keys()),
        "формулы_сохранены": all(
            formulas_after.get(name, 0) == n
            for name, n in formulas_before.items() if name not in APP_SHEETS),
        "vba_сохранён": (not vba_before) or vba_after,
        "именованные_диапазоны": names_before == names_after,
        "шаблон_не_изменён": before_sha == template_sha_after,
    }
    orders_sql = con.execute("SELECT COUNT(*) c FROM order_items").fetchone()["c"]
    report = {
        "файл": str(dest),
        "размер_МБ": round(dest.stat().st_size / 1024 / 1024, 2),
        "проверки": checks,
        "строк_заказов_sql": orders_sql,
        "ok": all(checks.values()),
    }
    sqldb.audit(con, actor, "export", "workbook", dest.name, report,
                "ok" if report["ok"] else "export_check_failed")
    return report
