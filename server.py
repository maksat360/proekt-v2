#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проект V2.1 — веб-портал швейного цеха.

Всё «гибкое» (цепочка процессов, тарифы, периоды выплат, цеха, разделы партий)
настраивается в Excel-файлах папки data/ и подтягивается при каждом запросе.

Запуск:  python3 server.py [--port 8787] [--host 0.0.0.0] [--dev]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
STATIC = BASE / "static"
GZIP_TYPES = {"application/json", "text/html", "text/css", "text/javascript",
              "application/javascript", "image/svg+xml", "application/manifest+json"}
REPORT_DIR = DATA / "отчёты"
BACKUP_DIR = BASE / "backups"

for _p in (DATA, STATIC, REPORT_DIR, BACKUP_DIR):
    _p.mkdir(parents=True, exist_ok=True)

IO_LOCK = threading.RLock()
# Все POST идут по одному: «прочитать лист → поменять → записать» не должны пересекаться,
# иначе вторая запись затирает первую, а проверка остатка проходит дважды.
WRITE_LOCK = threading.Lock()
SESSIONS: dict[str, dict] = {}
SESSIONS_LOCK = threading.Lock()
SESSIONS_FILE = DATA / "sessions.json"
SESSION_DAYS = 30
ACC_COOKIE = "v2acc"  # запомненные аккаунты устройства: токены через «.», HttpOnly


def _load_sessions() -> None:
    try:
        raw = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    cutoff = datetime.now().timestamp() - SESSION_DAYS * 86400
    with SESSIONS_LOCK:
        for tok, data in (raw or {}).items():
            if isinstance(data, dict) and data.get("логин") and float(data.get("ts", 0)) >= cutoff:
                SESSIONS[tok] = data


def _save_sessions() -> None:
    try:
        with SESSIONS_LOCK:
            data = json.dumps(SESSIONS, ensure_ascii=False)
        tmp = SESSIONS_FILE.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(SESSIONS_FILE)
        try:
            os.chmod(SESSIONS_FILE, 0o600)
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        print("сессии не сохранены:", exc)


def _new_session(login: str, company: str) -> str:
    token = secrets.token_urlsafe(24)
    with SESSIONS_LOCK:
        SESSIONS[token] = {"логин": login, "цех": company, "ts": datetime.now().timestamp()}
    _save_sessions()
    return token
mimetypes.add_type("application/manifest+json", ".webmanifest")
_load_sessions()
VERBOSE = False
DEV = False

import perms  # noqa: E402

ROLE_LABELS = perms.ROLE_LABELS

SCHEMAS = {
    "companies": ["код", "название", "город", "активен"],
    "users": ["логин", "пароль", "фио", "роль", "цех", "ставка_час", "активен"],
    "processes": ["код", "название", "порядок", "тариф", "артикул", "обязательный",
                  "зависимости", "склад_гп", "активен", "отключён"],
    "batches": ["номер", "цех", "артикул", "клиент", "статус", "технолог",
                "дата_создания", "срок", "примечание"],
    "sections": ["партия", "раздел", "цвет", "тон", "размер", "количество"],
    "passes": ["id", "дата", "партия", "раздел", "процесс", "логин", "фио",
               "количество", "тариф", "сумма", "начало", "конец", "статус", "комментарий"],
    "minus": ["дата", "партия", "раздел", "процесс", "количество", "логин", "комментарий"],
    "checks": ["дата", "партия", "раздел", "технолог", "оценка", "комментарий"],
    "materials": ["артикул", "название", "количество", "ед", "цена", "поставщик"],
    "moves": ["дата", "артикул", "тип", "количество", "партия", "кто", "комментарий"],
    "finished": ["дата", "партия", "раздел", "количество", "кто"],
    "shipments": ["дата", "партия", "количество", "покупатель", "сумма"],
    "announcements": ["дата", "логин", "фио", "цех", "текст", "активен"],
    "periods": ["код", "название", "начало", "конец"],
    "products": ["id", "артикул", "категория", "модель", "цвет", "размер",
                 "количество", "фк", "цена", "наименование", "иконка", "фото"],
    "sales": ["id", "дата", "id_товара", "наименование", "количество", "цена", "сумма",
              "покупатель", "кто", "отменена"],
    "operations": ["id", "дата", "тип", "id_товара", "наименование", "количество",
                   "откуда", "куда", "контрагент", "комментарий", "кто", "отменена"],
    "boxes": ["id", "дата", "коробка", "id_товара", "наименование", "количество",
              "проверка", "кто"],
}

def can(who, cap: str) -> bool:
    """Право сотрудника (who — пользователь) или роли (who — строка) из perms.py."""
    if cap == "users.manage":  # старое имя в интерфейсе портала
        cap = "staff.edit"
    user = who if isinstance(who, dict) else {"роль": str(who)}
    return perms.allowed(user, cap)


# ---------------------------------------------------------------- Excel layer
def table_path(name: str) -> Path:
    return DATA / f"{name}.xlsx"


def norm(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


_TABLE_CACHE: dict = {}  # имя таблицы → (mtime_ns, размер, строки)


def read_table(name: str) -> list[dict]:
    """Строки таблицы; файл перечитывается только после изменения."""
    path = table_path(name)
    try:
        st = path.stat()
    except OSError:
        return []
    sig = (st.st_mtime_ns, st.st_size)
    hit = _TABLE_CACHE.get(name)
    if hit and hit[0] == sig:
        return [dict(r) for r in hit[1]]
    rows = _read_table_file(name, path)
    _TABLE_CACHE[name] = (sig, rows)
    return [dict(r) for r in rows]


def _read_table_file(name: str, path: Path) -> list[dict]:
    with IO_LOCK:
        wb = load_workbook(path, data_only=True)
        ws = wb[name] if name in wb.sheetnames else wb.active
        rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(norm(c) or f"col{i}") for i, c in enumerate(rows[0])]
    out = []
    for raw in rows[1:]:
        if raw is None or all(c is None or c == "" for c in raw):
            continue
        out.append({header[i]: norm(raw[i]) if i < len(raw) else "" for i in range(len(header))})
    return out


def write_table(name: str, rows: list[dict]) -> None:
    cols = SCHEMAS[name]
    path = table_path(name)
    with IO_LOCK:
        wb = Workbook()
        ws = wb.active
        ws.title = name
        ws.append(cols)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F3864")
        for row in rows:
            ws.append([row.get(c, "") for c in cols])
        for i, col in enumerate(cols, start=1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, min(32, len(col) + 8))
        ws.freeze_panes = "A2"
        tmp = path.with_suffix(".tmp.xlsx")
        wb.save(tmp)
        tmp.replace(path)
        _TABLE_CACHE.pop(name, None)


def append_row(name: str, row: dict) -> None:
    rows = read_table(name)
    rows.append({c: row.get(c, "") for c in SCHEMAS[name]})
    write_table(name, rows)


def ensure_tables() -> None:
    for name in SCHEMAS:
        if not table_path(name).exists():
            write_table(name, [])


def backup_data() -> None:
    day = datetime.now().strftime("%Y-%m-%d")
    target = BACKUP_DIR / day
    if target.exists():
        return
    try:
        target.mkdir(parents=True, exist_ok=True)
        for src in [*DATA.glob("*.xlsx"), DATA / "permissions.json", DATA / "журнал_прав.jsonl"]:
            if src.exists():
                shutil.copyfile(src, target / src.name)
        dirs = sorted([d for d in BACKUP_DIR.iterdir() if d.is_dir()])
        for old in dirs[:-30]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        print("бэкап не сделан:", exc)


# ------------------------------------------------------------------ helpers
def now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def today() -> str:
    return date.today().strftime("%d.%m.%Y")


def as_num(v, default=0.0) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return default


def month_key(day: str) -> str:
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", str(day))
    return f"{m.group(3)}-{m.group(2)}" if m else ""


def month_title(key: str) -> str:
    names = ["", "январь", "февраль", "март", "апрель", "май", "июнь", "июль",
             "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    try:
        y, m = key.split("-")
        return f"{names[int(m)]} {y}"
    except Exception:
        return key


def parse_dt(s: str):
    s = str(s).strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def size_sort_key(value: str):
    v = str(value).strip().lower().replace(",", ".")
    m = re.match(r"^(\d+(?:\.\d+)?)", v)
    if m:
        return (0, float(m.group(1)), v)
    table = {"xs": 1, "s": 2, "m": 3, "l": 4, "xl": 5, "xxl": 6}
    return (1, table.get(v, 99), v)


def hash_password(raw: str) -> str:
    return hashlib.sha256(("v2salt::" + raw).encode("utf-8")).hexdigest()


def check_password(raw: str, stored: str) -> bool:
    stored = str(stored)
    return stored == hash_password(raw) if len(stored) == 64 else stored == raw


def staff_users() -> list[dict]:
    """Учётки из листа «сотрудники»; пароль добираем из users.xlsx, если в листе «изменён»."""
    try:
        import warehouse
        rows = warehouse.staff_rows()
    except Exception:
        rows = []
    if not rows:
        return read_table("users")
    base = {str(u.get("логин")): u for u in read_table("users")}
    out = []
    for r in rows:
        old = base.get(r["логин"], {})
        pwd = str(r.get("пароль") or "").strip()
        if not pwd or pwd.lower() in ("изменён", "изменен", "changed"):
            pwd = str(old.get("пароль") or "")
        role = str(r.get("роль") or "").strip()
        known = perms.all_roles()  # служебные + производственные роли
        if role not in known:
            reverse = {v.lower(): k for k, v in known.items()}
            role = reverse.get(role.lower(), role.upper() if role.upper() in known else old.get("роль", ""))
        out.append({
            "логин": r["логин"], "пароль": pwd, "фио": r.get("фио") or old.get("фио", ""),
            "роль": role, "цех": r.get("цех") or old.get("цех", ""),
            "ставка_час": r.get("ставка_час", 0), "активен": r.get("активен", 1),
        })
    known = {str(u.get("логин")) for u in out}
    for login, u in base.items():
        if login not in known:
            out.append(u)
    return out


def find_user(login: str, company: str | None = None) -> dict | None:
    for u in staff_users():
        if str(u.get("логин")) == login:
            if company and str(u.get("цех")) != company:
                return None
            return u
    return None


def portal_roles(u: dict) -> list[str]:
    roles = perms.roles_of(u)
    out = [r for r in roles if r in ROLE_LABELS]
    return out + (["prod"] if len(out) < len(roles) else [])


def public_user(u: dict) -> dict:
    return {
        "логин": u.get("логин", ""),
        "фио": u.get("фио", ""),
        "роль": u.get("роль", ""),
        "роль_название": perms.role_label(str(u.get("роль"))),
        "роли": perms.roles_of(u),
        # для меню портала: производственные роли (Оверлок, Карман…) сводятся в одну «prod»
        "роли_портала": portal_roles(u),
        "цех": u.get("цех", ""),
        "активен": str(u.get("активен", "1")) in ("1", "True", "true"),
    }


# ---------------------------------------------------------------- domain
def active_company(code: str | None) -> dict | None:
    for c in read_table("companies"):
        if str(c.get("код")) == str(code) and str(c.get("активен", "1")) in ("1", "True", "true"):
            return c
    return None


def batch_map() -> dict[int, dict]:
    return {int(b["номер"]): b for b in read_table("batches") if str(b.get("номер", "")).isdigit()}


def batch_sections(num: int) -> list[dict]:
    rows = [s for s in read_table("sections") if str(s.get("партия")) == str(num)]
    return sorted(rows, key=lambda s: (as_num(s.get("раздел")), str(s.get("размер"))))


def chain_for(art: str) -> list[dict]:
    rows = []
    for p in read_table("processes"):
        if str(p.get("активен", "1")) not in ("1", "True", "true"):
            continue
        target = str(p.get("артикул", "")).strip()
        if target and target.lower() not in str(art).lower():
            continue
        rows.append(p)
    return sorted(rows, key=lambda p: as_num(p.get("порядок")))


def process_map() -> dict[str, dict]:
    return {str(p.get("код")): p for p in read_table("processes")}


def passes_of(num: int | None = None) -> list[dict]:
    rows = read_table("passes")
    if num is None:
        return rows
    return [r for r in rows if str(r.get("партия")) == str(num)]


def minus_of(num: int, sec: int | None = None, proc: str | None = None) -> float:
    total = 0.0
    for m in read_table("minus"):
        if str(m.get("партия")) != str(num):
            continue
        if sec is not None and str(m.get("раздел")) != str(sec):
            continue
        if proc is not None and str(m.get("процесс")) != str(proc):
            continue
        total += as_num(m.get("количество"))
    return total


def done_qty(num: int, sec: int, proc: str) -> float:
    total = 0.0
    for p in passes_of(num):
        if str(p.get("раздел")) != str(sec) or str(p.get("процесс")) != str(proc):
            continue
        if str(p.get("статус")) != "готово":
            continue
        total += as_num(p.get("количество"))
    return max(0.0, total - minus_of(num, sec, proc))


def in_progress(num: int, sec: int, proc: str) -> dict | None:
    for p in passes_of(num):
        if (str(p.get("раздел")) == str(sec) and str(p.get("процесс")) == str(proc)
                and str(p.get("статус")) == "в работе"):
            return p
    return None


def deps_ready(num: int, sec: int, proc: dict, need: float) -> bool:
    deps = [d.strip() for d in str(proc.get("зависимости", "")).replace(",", ";").split(";") if d.strip()]
    for code in deps:
        if done_qty(num, sec, code) < need:
            return False
    return True


def batch_totals(num: int) -> dict:
    secs = batch_sections(num)
    total = sum(as_num(s.get("количество")) for s in secs)
    finished = sum(as_num(f.get("количество")) for f in read_table("finished")
                   if str(f.get("партия")) == str(num))
    shipped = sum(as_num(s.get("количество")) for s in read_table("shipments")
                  if str(s.get("партия")) == str(num))
    return {"штук": total, "разделов": len(secs), "на_складе": finished, "отгружено": shipped}


def batch_view(b: dict) -> dict:
    num = int(b["номер"])
    t = batch_totals(num)
    chain = chain_for(str(b.get("артикул", "")))
    secs = batch_sections(num)
    progress = 0.0
    if chain and secs:
        points = 0.0
        for s in secs:
            qty = as_num(s.get("количество")) or 1
            finished_steps = sum(1 for p in chain
                                 if done_qty(num, int(as_num(s.get("раздел"))), str(p.get("код"))) >= qty)
            points += finished_steps / len(chain)
        progress = round(points / len(secs) * 100, 0)
    return {
        "номер": num,
        "цех": str(b.get("цех", "")),
        "артикул": str(b.get("артикул", "")),
        "клиент": str(b.get("клиент", "")),
        "статус": str(b.get("статус", "в работе")),
        "технолог": str(b.get("технолог", "")),
        "дата_создания": str(b.get("дата_создания", "")),
        "срок": str(b.get("срок", "")),
        "примечание": str(b.get("примечание", "")),
        "штук": t["штук"],
        "разделов": t["разделов"],
        "на_складе": t["на_складе"],
        "отгружено": t["отгружено"],
        "прогресс": progress,
        "этапов": len(chain),
        "финал": chain[-1]["код"] if chain else "",
    }


def section_view(num: int, s: dict, chain: list[dict], login: str) -> dict:
    sec = int(as_num(s.get("раздел")))
    qty = as_num(s.get("количество"))
    steps = []
    live = None
    for p in chain:
        code = str(p.get("код"))
        done = done_qty(num, sec, code)
        busy = in_progress(num, sec, code)
        ready = deps_ready(num, sec, p, qty)
        if busy:
            state = "работает"
        elif done >= qty:
            state = "готово"
        elif ready:
            state = "можно взять"
        else:
            state = "ждёт зависимости"
        steps.append({
            "код": code,
            "название": str(p.get("название")),
            "тариф": as_num(p.get("тариф")),
            "зависимости": [d for d in str(p.get("зависимости", "")).replace(",", ";").split(";") if d],
            "обязательный": str(p.get("обязательный", "0")) in ("1", "True", "true"),
            "склад_гп": str(p.get("склад_гп", "0")) in ("1", "True", "true"),
            "сделано": done,
            "нужно": qty,
            "осталось": max(0.0, qty - done),
            "статус": state,
            "исполнитель": str(busy.get("фио")) if busy else "",
            "pass_id": str(busy.get("id")) if busy else "",
            "начало": str(busy.get("начало")) if busy else "",
            "готов_взять": bool(ready and not busy and done < qty),
        })
        if busy and not live:
            live = {
                "id": busy.get("id"),
                "процесс": code,
                "процесс_название": str(p.get("название")),
                "начало": str(busy.get("начало")),
                "логин": str(busy.get("логин")),
                "фио": str(busy.get("фио")),
                "количество": as_num(busy.get("количество")),
                "мое": str(busy.get("логин")) == login,
            }
    return {
        "раздел": sec,
        "цвет": str(s.get("цвет", "")),
        "тон": str(s.get("тон", "")),
        "размер": str(s.get("размер", "")),
        "количество": qty,
        "шаги": steps,
        "в_работе": live,
        "оценки": [c for c in read_table("checks")
                   if str(c.get("партия")) == str(num) and str(c.get("раздел")) == str(sec)],
    }


def batch_detail(num: int, me: dict) -> dict | None:
    b = batch_map().get(num)
    if not b:
        return None
    view = batch_view(b)
    chain = chain_for(str(b.get("артикул", "")))
    secs = [section_view(num, s, chain, str(me.get("логин"))) for s in batch_sections(num)]
    return {**view, "разделы": secs, "цепочка": [
        {"код": str(p.get("код")), "название": str(p.get("название")),
         "тариф": as_num(p.get("тариф")),
         "зависимости": [d for d in str(p.get("зависимости", "")).replace(",", ";").split(";") if d]}
        for p in chain]}


def my_tasks(me: dict) -> list[dict]:
    login, comp = str(me.get("логин")), str(me.get("цех"))
    out = []
    for b in read_table("batches"):
        if str(b.get("цех")) != comp:
            continue
        num = int(b["номер"])
        chain = chain_for(str(b.get("артикул", "")))
        for s in batch_sections(num):
            sec = int(as_num(s.get("раздел")))
            qty = as_num(s.get("количество"))
            for p in chain:
                code = str(p.get("код"))
                done = done_qty(num, sec, code)
                if done >= qty:
                    continue
                busy = in_progress(num, sec, code)
                if busy:
                    if str(busy.get("логин")) == login:
                        out.append({
                            "тип": "в работе", "партия": num, "артикул": str(b.get("артикул")),
                            "раздел": sec, "цвет": str(s.get("цвет")), "тон": str(s.get("тон")),
                            "размер": str(s.get("размер")), "процесс": code,
                            "название": str(p.get("название")), "тариф": as_num(p.get("тариф")),
                            "количество": as_num(busy.get("количество")),
                            "начало": str(busy.get("начало")), "pass_id": busy.get("id"),
                        })
                    break
                restricted = (str(p.get("склад_гп", "0")) in ("1", "True", "true")
                              or str(p.get("код")) == "ОТГРУЗ")
                if restricted and str(me.get("роль")) not in ("storekeeper", "admin", "manager"):
                    break
                if deps_ready(num, sec, p, qty):
                    out.append({
                        "тип": "можно взять", "партия": num, "артикул": str(b.get("артикул")),
                        "раздел": sec, "цвет": str(s.get("цвет")), "тон": str(s.get("тон")),
                        "размер": str(s.get("размер")), "процесс": code,
                        "название": str(p.get("название")), "тариф": as_num(p.get("тариф")),
                        "количество": qty - done, "начало": "", "pass_id": "",
                    })
                    break
    return out


def periods() -> list[dict]:
    rows = read_table("periods")
    if not rows:
        rows = [
            {"код": "p1", "название": "1–10", "начало": 1, "конец": 10},
            {"код": "p2", "название": "11–20", "начало": 11, "конец": 20},
            {"код": "p3", "название": "21–конец месяца", "начало": 21, "конец": 31},
        ]
    return rows


def period_range(code: str, month: str) -> tuple[str, str]:
    try:
        y, m = [int(x) for x in month.split("-")]
    except Exception:
        d0 = date.today()
        y, m = d0.year, d0.month
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    last_day = (nxt - timedelta(days=1)).day
    row = next((p for p in periods() if str(p.get("код")) == str(code)), None)
    start_day = min(int(as_num(row.get("начало")) or 1), last_day) if row else 1
    end_day = min(int(as_num(row.get("конец")) or last_day), last_day) if row else last_day
    return (date(y, m, start_day).strftime("%d.%m.%Y"),
            date(y, m, end_day).strftime("%d.%m.%Y"))


def date_in(day: str, start: str, end: str) -> bool:
    d, a, b = parse_dt(day), parse_dt(start), parse_dt(end)
    if not d or not a or not b:
        return True
    return a <= d <= b


def payroll(me: dict, period: str, month: str, scope_all: bool) -> dict:
    start, end = period_range(period, month) if period else ("", "")
    rows = read_table("passes")
    users = [u for u in staff_users() if str(u.get("цех")) == str(me.get("цех"))]
    if not scope_all:
        users = [u for u in users if str(u.get("логин")) == str(me.get("логин"))]
    result = []
    for u in users:
        mine = [r for r in rows
                if str(r.get("логин")) == str(u.get("логин")) and str(r.get("статус")) == "готово"
                and (not period or date_in(r.get("дата"), start, end))]
        result.append({
            "логин": u.get("логин"), "фио": u.get("фио"),
            "роль": perms.role_label(str(u.get("роль"))),
            "операций": len(mine),
            "штук": sum(as_num(r.get("количество")) for r in mine),
            "сумма": round(sum(as_num(r.get("сумма")) for r in mine), 2),
        })
    return {
        "период": period, "границы": [start, end],
        "месяц": month_title(month) if month else "всё время",
        "данные": sorted(result, key=lambda r: -r["сумма"]),
        "итого": round(sum(r["сумма"] for r in result), 2),
    }


def dashboard(me: dict) -> dict:
    role, comp = str(me.get("роль")), str(me.get("цех"))
    batches = [batch_view(b) for b in read_table("batches") if str(b.get("цех")) == comp]
    chain = chain_for("")
    shop = [p for p in chain
            if str(p.get("склад_гп", "0")) not in ("1", "True", "true")
            and str(p.get("код")) != "ОТГРУЗ"]
    wip = {str(p.get("название")): 0 for p in shop}
    for b in batches:
        for s in batch_sections(b["номер"]):
            sec = int(as_num(s.get("раздел")))
            for p in shop:
                if done_qty(b["номер"], sec, str(p.get("код"))) < as_num(s.get("количество")):
                    wip[str(p.get("название"))] += 1
                    break
    nums = {str(b["номер"]) for b in batches}
    fin = [f for f in read_table("finished") if str(f.get("партия")) in nums]
    ship = [s for s in read_table("shipments") if str(s.get("партия")) in nums]
    checks = [c for c in read_table("checks") if str(c.get("партия")) in nums]
    ratings = [as_num(c.get("оценка")) for c in checks]
    my_pass = [p for p in read_table("passes")
               if str(p.get("логин")) == str(me.get("логин")) and str(p.get("статус")) == "готово"]
    data = {
        "партий": len(batches),
        "в_работе": len([b for b in batches if b["прогресс"] < 100]),
        "готово": len([b for b in batches if b["прогресс"] >= 100]),
        "штук": sum(b["штук"] for b in batches),
        "на_складе": sum(as_num(f.get("количество")) for f in fin),
        "отгружено": sum(as_num(s.get("количество")) for s in ship),
        "незавершёнка": wip,
        "оценка_средняя": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "проверок": len(checks),
        "мои_задачи": [t for t in my_tasks(me) if t["тип"] == "в работе"] if "prod" in portal_roles(me) or role == "technologist" else [],
        "моя_выработка": {
            "штук": sum(as_num(p.get("количество")) for p in my_pass),
            "сумма": round(sum(as_num(p.get("сумма")) for p in my_pass), 2),
        },
        "последние": batches[:6],
    }
    if can(me, "materials.view"):
        mats = read_table("materials")
        data["материалов"] = len(mats)
        data["материалы_сумма"] = round(sum(as_num(m.get("количество")) * as_num(m.get("цена")) for m in mats), 2)
    return data


def analytics(me: dict) -> dict:
    comp = str(me.get("цех"))
    batches = [b for b in read_table("batches") if str(b.get("цех")) == comp]
    nums = {str(b["номер"]) for b in batches}
    passes = [p for p in read_table("passes") if str(p.get("партия")) in nums and str(p.get("статус")) == "готово"]
    checks = [c for c in read_table("checks") if str(c.get("партия")) in nums]
    ship = [s for s in read_table("shipments") if str(s.get("партия")) in nums]
    fin = [f for f in read_table("finished") if str(f.get("партия")) in nums]
    speed = {}
    for p in passes:
        a, b = parse_dt(p.get("начало")), parse_dt(p.get("конец"))
        if a and b and b >= a:
            speed.setdefault(str(p.get("процесс")), []).append((b - a).total_seconds() / 3600)
    ratings = {}
    for c in checks:
        ratings.setdefault(str(c.get("технолог")), []).append(as_num(c.get("оценка")))
    return {
        "партий": len(batches),
        "штук": sum(sum(as_num(s.get("количество")) for s in batch_sections(int(b["номер"]))) for b in batches),
        "готово_штук": sum(as_num(f.get("количество")) for f in fin),
        "отгружено": sum(as_num(s.get("количество")) for s in ship),
        "отгрузки_сумма": round(sum(as_num(s.get("сумма")) for s in ship), 2),
        "сдельно": round(sum(as_num(p.get("сумма")) for p in passes), 2),
        "скорость": {k: round(sum(v) / len(v), 1) for k, v in speed.items()},
        "оценки": {k: round(sum(v) / len(v), 1) for k, v in ratings.items()},
        "проверок": len(checks),
        "оценка_средняя": round(sum(as_num(c.get("оценка")) for c in checks) / len(checks), 1) if checks else None,
        "незавершёнка": dashboard(me)["незавершёнка"],
        "последние_проверки": checks[-8:][::-1],
    }


# ------------------------------------------------------------------ server
class Handler(BaseHTTPRequestHandler):
    server_version = "ProjectV2.1/1.0"
    # тайм-аут сокета: телефон, пропавший из Wi-Fi посреди POST, не держит WRITE_LOCK вечно
    timeout = 30

    def log_message(self, fmt, *args):  # noqa: A003
        if VERBOSE:
            super().log_message(fmt, *args)

    def _send(self, body: bytes, ctype: str, code: int = 200, extra: dict | None = None):
        # текст и JSON сжимаем: склад/магазин весят 100–200 КБ, по Wi-Fi на телефон это заметно
        gz = (len(body) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or "")
              and ctype.split(";")[0] in GZIP_TYPES)
        if gz:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    def _err(self, message: str, code: int = 400):
        self._json({"ok": False, "error": message}, code)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _cookie(self, key: str) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() == key:
                    return v.strip()
        return ""

    def _acc_tokens(self) -> list[str]:
        raw = self._cookie(ACC_COOKIE)
        return [t for t in raw.split(".") if t] if raw else []

    def _acc_cookie(self, tokens: list[str]) -> str:
        val = ".".join(tokens[-12:])
        if not val:
            return f"{ACC_COOKIE}=; Path=/; Max-Age=0"
        return f"{ACC_COOKIE}={val}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"

    def _send_json_cookies(self, obj: dict, cookies: list[str]) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(payload)

    def _device_accounts(self) -> list[tuple[str, dict, dict]]:
        """(токен, сессия, пользователь) для живых аккаунтов этого устройства."""
        out = []
        seen = set()
        for tok in self._acc_tokens():
            with SESSIONS_LOCK:
                data = SESSIONS.get(tok)
            if not data:
                continue
            key = (data["логин"], data["цех"])
            if key in seen:
                continue
            user = find_user(data["логин"], data["цех"])
            if not user or str(user.get("активен", "1")) not in ("1", "True", "true"):
                continue
            seen.add(key)
            out.append((tok, data, user))
        return out

    def _session(self) -> dict | None:
        token = self._cookie("v2sid")
        if not token:
            return None
        with SESSIONS_LOCK:
            data = SESSIONS.get(token)
        if not data:
            return None
        user = find_user(data["логин"], data["цех"])
        if not user or str(user.get("активен", "1")) not in ("1", "True", "true"):
            return None
        return user

    def do_GET(self):  # noqa: N802
        self._route("GET")

    def do_POST(self):  # noqa: N802
        self._route("POST")

    def do_HEAD(self):  # noqa: N802
        self._route("GET")

    def _route(self, method: str):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if path.startswith("/api/"):
                if method == "POST":
                    with WRITE_LOCK:
                        self._api(method, path, query)
                else:
                    self._api(method, path, query)
                return
            if path in ("/", "/index.html"):
                self._static("index.html")
                return
            if path in ("/sklad", "/sklad/", "/sklad.html"):
                self._static("sklad.html")
                return
            if path in ("/cex", "/cex/"):
                self._static("cex/index.html")
                return
            if path in ("/cex/labels", "/cex/labels/"):
                self._static("cex/labels.html")
                return
            if path in ("/cex/items", "/cex/items/"):
                self._static("cex/items.html")
                return
            if DEV and path == "/__dev_login":
                login = (query.get("логин") or ["boss"])[0]
                comp = (query.get("цех") or ["Ц-01"])[0]
                user = find_user(login, comp)
                if not user:
                    self._send(b"no user", "text/plain; charset=utf-8", 404)
                    return
                token = _new_session(login, comp)
                self.send_response(302)
                self.send_header("Location", (query.get("next") or ["/cex/"])[0])
                self.send_header("Set-Cookie", f"v2sid={token}; Path=/; HttpOnly; SameSite=Lax")
                self.end_headers()
                return
            if path.startswith("/static/"):
                self._static(path[len("/static/"):])
                return
            if path in ("/manifest.webmanifest", "/manifest-sklad.webmanifest"):
                self._static(path.lstrip("/"))
                return
            if path == "/sw.js":
                self._static("sw.js")
                return
            if path == "/favicon.ico":
                self._send(b"", "image/x-icon", 204)
                return
            self._send(b"not found", "text/plain; charset=utf-8", 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            if VERBOSE:
                import traceback
                traceback.print_exc()
            self._err(f"внутренняя ошибка: {exc}", 500)

    def _static(self, rel: str):
        target = (STATIC / rel).resolve()
        root = STATIC.resolve()
        if root not in target.parents and target != root:
            self._err("forbidden", 403)
            return
        if not target.is_file():
            self._send(b"not found", "text/plain; charset=utf-8", 404)
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or target.suffix in (".js", ".css", ".html"):
            ctype += "; charset=utf-8"
        self._send(target.read_bytes(), ctype)

    # -- api --------------------------------------------------------------
    def _api(self, method: str, path: str, query: dict):
        me = self._session()

        if path.startswith("/api/cex/"):
            import cex_api
            cex_api.dispatch({"json": self._json, "err": self._err, "body": self._body,
                              "me": me, "method": method, "path": path, "query": query})
            return

        if path == "/api/companies":
            self._json({"ok": True, "data": [
                {"код": c.get("код"), "название": c.get("название"), "город": c.get("город")}
                for c in read_table("companies")
                if str(c.get("активен", "1")) in ("1", "True", "true")]})
            return

        if path == "/api/logo" and method == "GET":
            # логотип: либо имя файла в static, либо полный путь к картинке на диске
            import mimetypes as _mt
            try:
                import warehouse
                value = str(warehouse.brand().get("логотип") or "").strip()
            except Exception:
                value = ""
            if not value:
                self._err("логотип не задан", 404)
                return
            ext_ok = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")
            target = None
            cand = Path(value).expanduser()
            if cand.is_absolute() and cand.is_file() and cand.suffix.lower() in ext_ok:
                target = cand
            elif (STATIC / value).is_file():
                target = STATIC / value
            if target is None:
                self._err("файл логотипа не найден", 404)
                return
            ctype = _mt.guess_type(str(target))[0] or "image/png"
            self._send(target.read_bytes(), ctype)
            return

        if path == "/api/brand" and method == "GET":
            data = {"название": "Швейный цех", "подзаголовок": "", "логотип": ""}
            try:
                import warehouse
                data = warehouse.brand()
            except Exception:
                pass
            self._json({"ok": True, "data": data})
            return

        if path == "/api/login" and method == "POST":
            body = self._body()
            company = str(body.get("цех", "")).strip()
            login = str(body.get("логин", "")).strip()
            if not active_company(company):
                self._err("Цех не найден", 404)
                return
            user = find_user(login, company)
            if not user or not check_password(str(body.get("пароль", "")), user.get("пароль", "")):
                self._err("Неверный логин или пароль", 401)
                return
            if str(user.get("активен", "1")) not in ("1", "True", "true"):
                self._err("Доступ закрыт: обратитесь к начальнику", 403)
                return
            token = _new_session(login, company)
            keep = []
            for tok in self._acc_tokens():
                with SESSIONS_LOCK:
                    data = SESSIONS.get(tok)
                if not data:
                    continue
                if data["логин"] == login and data["цех"] == company:
                    with SESSIONS_LOCK:
                        SESSIONS.pop(tok, None)
                    continue
                keep.append(tok)
            keep.append(token)
            _save_sessions()
            self._send_json_cookies({"ok": True, "user": public_user(user)}, [
                f"v2sid={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}",
                self._acc_cookie(keep)])
            return

        if path == "/api/accounts" and method == "GET":
            cur = self._cookie("v2sid")
            self._json({"ok": True, "data": [
                {"логин": d["логин"], "цех": d["цех"], "фио": u.get("фио", ""),
                 "роль": u.get("роль", ""), "роль_название": perms.role_label(str(u.get("роль"))),
                 "текущий": tok == cur}
                for tok, d, u in self._device_accounts()]})
            return

        if path in ("/api/accounts/switch", "/api/accounts/forget") and method == "POST":
            body = self._body()
            login = str(body.get("логин", "")).strip()
            company = str(body.get("цех", "")).strip()
            found = next((tok for tok, d, _ in self._device_accounts()
                          if d["логин"] == login and d["цех"] == company), None)
            if not found:
                self._err("Этот аккаунт не запомнен на устройстве — войдите с паролем", 404)
                return
            if path.endswith("/switch"):
                with SESSIONS_LOCK:
                    if found in SESSIONS:
                        SESSIONS[found]["ts"] = datetime.now().timestamp()
                _save_sessions()
                self._send_json_cookies({"ok": True}, [
                    f"v2sid={found}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"])
                return
            with SESSIONS_LOCK:
                SESSIONS.pop(found, None)
            _save_sessions()
            rest = [t for t in self._acc_tokens() if t != found]
            cookies = [self._acc_cookie(rest)]
            if self._cookie("v2sid") == found:
                cookies.append("v2sid=; Path=/; Max-Age=0")
            self._send_json_cookies({"ok": True}, cookies)
            return

        if path.startswith("/api/dev-login/") and DEV:
            login = path.rsplit("/", 1)[-1]
            user = find_user(login)
            if not user:
                self._err("нет логина", 404)
                return
            token = _new_session(login, str(user.get("цех")))
            target = "/" + ("#/" + str(query["to"][0]) if query.get("to") else "")
            self.send_response(302)
            self.send_header("Set-Cookie", f"v2sid={token}; Path=/; HttpOnly; SameSite=Lax")
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if me is None:
            self._err("нужна авторизация", 401)
            return
        role, comp = str(me.get("роль")), str(me.get("цех"))

        if path == "/api/brand" and method == "POST":
            if not can(me, "brand.manage"):
                self._err("менять оформление может только начальник", 403)
                return
            body = self._body()
            try:
                import warehouse
                saved = warehouse.save_brand({k: str(body.get(k, "")) for k in
                                              ("название", "подзаголовок", "логотип")})
                self._json({"ok": True, "data": saved})
            except Exception as exc:  # noqa: BLE001
                self._err(f"не удалось сохранить: {exc}", 500)
            return

        if path == "/api/brand/logo" and method == "POST":
            if not can(me, "brand.manage"):
                self._err("менять логотип может только начальник", 403)
                return
            body = self._body()
            import base64, re as _re
            raw = str(body.get("данные", ""))
            if "," in raw[:100]:
                raw = raw.split(",", 1)[1]
            ext = str(body.get("ext", "png")).lower()
            if ext not in ("png", "jpg", "jpeg", "webp", "svg"):
                self._err("поддерживаются PNG, JPG, WEBP, SVG")
                return
            try:
                data = base64.b64decode(raw, validate=True)
            except Exception:
                self._err("файл повреждён")
                return
            if len(data) > 2_000_000:
                self._err("файл больше 2 МБ")
                return
            name = "logo." + ("jpg" if ext == "jpeg" else ext)
            (STATIC / name).write_bytes(data)
            try:
                import warehouse
                warehouse.save_brand({"логотип": name})
            except Exception:
                pass
            self._json({"ok": True, "data": {"логотип": name, "url": "/static/" + name}})
            return

        if path == "/api/me":
            import json as _json
            cfg = {}
            try:
                cfg = _json.loads((BASE / "config.json").read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
            self._json({
                "ok": True, "user": public_user(me), "caps": {**{k: can(me, k) for k in perms.CODES}, "users.manage": can(me, "staff.edit")},
                "visible": cfg.get("visible", ["wh"]),
                "client_visible": cfg.get("client_visible", []),
                "roles": ROLE_LABELS, "company": active_company(comp),
                "periods": [{"код": p.get("код"), "название": p.get("название")} for p in periods()],
            })
            return

        if path == "/api/logout" and method == "POST":
            token = self._cookie("v2sid")
            with SESSIONS_LOCK:
                SESSIONS.pop(token, None)
            _save_sessions()
            rest = [t for t in self._acc_tokens() if t != token]
            self._send_json_cookies({"ok": True}, ["v2sid=; Path=/; Max-Age=0", self._acc_cookie(rest)])
            return

        if path == "/api/sync/pull" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа к данным склада", 403)
                return
            try:
                import warehouse
                self._json({"ok": True, "data": warehouse.snapshot()})
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад недоступен: {exc}", 500)
            return

        if path == "/api/sync/push" and method == "POST":
            if not can(me, "wh.write"):
                self._err("нет прав на операции склада", 403)
                return
            body = self._body()
            try:
                import warehouse
                res = warehouse.apply_ops(body.get("ops") or [],
                                          str(me.get("фио", "")),
                                          str(body.get("base_version", "")))
                self._json({"ok": True, **res})
            except ValueError as exc:
                self._err(str(exc))
            except Exception as exc:  # noqa: BLE001
                self._err(f"синхронизация: {exc}", 500)
            return

        if path == "/api/dashboard":
            self._json({"ok": True, "data": dashboard(me)})
            return

        if path == "/api/batches" and method == "GET":
            rows = [batch_view(b) for b in read_table("batches") if str(b.get("цех")) == comp]
            self._json({"ok": True, "data": sorted(rows, key=lambda b: -b["номер"])})
            return

        if path == "/api/batches" and method == "POST":
            if not can(me, "batches.create"):
                self._err("нет прав создавать партии", 403)
                return
            body = self._body()
            art = str(body.get("артикул", "")).strip()
            разделы = body.get("разделы") or []
            if not art:
                self._err("Укажи наименование изделия")
                return
            if not isinstance(разделы, list) or not разделы:
                self._err("Добавь хотя бы один раздел партии")
                return
            clean = []
            for s in разделы:
                qty = as_num(s.get("количество"))
                if qty <= 0:
                    continue
                clean.append({"цвет": str(s.get("цвет", "")).strip(),
                              "тон": str(s.get("тон", "")).strip(),
                              "размер": str(s.get("размер", "")).strip(),
                              "количество": qty})
            if not clean:
                self._err("Во всех разделах нулевое количество")
                return
            nums = [int(b["номер"]) for b in read_table("batches") if str(b.get("номер", "")).isdigit()]
            num = (max(nums) + 1) if nums else 1
            rows = read_table("batches")
            rows.append({"номер": num, "цех": comp, "артикул": art,
                         "клиент": str(body.get("клиент", "")).strip(), "статус": "в работе",
                         "технолог": str(me.get("логин")), "дата_создания": today(),
                         "срок": str(body.get("срок", "")), "примечание": str(body.get("примечание", ""))})
            write_table("batches", rows)
            sec_rows = read_table("sections")
            for i, s in enumerate(clean, start=1):
                sec_rows.append({"партия": num, "раздел": i, **s})
            write_table("sections", sec_rows)
            self._json({"ok": True, "номер": num, "разделов": len(clean)})
            return

        m = re.match(r"^/api/batches/(\d+)$", path)
        if m and method == "GET":
            data = batch_detail(int(m.group(1)), me)
            if not data or data["цех"] != comp:
                self._err("партия не найдена", 404)
                return
            self._json({"ok": True, "data": data})
            return

        if path == "/api/tasks":
            self._json({"ok": True, "data": my_tasks(me)})
            return

        if path == "/api/passes" and method == "POST":
            if not can(me, "passes.take"):
                self._err("нет прав", 403)
                return
            body = self._body()
            num, sec = int(as_num(body.get("партия"))), int(as_num(body.get("раздел")))
            code = str(body.get("процесс", ""))
            qty = as_num(body.get("количество"))
            batch = batch_map().get(num)
            if not batch or str(batch.get("цех")) != comp:
                self._err("партия не найдена", 404)
                return
            proc = next((p for p in chain_for(str(batch.get("артикул", ""))) if str(p.get("код")) == code), None)
            if not proc:
                self._err("процесс не найден", 404)
                return
            section = next((s for s in batch_sections(num) if int(as_num(s.get("раздел"))) == sec), None)
            if not section:
                self._err("раздел не найден", 404)
                return
            need = as_num(section.get("количество")) - done_qty(num, sec, code)
            if qty <= 0:
                qty = need
            if qty > need:
                self._err(f"Осталось всего {need:g} шт")
                return
            if not deps_ready(num, sec, proc, as_num(section.get("количество"))):
                self._err("Сначала должны быть готовы предыдущие процессы")
                return
            restricted = (str(proc.get("склад_гп", "0")) in ("1", "True", "true")
                          or str(proc.get("код")) == "ОТГРУЗ")
            if restricted and role not in ("storekeeper", "admin", "manager"):
                self._err("Этот этап принимает склад готовой продукции", 403)
                return
            if in_progress(num, sec, code):
                self._err("Этот процесс уже кто-то выполняет")
                return
            rows = read_table("passes")
            pid = max([int(as_num(r.get("id"))) for r in rows] + [0]) + 1
            rows.append({"id": pid, "дата": today(), "партия": num, "раздел": sec, "процесс": code,
                         "логин": me.get("логин"), "фио": me.get("фио"), "количество": qty,
                         "тариф": as_num(proc.get("тариф")),
                         "сумма": round(qty * as_num(proc.get("тариф")), 2),
                         "начало": now_str(), "конец": "", "статус": "в работе", "комментарий": ""})
            write_table("passes", rows)
            self._json({"ok": True, "id": pid})
            return

        m = re.match(r"^/api/passes/(\d+)/(finish|minus)$", path)
        if m and method == "POST":
            pid, action = int(m.group(1)), m.group(2)
            rows = read_table("passes")
            row = next((r for r in rows if int(as_num(r.get("id"))) == pid), None)
            if not row:
                self._err("операция не найдена", 404)
                return
            if str(row.get("логин")) != str(me.get("логин")) and role not in ("admin", "manager"):
                self._err("это не твоя операция", 403)
                return
            if action == "minus":
                qty = as_num(self._body().get("количество")) or 1
                append_row("minus", {"дата": now_str(), "партия": row.get("партия"),
                                     "раздел": row.get("раздел"), "процесс": row.get("процесс"),
                                     "количество": qty, "логин": me.get("логин"),
                                     "комментарий": "минус при передаче"})
                self._json({"ok": True})
                return
            row["статус"] = "готово"
            row["конец"] = now_str()
            write_table("passes", rows)
            proc = process_map().get(str(row.get("процесс")))
            if proc and str(proc.get("склад_гп", "0")) in ("1", "True", "true"):
                append_row("finished", {"дата": today(), "партия": row.get("партия"),
                                        "раздел": row.get("раздел"),
                                        "количество": row.get("количество"), "кто": me.get("фио")})
            self._json({"ok": True, "сумма": as_num(row.get("сумма"))})
            return

        if path == "/api/checks" and method == "POST":
            if not can(me, "checks.create"):
                self._err("нет прав", 403)
                return
            body = self._body()
            num, sec = int(as_num(body.get("партия"))), int(as_num(body.get("раздел")))
            score = as_num(body.get("оценка"))
            if score < 1 or score > 5:
                self._err("Оценка от 1 до 5")
                return
            append_row("checks", {"дата": now_str(), "партия": num, "раздел": sec,
                                  "технолог": me.get("фио"), "оценка": int(score),
                                  "комментарий": str(body.get("комментарий", "")).strip()})
            self._json({"ok": True})
            return

        if path == "/api/materials" and method == "GET":
            if not can(me, "materials.view"):
                self._err("нет прав", 403)
                return
            items = read_table("materials")
            for i in items:
                i["сумма"] = round(as_num(i.get("количество")) * as_num(i.get("цена")), 2)
            self._json({"ok": True, "data": items,
                        "moves": list(reversed(read_table("moves")))[:40]})
            return

        if path == "/api/materials/move" and method == "POST":
            if not can(me, "materials.move"):
                self._err("нет прав", 403)
                return
            body = self._body()
            art = str(body.get("артикул", "")).strip()
            kind = str(body.get("тип", ""))
            qty = as_num(body.get("количество"))
            if kind not in ("приход", "расход"):
                self._err("Тип: приход или расход")
                return
            if qty <= 0:
                self._err("Количество больше нуля")
                return
            items = read_table("materials")
            item = next((i for i in items if str(i.get("артикул")) == art), None)
            if not item:
                self._err("артикул не найден", 404)
                return
            cur = as_num(item.get("количество"))
            if kind == "расход" and qty > cur:
                self._err(f"Остаток всего {cur:g} {item.get('ед', '')}")
                return
            item["количество"] = cur + qty if kind == "приход" else cur - qty
            write_table("materials", items)
            append_row("moves", {"дата": today(), "артикул": art, "тип": kind, "количество": qty,
                                 "партия": str(body.get("партия", "")), "кто": me.get("фио"),
                                 "комментарий": str(body.get("комментарий", ""))})
            self._json({"ok": True, "остаток": item["количество"]})
            return

        if path == "/api/materials/item" and method == "POST":
            if not can(me, "materials.move"):
                self._err("нет прав", 403)
                return
            body = self._body()
            art = str(body.get("артикул", "")).strip()
            if not art:
                self._err("Укажи артикул")
                return
            items = read_table("materials")
            if any(str(i.get("артикул")) == art for i in items):
                self._err("Такой артикул уже есть")
                return
            items.append({"артикул": art, "название": str(body.get("название", "")),
                          "количество": as_num(body.get("количество")), "ед": str(body.get("ед") or "шт"),
                          "цена": as_num(body.get("цена")), "поставщик": str(body.get("поставщик", ""))})
            write_table("materials", items)
            self._json({"ok": True})
            return

        if path == "/api/finished" and method == "GET":
            if not can(me, "finished.view"):
                self._err("нет прав", 403)
                return
            batches = {int(b["номер"]): b for b in read_table("batches") if str(b.get("цех")) == comp}
            fin = [f for f in read_table("finished") if int(as_num(f.get("партия"))) in batches]
            ship = [s for s in read_table("shipments") if int(as_num(s.get("партия"))) in batches]
            grouped = {}
            for f in fin:
                key = int(as_num(f.get("партия")))
                grouped.setdefault(key, {"партия": key, "артикул": batches[key].get("артикул"),
                                         "принято": 0.0, "отгружено": 0.0, "сумма": 0.0})
                grouped[key]["принято"] += as_num(f.get("количество"))
            for s in ship:
                key = int(as_num(s.get("партия")))
                if key in grouped:
                    grouped[key]["отгружено"] += as_num(s.get("количество"))
                    grouped[key]["сумма"] += as_num(s.get("сумма"))
            self._json({"ok": True, "data": sorted(grouped.values(), key=lambda g: -g["партия"]),
                        "отгрузки": list(reversed(ship))[:30]})
            return

        if path == "/api/shipments" and method == "POST":
            if not can(me, "shipments.create"):
                self._err("нет прав", 403)
                return
            body = self._body()
            num, qty = int(as_num(body.get("партия"))), as_num(body.get("количество"))
            if qty <= 0:
                self._err("Количество больше нуля")
                return
            t = batch_totals(num)
            free = t["на_складе"] - t["отгружено"]
            if qty > free:
                self._err(f"На складе свободно {free:g} шт")
                return
            append_row("shipments", {"дата": today(), "партия": num, "количество": qty,
                                     "покупатель": str(body.get("покупатель", "")),
                                     "сумма": as_num(body.get("сумма"))})
            self._json({"ok": True})
            return

        if path == "/api/payroll" and method == "GET":
            period = query.get("период", [""])[0]
            month = query.get("месяц", [""])[0]
            data = payroll(me, period, month, scope_all=can(me, "payroll.all"))
            months = sorted({month_key(p.get("дата")) for p in read_table("passes") if month_key(p.get("дата"))},
                            reverse=True)
            self._json({"ok": True, "data": data, "месяцы": months})
            return

        if path == "/api/analytics":
            if not can(me, "analytics.view"):
                self._err("нет прав", 403)
                return
            self._json({"ok": True, "data": analytics(me)})
            return

        if path == "/api/shop/ops" and method == "GET":
            rows = read_table("operations")
            kind = query.get("тип", [""])[0]
            for r in rows:
                r["отменена"] = str(r.get("отменена", "0")) in ("1", "True", "true")
            if kind:
                rows = [r for r in rows if str(r.get("тип")) == kind]
            self._json({"ok": True, "data": list(reversed(rows))[:300],
                        "итоги": {"всего": len(rows),
                                  "активных": len([r for r in rows if not r["отменена"]])}})
            return

        if path == "/api/shop/ops" and method == "POST":
            if not can(me, "shop.stock"):
                self._err("операции по складу делает склад, менеджер или начальник", 403)
                return
            body = self._body()
            kind = str(body.get("тип", ""))
            if kind not in ("приход", "поставка", "перевод", "корректировка"):
                self._err("Неизвестный тип операции")
                return
            qty = as_num(body.get("количество"))
            if kind == "корректировка":
                if qty == 0:
                    self._err("Количество не может быть нулевым")
                    return
            elif qty <= 0:
                self._err("Количество должно быть больше нуля")
                return
            products = read_table("products")
            item = next((p for p in products if str(p.get("id")) == str(body.get("id_товара"))), None)
            if item is None:
                item = next((p for p in products if str(p.get("наименование")) == str(body.get("наименование"))), None)
            if item is None:
                self._err("Товар не найден", 404)
                return
            have = as_num(item.get("количество"))
            if kind in ("поставка", "перевод") and qty > have:
                self._err(f"{item.get('наименование')}: на складе всего {have:g} шт")
                return
            delta = 0.0
            if kind == "приход":
                delta = qty
            elif kind == "поставка":
                delta = -qty
            elif kind == "корректировка":
                delta = qty
            if delta:
                item["количество"] = max(0.0, have + delta)
                write_table("products", products)
            rows = read_table("operations")
            oid = max([int(as_num(r.get("id"))) for r in rows] + [0]) + 1
            rows.append({"id": oid, "дата": now_str(), "тип": kind,
                         "id_товара": item.get("id"), "наименование": item.get("наименование"),
                         "количество": qty, "откуда": str(body.get("откуда", "")),
                         "куда": str(body.get("куда", "")), "контрагент": str(body.get("контрагент", "")),
                         "комментарий": str(body.get("комментарий", "")), "кто": me.get("фио"),
                         "отменена": 0})
            write_table("operations", rows)
            if kind == "приход":
                boxes = read_table("boxes")
                bid = max([int(as_num(b.get("id"))) for b in boxes] + [0]) + 1
                number = str(body.get("коробка") or "").strip() or f"K-{bid:04d}"
                boxes.append({"id": bid, "дата": today(), "коробка": number,
                              "id_товара": item.get("id"), "наименование": item.get("наименование"),
                              "количество": qty, "проверка": "Nice✅", "кто": me.get("фио")})
                write_table("boxes", boxes)
            self._json({"ok": True, "id": oid, "остаток": item["количество"]})
            return

        if path == "/api/shop/ops/cancel" and method == "POST":
            if not can(me, "shop.stock"):
                self._err("нет прав", 403)
                return
            oid = int(as_num(self._body().get("id")))
            rows = read_table("operations")
            row = next((r for r in rows if int(as_num(r.get("id"))) == oid), None)
            if not row:
                self._err("операция не найдена", 404)
                return
            if str(row.get("отменена", "0")) in ("1", "True", "true"):
                self._err("операция уже отменена")
                return
            qty = as_num(row.get("количество"))
            kind = str(row.get("тип"))
            products = read_table("products")
            item = next((p for p in products if str(p.get("id")) == str(row.get("id_товара"))), None)
            if item is not None:
                delta = 0.0
                if kind == "приход":
                    delta = -qty
                elif kind == "поставка":
                    delta = qty
                elif kind == "корректировка":
                    delta = -qty
                if delta:
                    item["количество"] = max(0.0, as_num(item.get("количество")) + delta)
                    write_table("products", products)
            row["отменена"] = 1
            write_table("operations", rows)
            self._json({"ok": True, "тип": kind, "количество": qty})
            return

        if path == "/api/shop/boxes" and method == "GET":
            rows = read_table("boxes")
            checked = len([r for r in rows if str(r.get("проверка", "")).startswith("Nice")])
            self._json({"ok": True, "data": list(reversed(rows))[:300],
                        "итоги": {"коробок": len(rows), "проверено": checked,
                                  "штук": sum(as_num(r.get("количество")) for r in rows)}})
            return

        if path == "/api/shop/boxes/check" and method == "POST":
            if not can(me, "shop.stock"):
                self._err("нет прав", 403)
                return
            body = self._body()
            bid = int(as_num(body.get("id")))
            rows = read_table("boxes")
            row = next((r for r in rows if int(as_num(r.get("id"))) == bid), None)
            if not row:
                self._err("коробка не найдена", 404)
                return
            row["проверка"] = "Nice✅" if body.get("проверка") else "—"
            write_table("boxes", rows)
            self._json({"ok": True})
            return

        if path == "/api/shop/locations" and method == "GET":
            locs = ["Основной склад", "ЖСК", "ААТ", "ККМ", "Магазин"]
            ops = [o for o in read_table("operations")
                   if str(o.get("отменена", "0")) not in ("1", "True", "true")]
            bal = {l: 0.0 for l in locs}
            for o in ops:
                qty = as_num(o.get("количество"))
                kind = str(o.get("тип"))
                src, dst = str(o.get("откуда")), str(o.get("куда"))
                if kind == "приход":
                    bal[dst if dst in bal else "Основной склад"] += qty
                elif kind == "поставка":
                    bal[src if src in bal else "Основной склад"] -= qty
                elif kind == "перевод":
                    if src in bal:
                        bal[src] -= qty
                    if dst in bal:
                        bal[dst] += qty
            self._json({"ok": True, "data": [{"локация": k, "движение": round(v, 2)} for k, v in bal.items()]})
            return

        if path == "/api/employees":
            if not (can(me, "staff.view") or can(me, "batches.create")):
                self._err("нет прав", 403)
                return
            self._json({"ok": True, "data": [public_user(u) for u in staff_users()
                                             if str(u.get("цех")) == comp]})
            return

        if path == "/api/users" and method == "GET":
            if not can(me, "staff.view"):
                self._err("нет прав", 403)
                return
            self._json({"ok": True, "data": [public_user(u) for u in staff_users()
                                             if str(u.get("цех")) == comp]})
            return

        if path in ("/api/users", "/api/users/delete") and method == "POST":
            # те же проверки, что в разделе «Сотрудники» цеха: цех, роль, последний админ
            import cex_api
            import perms as _perms
            body = self._body()
            if path.endswith("/delete"):
                body = {"логин": body.get("логин"), "активен": False}
            elif "активен" in body:
                body["активен"] = bool(body.get("активен"))
            try:
                if not str(body.get("логин", "")).strip():
                    raise ValueError("Укажи логин")
                cex_api.save_account(me, body)
            except _perms.AccessError as exc:
                self._err(str(exc), 403)
                return
            except ValueError as exc:
                self._err(str(exc))
                return
            self._json({"ok": True})
            return

        if path == "/api/announcements" and method == "GET":
            rows = [a for a in read_table("announcements")
                    if str(a.get("цех")) == comp and str(a.get("активен", "1")) in ("1", "True", "true")]
            self._json({"ok": True, "data": list(reversed(rows))})
            return

        if path == "/api/announcements" and method == "POST":
            if not can(me, "announce.create"):
                self._err("нет прав", 403)
                return
            text = str(self._body().get("текст", "")).strip()
            if not text:
                self._err("Текст пустой")
                return
            append_row("announcements", {"дата": today(), "логин": me.get("логин"),
                                         "фио": me.get("фио"), "цех": comp,
                                         "текст": text, "активен": 1})
            self._json({"ok": True})
            return

        if path == "/api/shop" and method == "GET":
            try:
                import shop_sync
                with WRITE_LOCK:  # перезаписывает products.xlsx — не пересекаться с продажей
                    shop_sync.sync_if_changed()
                shop_state = shop_sync.status()
            except Exception as exc:  # noqa: BLE001
                shop_state = {"error": str(exc)}
            items = read_table("products")
            # остаток магазина = фактический остаток склада − активные продажи
            wh_stock = {}
            try:
                import warehouse
                wh_stock = {i["наименование"]: i["остаток"] for i in warehouse.stock_items()}
            except Exception:
                wh_stock = {}
            free = {}
            try:
                import warehouse
                free = warehouse.available_for_order()
            except Exception:
                free = {}
            sold = {}
            for sale in read_table("sales"):
                if str(sale.get("отменена", "0")) in ("1", "True", "true"):
                    continue
                key = str(sale.get("наименование"))
                sold[key] = sold.get(key, 0.0) + as_num(sale.get("количество"))
            for it in items:
                it["цена"] = as_num(it.get("цена"))
                name = str(it.get("наименование"))
                if wh_stock:
                    it["количество"] = round(max(0.0, wh_stock.get(name, 0.0) - sold.get(name, 0.0)), 2)
                    it["доступно"] = round(free.get(name, it["количество"]), 2)
                    it["склад"] = round(wh_stock.get(name, 0.0), 2)
                    it["пересорт"] = round(max(0.0, -wh_stock.get(name, 0.0)), 2)
                else:
                    it["количество"] = as_num(it.get("количество"))
            cats = sorted({str(i.get("категория")) for i in items if str(i.get("категория"))})
            colors = sorted({str(i.get("цвет")).split(",")[0].strip()
                             for i in items if str(i.get("цвет")).strip()})
            sizes = sorted({str(i.get("размер")) for i in items if str(i.get("размер")).strip()},
                           key=size_sort_key)
            sales = list(reversed(read_table("sales")))[:25]
            self._json({
                "ok": True, "data": items, "категории": cats, "цвета": colors,
                "размеры": sizes, "продажи": sales,
                "итоги": {"позиций": len(items),
                          "в_наличии": len([i for i in items if i["количество"] > 0]),
                          # «штук» — истинный остаток склада (как в «главном»), минус не скрываем
                          "штук": round(sum(i.get("склад", i["количество"]) for i in items), 2),
                          "свободно": round(sum(i["количество"] for i in items), 2),
                          "пересорт": round(sum(i.get("пересорт", 0) for i in items), 2),
                          "сумма": round(sum(i["количество"] * i["цена"] for i in items), 2)},
                "источник": shop_state,
            })
            return

        if path == "/api/shop/sale" and method == "POST":
            if not can(me, "shop.sell"):
                self._err("продажи оформляет склад или менеджер", 403)
                return
            body = self._body()
            lines = body.get("позиции") or []
            buyer = str(body.get("покупатель", "")).strip() or "розница"
            products = read_table("products")
            index = {str(p.get("id")): p for p in products}
            prepared = []
            for line in lines if isinstance(lines, list) else []:
                item = index.get(str(line.get("id")))
                qty = as_num(line.get("количество"))
                if not item or qty <= 0:
                    continue
                have = as_num(item.get("количество"))
                if qty > have:
                    self._err(f"{item.get('наименование')}: в наличии {have:g} шт")
                    return
                prepared.append((item, qty))
            if not prepared:
                self._err("Корзина пуста")
                return
            for item, qty in prepared:
                item["количество"] = as_num(item.get("количество")) - qty
            write_table("products", products)
            rows = read_table("sales")
            next_id = max([int(as_num(r.get("id"))) for r in rows] + [0]) + 1
            total = 0.0
            for item, qty in prepared:
                price = as_num(item.get("цена"))
                summ = round(qty * price, 2)
                total += summ
                rows.append({"id": next_id, "дата": now_str(), "id_товара": item.get("id"),
                             "наименование": item.get("наименование"), "количество": qty,
                             "цена": price, "сумма": summ, "покупатель": buyer,
                             "кто": me.get("фио"), "отменена": 0})
                next_id += 1
            write_table("sales", rows)
            self._json({"ok": True, "сумма": round(total, 2), "позиций": len(prepared),
                        "ids": [r["id"] for r in rows[-len(prepared):]]})
            return

        if path == "/api/shop/price" and method == "POST":
            if not can(me, "shop.price"):
                self._err("цену меняет начальник или менеджер", 403)
                return
            body = self._body()
            pid = str(body.get("id"))
            price = as_num(body.get("цена"))
            if price < 0:
                self._err("Цена не может быть отрицательной")
                return
            products = read_table("products")
            item = next((p for p in products if str(p.get("id")) == pid), None)
            if not item:
                self._err("товар не найден", 404)
                return
            item["цена"] = price
            write_table("products", products)
            self._json({"ok": True})
            return

        if path == "/api/sales" and method == "GET":
            rows = read_table("sales")
            for r in rows:
                r["отменена"] = str(r.get("отменена", "0")) in ("1", "True", "true")
            active = [r for r in rows if not r["отменена"]]
            today_s = date.today().strftime("%d.%m.%Y")
            today_rows = [r for r in active if str(r.get("дата", "")).startswith(today_s)]
            self._json({
                "ok": True,
                "data": list(reversed(rows))[:200],
                "итоги": {
                    "продаж": len(active),
                    "штук": sum(as_num(r.get("количество")) for r in active),
                    "сумма": round(sum(as_num(r.get("сумма")) for r in active), 2),
                    "сегодня_продаж": len(today_rows),
                    "сегодня_сумма": round(sum(as_num(r.get("сумма")) for r in today_rows), 2),
                },
            })
            return

        if path == "/api/sales/cancel" and method == "POST":
            if not can(me, "shop.sell"):
                self._err("отменять продажи может склад, менеджер или начальник", 403)
                return
            body = self._body()
            sid = int(as_num(body.get("id")))
            rows = read_table("sales")
            row = next((r for r in rows if int(as_num(r.get("id"))) == sid), None)
            if not row:
                self._err("продажа не найдена", 404)
                return
            if str(row.get("отменена", "0")) in ("1", "True", "true"):
                self._err("эта продажа уже отменена")
                return
            qty = as_num(row.get("количество"))
            products = read_table("products")
            name = str(row.get("наименование"))
            item = next((p for p in products if str(p.get("id")) == str(row.get("id_товара"))), None)
            if item is None:
                item = next((p for p in products if str(p.get("наименование")) == name), None)
            if item is not None:
                item["количество"] = as_num(item.get("количество")) + qty
                write_table("products", products)
            row["отменена"] = 1
            write_table("sales", rows)
            self._json({"ok": True, "вернулось": qty, "товар": name})
            return

        if path.startswith("/api/wh/") and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа к складу", 403)
                return
            try:
                import warehouse
            except Exception as exc:  # noqa: BLE001
                self._err(f"модуль склада недоступен: {exc}", 500)
                return
            try:
                if path == "/api/wh/meta":
                    self._json({"ok": True, "data": warehouse.meta()})
                    return
                if path == "/api/wh/stock":
                    items = warehouse.stock_items()
                    if query.get("только", ["1"])[0] == "1":
                        items = [i for i in items if i["остаток"] != 0]  # минус (пересорт) тоже показываем
                    self._json({"ok": True, "data": items,
                                "итоги": {"позиций": len(items),
                                          "штук": round(sum(i["остаток"] for i in items), 2)}})
                    return
                if path == "/api/wh/address":
                    self._json({"ok": True, "data": warehouse.addresses()})
                    return
                if path == "/api/wh/shipments":
                    target = query.get("получатель", ["ЖСК"])[0]
                    self._json({"ok": True, "data": warehouse.shipments(target)})
                    return
                if path == "/api/wh/purchases":
                    self._json({"ok": True, "data": warehouse.purchases()})
                    return
                if path == "/api/wh/sync_status":
                    self._json({"ok": True, "data": warehouse.flush_status()})
                    return
                if path == "/api/wh/negatives":
                    self._json({"ok": True, "data": warehouse.negatives()})
                    return
                if path == "/api/wh/verify":
                    items = warehouse.stock_items()
                    rows = [{
                        "наименование": i["наименование"],
                        "файл": i["фк"],
                        "списано_wb": i.get("фbs", 0),
                        "на_сайте": i["остаток"],
                    } for i in items if i.get("фbs", 0) or i["фк"]]
                    rows.sort(key=lambda r: (r["на_сайте"], -r["списано_wb"]))
                    self._json({"ok": True, "data": rows[:300],
                                "итоги": {
                                    "позиций": len(rows),
                                    "файл": round(sum(r["файл"] for r in rows), 2),
                                    "списано_wb": round(sum(r["списано_wb"] for r in rows), 2),
                                    "на_сайте": round(sum(r["на_сайте"] for r in rows), 2),
                                    "минусов": sum(1 for r in rows if r["на_сайте"] < 0),
                                }})
                    return
                if path == "/api/wh/find":
                    q = query.get("q", [""])[0]
                    variants = warehouse.find_many(q)
                    self._json({"ok": True, "data": variants[0] if variants else None,
                                "вариантов": len(variants),
                                "подсказки": [{"наименование": v["наименование"],
                                               "остаток": v["остаток"], "ожидает": v["ожидает"]}
                                              for v in variants[:5]]})
                    return
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад: {exc}", 500)
                return
            self._err("неизвестный запрос", 404)
            return

        if path.startswith("/api/wh/") and method == "POST":
            if not can(me, "wh.write"):
                self._err("операции по складу делает склад, менеджер или начальник", 403)
                return
            try:
                import warehouse
            except Exception as exc:  # noqa: BLE001
                self._err(f"модуль склада недоступен: {exc}", 500)
                return
            body = self._body()
            try:
                if path == "/api/wh/receive":
                    res = warehouse.receive(
                        str(body.get("поставщик", "")), str(body.get("наименование", "")),
                        as_num(body.get("количество")), as_num(body.get("неликвид")),
                        str(body.get("партия", "")))
                    self._json({"ok": True, **res})
                    return
                if path == "/api/wh/place":
                    res = warehouse.place(
                        str(body.get("коробка", "")), str(body.get("наименование", "")),
                        as_num(body.get("количество")))
                    self._json({"ok": True, **res})
                    return
                if path == "/api/wh/receive_multi":
                    res = warehouse.receive_multi(
                        str(body.get("поставщик", "")), str(body.get("партия", "")),
                        as_num(body.get("неликвид")), body.get("позиции") or [])
                    self._json({"ok": True, **res})
                    return
                if path == "/api/wh/export":
                    res = warehouse.export_to_excel(str(me.get("фио", "")))
                    self._json({"ok": True, **res})
                    return
                if path == "/api/wh/ship":
                    res = warehouse.ship(
                        str(body.get("получатель", "")), str(body.get("наименование", "")),
                        as_num(body.get("количество")), str(body.get("заказ", "")),
                        str(me.get("фио", "")))
                    self._json({"ok": True, **res})
                    return
            except ValueError as exc:
                self._err(str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад: {exc}", 500)
                return
            self._err("неизвестный запрос", 404)
            return

        if path == "/api/wb/orders" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            try:
                import wb_sync
                status = query.get("статус", [""])[0] or None
                cab = query.get("кабинет", [""])[0] or None
                self._json({"ok": True, "data": wb_sync.list_orders(status, cab),
                            "счётчики": wb_sync.counts()})
            except Exception as exc:  # noqa: BLE001
                self._err(f"заказы WB: {exc}", 500)
            return

        if path == "/api/fbs/aggregate" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            try:
                import wb_sync
                self._json({"ok": True, "data": wb_sync.aggregate_order()})
            except Exception as exc:  # noqa: BLE001
                self._err(f"заказы FBS: {exc}", 500)
            return

        if path == "/api/wb/confirm-items" and method == "POST":
            if not can(me, "wb.manage"):
                self._err("нет прав", 403)
                return
            body = self._body()
            ids = body.get("items") or []
            if not isinstance(ids, list) or not ids:
                self._err("не выбрано ни одной позиции")
                return
            try:
                import wb_sync
                self._json({"ok": True, **wb_sync.confirm_items([str(i) for i in ids],
                                                                str(me.get("фио", "")))})
            except Exception as exc:  # noqa: BLE001
                self._err(f"подтверждение: {exc}", 500)
            return

        if path == "/api/fbs/pickable" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            try:
                import wb_sync
                rows = wb_sync.pickable()
                self._json({"ok": True, "data": rows,
                            "итоги": {"к_сборке": sum(1 for r in rows if r["can_pick"] and not r["picked"]),
                                      "собрано": sum(1 for r in rows if r["picked"]),
                                      "нет_в_наличии": sum(1 for r in rows if not r["can_pick"])}})
            except Exception as exc:  # noqa: BLE001
                self._err(f"сборка FBS: {exc}", 500)
            return

        if path == "/api/fbs/pick" and method == "POST":
            if not can(me, "wb.manage"):
                self._err("собирать заказы может склад, менеджер или начальник", 403)
                return
            body = self._body()
            oid = str(body.get("id", ""))
            if not oid:
                raw = str(body.get("скан", "")).strip()
                try:
                    import wb_sync
                    candidates = [r for r in wb_sync.pickable()
                                  if r["status"] == "new" and
                                  (raw and (raw == r["sku"] or raw.lower() == (r["title"] or "").lower()))]
                    if not candidates:
                        self._err("по этому коду нет новых заказов")
                        return
                    oid = candidates[0]["id"]
                except ValueError as exc:
                    self._err(str(exc))
                    return
            try:
                import wb_sync
                self._json({"ok": True, **wb_sync.pick(oid, str(me.get("фио", "")))})
            except ValueError as exc:
                self._err(str(exc))
            except Exception as exc:  # noqa: BLE001
                self._err(f"сборка: {exc}", 500)
            return

        if path == "/api/wb/sync" and method == "POST":
            if not can(me, "wb.manage"):
                self._err("обновлять заказы может склад, менеджер или начальник", 403)
                return
            try:
                import wb_sync
                res = wb_sync.sync(actor=str(me.get("фио", "")))
                self._json({"ok": True, **res})
            except Exception as exc:  # noqa: BLE001
                self._err(f"синхронизация WB: {exc}", 500)
            return

        if path == "/api/wb/confirm" and method == "POST":
            if not can(me, "wb.manage"):
                self._err("подтверждать может склад, менеджер или начальник", 403)
                return
            body = self._body()
            ids = body.get("ids") or []
            if not isinstance(ids, list) or not ids:
                self._err("не выбрано ни одного заказа")
                return
            try:
                import wb_sync
                res = wb_sync.confirm([str(i) for i in ids], actor=str(me.get("фио", "")))
                self._json({"ok": True, **res})
            except Exception as exc:  # noqa: BLE001
                self._err(f"подтверждение: {exc}", 500)
            return

        if path == "/api/wb/cabinets" and method == "GET":
            if not can(me, "wb.manage") and not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            import cabinets_store
            self._json({"ok": True, "data": cabinets_store.cabinets()})
            return

        if path == "/api/wb/cabinets" and method == "POST":
            if not can(me, "wb.manage"):
                self._err("настраивать кабинеты может склад, менеджер или начальник", 403)
                return
            body = self._body()
            try:
                import cabinets_store
                res = cabinets_store.save_cabinet(
                    str(body.get("id", "")), str(body.get("name", "")),
                    body.get("token") if body.get("token") else None,
                    body.get("active") if "active" in body else None)
                self._json({"ok": True, **res})
            except ValueError as exc:
                self._err(str(exc))
            return

        if path == "/api/wb/cabinets/delete" and method == "POST":
            if not can(me, "wb.manage"):
                self._err("нет прав", 403)
                return
            try:
                import cabinets_store
                cabinets_store.remove_cabinet(str(self._body().get("id", "")))
                self._json({"ok": True})
            except ValueError as exc:
                self._err(str(exc))
            return

        if path == "/api/orders" and method == "GET":
            try:
                import warehouse
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад недоступен: {exc}", 500)
                return
            if role == "client":
                self._json({"ok": True, "data": warehouse.orders(client=str(me.get("фио")))})
                return
            if not can(me, "orders.view"):
                self._err("нет доступа к заказам", 403)
                return
            self._json({"ok": True, "data": warehouse.orders()})
            return

        if path == "/api/orders/pick" and method == "POST":
            if not can(me, "orders.view"):
                self._err("нет прав", 403)
                return
            try:
                import warehouse
                body = self._body()
                res = warehouse.pick_order(int(as_num(body.get("id"))),
                                           body.get("позиции") or [],
                                           str(me.get("фио", "")))
                self._json({"ok": True, **res})
            except ValueError as exc:
                self._err(str(exc))
            except Exception as exc:  # noqa: BLE001
                self._err(f"сборка: {exc}", 500)
            return

        if path == "/api/orders/ship" and method == "POST":
            if not can(me, "orders.view"):
                self._err("нет прав", 403)
                return
            try:
                import warehouse
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад недоступен: {exc}", 500)
                return
            body = self._body()
            try:
                res = warehouse.order_ship(int(as_num(body.get("id"))),
                                           str(body.get("наименование", "")),
                                           as_num(body.get("количество")),
                                           str(me.get("фио", "")))
                self._json({"ok": True, **res})
            except ValueError as exc:
                self._err(str(exc))
            return

        if path == "/api/orders/cancel" and method == "POST":
            try:
                import warehouse
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад недоступен: {exc}", 500)
                return
            body = self._body()
            oid = int(as_num(body.get("id")))
            if role == "client":
                own = [o for o in warehouse.orders(client=str(me.get("фио")))
                       if int(o.get("id", 0)) == oid]
                if not own:
                    self._err("это не ваш заказ", 403)
                    return
            elif not can(me, "orders.view"):
                self._err("нет прав", 403)
                return
            try:
                self._json({"ok": True, **warehouse.cancel_order(
                    oid, str(me.get("фио")), str(body.get("причина", "")))})
            except ValueError as exc:
                self._err(str(exc))
            return

        if path == "/api/orders/close" and method == "POST":
            if not can(me, "orders.view"):
                self._err("нет прав", 403)
                return
            try:
                import warehouse
                self._json({"ok": True, **warehouse.close_order(int(as_num(self._body().get("id"))))})
            except ValueError as exc:
                self._err(str(exc))
            return

        if path == "/api/orders" and method == "POST":
            if not can(me, "orders.create"):
                self._err("нет прав на заказ", 403)
                return
            try:
                import warehouse
            except Exception as exc:  # noqa: BLE001
                self._err(f"склад недоступен: {exc}", 500)
                return
            body = self._body()
            try:
                res = warehouse.create_order(str(me.get("фио")), body.get("позиции") or [])
                self._json({"ok": True, **res})
            except ValueError as exc:
                self._err(str(exc))
            return

        if path == "/api/export/workbook" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            try:
                import export_workbook
                info = export_workbook.snapshot()
            except Exception as exc:  # noqa: BLE001
                self._err(f"не удалось сделать копию: {exc}", 500)
                return
            data = Path(info["путь"]).read_bytes()
            ascii_name = f"ceh_sklad_{datetime.now():%Y%m%d_%H%M}.xlsm"
            disp = ("attachment; filename=\"" + ascii_name + "\"; filename*=UTF-8''"
                    + quote(Path(info["путь"]).name))
            self._send(data,
                       "application/vnd.ms-excel.sheet.macroEnabled.12", 200,
                       {"Content-Disposition": disp})
            return

        if path == "/api/export/backups" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            import export_workbook
            self._json({"ok": True, "data": export_workbook.list_backups()})
            return

        if path == "/api/export/backup" and method == "GET":
            if not can(me, "wh.view"):
                self._err("нет доступа", 403)
                return
            name = str(query.get("name", [""])[0])
            try:
                import export_workbook
                target = export_workbook.backup_path(name)
            except ValueError as exc:
                self._err(str(exc), 400)
                return
            data = target.read_bytes()
            disp = ("attachment; filename=\"backup.xlsm\"; filename*=UTF-8''" + quote(target.name))
            self._send(data, "application/vnd.ms-excel.sheet.macroEnabled.12", 200,
                       {"Content-Disposition": disp})
            return

        if path == "/api/report" and method == "POST":
            if not can(me, "report.build"):
                self._err("нет прав", 403)
                return
            path_xlsx = build_report(comp)
            data = path_xlsx.read_bytes()
            ascii_name = f"report_{datetime.now():%Y%m%d_%H%M}.xlsx"
            disp = ("attachment; filename=\"" + ascii_name + "\"; filename*=UTF-8''"
                    + quote(path_xlsx.name))
            self._send(data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       200, {"Content-Disposition": disp})
            return

        self._err("неизвестный запрос", 404)


def build_report(comp: str):
    wb = Workbook()
    fill = PatternFill("solid", fgColor="1F3864")
    font = Font(bold=True, color="FFFFFF")

    def sheet(name, cols, rows):
        ws = wb.create_sheet(name)
        ws.append(cols)
        for c in ws[1]:
            c.font, c.fill = font, fill
        for r in rows:
            ws.append(r)
        for i, col in enumerate(cols, start=1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, len(col) + 6)
        ws.freeze_panes = "A2"

    wb.remove(wb.active)
    batches = [b for b in read_table("batches") if str(b.get("цех")) == comp]
    nums = {str(b["номер"]) for b in batches}
    sheet("Партии", ["номер", "артикул", "клиент", "статус", "дата_создания", "срок", "штук", "прогресс"],
          [[b["номер"], b.get("артикул"), b.get("клиент"), b.get("статус"), b.get("дата_создания"),
            b.get("срок"), batch_view(b)["штук"], batch_view(b)["прогресс"]] for b in batches])
    sheet("Разделы", ["партия", "раздел", "цвет", "тон", "размер", "количество"],
          [[s.get("партия"), s.get("раздел"), s.get("цвет"), s.get("тон"), s.get("размер"),
            s.get("количество")] for s in read_table("sections") if str(s.get("партия")) in nums])
    sheet("Проходы", ["id", "дата", "партия", "раздел", "процесс", "сотрудник", "штук", "тариф",
                      "сумма", "начало", "конец", "статус"],
          [[p.get("id"), p.get("дата"), p.get("партия"), p.get("раздел"), p.get("процесс"),
            p.get("фио"), p.get("количество"), p.get("тариф"), p.get("сумма"),
            p.get("начало"), p.get("конец"), p.get("статус")]
           for p in read_table("passes") if str(p.get("партия")) in nums])
    sheet("Оценки технолога", ["дата", "партия", "раздел", "технолог", "оценка", "комментарий"],
          [[c.get("дата"), c.get("партия"), c.get("раздел"), c.get("технолог"), c.get("оценка"),
            c.get("комментарий")] for c in read_table("checks") if str(c.get("партия")) in nums])
    sheet("Готовая продукция", ["дата", "партия", "раздел", "количество", "кто"],
          [[f.get("дата"), f.get("партия"), f.get("раздел"), f.get("количество"), f.get("кто")]
           for f in read_table("finished") if str(f.get("партия")) in nums])
    sheet("Отгрузки", ["дата", "партия", "количество", "покупатель", "сумма"],
          [[s.get("дата"), s.get("партия"), s.get("количество"), s.get("покупатель"), s.get("сумма")]
           for s in read_table("shipments") if str(s.get("партия")) in nums])
    sheet("Материалы", ["артикул", "название", "количество", "ед", "цена", "поставщик"],
          [[m.get("артикул"), m.get("название"), m.get("количество"), m.get("ед"), m.get("цена"),
            m.get("поставщик")] for m in read_table("materials")])
    sheet("Цепочка процессов", ["код", "название", "порядок", "тариф", "зависимости", "обязательный"],
          [[p.get("код"), p.get("название"), p.get("порядок"), p.get("тариф"),
            p.get("зависимости"), p.get("обязательный")] for p in read_table("processes")])

    name = f"отчёт_{comp}_{datetime.now():%Y-%m-%d_%H%M}.xlsx"
    path = REPORT_DIR / name
    wb.save(path)
    return path


def lan_ip() -> str:
    """Первый приватный IPv4 этого Mac — по нему подключается телефон."""
    import socket
    try:
        for target in ("10.255.255.255", "192.168.1.255", "8.8.8.8"):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect((target, 1))
                ip = sock.getsockname()[0]
                if ip and not ip.startswith("127."):
                    return ip
            finally:
                sock.close()
    except Exception:
        pass
    return "127.0.0.1"


def main():
    global VERBOSE, DEV
    parser = argparse.ArgumentParser(description="Проект V2.1 — портал швейного цеха")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    VERBOSE, DEV = args.verbose, args.dev
    ensure_tables()
    backup_data()

    def _boot_sync():
        try:
            import shop_sync
            with WRITE_LOCK:
                shop_sync.sync_if_changed()
        except Exception as exc:  # noqa: BLE001
            print("каталог магазина не синхронизирован:", exc)
        try:
            import warehouse
            warehouse.stock_items()
            print("склад: кэш прогрет")
            warehouse.flush_pending()
        except Exception as exc:  # noqa: BLE001
            print("склад не прогрет:", exc)

    threading.Thread(target=_boot_sync, daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Проект V2.1 · http://{args.host}:{args.port}")
    if args.host in ("0.0.0.0", ""):
        print(f"С телефона в Wi-Fi: http://{lan_ip()}:{args.port}")
    print(f"Данные: {DATA}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено")


if __name__ == "__main__":
    main()
