# -*- coding: utf-8 -*-
"""Цех: зарплата — сдельно, оклад, посменно; начисления и выплаты.

Вынесено из cex_api.py. Общие данные и функции цеха — через cex_api (C.…):
так подмены в тестах и вызовы из других разделов идут через один модуль.
Импортировать этот модуль напрямую не нужно: cex_api сам отдаёт его функции."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
import perms

import cex_api as C


# -------------------------------------------------------- зарплата (модуль 6)


def _month_bounds(month: str) -> tuple[int, int, int]:
    from calendar import monthrange
    try:
        y, m = [int(x) for x in month.split("-")[:2]]
    except Exception:
        now = datetime.now()
        y, m = now.year, now.month
    return y, m, monthrange(y, m)[1]


def _date_of(s: str):
    try:
        return datetime.strptime(C._s(s)[:10], "%d.%m.%Y").date()
    except ValueError:
        return None


def periods_for(month: str, kind: str) -> list[dict]:
    from datetime import date as _date, timedelta
    y, m, last = C._month_bounds(month)
    if kind == "3 раза":
        spans = [(1, 10), (11, 20), (21, last)]
    elif kind == "неделя":
        first = _date(y, m, 1)
        start = first - timedelta(days=first.weekday())
        spans = []
        while start <= _date(y, m, last):
            end = start + timedelta(days=6)
            spans.append((max(start, first).day, min(end, _date(y, m, last)).day))
            start = end + timedelta(days=1)
    else:
        spans = [(1, last)]
    out = []
    for a, b in spans:
        out.append({
            "код": f"{a:02d}-{b:02d}",
            "название": f"{a:02d}–{b:02d}.{m:02d}",
            "первый": a, "последний": b, "дней": b - a + 1,
        })
    return out


def staff_cards() -> list[dict]:
    return C._rows(C.STAFF)


def seed_staff() -> int:
    if C._rows(C.STAFF):
        return 0
    try:
        from server import read_table  # noqa: WPS433
        users = read_table("users")
    except Exception:
        users = []
    rows = []
    for u in users:
        role = C._s(u.get("роль"))
        if role in ("client", "") or str(u.get("активен", 1)) in ("0", "False"):
            continue
        rows.append({
            "логин": C._s(u.get("логин")), "ФИО": C._s(u.get("фио")),
            "должность": role, "роли": "",
            "тип оплаты": "сдельная" if role in ("cutter", "packer") or role in C.production_roles() else "оклад",
            "ставка": 0, "периодичность": "месяц", "модели": "",
            "телефон": "", "активен": 1,
        })
    if rows:
        C.store.write_sheet(C.STAFF[0], C.STAFF[1], rows)
    return len(rows)


def _party_models() -> dict[str, str]:
    out = {}
    for r in C._rows(C.PARTIES):
        out.setdefault(C._s(r.get("№ партии")), C._s(r.get("модель")))
    return out


def dash_summary(login: str | None = None) -> dict:
    """Для «Сводки» портала: сдано и начислено сдельно за этот месяц (Выдачи «готово»),
    незавершённые штуки заказов цеха по этапам и последние заказы. login — только свои выдачи."""
    today = date.today()
    qty, money = 0, 0.0
    for r in C._rows(C.OUT):
        d = C._date_of(r.get("дата"))
        if C._s(r.get("статус")) != "готово" or not d or (d.year, d.month) != (today.year, today.month):
            continue
        if login and C._s(r.get("логин")) != login:
            continue
        qty += C._int(r.get("количество"))
        money += float(str(r.get("сумма") or 0).replace(",", ".") or 0)
    stages = {st: 0 for st in C.CARD_STAGES}
    recent = []
    for o in C.orders():
        if o["статус"] == "отклонён":
            continue
        for pos in o["позиции"]:
            if pos["остаток"]:
                stages[pos["этап"]] = stages.get(pos["этап"], 0) + pos["остаток"]
        recent.append({"номер": o["номер"], "дата": o["дата"], "клиент": o["клиент"], "штук": o["штук"],
                       "принято": o["принято"], "статус": o["статус"]})
    left = {k: v for k, v in C.stock().items() if v > 0}
    prices = {k: C.mat_price(*k)[0] for k in left}  # средняя цена поступлений; без цены — 0
    mats = {"в_справочнике": len(C.materials()), "на_складе": len(left),
            "сумма": round(sum(v * prices[k] for k, v in left.items()), 2),
            "без_цены": sum(1 for k in left if not prices[k])}
    return {"сдано": qty, "заработано": round(money, 2), "этапы": stages, "заказы": recent[:6], "материалы": mats}


def payroll_data(month: str, me: dict) -> dict:
    C.seed_staff()
    y, m, last = C._month_bounds(month)
    cards = {C._s(c.get("логин")): c for c in C.staff_cards()}
    role = C._s(me.get("роль"))
    only_me = not C._can(me, "cex.pay")

    models = C._party_models()
    issued = []
    for r in C._rows(C.OUT):
        if C._s(r.get("статус")) != "готово":
            continue
        d = C._date_of(r.get("дата"))
        if not d or d.year != y or d.month != m:
            continue
        issued.append((r, d))

    shifts = []
    for r in C._rows(C.SHIFTS):
        d = C._date_of(r.get("дата"))
        if d and d.year == y and d.month == m:
            shifts.append((r, d))

    people = []
    logins = set(cards)
    for r, _d in issued:
        logins.add(C._s(r.get("логин")))
    for login in sorted(logins):
        card = cards.get(login) or {}
        if only_me and login != C._s(me.get("логин")):
            continue
        if str(card.get("активен", 1)) in ("0", "False"):
            continue
        kind = C._s(card.get("тип оплаты")) or ("сдельная" if C._s(card.get("должность")) in
                                             ("cutter", "packer", *C.production_roles()) else "оклад")
        if kind not in C.PAY_TYPES:
            kind = "сдельная"
        rate = float(str(card.get("ставка") or 0).replace(",", ".") or 0)
        periodicity = C._s(card.get("периодичность")) or "месяц"
        if periodicity not in C.PAY_PERIODS:
            periodicity = "месяц"
        fio = C._s(card.get("ФИО")) or login
        spans = C.periods_for(month, periodicity)

        per_period = []
        total_piece = 0.0
        total_salary = 0.0
        total_shift = 0.0
        qty_total = 0
        by_model: dict[str, dict] = {}

        for span in spans:
            piece = 0.0
            salary = 0.0
            shift_sum = 0.0
            qty = 0
            for r, d in issued:
                if C._s(r.get("логин")) != login:
                    continue
                if not (span["первый"] <= d.day <= span["последний"]):
                    continue
                amount = float(str(r.get("сумма") or 0).replace(",", ".") or 0)
                piece += amount
                qty += C._int(r.get("количество"))
                model = models.get(C._s(r.get("партия")), "")
                item = by_model.setdefault(model or "—", {"модель": model or "—", "шт": 0, "сумма": 0.0})
                item["шт"] += C._int(r.get("количество"))
                item["сумма"] += amount
            if kind == "оклад" and rate:
                salary = round(rate * span["дней"] / last, 2)
            if kind == "посменная":
                for r, d in shifts:
                    if C._s(r.get("логин")) != login:
                        continue
                    if not (span["первый"] <= d.day <= span["последний"]):
                        continue
                    amount = float(str(r.get("сумма") or 0).replace(",", ".") or 0)
                    if not amount:
                        amount = float(str(r.get("часов") or 0).replace(",", ".") or 0) * rate
                    shift_sum += amount
            per_period.append({
                "код": span["код"], "название": span["название"],
                "сдельно": round(piece, 2), "оклад": salary, "смены": round(shift_sum, 2),
                "к выплате": round(piece + salary + shift_sum, 2), "шт": qty,
            })
            total_piece += piece
            total_salary += salary
            total_shift += shift_sum
            qty_total += qty

        people.append({
            "логин": login, "ФИО": fio, "тип": kind, "ставка": rate,
            "периодичность": periodicity, "этап": ", ".join(perms.role_label(c) for c in C._deps(card.get("роли"))),
            "должность": C.ROLE_NAMES.get(C._s(card.get("должность"))) or perms.role_label(C._s(card.get("должность"))),
            "сдельно": round(total_piece, 2), "оклад": round(total_salary, 2),
            "смены": round(total_shift, 2),
            "к выплате": round(total_piece + total_salary + total_shift, 2),
            "шт": qty_total, "периоды": per_period,
            "артикулы": sorted(by_model.values(), key=lambda x: -x["сумма"]),
        })

    people.sort(key=lambda p: (p["тип"] != "сдельная", -p["к выплате"]))
    totals = {
        "людей": len(people),
        "сдельно": round(sum(p["сдельно"] for p in people), 2),
        "оклад": round(sum(p["оклад"] for p in people), 2),
        "смены": round(sum(p["смены"] for p in people), 2),
        "к выплате": round(sum(p["к выплате"] for p in people), 2),
        "шт": sum(p["шт"] for p in people),
    }
    closed = [r for r in C._rows(C.SALARY) if C._s(r.get("месяц")) == month]
    return {"месяц": month, "люди": people, "итого": totals,
            "закрыто": len(closed), "только_своё": only_me}


def close_payroll(me: dict, body: dict) -> dict:
    month = C._s(body.get("месяц"))
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Неверный месяц")
    data = C.payroll_data(month, me)
    existing = {(C._s(r.get("месяц")), C._s(r.get("период")), C._s(r.get("логин")))
                for r in C._rows(C.SALARY)}
    rows = C._rows(C.SALARY)
    added = 0
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    for p in data["люди"]:
        for per in p["периоды"]:
            if per["к выплате"] <= 0:
                continue
            key = (month, per["название"], p["логин"])
            if key in existing:
                continue
            rows.append({
                "месяц": month, "период": per["название"], "логин": p["логин"],
                "ФИО": p["ФИО"], "тип": p["тип"],
                "сдельно": per["сдельно"], "оклад": per["оклад"], "смены": per["смены"],
                "к выплате": per["к выплате"], "выплачено": 0, "дата": now,
                "комментарий": "",
            })
            existing.add(key)
            added += 1
    if not added:
        raise ValueError("За этот месяц уже всё начислено")
    C.store.write_sheets([(C.SALARY[0], C.SALARY[1], rows)])
    return {"начислено": added}


def update_card(me: dict, body: dict) -> dict:
    login = C._s(body.get("логин"))
    if not login:
        raise ValueError("Не указан сотрудник")
    rows = C._rows(C.STAFF)
    row = next((r for r in rows if C._s(r.get("логин")) == login), None)
    if not row:
        raise ValueError("Сотрудник не найден в листе «Сотрудники цеха»")
    if "тип оплаты" in body:
        kind = C._s(body.get("тип оплаты"))
        if kind not in C.PAY_TYPES:
            raise ValueError("Неизвестный тип оплаты")
        row["тип оплаты"] = kind
    if "периодичность" in body:
        per = C._s(body.get("периодичность"))
        if per not in C.PAY_PERIODS:
            raise ValueError("Неизвестная периодичность")
        row["периодичность"] = per
    if "ставка" in body:
        row["ставка"] = C._int(body.get("ставка"))
    C.store.write_sheets([(C.STAFF[0], C.STAFF[1], rows)])
    return {"логин": login}
