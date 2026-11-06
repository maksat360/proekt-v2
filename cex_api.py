# -*- coding: utf-8 -*-
"""Модуль «Заказ»: логика поверх листов рабочей книги."""
from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta

import cex_store as store

MODELS = ("Справочник модели",
          ["категория", "модель", "название", "размерная сетка", "цена", "активна"],
          [14, 10, 30, 16, 10, 9])
COLORS = ("Справочник цвета", ["цвет", "код тона", "активен"], [22, 16, 9])
SIZES = ("Справочник размеров", ["сетка", "размер", "порядок"], [14, 10, 9])
PARTIES = ("Партии",
           ["№ партии", "№ заказа", "дата", "клиент", "категория", "модель",
            "цвет", "размер", "план шт", "статус", "технолог", "срок"],
           [9, 9, 12, 18, 14, 10, 16, 9, 10, 14, 10, 12])
STAFF = ("Сотрудники цеха",
         ["логин", "ФИО", "должность", "этап", "тип оплаты", "ставка", "периодичность",
          "модели", "телефон", "активен"],
         [12, 24, 16, 14, 14, 10, 16, 18, 14, 9])
SHIFTS = ("Смены", ["дата", "логин", "часов", "ставка", "сумма"], [12, 12, 8, 10, 10])
RATES = ("Ставки артикул", ["модель", "этап", "ставка", "с даты"], [12, 12, 10, 12])
SALARY = ("Зарплата",
          ["месяц", "период", "логин", "ФИО", "тип", "сдельно", "оклад", "смены",
           "к выплате", "выплачено", "дата", "комментарий"],
          [10, 18, 12, 24, 14, 11, 11, 10, 12, 12, 12, 24])
PACK = ("Упаковка",
        ["id", "дата", "партия", "цвет", "размер", "коробка", "количество",
         "этикеток", "кто", "статус"],
        [6, 12, 9, 16, 9, 10, 11, 10, 20, 12])
ROUTE = ("Маршрут",
         ["шаблон", "этап", "после каких этапов", "на склад ГП", "кто может", "активен"],
         [16, 14, 26, 13, 18, 9])
ROUTE_MODEL = ("Маршрут модели", ["модель", "шаблон"], [14, 22])
ITEM_LABELS = ("Этикетки",
               ["№ партии", "наименование", "категория", "модель", "цвет", "размер",
                "количество", "сгенерировал", "дата"],
               [9, 38, 12, 10, 18, 8, 11, 18, 16])
ASSIGN = ("Распределение", ["№ партии", "настил", "этап", "логин", "ФИО", "назначил", "дата"],
          [9, 8, 12, 12, 24, 12, 16])
ROUTE_PARTY = ("Маршрут партии",
               ["№ партии", "шаблон", "этап", "после каких этапов", "на склад ГП", "кто может"],
               [9, 16, 14, 26, 13, 18])
CUT = ("крой",
       ["№ партии", "настил", "цвет", "размер", "план шт", "факт шт",
        "закройщик", "дата", "комментарий", "карта"],
       [9, 8, 16, 9, 10, 10, 14, 14, 26, 8])
CARDS = ("Карты кроя",
         ["№ карты", "№ партии", "дата", "закройщик", "лекало", "длина м", "рулонов",
          "вес кг", "разделов", "настилы", "штук", "комментарий"],
         [8, 9, 16, 18, 14, 9, 9, 9, 9, 10, 8, 24])
ROLLS = ("Рулоны",
         ["№ карты", "№ партии", "№", "код рулона", "граммаж г", "цвет", "вес кг"],
         [8, 9, 5, 16, 11, 18, 9])
PATTERNS = ("Лекала", ["код", "название", "модель", "длина м", "ширина м", "комментарий"],
            [12, 24, 10, 9, 9, 30])
OUT = ("Выдачи",
       ["id", "дата", "партия", "настил", "цвет", "размер", "этап", "логин", "ФИО",
        "количество", "начало", "конец", "ставка", "сумма", "статус", "комментарий", "секунд"],
       [6, 12, 8, 8, 16, 9, 10, 10, 20, 11, 14, 14, 8, 10, 12, 24])
TECH = ("технолог",
        ["№ заказа", "дата", "решение", "причина", "сырьё", "свободных швей",
         "проверил", "комментарий"],
        [10, 14, 16, 30, 14, 14, 12, 30])
ORDERS = ("Заказ на цех",
          ["№ заказа", "дата", "клиент", "источник", "поставщик", "категория", "модель",
           "цвет", "размер", "количество", "срок", "статус", "создал", "№ партии",
           "комментарий"],
          [10, 12, 18, 12, 18, 14, 10, 16, 9, 11, 12, 15, 10, 10, 30])

NEW = "у технолога"
OWN = "свой цех"
SUPPLIER = "поставщик"
AT_SUPPLIER = "заказан у поставщика"
ORDER_LOCK = threading.Lock()
CAN_CREATE = {"admin", "manager"}
CAN_TECH = {"admin", "manager", "technologist"}
CAN_CUT = {"admin", "manager", "cutter"}
CAN_WORK = {"admin", "manager", "technologist", "user"}
CAN_PACK = {"admin", "manager", "packer"}
CAN_PAY = {"admin", "manager", "accountant"}
CAN_VIEW = {"admin", "manager", "technologist", "accountant", "storekeeper",
            "cutter", "packer", "user"}
EDITORS = {"admin", "manager"}


def _int(v, default=0) -> int:
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _norm_size(v) -> str:
    """42.0 -> '42', 'XL' -> 'XL'."""
    s = _s(v)
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s


def ensure_sheets() -> None:
    specs = [MODELS, COLORS, SIZES, ORDERS, PARTIES, TECH, CUT, OUT, ROUTE, PACK,
             STAFF, SHIFTS, RATES, SALARY, ROUTE_MODEL, ROUTE_PARTY, ASSIGN, ITEM_LABELS, CARDS, ROLLS, PATTERNS]
    store.ensure_sheets(specs)
    for name, headers, _ in specs:
        if store.first_row(name) != headers:
            if not store.read_sheet(name):
                store.write_sheet(name, headers, [])


# ------------------------------------------------------------------ данные
def _rows(spec) -> list[dict]:
    name, headers, _ = spec
    return [{h: r.get(h, "") for h in headers} for r in store.read_sheet(name)]


def refs() -> dict:
    models = [r for r in _rows(MODELS) if _s(r.get("модель"))]
    active_models = [r for r in models if str(r.get("активна", 1)) not in ("0", "нет", "False")]
    colors = [r for r in _rows(COLORS) if _s(r.get("цвет"))]
    sizes = [r for r in _rows(SIZES) if _s(r.get("размер"))]

    categories: list[str] = []
    for r in active_models:
        c = _s(r.get("категория"))
        if c and c not in categories:
            categories.append(c)

    size_map: dict[str, list[dict]] = {}
    for r in sizes:
        grid = _s(r.get("сетка")) or "числовая"
        size_map.setdefault(grid, []).append(
            {"размер": _norm_size(r.get("размер")), "порядок": _int(r.get("порядок"), 0)})
    for grid in size_map:
        size_map[grid].sort(key=lambda x: (x["порядок"], x["размер"]))

    return {
        "категории": categories,
        "модели": [{
            "категория": _s(r.get("категория")),
            "модель": _s(r.get("модель")),
            "название": _s(r.get("название")) or _s(r.get("модель")),
            "сетка": _s(r.get("размерная сетка")) or "числовая",
            "цена": r.get("цена", ""),
        } for r in active_models],
        "цвета": [{"цвет": _s(r.get("цвет")), "тон": _s(r.get("код тона"))}
                  for r in colors if str(r.get("активен", 1)) not in ("0", "нет", "False")],
        "размеры": [{"сетка": g, "размеры": v} for g, v in size_map.items()],
        "варианты": model_variants(),
    }


def orders() -> list[dict]:
    rows = _rows(ORDERS)
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        num = _s(r.get("№ заказа"))
        if not num:
            continue
        if num not in grouped:
            grouped[num] = {
                "номер": num,
                "дата": _s(r.get("дата")),
                "клиент": _s(r.get("клиент")),
                "источник": _s(r.get("источник")) or OWN,
                "поставщик": _s(r.get("поставщик")),
                "срок": _s(r.get("срок")),
                "статус": _s(r.get("статус")),
                "создал": _s(r.get("создал")),
                "комментарий": _s(r.get("комментарий")),
                "позиции": [],
                "штук": 0,
            }
            order.append(num)
        item = {
            "категория": _s(r.get("категория")),
            "модель": _s(r.get("модель")),
            "цвет": _s(r.get("цвет")),
            "размер": _norm_size(r.get("размер")),
            "количество": _int(r.get("количество")),
        }
        grouped[num]["позиции"].append(item)
        grouped[num]["штук"] += item["количество"]
    out = [grouped[n] for n in order]
    out.sort(key=lambda o: _int(o["номер"]), reverse=True)
    accepted = accepted_map()
    for o in out:
        o["позиций"] = len(o["позиции"])
        o["принято"] = 0
        o["остаток"] = 0
        for p in o["позиции"]:
            key = (o["номер"], p["модель"], p["цвет"], p["размер"])
            done = accepted.get(key, 0)
            p["принято"] = done
            p["остаток"] = max(0, p["количество"] - done)
            o["принято"] += done
            o["остаток"] += p["остаток"]
    return out


def accepted_map() -> dict[tuple, int]:
    """Сколько уже принято в партии по каждой позиции заказа."""
    out: dict[tuple, int] = {}
    for r in _rows(PARTIES):
        key = (_s(r.get("№ заказа")), _s(r.get("модель")), _s(r.get("цвет")),
               _norm_size(r.get("размер")))
        out[key] = out.get(key, 0) + _int(r.get("план шт"))
    return out


def decisions() -> list[dict]:
    return _rows(TECH)


def parties() -> list[dict]:
    return _rows(PARTIES)


def next_party_number() -> int:
    nums = []
    for r in _rows(PARTIES):
        v = _s(r.get("№ партии"))
        if v.isdigit():
            nums.append(int(v))
    if nums:
        return max(nums) + 1
    start = 1
    try:
        for row in store.read_sheet("настройки"):
            if _s(row.get("параметр")) in ("первая партия", "старт партий"):
                start = _int(row.get("значение"), 1) or 1
    except Exception:
        pass
    return start


def staff_stats() -> dict:
    try:
        from server import read_table  # noqa: WPS433
        users = read_table("users")
    except Exception:
        users = []
    seam = [u for u in users if _s(u.get("роль")) == "user"
            and str(u.get("активен", 1)) not in ("0", "False", "нет")]
    busy = set()
    try:
        for r in store.read_sheet("Выдачи"):
            if _s(r.get("статус")) == "в работе":
                busy.add(_s(r.get("логин")))
    except Exception:
        pass
    return {"швей": len(seam), "занято": len(busy), "свободно": max(0, len(seam) - len(busy))}


def queue() -> list[dict]:
    """Заказы, которые ждут решения технолога."""
    return [o for o in orders()
            if o["остаток"] > 0 and o["статус"] not in ("отклонён",)
            and o["источник"] != SUPPLIER]  # заказ у поставщика идёт мимо цеха


def supplier_list() -> list[str]:
    out: list[str] = []
    for r in _rows(ORDERS):
        name = _s(r.get("поставщик"))
        if name and name not in out:
            out.append(name)
    return sorted(out, key=str.lower)


def next_number() -> int:
    return max([_int(r.get("№ заказа")) for r in _rows(ORDERS)] or [0]) + 1


# --------------------------------------------------------- приёмка (модуль 2)
def _add_party_ref(row: dict, num: int) -> None:
    cur = _s(row.get("№ партии"))
    parts = [x.strip() for x in cur.split(",") if x.strip()]
    if str(num) not in parts:
        parts.append(str(num))
    row["№ партии"] = ", ".join(parts)


def _free(body: dict) -> int:
    for key in ("свободных_швей", "свободных швей", "швей"):
        if key in body:
            return _int(body.get(key), 0)
    return 0


def apply_decision(me: dict, body: dict) -> dict:
    num = _s(body.get("номер"))
    decision = _s(body.get("решение")) or "принять"
    orders_rows = _rows(ORDERS)
    target = [r for r in orders_rows if _s(r.get("№ заказа")) == num]
    if not target:
        raise ValueError("Заказ не найден")
    if _s(target[0].get("статус")) == "отклонён" and decision != "вернуть":
        raise ValueError("Заказ отклонён. Верните его в работу, чтобы принять.")

    tech_rows = _rows(TECH)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    party_num = None
    status = ""

    if decision == "вернуть":
        if _s(me.get("роль")) != "admin":
            raise ValueError("Вернуть заказ в работу может только начальник")
        for r in target:
            r["статус"] = NEW
        status = NEW
        tech_rows.append({
            "№ заказа": num, "дата": now, "решение": "возвращён в работу",
            "причина": _s(body.get("причина")), "сырьё": "", "свободных швей": "",
            "проверил": _s(me.get("логин")), "комментарий": _s(body.get("комментарий")),
        })
        store.write_sheets([(ORDERS[0], ORDERS[1], orders_rows),
                            (TECH[0], TECH[1], tech_rows)])
        return {"статус": status}

    if decision == "отклонить":
        reason = _s(body.get("причина"))
        for r in target:
            r["статус"] = "отклонён"
        status = "отклонён"
        tech_rows.append({
            "№ заказа": num, "дата": now, "решение": "отклонён", "причина": reason,
            "сырьё": _s(body.get("сырьё")), "свободных швей": _free(body),
            "проверил": _s(me.get("логин")), "комментарий": _s(body.get("комментарий")),
        })
        store.write_sheets([(ORDERS[0], ORDERS[1], orders_rows),
                            (TECH[0], TECH[1], tech_rows)])
        return {"статус": status}

    # принять (целиком или частично)
    current = {o["номер"]: o for o in orders()}.get(num)
    if not current:
        raise ValueError("Заказ не найден")
    remaining = {(p["модель"], p["цвет"], p["размер"]): p["остаток"]
                 for p in current["позиции"]}
    wanted = body.get("позиции") or []
    accepted: dict[tuple, int] = {}
    for it in wanted:
        qty = _int(it.get("количество"), 0)
        if qty <= 0:
            continue
        key = (_s(it.get("модель")), _s(it.get("цвет")), _norm_size(it.get("размер")))
        if key not in remaining:
            raise ValueError(f"Позиции {key[0]} / {key[1]} / {key[2]} нет в заказе")
        if qty > remaining[key]:
            raise ValueError(
                f"По позиции {key[0]} / {key[1]} / {key[2]} осталось {remaining[key]} шт — "
                f"нельзя принять {qty}")
        accepted[key] = accepted.get(key, 0) + qty

    total = sum(accepted.values())
    if total <= 0:
        raise ValueError("Укажите количество хотя бы по одной позиции")

    party_num = next_party_number()
    bypos = {(p["модель"], p["цвет"], p["размер"]): p for p in current["позиции"]}
    newparty = []
    for (model, color, size), qty in accepted.items():
        pos = bypos[(model, color, size)]
        newparty.append({
            "№ партии": party_num, "№ заказа": num, "дата": now,
            "клиент": current["клиент"], "категория": pos["категория"],
            "модель": model, "цвет": color, "размер": size,
            "план шт": qty, "статус": "крой", "технолог": _s(me.get("логин")),
            "срок": current["срок"],
        })

    left = {k: v - accepted.get(k, 0) for k, v in remaining.items()}
    partial = any(v > 0 for v in left.values())
    status = "принят частично" if partial else "принят"
    for r in target:
        r["статус"] = status
    for (model, color, size) in accepted:
        for r in target:
            if (_s(r.get("модель")) == model and _s(r.get("цвет")) == color
                    and _norm_size(r.get("размер")) == size):
                _add_party_ref(r, party_num)

    tech_rows.append({
        "№ заказа": num, "дата": now,
        "решение": "принят частично" if partial else "принят",
        "причина": "", "сырьё": _s(body.get("сырьё")) or "хватает",
        "свободных швей": _free(body),
        "проверил": _s(me.get("логин")), "комментарий": _s(body.get("комментарий")),
    })
    seed_route()
    first_model = newparty[0]["модель"] if newparty else ""
    snap = _rows(ROUTE_PARTY) + snapshot_rows(party_num, first_model)
    store.write_sheets([(ORDERS[0], ORDERS[1], orders_rows),
                        (PARTIES[0], PARTIES[1], _rows(PARTIES) + newparty),
                        (TECH[0], TECH[1], tech_rows),
                        (ROUTE_PARTY[0], ROUTE_PARTY[1], snap)])
    return {"статус": status, "партия": party_num, "штук": total}


# ------------------------------------------------------------- крой (модуль 3)
def _size_key(value: str):
    s = _s(value)
    plain = s.replace(",", ".").replace(".", "")
    if plain.isdigit():
        return (0, float(s.replace(",", ".")), s)
    return (1, 0.0, s)


def rate_of(code: str, default: float = 0.0) -> float:
    try:
        for r in store.read_sheet("расценки"):
            if _s(r.get("код")) == code:
                raw = _s(r.get("расценка за шт")).replace(",", ".")
                return float(raw) if raw else default
    except Exception:
        pass
    return default


def cut_state() -> dict:
    groups: dict[str, dict] = {}
    for r in _rows(PARTIES):
        num = _s(r.get("№ партии"))
        if not num:
            continue
        g = groups.get(num)
        if g is None:
            g = groups[num] = {
                "номер": num, "заказ": _s(r.get("№ заказа")), "клиент": _s(r.get("клиент")),
                "категория": _s(r.get("категория")), "модель": _s(r.get("модель")),
                "статус": _s(r.get("статус")), "срок": _s(r.get("срок")),
                "дата": _s(r.get("дата")), "технолог": _s(r.get("технолог")),
                "строки": {}, "настилы": [], "план": 0, "раскроено": 0,
            }
        key = (_s(r.get("цвет")), _norm_size(r.get("размер")))
        row = g["строки"].get(key)
        if row is None:
            row = g["строки"][key] = {"цвет": key[0], "размер": key[1], "план": 0,
                                      "раскроено": 0, "остаток": 0}
        row["план"] += _int(r.get("план шт"))
        g["план"] += _int(r.get("план шт"))

    cut_rows = _rows(CUT)
    for r in cut_rows:
        num = _s(r.get("№ партии"))
        g = groups.get(num)
        if not g:
            continue
        key = (_s(r.get("цвет")), _norm_size(r.get("размер")))
        row = g["строки"].get(key)
        if row is None:
            row = g["строки"][key] = {"цвет": key[0], "размер": key[1], "план": 0,
                                      "раскроено": 0, "остаток": 0}
        row["раскроено"] += _int(r.get("факт шт"))
        g["раскроено"] += _int(r.get("факт шт"))
        name = _s(r.get("настил"))
        found = next((x for x in g["настилы"] if x["настил"] == name), None)
        if found is None:
            found = {"настил": name, "дата": _s(r.get("дата")),
                     "закройщик": _s(r.get("закройщик")), "шт": 0, "строки": []}
            g["настилы"].append(found)
        found["строки"].append({"цвет": key[0], "размер": key[1],
                                "план": _int(r.get("план шт")),
                                "факт": _int(r.get("факт шт"))})
        found["шт"] += _int(r.get("факт шт"))

    out = []
    for g in groups.values():
        rows = sorted(g["строки"].values(), key=lambda x: (x["цвет"], _size_key(x["размер"])))
        for row in rows:
            row["остаток"] = max(0, row["план"] - row["раскроено"])
        g["строки"] = rows
        for n in g["настилы"]:
            n["строки"].sort(key=lambda x: (x["цвет"], _size_key(x["размер"])))
            n["номер"] = f'{g["номер"]}/{n["настил"]}'
        g["настилы"].sort(key=lambda x: _int(x["настил"]))
        g["остаток"] = max(0, g["план"] - g["раскроено"])
        g["прогресс"] = int(round(100 * g["раскроено"] / g["план"])) if g["план"] else 0
        out.append(g)
    out.sort(key=lambda g: _int(g["номер"]))
    for g in out:
        g["карты"] = cards_of(g["номер"])
    return {"партии": out, "ставка": rate_of("РАСКР", 15.0), "лекала": patterns()}


# --------------------------------------------------- карта кроя (закройщик)
# Карта = один настил по длине: лекало, длина, рулоны (код, граммаж, цвет, вес)
# и разделы — каждый раздел становится настилом партии с количеством
# по цвету и размеру. Рулоны — справочная информация для расчётов.

def patterns() -> list[dict]:
    out = []
    for r in _rows(PATTERNS):
        code = _s(r.get("код")) or _s(r.get("название"))
        if code:
            out.append({"код": code, "название": _s(r.get("название")) or code,
                        "модель": _s(r.get("модель")), "длина": _s(r.get("длина м"))})
    return out


def _num(v) -> float:
    try:
        return float(_s(v).replace(",", "."))
    except ValueError:
        return 0.0


def save_card(me: dict, body: dict) -> dict:
    num = _s(body.get("партия"))
    state = cut_state()
    party = next((p for p in state["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError(f"Партии №{num} нет")
    if party["статус"] not in ("крой", "в производстве"):
        raise ValueError(f"Партия в статусе «{party['статус']}» — крой недоступен")
    length = _num(body.get("длина"))
    if length <= 0:
        raise ValueError("Укажите длину настила, м")
    pattern = _s(body.get("лекало"))
    rolls = []
    for i, r in enumerate(body.get("рулоны") or [], start=1):
        code = _s(r.get("код"))
        weight = _num(r.get("вес"))
        if not code and weight <= 0 and not _s(r.get("цвет")):
            continue
        if not code:
            raise ValueError(f"Рулон {i}: укажите код рулона")
        rolls.append({"код": code, "граммы": _num(r.get("граммы")), "цвет": _s(r.get("цвет")),
                      "вес": weight})
    if not rolls:
        raise ValueError("Добавьте хотя бы один рулон")

    index = {(r["цвет"], r["размер"]): r for r in party["строки"]}
    left = {k: r["остаток"] for k, r in index.items()}
    sections = []
    for si, sec in enumerate(body.get("разделы") or [], start=1):
        items = []
        for p in sec.get("позиции") or []:
            qty = _int(p.get("факт"), 0)
            if qty <= 0:
                continue
            key = (_s(p.get("цвет")), _norm_size(p.get("размер")))
            if key not in index:
                raise ValueError(f"Раздел {si}: {key[0]} / {key[1]} нет в партии")
            if qty > left[key]:
                raise ValueError(f"Раздел {si}: {key[0]} / {key[1]} — осталось по плану {left[key]} шт, "
                                 f"нельзя {qty}. Лишнее исправит технолог")
            left[key] -= qty
            items.append((key, qty))
        if items:
            sections.append(items)
    if not sections:
        raise ValueError("Заполните хотя бы один раздел: цвет, размер, количество")

    cards = _rows(CARDS)
    card_no = max([_int(r.get("№ карты")) for r in cards] or [0]) + 1
    numbers = [_int(n["настил"]) for n in party["настилы"]]
    first = max(numbers or [0]) + 1
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    day = datetime.now().strftime("%d.%m.%Y")
    who = _s(me.get("фио")) or _s(me.get("логин"))

    cut_rows = _rows(CUT)
    total = 0
    for i, items in enumerate(sections):
        nas = first + i
        for (color, size), qty in items:
            cut_rows.append({"№ партии": num, "настил": nas, "цвет": color, "размер": size,
                             "план шт": index[(color, size)]["остаток"], "факт шт": qty,
                             "закройщик": who, "дата": now, "комментарий": "",
                             "карта": card_no})
            total += qty
    last = first + len(sections) - 1

    cards.append({"№ карты": card_no, "№ партии": num, "дата": now, "закройщик": who,
                  "лекало": pattern, "длина м": length, "рулонов": len(rolls),
                  "вес кг": round(sum(r["вес"] for r in rolls), 3),
                  "разделов": len(sections), "настилы": f"{first}–{last}" if last > first else str(first),
                  "штук": total, "комментарий": _s(body.get("комментарий"))})
    roll_rows = _rows(ROLLS)
    for i, r in enumerate(rolls, start=1):
        roll_rows.append({"№ карты": card_no, "№ партии": num, "№": i, "код рулона": r["код"],
                          "граммаж г": r["граммы"] or "", "цвет": r["цвет"], "вес кг": r["вес"] or ""})

    rate = rate_of("РАСКР", 15.0)
    issue_rows = _rows(OUT)
    new_id = max([_int(r.get("id")) for r in issue_rows] or [0]) + 1
    issue_rows.append({
        "id": new_id, "дата": day, "партия": num, "настил": first, "цвет": "", "размер": "",
        "этап": START_STAGE, "логин": _s(me.get("логин")), "ФИО": who, "количество": total,
        "начало": now, "конец": now, "ставка": rate, "сумма": round(total * rate, 2),
        "статус": "готово", "комментарий": f"карта {card_no}, настилы {first}–{last}",
    })
    done = party["остаток"] - total <= 0
    party_rows = _rows(PARTIES)
    new_status = "в производстве" if done else "крой"
    for r in party_rows:
        if _s(r.get("№ партии")) == num:
            r["статус"] = new_status
    store.write_sheets([(CUT[0], CUT[1], cut_rows), (CARDS[0], CARDS[1], cards),
                        (ROLLS[0], ROLLS[1], roll_rows), (OUT[0], OUT[1], issue_rows),
                        (PARTIES[0], PARTIES[1], party_rows)])
    return {"карта": card_no, "настилы": f"{num}/{first}" + (f"–{last}" if last > first else ""),
            "штук": total, "сумма": round(total * rate, 2), "статус": new_status, "готово": done}


def cards_of(num: str) -> list[dict]:
    rolls: dict[str, list] = {}
    for r in _rows(ROLLS):
        if _norm_size(r.get("№ партии")) == num:
            rolls.setdefault(_norm_size(r.get("№ карты")), []).append(
                {"код": _s(r.get("код рулона")), "граммы": _s(r.get("граммаж г")),
                 "цвет": _s(r.get("цвет")), "вес": _s(r.get("вес кг"))})
    out = []
    for r in _rows(CARDS):
        if _norm_size(r.get("№ партии")) != num:
            continue
        no = _norm_size(r.get("№ карты"))
        out.append({"карта": no, "дата": _s(r.get("дата")), "закройщик": _s(r.get("закройщик")),
                    "лекало": _s(r.get("лекало")), "длина": _s(r.get("длина м")),
                    "рулонов": _int(r.get("рулонов")), "вес": _s(r.get("вес кг")),
                    "настилы": _s(r.get("настилы")), "штук": _int(r.get("штук")),
                    "рулоны": rolls.get(no, [])})
    return out


def save_cut(me: dict, body: dict) -> dict:
    num = _s(body.get("партия"))
    state = cut_state()
    party = next((p for p in state["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    if party["остаток"] <= 0:
        raise ValueError("Партия уже раскроена полностью")
    if party["статус"] not in ("крой", "в производстве"):
        raise ValueError(f"Партия в статусе «{party['статус']}» — крой недоступен")

    index = {(r["цвет"], r["размер"]): r for r in party["строки"]}
    prepared = []
    for p in body.get("позиции") or []:
        qty = _int(p.get("факт"), 0)
        if qty <= 0:
            continue
        key = (_s(p.get("цвет")), _norm_size(p.get("размер")))
        row = index.get(key)
        if not row:
            raise ValueError(f"Позиции {key[0]} / {key[1]} нет в партии")
        if qty > row["остаток"]:
            raise ValueError(f"{key[0]} / {key[1]}: осталось {row['остаток']} шт, "
                             f"нельзя раскроить {qty}")
        prepared.append((row, qty))
    if not prepared:
        raise ValueError("Укажите, сколько раскроено")

    numbers = [_int(n["настил"]) for n in party["настилы"]]
    настил = _int(body.get("настил")) or (max(numbers) + 1 if numbers else 1)
    if настил in numbers:
        raise ValueError(f"Настил {настил} уже существует")
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    day = datetime.now().strftime("%d.%m.%Y")
    who = _s(me.get("фио")) or _s(me.get("логин"))

    cut_rows = _rows(CUT)
    for row, qty in prepared:
        cut_rows.append({
            "№ партии": num, "настил": настил, "цвет": row["цвет"],
            "размер": row["размер"], "план шт": row["остаток"], "факт шт": qty,
            "закройщик": who, "дата": now, "комментарий": _s(body.get("комментарий")),
        })

    total = sum(q for _, q in prepared)
    rate = rate_of("РАСКР", 15.0)
    issue_rows = _rows(OUT)
    new_id = max([_int(r.get("id")) for r in issue_rows] or [0]) + 1
    issue_rows.append({
        "id": new_id, "дата": day, "партия": num, "настил": настил, "цвет": "", "размер": "",
        "этап": "РАСКР", "логин": _s(me.get("логин")), "ФИО": who, "количество": total,
        "начало": now, "конец": now, "ставка": rate, "сумма": round(total * rate, 2),
        "статус": "готово", "комментарий": f"настил {настил}",
    })

    done = party["остаток"] - total <= 0
    party_rows = _rows(PARTIES)
    new_status = "в производстве" if done else "крой"
    for r in party_rows:
        if _s(r.get("№ партии")) == num:
            r["статус"] = new_status

    store.write_sheets([(CUT[0], CUT[1], cut_rows),
                        (OUT[0], OUT[1], issue_rows),
                        (PARTIES[0], PARTIES[1], party_rows)])
    return {"настил": f"{num}/{настил}", "штук": total,
            "сумма": round(total * rate, 2), "ставка": rate,
            "статус": new_status, "готово": done}


# ------------------------------------------------------------ швеи (модуль 4)
# Маршрут — граф этапов: у каждого этапа список «после каких этапов».
# Шаблонов может быть несколько (колонка «шаблон» листа «Маршрут»), модель
# привязывается к шаблону в листе «Маршрут модели». При приёмке заказа маршрут
# копируется в лист «Маршрут партии» — правка шаблона не ломает партии в работе.
MAIN_ROUTE = "Основной"
START_STAGE = "РАСКР"
DONE_PARTY = ("упакован", "на складе", "отгружен", "отгружена")

DEFAULT_ROUTE = [
    ("ОВЕРЛ", "РАСКР"),
    ("КАРМАН", "РАСКР"),
    ("СБОРКА", "ОВЕРЛ;КАРМАН"),
    ("ОТДЕЛКА", "СБОРКА"),
]


def seed_route() -> int:
    if _rows(ROUTE):
        return 0
    rows = [{"шаблон": MAIN_ROUTE, "этап": code, "после каких этапов": dep,
             "на склад ГП": 0, "кто может": "", "активен": 1}
            for code, dep in DEFAULT_ROUTE]
    store.write_sheet(ROUTE[0], ROUTE[1], rows)
    return len(rows)


def _flag(v, default: bool = True) -> bool:
    s = _s(v).lower()
    if not s:
        return default
    return s not in ("0", "0.0", "нет", "false")


def _yes(v) -> bool:
    return _s(v).lower() in ("1", "1.0", "да", "true", "yes")


def _deps(v) -> list[str]:
    if isinstance(v, (list, tuple)):
        items = v
    else:
        items = _s(v).replace(",", ";").split(";")
    out = []
    for x in items:
        x = _s(x)
        if x and x not in out:
            out.append(x)
    return out


def _ops() -> dict[str, dict]:
    """Справочник операций из листа «расценки»: код → название, ставка, порядок."""
    base: dict[str, dict] = {}
    try:
        for r in store.read_sheet("расценки"):
            code = _s(r.get("код"))
            if not code:
                continue
            raw = _s(r.get("расценка за шт")).replace(",", ".")
            try:
                rate = float(raw) if raw else 0.0
            except ValueError:
                rate = 0.0
            base[code] = {"код": code, "название": _s(r.get("операция")) or code,
                          "ставка": rate, "порядок": _int(r.get("порядок"), 500)}
    except Exception:
        pass
    return base


def _topo(items: list[dict]) -> list[dict]:
    """Порядок «по потоку»: сначала те, кого ждут; при равенстве — по «порядку»."""
    codes = {x["код"] for x in items}
    pos = {x["код"]: i for i, x in enumerate(items)}
    need = {x["код"]: {d for d in x["зависимости"] if d in codes and d != x["код"]}
            for x in items}
    out: list[dict] = []
    left = list(items)
    placed: set[str] = set()
    while left:
        ready = [x for x in left if need[x["код"]] <= placed]
        if not ready:  # цикл — оставшиеся как есть
            out.extend(left)
            break
        ready.sort(key=lambda x: (x.get("порядок", 500), pos[x["код"]]))
        nxt = ready[0]
        out.append(nxt)
        placed.add(nxt["код"])
        left.remove(nxt)
    return out


def _stage_items(rows: list[dict], ops: dict) -> list[dict]:
    out = []
    seen = set()
    for r in rows:
        code = _s(r.get("этап"))
        if not code or code in seen or not _flag(r.get("активен"), True):
            continue
        seen.add(code)
        item = dict(ops.get(code, {"код": code, "название": code, "ставка": 0.0,
                                   "порядок": 500}))
        item["зависимости"] = _deps(r.get("после каких этапов"))
        item["склад_гп"] = _yes(r.get("на склад ГП"))
        item["кто"] = _s(r.get("кто может"))
        out.append(item)
    return _topo(out)


def route_templates() -> dict[str, list[dict]]:
    """Сырые строки листа «Маршрут» по шаблонам (пустой шаблон = «Основной»)."""
    out: dict[str, list[dict]] = {}
    for r in _rows(ROUTE):
        if not _s(r.get("этап")):
            continue
        out.setdefault(_s(r.get("шаблон")) or MAIN_ROUTE, []).append(r)
    return out


def model_routes() -> dict[str, str]:
    out = {}
    for r in _rows(ROUTE_MODEL):
        m, t = _s(r.get("модель")), _s(r.get("шаблон"))
        if m and t:
            out[m] = t
    return out


def _pick_template(model: str, templates: dict, bind: dict) -> str:
    t = bind.get(model, "")
    if t in templates:
        return t
    if MAIN_ROUTE in templates or not templates:
        return MAIN_ROUTE
    return next(iter(templates))


def route_stages(template: str = MAIN_ROUTE) -> list[dict]:
    templates = route_templates()
    rows = templates.get(template)
    if rows is None:
        rows = templates.get(MAIN_ROUTE) or (next(iter(templates.values())) if templates else [])
    return _stage_items(rows, _ops())


def _party_snapshots() -> dict[str, list[dict]]:
    snap: dict[str, list[dict]] = {}
    for r in _rows(ROUTE_PARTY):
        num = _s(r.get("№ партии"))
        if num.endswith(".0"):
            num = num[:-2]
        if num and _s(r.get("этап")):
            snap.setdefault(num, []).append(r)
    return snap


def party_routes(parties: list[dict]) -> dict[str, dict]:
    """№ партии → {шаблон, своя (есть копия в «Маршрут партии»), этапы}."""
    ops = _ops()
    templates = route_templates()
    bind = model_routes()
    snap = _party_snapshots()
    cache: dict[str, list[dict]] = {}
    out: dict[str, dict] = {}
    for p in parties:
        num = _s(p.get("номер"))
        if num in snap:
            rows = snap[num]
            out[num] = {"шаблон": _s(rows[0].get("шаблон")) or MAIN_ROUTE, "своя": True,
                        "этапы": _stage_items(rows, ops)}
            continue
        t = _pick_template(_s(p.get("модель")), templates, bind)
        if t not in cache:
            cache[t] = _stage_items(templates.get(t, []), ops)
        out[num] = {"шаблон": t, "своя": False, "этапы": cache[t]}
    return out


def _union_stages(routes: dict[str, dict]) -> list[dict]:
    """Все этапы всех маршрутов партий — для общих списков (очередь, сводка)."""
    seen: dict[str, dict] = {}
    order: list[str] = []
    for r in routes.values():
        for i, st in enumerate(r["этапы"]):
            if st["код"] not in seen:
                seen[st["код"]] = st
                order.append(st["код"])
    if not seen:
        for st in route_stages():
            seen[st["код"]] = st
            order.append(st["код"])
    return _topo([seen[c] for c in order])


def _source_qty(num: str, st: dict, stages: list[dict], done: dict, base: int) -> int:
    """Сколько штук пришло на этап: минимум сданного всеми предшественниками."""
    if not st["зависимости"]:
        return base
    codes = {x["код"] for x in stages}
    return min(done.get((num, dep), base if dep not in codes else 0)
               for dep in st["зависимости"])


def _finals(stages: list[dict]) -> list[str]:
    used = {d for st in stages for d in st["зависимости"]}
    return [st["код"] for st in stages if st["код"] not in used]


def check_route(stages: list[dict], known: dict | None = None) -> dict:
    """Проверка маршрута. stages: [{код, зависимости, активен?}]."""
    errors: list[str] = []
    warnings: list[str] = []
    active = [s for s in stages if s.get("активен", True)]
    codes: list[str] = []
    for s in active:
        c = _s(s.get("код"))
        if not c:
            errors.append("Есть этап без кода")
            continue
        if c == START_STAGE:
            errors.append(f"{START_STAGE} (крой) — это старт маршрута, его не нужно добавлять этапом")
        if c in codes:
            errors.append(f"Этап {c} указан дважды")
        codes.append(c)
    if not active:
        errors.append("В маршруте нет ни одного этапа")
    cs = set(codes)
    for s in active:
        c = _s(s.get("код"))
        for d in s.get("зависимости") or []:
            if d == c:
                errors.append(f"{c} не может идти после самого себя")
            elif d not in cs and d != START_STAGE:
                errors.append(f"{c} ждёт этап {d}, которого нет в маршруте")
    # циклы
    need = {_s(s.get("код")): {d for d in (s.get("зависимости") or []) if d in cs and d != _s(s.get("код"))}
            for s in active}
    placed: set[str] = set()
    changed = True
    while changed:
        changed = False
        for c, ds in need.items():
            if c not in placed and ds <= placed:
                placed.add(c)
                changed = True
    loop = [c for c in codes if c not in placed]
    if loop:
        errors.append("Замкнутый круг: " + " → ".join(loop) + " — этапы ждут друг друга и никогда не начнутся")
    finals = _finals([{"код": _s(s.get("код")), "зависимости": s.get("зависимости") or []}
                      for s in active])
    if len(finals) > 1 and not loop:
        warnings.append("Несколько последних этапов: " + ", ".join(finals)
                        + ". Партия будет готова, когда закончатся все они.")
    if known is not None:
        missing = [c for c in codes if c not in known and c != START_STAGE]
        if missing:
            warnings.append("Нет ставки в листе «расценки»: " + ", ".join(missing)
                            + " — швея получит 0 сом/шт")
    return {"ошибки": errors, "предупреждения": warnings, "финал": finals}


def _clean_stage_input(raw: list) -> list[dict]:
    out = []
    for s in raw or []:
        code = _s(s.get("код") or s.get("этап")).upper()
        if not code:
            continue
        out.append({"код": code, "зависимости": [d.upper() for d in _deps(s.get("после") or s.get("зависимости"))],
                    "склад_гп": bool(s.get("склад_гп")), "кто": _s(s.get("кто")),
                    "активен": bool(s.get("активен", True))})
    return out


def _editor_stages(rows: list[dict], ops: dict) -> list[dict]:
    out = []
    for r in rows:
        code = _s(r.get("этап"))
        if not code:
            continue
        op = ops.get(code, {})
        out.append({"код": code, "название": op.get("название", code),
                    "ставка": op.get("ставка", 0.0), "порядок": op.get("порядок", 500),
                    "после": _deps(r.get("после каких этапов")),
                    "склад_гп": _yes(r.get("на склад ГП")), "кто": _s(r.get("кто может")),
                    "активен": _flag(r.get("активен"), True)})
    return out


def routes_state(me: dict) -> dict:
    seed_route()
    ops = _ops()
    templates = route_templates()
    bind = model_routes()
    models = [m for m in refs()["модели"]]
    tpl_out = []
    names = list(templates)
    if MAIN_ROUTE in names:
        names.remove(MAIN_ROUTE)
        names.insert(0, MAIN_ROUTE)
    for name in names:
        stages = _editor_stages(templates[name], ops)
        tpl_out.append({
            "имя": name, "этапы": stages,
            "проверка": check_route(stages_for_check(stages), ops),
            "модели": [m["модель"] for m in models
                       if _pick_template(m["модель"], templates, bind) == name],
        })

    parties_all = cut_state()["партии"]
    routes = party_routes(parties_all)
    snap = _party_snapshots()
    done: dict[tuple, int] = {}
    inwork: dict[tuple, int] = {}
    for r in _rows(OUT):
        key = (_s(r.get("партия")), _s(r.get("этап")))
        if _s(r.get("статус")) == "готово":
            done[key] = done.get(key, 0) + _int(r.get("количество"))
        elif _s(r.get("статус")) == "в работе":
            inwork[key] = inwork.get(key, 0) + _int(r.get("количество"))
    party_out = []
    for p in sorted(parties_all, key=lambda x: -_int(x["номер"])):
        if p["статус"] in DONE_PARTY:
            continue
        num = p["номер"]
        info = routes.get(num) or {"шаблон": MAIN_ROUTE, "своя": False, "этапы": []}
        rows = snap.get(num) or templates.get(info["шаблон"], [])
        party_out.append({
            "номер": num, "модель": p["модель"], "клиент": p["клиент"],
            "статус": p["статус"], "план": p["план"], "раскроено": p["раскроено"],
            "шаблон": info["шаблон"], "своя": info["своя"],
            "этапы": _editor_stages(rows, ops),
            "сдано": {st["код"]: done.get((num, st["код"]), 0) for st in info["этапы"]},
            "в_работе": {st["код"]: inwork.get((num, st["код"]), 0) for st in info["этапы"]},
        })

    return {
        "шаблоны": tpl_out,
        "операции": sorted(ops.values(), key=lambda x: (x["порядок"], x["код"])),
        "модели": [{"модель": m["модель"], "название": m["название"],
                    "категория": m["категория"],
                    "шаблон": _pick_template(m["модель"], templates, bind),
                    "назначен": m["модель"] in bind} for m in models],
        "партии": party_out,
        "сотрудники": staff_people(_s(me.get("цех"))),
        "старт": START_STAGE,
        "можно": _s(me.get("роль")) in CAN_TECH,
    }


def stages_for_check(stages: list[dict]) -> list[dict]:
    return [{"код": s["код"], "зависимости": s.get("после") or [],
             "активен": s.get("активен", True)} for s in stages]


def _route_rows(template: str, stages: list[dict]) -> list[dict]:
    return [{"шаблон": template, "этап": s["код"],
             "после каких этапов": ";".join(s["зависимости"]),
             "на склад ГП": 1 if s["склад_гп"] else 0, "кто может": s["кто"],
             "активен": 1 if s["активен"] else 0} for s in stages]


def save_route(me: dict, body: dict) -> dict:
    stages = _clean_stage_input(body.get("этапы"))
    ops = _ops()
    check = check_route(stages, ops)
    if check["ошибки"]:
        raise ValueError(check["ошибки"][0])
    party = _s(body.get("партия"))
    if party:
        return _save_party_route(party, _s(body.get("шаблон")) or MAIN_ROUTE, stages, check)

    name = _s(body.get("шаблон"))
    old = _s(body.get("старое_имя")) or name
    if not name:
        raise ValueError("Назовите шаблон")
    if len(name) > 40:
        raise ValueError("Слишком длинное название шаблона")
    templates = route_templates()
    if name != old and name in templates:
        raise ValueError(f"Шаблон «{name}» уже есть")
    if old == MAIN_ROUTE and name != MAIN_ROUTE:
        raise ValueError("Основной шаблон нельзя переименовать")
    rows = [r for r in _rows(ROUTE) if (_s(r.get("шаблон")) or MAIN_ROUTE) not in (old, name)]
    for r in rows:
        if not _s(r.get("шаблон")):
            r["шаблон"] = MAIN_ROUTE
    rows += _route_rows(name, stages)
    items = [(ROUTE[0], ROUTE[1], rows)]
    if name != old:
        bind_rows = _rows(ROUTE_MODEL)
        for r in bind_rows:
            if _s(r.get("шаблон")) == old:
                r["шаблон"] = name
        items.append((ROUTE_MODEL[0], ROUTE_MODEL[1], bind_rows))
    store.write_sheets(items)
    return {"шаблон": name, "этапов": len(stages), "предупреждения": check["предупреждения"]}


def _save_party_route(num: str, template: str, stages: list[dict], check: dict) -> dict:
    parties_all = cut_state()["партии"]
    if not any(p["номер"] == num for p in parties_all):
        raise ValueError("Партия не найдена")
    codes = {s["код"] for s in stages if s["активен"]}
    warn = list(check["предупреждения"])
    for r in _rows(OUT):
        if _s(r.get("партия")) != num:
            continue
        code = _s(r.get("этап"))
        if code == START_STAGE or code in codes:
            continue
        if _s(r.get("статус")) == "в работе":
            raise ValueError(f"Этап {code} сейчас в работе у {_s(r.get('ФИО')) or _s(r.get('логин'))}"
                             " — сначала сдайте или верните работу")
        if _s(r.get("статус")) == "готово":
            msg = f"По этапу {code} уже есть сданные штуки — они останутся в зарплате, но в маршруте не участвуют"
            if msg not in warn:
                warn.append(msg)
    rows = [r for r in _rows(ROUTE_PARTY) if _norm_size(r.get("№ партии")) != num]
    rows += [{"№ партии": num, "шаблон": template, "этап": s["код"],
              "после каких этапов": ";".join(s["зависимости"]),
              "на склад ГП": 1 if s["склад_гп"] else 0, "кто может": s["кто"]}
             for s in stages if s["активен"]]
    store.write_sheets([(ROUTE_PARTY[0], ROUTE_PARTY[1], rows)])
    return {"партия": num, "этапов": len(rows), "предупреждения": warn}


def delete_route(me: dict, body: dict) -> dict:
    name = _s(body.get("шаблон"))
    if not name or name == MAIN_ROUTE:
        raise ValueError("Основной шаблон удалить нельзя")
    rows = [r for r in _rows(ROUTE) if (_s(r.get("шаблон")) or MAIN_ROUTE) != name]
    for r in rows:
        if not _s(r.get("шаблон")):
            r["шаблон"] = MAIN_ROUTE
    bind_rows = [r for r in _rows(ROUTE_MODEL) if _s(r.get("шаблон")) != name]
    store.write_sheets([(ROUTE[0], ROUTE[1], rows), (ROUTE_MODEL[0], ROUTE_MODEL[1], bind_rows)])
    return {"ok": True}


def bind_route(me: dict, body: dict) -> dict:
    model = _s(body.get("модель"))
    name = _s(body.get("шаблон"))
    if not model:
        raise ValueError("Не выбрана модель")
    if name and name not in route_templates():
        raise ValueError(f"Шаблона «{name}» нет")
    rows = [r for r in _rows(ROUTE_MODEL) if _s(r.get("модель")) != model]
    if name and name != MAIN_ROUTE:
        rows.append({"модель": model, "шаблон": name})
    store.write_sheets([(ROUTE_MODEL[0], ROUTE_MODEL[1], rows)])
    return {"модель": model, "шаблон": name or MAIN_ROUTE}


def snapshot_rows(num, model: str) -> list[dict]:
    """Строки «Маршрут партии» для новой партии — копия шаблона её модели."""
    templates = route_templates()
    t = _pick_template(model, templates, model_routes())
    return [{"№ партии": num, "шаблон": t, "этап": _s(r.get("этап")),
             "после каких этапов": _s(r.get("после каких этапов")),
             "на склад ГП": r.get("на склад ГП", 0), "кто может": _s(r.get("кто может"))}
            for r in templates.get(t, []) if _flag(r.get("активен"), True)]


# ------------------------------------------------------- роли сотрудников
# Этап = роль. В листе «Сотрудники цеха» колонка «этап» хранит коды через «;»:
# «ОВЕРЛ;КАРМАН;СБОРКА». Пусто — роли не назначены, человек видит все этапы.
BOSSES = ("admin", "manager")


def roles_of(login: str) -> list[str]:
    for r in _rows(STAFF):
        if _s(r.get("логин")) == login:
            return [c.upper() for c in _deps(r.get("этап"))]
    return []


def can_take(me: dict, stage: dict, roles: list[str] | None = None) -> bool:
    if _s(me.get("роль")) in BOSSES:
        return True
    login = _s(me.get("логин"))
    mine = roles_of(login) if roles is None else roles
    if mine and stage["код"] not in mine:
        return False
    who = [x.strip() for x in _s(stage.get("кто")).split(",") if x.strip()]
    return not who or login in who


def staff_people(company: str = "") -> list[dict]:
    """Сотрудники цеха: карточки + пользователи портала без карточки.
    company — код цеха (Ц-01): сотрудники других цехов не показываются."""
    cards = {_s(r.get("логин")): r for r in _rows(STAFF) if _s(r.get("логин"))}
    try:
        # учётки — из листа «сотрудники» рабочей книги (как при входе), запасной вариант — users.xlsx
        from server import staff_users  # noqa: WPS433
        users = staff_users()
    except Exception:
        try:
            from server import read_table  # noqa: WPS433
            users = read_table("users")
        except Exception:
            users = []
    out: dict[str, dict] = {}
    other: set[str] = set()
    for u in users:
        login = _s(u.get("логин"))
        role = _s(u.get("роль"))
        if not login or role in ("client", ""):
            continue
        if company and _s(u.get("цех")) and _s(u.get("цех")) != company:
            other.add(login)
            continue
        out[login] = {"логин": login, "ФИО": _s(u.get("фио")) or login, "должность": role,
                      "активен": _flag(u.get("активен"), True)}
    for login, c in cards.items():
        if login in other:
            continue
        item = out.setdefault(login, {"логин": login, "ФИО": _s(c.get("ФИО")) or login,
                                      "должность": _s(c.get("должность")), "активен": True})
        if not _flag(c.get("активен"), True):
            item["активен"] = False
    res = []
    for login, item in out.items():
        if not item["активен"]:
            continue
        item["этапы"] = [x.upper() for x in _deps((cards.get(login) or {}).get("этап"))]
        res.append(item)
    res.sort(key=lambda x: (x["должность"] in BOSSES, x["ФИО"].lower()))
    return res


def set_roles(me: dict, body: dict) -> dict:
    """Назначить сотруднику этапы. body: {логин, этапы: [...]} или {логин, этап, можно: bool}."""
    login = _s(body.get("логин"))
    if not login:
        raise ValueError("Не выбран сотрудник")
    person = next((p for p in staff_people(_s(me.get("цех"))) if p["логин"] == login), None)
    if not person:
        raise ValueError("Сотрудник не найден")
    rows = _rows(STAFF)
    row = next((r for r in rows if _s(r.get("логин")) == login), None)
    if row is None:
        row = {"логин": login, "ФИО": person["ФИО"], "должность": person["должность"],
               "этап": "", "тип оплаты": "сдельная", "ставка": 0, "периодичность": "месяц",
               "модели": "", "телефон": "", "активен": 1}
        rows.append(row)
    current = [c.upper() for c in _deps(row.get("этап"))]
    if "этапы" in body:
        new = [c.upper() for c in _deps(body.get("этапы"))]
    else:
        code = _s(body.get("этап")).upper()
        if not code:
            raise ValueError("Не выбран этап")
        new = [c for c in current if c != code]
        if body.get("можно"):
            new.append(code)
    if START_STAGE in new:
        raise ValueError("Крой назначается ролью «закройщик» в портале, а не этапом")
    row["этап"] = ";".join(new)
    store.write_sheets([(STAFF[0], STAFF[1], rows)])
    return {"логин": login, "этапы": new}


def stage_rate(code: str, model: str = "") -> float:
    if model:
        try:
            for r in store.read_sheet("Ставки артикул"):
                if _s(r.get("модель")) == model and _s(r.get("этап")) == code:
                    raw = _s(r.get("ставка")).replace(",", ".")
                    if raw:
                        return float(raw)
        except Exception:
            pass
    return rate_of(code, 0.0)


def _fifo_key(p: dict):
    d = _s(p.get("дата"))
    try:
        dt = datetime.strptime(d.split(" ")[0], "%d.%m.%Y")
    except ValueError:
        dt = datetime(2000, 1, 1)
    return (dt, _int(p.get("номер")))


# ------------------------------------------------- работа по настилам (разделам)
# Партия — родитель, её разделы — настилы кроя. Каждая пара «настил × этап»
# закрепляется технологом за одной швеёй (лист «Распределение»). Швея видит
# только своё и берёт настилы по возрастанию. Этап настила открывается, когда
# все его предшественники сдали штуки этого же настила.

def _nastils(p: dict) -> list[dict]:
    out = []
    for n in p.get("настилы") or []:
        out.append({"настил": _s(n["настил"]), "шт": _int(n["шт"]), "строки": n.get("строки") or [],
                    "дата": n.get("дата", ""), "закройщик": n.get("закройщик", "")})
    out.sort(key=lambda x: _int(x["настил"]))
    return out


def _parse_ts(v):
    s = _s(v)
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _work_index(issued: list[dict] | None = None) -> tuple[dict, dict, list[dict]]:
    """done / inwork по (партия, настил, этап) + строки «в работе»."""
    done: dict[tuple, int] = {}
    inwork: dict[tuple, int] = {}
    active: list[dict] = []
    for r in issued if issued is not None else _rows(OUT):
        code = _s(r.get("этап"))
        if code == START_STAGE:
            continue
        key = (_s(r.get("партия")), _s(r.get("настил")), code)
        qty = _int(r.get("количество"))
        st = _s(r.get("статус"))
        if st == "готово":
            done[key] = done.get(key, 0) + qty
        elif st == "в работе":
            inwork[key] = inwork.get(key, 0) + qty
            active.append(r)
    return done, inwork, active


def _src_nastil(num: str, nas: str, st: dict, stages: list[dict], done: dict, base: int) -> int:
    if not st["зависимости"]:
        return base
    codes = {x["код"] for x in stages}
    return min(done.get((num, nas, dep), 0) if dep in codes else base
               for dep in st["зависимости"])


def assignments() -> dict[tuple, str]:
    out = {}
    for r in _rows(ASSIGN):
        key = (_s(r.get("№ партии")), _s(r.get("настил")), _s(r.get("этап")))
        if all(key) and _s(r.get("логин")):
            out[key] = _s(r.get("логин"))
    return out


def _nastil_complete(num: str, n: dict, stages: list[dict], done: dict) -> bool:
    if not stages or n["шт"] <= 0:
        return False
    return all(done.get((num, n["настил"], c), 0) >= n["шт"] for c in _finals(stages))


def work_state(me: dict, as_worker: bool = False) -> dict:
    parties = [p for p in cut_state()["партии"] if p["раскроено"] > 0]
    parties.sort(key=_fifo_key)
    routes = party_routes(parties)
    stages_all = _union_stages(routes)
    names = {st["код"]: st["название"] for st in stages_all}
    issued = _rows(OUT)
    done, inwork, active = _work_index(issued)
    assign = assignments()
    login = _s(me.get("логин"))
    boss = (_s(me.get("роль")) in BOSSES or _s(me.get("роль")) == "technologist") and not as_worker
    people = {p["логин"]: p["ФИО"] for p in staff_people(_s(me.get("цех")))}

    def item_of(r):
        code = _s(r.get("этап"))
        return {"id": _int(r.get("id")), "партия": _s(r.get("партия")), "настил": _s(r.get("настил")),
                "этап": code, "этап_название": names.get(code, code),
                "количество": _int(r.get("количество")), "логин": _s(r.get("логин")),
                "ФИО": _s(r.get("ФИО")), "начало": _s(r.get("начало")), "ставка": r.get("ставка"),
                "начало_iso": (_parse_ts(r.get("начало")) or datetime.now()).isoformat(timespec="seconds")}

    mine = [item_of(r) for r in active if _s(r.get("логин")) == login]
    everyone = [item_of(r) for r in active]

    cards = []
    unassigned = 0
    for p in parties:
        num = p["номер"]
        stages = (routes.get(num) or {}).get("этапы") or []
        nas_list = _nastils(p)
        lines = []
        locked: set[str] = set()  # этап, на котором швея ещё не закрыла меньший настил
        for n in nas_list:
            tasks = []
            for st in stages:
                code = st["код"]
                key = (num, n["настил"], code)
                who = assign.get(key, "")
                if not who:
                    unassigned += 1
                if not boss and who != login:
                    continue
                src = _src_nastil(num, n["настил"], st, stages, done, n["шт"])
                d, w = done.get(key, 0), inwork.get(key, 0)
                avail = max(0, src - d - w)
                if d >= n["шт"]:
                    status = "готово"
                elif w > 0 and avail <= 0:
                    status = "в работе"
                elif avail > 0:
                    status = "можно"
                else:
                    status = "ждёт"
                can = status == "можно" and (boss or code not in locked) and (boss or who == login)
                if who == login and d < n["шт"]:
                    locked.add(code)  # следующие настилы этого этапа — после этого
                tasks.append({"этап": code, "название": st["название"], "кто": who,
                              "ФИО": people.get(who, who), "сдано": d, "в_работе": w,
                              "доступно": avail, "статус": status, "можно": can,
                              "ставка": stage_rate(code, p["модель"])})
            if tasks or boss:
                lines.append({"настил": n["настил"], "номер": f'{num}/{n["настил"]}', "шт": n["шт"],
                              "готов": _nastil_complete(num, n, stages, done), "задачи": tasks})
        if not any(l["задачи"] for l in lines) and not boss:
            continue
        cards.append({"номер": num, "модель": p["модель"], "категория": p["категория"],
                      "клиент": p["клиент"], "срок": p["срок"], "статус": p["статус"],
                      "план": p["план"], "раскроено": p["раскроено"], "остаток_крой": p["остаток"],
                      "настилы": lines})

    queue = [dict(t, партия=c["номер"], настил=l["настил"], этап_название=t["название"],
                  клиент=c["клиент"], модель=c["модель"], категория=c["категория"], срок=c["срок"])
             for c in cards for l in c["настилы"] for t in l["задачи"] if t["можно"]]
    mine.sort(key=lambda x: -x["id"])
    everyone.sort(key=lambda x: -x["id"])
    my_roles = roles_of(login)
    ops = _ops()
    return {
        "этапы": stages_all,
        "партии": cards,
        "очередь": queue,
        "мои": mine,
        "все": everyone,
        "не_распределено": unassigned,
        "мои_этапы": [{"код": c, "название": names.get(c) or ops.get(c, {}).get("название", c)}
                      for c in my_roles],
        "все_этапы_видны": boss,
        "итог": _my_today(me),
    }


def _my_today(me: dict) -> dict:
    today = datetime.now().strftime("%d.%m.%Y")
    qty = 0
    total = 0.0
    for r in _rows(OUT):
        if _s(r.get("логин")) != _s(me.get("логин")):
            continue
        if _s(r.get("статус")) != "готово":
            continue
        if not _s(r.get("дата")).startswith(today):
            continue
        qty += _int(r.get("количество"))
        total += float(str(r.get("сумма") or 0).replace(",", ".") or 0)
    return {"сегодня_шт": qty, "сегодня_сумма": round(total, 2)}


def assign_state(me: dict) -> dict:
    """Экран технолога: партии после кроя, настилы × этапы, кто закреплён."""
    parties = [p for p in cut_state()["партии"]
               if p["раскроено"] > 0 and p["статус"] not in DONE_PARTY]
    parties.sort(key=_fifo_key)
    routes = party_routes(parties)
    assign = assignments()
    done, inwork, _ = _work_index()
    people = [p for p in staff_people(_s(me.get("цех"))) if p["должность"] not in BOSSES or p["этапы"]]
    out = []
    for p in parties:
        num = p["номер"]
        stages = (routes.get(num) or {}).get("этапы") or []
        nas = _nastils(p)
        cells = {}
        for n in nas:
            for st in stages:
                key = (num, n["настил"], st["код"])
                cells[f'{n["настил"]}|{st["код"]}'] = {
                    "логин": assign.get(key, ""), "сдано": done.get(key, 0),
                    "в_работе": inwork.get(key, 0)}
        free = sum(1 for c in cells.values() if not c["логин"])
        lab = labels_state(num)
        out.append({"номер": num, "модель": p["модель"], "клиент": p["клиент"],
                    "этикетки": {k: lab[k] for k in ("сгенерировано", "дата", "кто", "устарели", "всего")},
                    "срок": p["срок"], "статус": p["статус"], "план": p["план"],
                    "раскроено": p["раскроено"], "остаток_крой": p["остаток"],
                    "настилы": [{"настил": n["настил"], "шт": n["шт"], "закройщик": n["закройщик"],
                                 "строки": [{"цвет": r["цвет"], "размер": r["размер"],
                                             "план": r["план"], "факт": r["факт"]} for r in n["строки"]]}
                                for n in nas],
                    "этапы": [{"код": st["код"], "название": st["название"]} for st in stages],
                    "ячейки": cells, "не_распределено": free})
    return {"партии": out,
            "люди": [{"логин": p["логин"], "ФИО": p["ФИО"], "этапы": p["этапы"]} for p in people]}


def fix_cut(me: dict, body: dict) -> dict:
    """Технолог исправляет фактическое количество кроя: body {партия, строки:[{настил, цвет, размер, факт}]}.
    Исправление пишется прямо в лист «крой» (факт шт) с пометкой в комментарии —
    от него считаются работа, упаковка и этикетки."""
    num = _s(body.get("партия"))
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    stages = (party_routes([party]).get(num) or {}).get("этапы") or []
    done, inwork, _ = _work_index()
    rows = _rows(CUT)
    who = _s(me.get("фио")) or _s(me.get("логин"))
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    by_key = {}
    for r in rows:
        if _norm_size(r.get("№ партии")) == num:
            by_key[(_s(r.get("настил")), _s(r.get("цвет")), _norm_size(r.get("размер")))] = r
    new_tot: dict[str, int] = {}
    for r in rows:
        if _norm_size(r.get("№ партии")) == num:
            n = _s(r.get("настил"))
            new_tot[n] = new_tot.get(n, 0) + _int(r.get("факт шт"))
    changes = []
    for it in body.get("строки") or []:
        key = (_s(it.get("настил")), _s(it.get("цвет")), _norm_size(it.get("размер")))
        r = by_key.get(key)
        if r is None:
            raise ValueError(f"Строки {key[1]} / {key[2]} в настиле {key[0]} нет")
        val = _int(it.get("факт"), -1)
        if val < 0:
            raise ValueError("Количество не может быть отрицательным")
        old = _int(r.get("факт шт"))
        if val == old:
            continue
        new_tot[key[0]] += val - old
        changes.append((r, old, val))
    if not changes:
        return {"изменено": 0}
    # нельзя уменьшить настил ниже того, что цех уже сдал или держит в работе
    for n, tot in new_tot.items():
        for st in stages:
            used = done.get((num, n, st["код"]), 0) + inwork.get((num, n, st["код"]), 0)
            if tot < used:
                raise ValueError(f"Настил {num}/{n}: на этапе «{st['название']}» уже {used} шт — "
                                 f"нельзя сделать настил меньше ({tot} шт)")
    for r, old, val in changes:
        r["факт шт"] = val
        note = f"исправил {who} {now}: было {old}"
        r["комментарий"] = (_s(r.get("комментарий")) + "; " if _s(r.get("комментарий")) else "") + note
    store.write_sheets([(CUT[0], CUT[1], rows)])
    return {"изменено": len(changes)}


def save_assign(me: dict, body: dict) -> dict:
    """body: {партия, назначения: [{настил, этап, логин}]} — логин пустой = снять."""
    num = _s(body.get("партия"))
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    stages = {st["код"] for st in (party_routes([party]).get(num) or {}).get("этапы") or []}
    nas = {n["настил"] for n in _nastils(party)}
    people = {p["логин"]: p for p in staff_people(_s(me.get("цех")))}
    _, inwork, _ = _work_index()
    rows = _rows(ASSIGN)
    index = {(_s(r.get("№ партии")), _s(r.get("настил")), _s(r.get("этап"))): r for r in rows}
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    changed = 0
    for a in body.get("назначения") or []:
        n, code, login = _s(a.get("настил")), _s(a.get("этап")), _s(a.get("логин"))
        if n not in nas or code not in stages:
            raise ValueError(f"Настила {n} или этапа {code} нет в партии")
        if login and login not in people:
            raise ValueError(f"Сотрудник {login} не найден в этом цехе")
        key = (num, n, code)
        cur = index.get(key)
        if cur and _s(cur.get("логин")) == login:
            continue
        if cur and inwork.get(key, 0) > 0:
            raise ValueError(f"Настил {num}/{n}, {code}: работа уже взята — сначала сдайте или верните её")
        if cur:
            rows.remove(cur)
            index.pop(key, None)
        if login:
            row = {"№ партии": num, "настил": n, "этап": code, "логин": login,
                   "ФИО": people[login]["ФИО"], "назначил": _s(me.get("логин")), "дата": now}
            rows.append(row)
            index[key] = row
        changed += 1
    if changed:
        rows.sort(key=lambda r: (_int(r.get("№ партии")), _int(r.get("настил")), _s(r.get("этап"))))
        store.write_sheets([(ASSIGN[0], ASSIGN[1], rows)])
    return {"изменено": changed}


def take_work(me: dict, body: dict) -> dict:
    code = _s(body.get("этап"))
    num = _s(body.get("партия"))
    nas = _s(body.get("настил"))
    qty = _int(body.get("количество"))
    if qty <= 0:
        raise ValueError("Укажите количество")
    if not code or not num or not nas:
        raise ValueError("Не выбрана работа")
    if _s(me.get("роль")) not in BOSSES and any(
            _s(r.get("статус")) == "в работе" and _s(r.get("логин")) == _s(me.get("логин"))
            for r in _rows(OUT)):
        raise ValueError("Сначала закончите или отмените текущую работу")
    state = work_state(me, as_worker=bool(body.get("как_швея")))
    card = next((c for c in state["партии"] if c["номер"] == num), None)
    line = next((l for l in (card or {}).get("настилы", []) if l["настил"] == nas), None)
    task = next((t for t in (line or {}).get("задачи", []) if t["этап"] == code), None)
    if not task:
        raise ValueError("Эта работа за вами не закреплена — её распределяет технолог")
    if not task["можно"]:
        if task["статус"] == "можно":
            raise ValueError("Сначала закончите предыдущий настил на этом этапе")
        raise ValueError("Эта работа пока недоступна — обновите список")
    if qty > task["доступно"]:
        raise ValueError(f"Доступно только {task['доступно']} шт")

    rows = _rows(OUT)
    new_id = max([_int(r.get("id")) for r in rows] or [0]) + 1
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    rows.append({
        "id": new_id, "дата": datetime.now().strftime("%d.%m.%Y"),
        "партия": num, "настил": nas, "цвет": "", "размер": "",
        "этап": code, "логин": _s(me.get("логин")),
        "ФИО": _s(me.get("фио")), "количество": qty,
        "начало": now, "конец": "", "ставка": task["ставка"], "сумма": 0,
        "статус": "в работе", "комментарий": "",
    })
    store.write_sheets([(OUT[0], OUT[1], rows)])
    return {"id": new_id, "количество": qty}


def finish_work(me: dict, body: dict) -> dict:
    work_id = _int(body.get("id"))
    rows = _rows(OUT)
    row = next((r for r in rows if _int(r.get("id")) == work_id), None)
    if not row:
        raise ValueError("Работа не найдена")
    if _s(row.get("статус")) != "в работе":
        raise ValueError("Эта работа уже закрыта")
    role = _s(me.get("роль"))
    if _s(row.get("логин")) != _s(me.get("логин")) and role not in ("admin", "manager"):
        raise ValueError("Это чужая работа")

    qty = _int(body.get("количество"), _int(row.get("количество")))
    if qty <= 0:
        raise ValueError("Количество должно быть больше нуля")
    if qty > _int(row.get("количество")):
        raise ValueError("Сдано больше, чем взято")
    rate = float(str(row.get("ставка") or 0).replace(",", ".") or 0)
    row["количество"] = qty
    row["сумма"] = round(qty * rate, 2)
    row["конец"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    started = _parse_ts(row.get("начало"))
    if started:
        row["секунд"] = int((datetime.now() - started).total_seconds())
    row["статус"] = "готово"

    party_rows = _rows(PARTIES)
    num = _s(row.get("партия"))
    if _party_done(num, rows):
        for r in party_rows:
            if _s(r.get("№ партии")) == num:
                r["статус"] = "готово к упаковке"

    store.write_sheets([(OUT[0], OUT[1], rows), (PARTIES[0], PARTIES[1], party_rows)])
    return {"сумма": row["сумма"], "количество": qty, "статус": _s(row.get("статус"))}


def _party_done(num: str, issued: list[dict]) -> bool:
    """Партия готова к упаковке: все её настилы прошли маршрут (недокрой не держит партию)."""
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party or party["раскроено"] <= 0:
        return False
    stages = party_routes([party]).get(num, {}).get("этапы") or []
    done, _, _ = _work_index(issued)
    nas = _nastils(party)
    return bool(nas) and all(_nastil_complete(num, n, stages, done) for n in nas)


def cancel_work(me: dict, body: dict) -> dict:
    work_id = _int(body.get("id"))
    rows = _rows(OUT)
    row = next((r for r in rows if _int(r.get("id")) == work_id), None)
    if not row:
        raise ValueError("Работа не найдена")
    if _s(row.get("статус")) != "в работе":
        raise ValueError("Закрытую работу нельзя отменить")
    if _s(me.get("роль")) not in ("admin", "manager") and _s(row.get("логин")) != _s(me.get("логин")):
        raise ValueError("Отменить можно только свою работу")
    row["статус"] = "отменена"
    row["конец"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    store.write_sheets([(OUT[0], OUT[1], rows)])
    return {"ok": True}


# -------------------------------------------------------- упаковка (модуль 5)
def _brand() -> dict:
    try:
        rows = {_s(r.get("параметр")): _s(r.get("значение")) for r in store.read_sheet("настройки")}
    except Exception:
        rows = {}
    return {"название": rows.get("название") or "Швейный цех",
            "подзаголовок": rows.get("подзаголовок") or ""}


def pack_state(me: dict) -> dict:
    parties = cut_state()["партии"]
    packed = _rows(PACK)
    acc: dict[tuple, int] = {}
    boxes_by_party: dict[str, set] = {}
    for r in packed:
        num = _s(r.get("партия"))
        key = (num, _s(r.get("цвет")), _norm_size(r.get("размер")))
        acc[key] = acc.get(key, 0) + _int(r.get("количество"))
        boxes_by_party.setdefault(num, set()).add(_s(r.get("коробка")))

    routes = party_routes(parties)
    work_done, _, _ = _work_index()
    out = []
    for p in parties:
        if p["раскроено"] <= 0:
            continue
        num = p["номер"]
        stages = (routes.get(num) or {}).get("этапы") or []
        nas = _nastils(p)
        ready_nas = [n for n in nas if _nastil_complete(num, n, stages, work_done)]
        if not ready_nas and p["статус"] not in ("упакован", "на складе"):
            continue
        # к упаковке доступно только то, что пришло из настилов, прошедших весь маршрут
        ready: dict[tuple, int] = {}
        for n in ready_nas:
            for r in n["строки"]:
                k = (r["цвет"], _norm_size(r["размер"]))
                ready[k] = ready.get(k, 0) + _int(r.get("факт"))
        rows = []
        done_total = 0
        for r in p["строки"]:
            fact = ready.get((r["цвет"], r["размер"]), 0)
            got = acc.get((num, r["цвет"], r["размер"]), 0)
            done_total += min(got, r["раскроено"])
            rows.append({"цвет": r["цвет"], "размер": r["размер"], "факт": fact,
                         "раскроено": r["раскроено"],
                         "упаковано": got, "остаток": max(0, fact - got)})
        boxes = sorted(boxes_by_party.get(p["номер"], set()), key=lambda x: _int(x))
        out.append({
            "номер": p["номер"], "клиент": p["клиент"], "модель": p["модель"],
            "категория": p["категория"], "срок": p["срок"], "дата": p["дата"],
            "статус": p["статус"], "план": p["план"], "факт": p["раскроено"],
            "упаковано": done_total, "остаток": max(0, p["раскроено"] - done_total),
            "готово_к_упаковке": sum(r["остаток"] for r in rows),
            "настилы": [{"настил": n["настил"], "шт": n["шт"], "готов": n in ready_nas} for n in nas],
            "строки": rows, "коробки": [b for b in boxes if b],
            "коробка_следующая": (max([_int(b) for b in boxes if b], default=0) + 1),
        })
    out.sort(key=lambda p: _int(p["номер"]))
    return {"партии": out, "бренд": _brand()}


def save_pack(me: dict, body: dict) -> dict:
    num = _s(body.get("партия"))
    state = pack_state(me)
    party = next((p for p in state["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    if party["остаток"] <= 0:
        raise ValueError("Партия уже упакована")
    if party["готово_к_упаковке"] <= 0:
        raise ValueError("Ни один настил ещё не прошёл весь маршрут")

    index = {(r["цвет"], r["размер"]): r for r in party["строки"]}
    prepared = []
    for p in body.get("позиции") or []:
        qty = _int(p.get("количество"), 0)
        if qty <= 0:
            continue
        key = (_s(p.get("цвет")), _norm_size(p.get("размер")))
        row = index.get(key)
        if not row:
            raise ValueError(f"Позиции {key[0]} / {key[1]} нет в партии")
        if qty > row["остаток"]:
            raise ValueError(f"{key[0]} / {key[1]}: готово к упаковке только {row['остаток']} шт")
        prepared.append((row, qty))
    if not prepared:
        raise ValueError("Укажите, что упаковываем")

    box = _s(body.get("коробка")) or str(party["коробка_следующая"])
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    who = _s(me.get("фио")) or _s(me.get("логин"))

    rows = _rows(PACK)
    new_id = max([_int(r.get("id")) for r in rows] or [0]) + 1
    for row, qty in prepared:
        rows.append({
            "id": new_id, "дата": now, "партия": num, "цвет": row["цвет"],
            "размер": row["размер"], "коробка": box, "количество": qty,
            "этикеток": 1, "кто": who, "статус": "упаковано",
        })
        new_id += 1

    total = sum(q for _, q in prepared)
    left = party["остаток"] - total
    party_rows = _rows(PARTIES)
    new_status = party["статус"]
    if left <= 0:
        new_status = "упакован"
        for r in party_rows:
            if _s(r.get("№ партии")) == num:
                r["статус"] = new_status

    store.write_sheets([(PACK[0], PACK[1], rows), (PARTIES[0], PARTIES[1], party_rows)])
    return {"коробка": box, "штук": total, "этикеток": len(prepared),
            "статус": new_status, "готово": left <= 0}


# -------------------------------------------------- этикетки изделий (DataMatrix)
# На каждое изделие — этикетка 40×30: DataMatrix + наименование
# «Категория/Модель/Цвет/Размер» (как в листе «главный»). В DataMatrix зашито
# то же наименование в кодировке Windows-1251 — так же, как делает BarTender.
# Технолог генерирует после кроя: количество = раскроено по цвету и размеру.

_DM_CACHE: dict[str, str] = {}


def item_name(category: str, model: str, color: str, size: str) -> str:
    return f"{category}/{model}/{color}/{_norm_size(size)}"


def datamatrix_svg(text: str) -> str:
    """SVG-разметка DataMatrix (только <path>), квадрат в модулях."""
    if text in _DM_CACHE:
        return _DM_CACHE[text]
    import zxingcpp
    try:
        data = text.encode("cp1251")
    except UnicodeEncodeError:
        data = text.encode("utf-8")
    svg = zxingcpp.create_barcode(data, zxingcpp.BarcodeFormat.DataMatrix,
                                  forceSquare=True).to_svg()  # квадрат, как в BarTender
    svg = svg[svg.index("<svg"):]
    m = re.search(r'width="(\d+)" height="(\d+)"', svg)
    if m and "viewBox" not in svg[:200]:  # без viewBox картинка не масштабируется под этикетку
        svg = svg.replace("<svg ", f'<svg viewBox="0 0 {m.group(1)} {m.group(2)}" ', 1)
    if len(_DM_CACHE) > 2000:
        _DM_CACHE.clear()
    _DM_CACHE[text] = svg
    return svg


def _catalog_names() -> dict[tuple, str]:
    """(модель, цвет, размер) → категория из каталога «главный»."""
    out = {}
    for r in _catalog_rows():
        out[(r["модель"], r["цвет"].lower(), r["размер"])] = r["категория"]
    return out


def _label_rows_for(p: dict) -> list[dict]:
    cats = _catalog_names()
    rows = []
    for r in p["строки"]:
        qty = _int(r.get("раскроено"))
        if qty <= 0:
            continue
        cat = cats.get((p["модель"], r["цвет"].lower(), r["размер"])) or p["категория"]
        rows.append({"категория": cat, "модель": p["модель"], "цвет": r["цвет"], "размер": r["размер"],
                     "наименование": item_name(cat, p["модель"], r["цвет"], r["размер"]),
                     "количество": qty})
    return rows


def labels_state(num: str) -> dict:
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    saved = [r for r in _rows(ITEM_LABELS) if _norm_size(r.get("№ партии")) == num]
    fresh = _label_rows_for(party)
    now_map = {x["наименование"]: x["количество"] for x in fresh}
    old_map = {_s(r.get("наименование")): _int(r.get("количество")) for r in saved}
    return {
        "партия": num, "модель": party["модель"], "клиент": party["клиент"],
        "раскроено": party["раскроено"], "план": party["план"], "крой_идёт": party["остаток"] > 0,
        "сгенерировано": bool(saved),
        "дата": _s(saved[0].get("дата")) if saved else "",
        "кто": _s(saved[0].get("сгенерировал")) if saved else "",
        "устарели": bool(saved) and now_map != old_map,
        "строки": [{"наименование": _s(r.get("наименование")), "цвет": _s(r.get("цвет")),
                    "размер": _norm_size(r.get("размер")), "количество": _int(r.get("количество"))}
                   for r in saved],
        "всего": sum(old_map.values()),
    }


def generate_labels(me: dict, body: dict) -> dict:
    num = _s(body.get("партия"))
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    fresh = _label_rows_for(party)
    if not fresh:
        raise ValueError("Партия ещё не раскроена — этикетки генерируются по факту кроя")
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    who = _s(me.get("фио")) or _s(me.get("логин"))
    rows = [r for r in _rows(ITEM_LABELS) if _norm_size(r.get("№ партии")) != num]
    rows += [{"№ партии": num, "наименование": x["наименование"], "категория": x["категория"],
              "модель": x["модель"], "цвет": x["цвет"], "размер": x["размер"],
              "количество": x["количество"], "сгенерировал": who, "дата": now} for x in fresh]
    store.write_sheets([(ITEM_LABELS[0], ITEM_LABELS[1], rows)])
    return {"партия": num, "строк": len(fresh), "этикеток": sum(x["количество"] for x in fresh)}


def item_labels_print(num: str) -> dict:
    st = labels_state(num)
    if not st["сгенерировано"]:
        raise ValueError("Этикетки этой партии ещё не сгенерированы")
    size = "40x30"
    try:
        for r in store.read_sheet("настройки"):
            if _s(r.get("параметр")) in ("этикетка изделия", "этикетка мм"):
                size = _s(r.get("значение")) or size
    except Exception:
        pass
    w, _, h = size.lower().replace("×", "x").partition("x")
    for r in st["строки"]:
        r["svg"] = datamatrix_svg(r["наименование"])
    st["мм"] = {"ш": _int(w, 40) or 40, "в": _int(h, 30) or 30}
    return st


def labels_data(party: str = "", box: str = "") -> dict:
    packed = _rows(PACK)
    party_rows = _rows(PARTIES)
    meta = {}
    for r in party_rows:
        meta.setdefault(_s(r.get("№ партии")), {
            "модель": _s(r.get("модель")), "категория": _s(r.get("категория")),
            "клиент": _s(r.get("клиент")),
        })
    brand = _brand()
    labels = []
    for r in packed:
        num = _s(r.get("партия"))
        if party and num != party:
            continue
        if box and _s(r.get("коробка")) != box:
            continue
        m = meta.get(num, {})
        labels.append({
            "партия": num, "коробка": _s(r.get("коробка")), "цвет": _s(r.get("цвет")),
            "размер": _norm_size(r.get("размер")), "количество": _int(r.get("количество")),
            "модель": m.get("модель", ""), "категория": m.get("категория", ""),
            "клиент": m.get("клиент", ""), "дата": _s(r.get("дата")),
            "бренд": brand["название"], "подзаголовок": brand["подзаголовок"],
        })
    labels.reverse()
    return {"этикетки": labels, "бренд": brand}


# -------------------------------------------------------- зарплата (модуль 6)
ROLE_NAMES = {"admin": "начальник", "manager": "менеджер", "technologist": "технолог",
              "accountant": "бухгалтер", "storekeeper": "складчик", "user": "швея",
              "cutter": "закройщик", "packer": "упаковщик"}
PAY_TYPES = ("сдельная", "оклад", "посменная")
PAY_PERIODS = ("месяц", "3 раза", "неделя")


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
        return datetime.strptime(_s(s)[:10], "%d.%m.%Y").date()
    except ValueError:
        return None


def periods_for(month: str, kind: str) -> list[dict]:
    from datetime import date as _date, timedelta
    y, m, last = _month_bounds(month)
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
    return _rows(STAFF)


def seed_staff() -> int:
    if _rows(STAFF):
        return 0
    try:
        from server import read_table  # noqa: WPS433
        users = read_table("users")
    except Exception:
        users = []
    rows = []
    for u in users:
        role = _s(u.get("роль"))
        if role in ("client", "") or str(u.get("активен", 1)) in ("0", "False"):
            continue
        rows.append({
            "логин": _s(u.get("логин")), "ФИО": _s(u.get("фио")),
            "должность": role, "этап": "",
            "тип оплаты": "оклад" if role not in ("user", "cutter", "packer") else "сдельная",
            "ставка": 0, "периодичность": "месяц", "модели": "",
            "телефон": "", "активен": 1,
        })
    if rows:
        store.write_sheet(STAFF[0], STAFF[1], rows)
    return len(rows)


def _party_models() -> dict[str, str]:
    out = {}
    for r in _rows(PARTIES):
        out.setdefault(_s(r.get("№ партии")), _s(r.get("модель")))
    return out


def payroll_data(month: str, me: dict) -> dict:
    seed_staff()
    y, m, last = _month_bounds(month)
    cards = {_s(c.get("логин")): c for c in staff_cards()}
    role = _s(me.get("роль"))
    only_me = role not in CAN_PAY

    models = _party_models()
    issued = []
    for r in _rows(OUT):
        if _s(r.get("статус")) != "готово":
            continue
        d = _date_of(r.get("дата"))
        if not d or d.year != y or d.month != m:
            continue
        issued.append((r, d))

    shifts = []
    for r in _rows(SHIFTS):
        d = _date_of(r.get("дата"))
        if d and d.year == y and d.month == m:
            shifts.append((r, d))

    people = []
    logins = set(cards)
    for r, _d in issued:
        logins.add(_s(r.get("логин")))
    for login in sorted(logins):
        card = cards.get(login) or {}
        if only_me and login != _s(me.get("логин")):
            continue
        if str(card.get("активен", 1)) in ("0", "False"):
            continue
        kind = _s(card.get("тип оплаты")) or ("сдельная" if _s(card.get("должность")) in
                                             ("user", "cutter", "packer") else "оклад")
        if kind not in PAY_TYPES:
            kind = "сдельная"
        rate = float(str(card.get("ставка") or 0).replace(",", ".") or 0)
        periodicity = _s(card.get("периодичность")) or "месяц"
        if periodicity not in PAY_PERIODS:
            periodicity = "месяц"
        fio = _s(card.get("ФИО")) or login
        spans = periods_for(month, periodicity)

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
                if _s(r.get("логин")) != login:
                    continue
                if not (span["первый"] <= d.day <= span["последний"]):
                    continue
                amount = float(str(r.get("сумма") or 0).replace(",", ".") or 0)
                piece += amount
                qty += _int(r.get("количество"))
                model = models.get(_s(r.get("партия")), "")
                item = by_model.setdefault(model or "—", {"модель": model or "—", "шт": 0, "сумма": 0.0})
                item["шт"] += _int(r.get("количество"))
                item["сумма"] += amount
            if kind == "оклад" and rate:
                salary = round(rate * span["дней"] / last, 2)
            if kind == "посменная":
                for r, d in shifts:
                    if _s(r.get("логин")) != login:
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
            "периодичность": periodicity, "этап": _s(card.get("этап")),
            "должность": ROLE_NAMES.get(_s(card.get("должность")), _s(card.get("должность"))),
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
    closed = [r for r in _rows(SALARY) if _s(r.get("месяц")) == month]
    return {"месяц": month, "люди": people, "итого": totals,
            "закрыто": len(closed), "только_своё": only_me}


def close_payroll(me: dict, body: dict) -> dict:
    month = _s(body.get("месяц"))
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Неверный месяц")
    data = payroll_data(month, me)
    existing = {(_s(r.get("месяц")), _s(r.get("период")), _s(r.get("логин")))
                for r in _rows(SALARY)}
    rows = _rows(SALARY)
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
    store.write_sheets([(SALARY[0], SALARY[1], rows)])
    return {"начислено": added}


def update_card(me: dict, body: dict) -> dict:
    login = _s(body.get("логин"))
    if not login:
        raise ValueError("Не указан сотрудник")
    rows = _rows(STAFF)
    row = next((r for r in rows if _s(r.get("логин")) == login), None)
    if not row:
        raise ValueError("Сотрудник не найден в листе «Сотрудники цеха»")
    if "тип оплаты" in body:
        kind = _s(body.get("тип оплаты"))
        if kind not in PAY_TYPES:
            raise ValueError("Неизвестный тип оплаты")
        row["тип оплаты"] = kind
    if "периодичность" in body:
        per = _s(body.get("периодичность"))
        if per not in PAY_PERIODS:
            raise ValueError("Неизвестная периодичность")
        row["периодичность"] = per
    if "ставка" in body:
        row["ставка"] = _int(body.get("ставка"))
    if "этап" in body:
        row["этап"] = _s(body.get("этап"))
    store.write_sheets([(STAFF[0], STAFF[1], rows)])
    return {"логин": login}


# --------------------------------------------------------- сводка (модуль 7)
def summary(me: dict) -> dict:
    parties = cut_state()["партии"]
    routes = party_routes(parties)
    stages = _union_stages(routes)
    issued = _rows(OUT)
    packed = _rows(PACK)

    done: dict[tuple, int] = {}
    inwork: dict[tuple, int] = {}
    for r in issued:
        key = (_s(r.get("партия")), _s(r.get("этап")))
        qty = _int(r.get("количество"))
        if _s(r.get("статус")) == "готово":
            done[key] = done.get(key, 0) + qty
        elif _s(r.get("статус")) == "в работе":
            inwork[key] = inwork.get(key, 0) + qty

    stage_rows = []
    for st in stages:
        waiting = 0
        active = 0
        for p in parties:
            num = p["номер"]
            route = routes.get(num, {}).get("этапы") or []
            own = next((x for x in route if x["код"] == st["код"]), None)
            if own is None:
                continue
            src = _source_qty(num, own, route, done, p["раскроено"])
            left = max(0, src - done.get((num, st["код"]), 0))
            waiting += left
            if left > 0:
                active += 1
        stage_rows.append({"код": st["код"], "название": st["название"],
                           "ждёт": waiting, "партий": active})

    packed_by_party: dict[str, int] = {}
    for r in packed:
        num = _s(r.get("партия"))
        packed_by_party[num] = packed_by_party.get(num, 0) + _int(r.get("количество"))

    articles: dict[str, dict] = {}
    for p in parties:
        model = p["модель"] or "—"
        item = articles.setdefault(model, {
            "модель": model, "категория": p["категория"], "партий": 0,
            "план": 0, "раскроено": 0, "упаковано": 0, "сумма": 0.0, "недостача": 0,
        })
        item["партий"] += 1
        item["план"] += p["план"]
        item["раскроено"] += p["раскроено"]
        item["упаковано"] += packed_by_party.get(p["номер"], 0)
        item["недостача"] += max(0, p["план"] - p["раскроено"])

    for r in issued:
        if _s(r.get("статус")) != "готово":
            continue
        model = next((p["модель"] for p in parties if p["номер"] == _s(r.get("партия"))), "")
        if model in articles:
            articles[model]["сумма"] += float(str(r.get("сумма") or 0).replace(",", ".") or 0)

    shortages = []
    for p in parties:
        if p["план"] > p["раскроено"]:
            shortages.append({
                "партия": p["номер"], "модель": p["модель"], "клиент": p["клиент"],
                "план": p["план"], "факт": p["раскроено"],
                "недостача": p["план"] - p["раскроено"],
            })

    today = datetime.now().date()
    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        days.append({"дата": d.strftime("%d.%m"), "шт": 0, "сумма": 0.0})
    index = {d["дата"]: d for d in days}
    for r in issued:
        if _s(r.get("статус")) != "готово":
            continue
        dt = _date_of(r.get("дата"))
        if not dt:
            continue
        key = dt.strftime("%d.%m")
        if key in index:
            index[key]["шт"] += _int(r.get("количество"))
            index[key]["сумма"] += float(str(r.get("сумма") or 0).replace(",", ".") or 0)

    orders_rows = _rows(ORDERS)
    waiting_orders = len({_s(r.get("№ заказа")) for r in orders_rows
                          if _s(r.get("статус")) == "у технолога"})
    in_work = [p for p in parties if p["раскроено"] > 0 and p["статус"] not in
               ("готово к упаковке", "упакован", "на складе")]
    packed_total = sum(packed_by_party.values())
    plan_total = sum(p["план"] for p in parties)
    cut_total = sum(p["раскроено"] for p in parties)

    return {
        "кпі": {
            "заказов_в_работе": len(in_work),
            "ждут_технолога": waiting_orders,
            "партий": len(parties),
            "план": plan_total,
            "раскроено": cut_total,
            "упаковано": packed_total,
            "недостача": max(0, plan_total - cut_total),
            "в_производстве": sum(max(0, s["ждёт"]) for s in stage_rows),
        },
        "этапы": stage_rows,
        "недостачи": sorted(shortages, key=lambda x: -x["недостача"]),
        "артикулы": sorted(articles.values(), key=lambda x: -x["план"]),
        "выработка": days,
    }


# ------------------------------------------------------------- сиды (данные)
LETTERS = {"XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "XXXL"}


def _grid_for(size: str) -> str:
    s = _s(size).upper().replace(" ", "")
    if not s:
        return ""
    if s.replace(",", "").replace(".", "").isdigit():
        return "числовая"
    if s in LETTERS:
        return "буквенная"
    return "постель"


def _catalog_rows() -> list[dict]:
    """Каталог «главный»: [{категория, модель, цвет, размер}].
    Шапку ищем в первых строках по слову «модел» — над ней бывают пустые строки."""
    import zipfile
    path = store.source_path()
    try:
        st = path.stat()
    except OSError:
        return []
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _CATALOG_CACHE.get("key") == key:
        return _CATALOG_CACHE["rows"]
    try:
        with zipfile.ZipFile(path) as zf:
            target = store._sheet_map(zf).get("главный")
            if not target:
                return []
            raw = store._cells_to_values(zf.read(target), store._shared_strings(zf))
    except Exception:
        return []
    head_i, cols = None, {}
    for i, r in enumerate(raw[:10]):
        names = {_s(v).lower(): c for c, v in r.items()}
        if "модел" in names:
            head_i, cols = i, names
            break
    out = []
    if head_i is not None:
        c_model = cols.get("модел")
        c_color = cols.get("свет5")
        c_size = cols.get("размер6")
        c_cat = cols.get("столбец1")
        c_name = cols.get("наименования товаров")
        for r in raw[head_i + 1:]:
            model = _s(r.get(c_model)) if c_model else ""
            color = _s(r.get(c_color)) if c_color else ""
            size = _norm_size(r.get(c_size)) if c_size else ""
            cat = _s(r.get(c_cat)) if c_cat else ""
            if (not model or not color or not size) and c_name:
                parts = _s(r.get(c_name)).split("/")  # «Брюки/477/бежевый/42»
                if len(parts) >= 4:
                    cat = cat or parts[0].strip()
                    model = model or parts[1].strip()
                    color = color or parts[2].strip()
                    size = size or _norm_size(parts[3].strip())
            if model.endswith(".0"):
                model = model[:-2]
            if not model or model.lower() in ("итог", "итого"):
                continue
            out.append({"категория": cat, "модель": model, "цвет": color, "размер": size})
    _CATALOG_CACHE.update({"key": key, "rows": out})
    return out


_CATALOG_CACHE: dict = {}


def model_variants() -> dict[str, dict]:
    """Модель → её цвета и размеры по каталогу «главный» (в порядке появления)."""
    out: dict[str, dict] = {}
    for r in _catalog_rows():
        item = out.setdefault(r["модель"], {"цвета": [], "размеры": []})
        if r["цвет"] and r["цвет"] not in item["цвета"]:
            item["цвета"].append(r["цвет"])
        if r["размер"] and r["размер"] not in item["размеры"]:
            item["размеры"].append(r["размер"])
    return out


def seed_refs() -> dict:
    """Заполнить справочники из каталога «главный», если они пустые."""
    created = {}
    catalog = _catalog_rows()
    if not catalog:
        return created

    models: dict[tuple[str, str], dict] = {}
    model_grids: dict[tuple[str, str], dict[str, int]] = {}
    colors: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for r in catalog:
        cat, model, color, size = r["категория"], r["модель"], r["цвет"], r["размер"]
        if model and model.strip().lower() not in ("итог", "итого"):
            key = (cat, model)
            if key not in models:
                models[key] = {"категория": cat, "модель": model, "название": model,
                               "сетка": "числовая", "цена": "", "активна": 1}
                model_grids[key] = {}
            grid = _grid_for(size)
            if grid:
                model_grids[key][grid] = model_grids[key].get(grid, 0) + 1
                sizes.setdefault(size, 0)
        if color:
            colors.setdefault(color, "")

    for key, grid_counts in model_grids.items():
        if grid_counts:
            models[key]["сетка"] = max(grid_counts.items(), key=lambda kv: kv[1])[0]

    batch = []
    if not _rows(MODELS) and models:
        batch.append((MODELS[0], MODELS[1], list(models.values())))
        created["модели"] = len(models)

    if not _rows(COLORS) and colors:
        batch.append((COLORS[0], COLORS[1],
                      [{"цвет": c, "код тона": t, "активен": 1} for c, t in colors.items()]))
        created["цвета"] = len(colors)

    if not _rows(SIZES) and sizes:
        buckets: dict[str, list[str]] = {}
        for s in sizes:
            buckets.setdefault(_grid_for(s) or "числовая", []).append(s)
        rows = []
        for grid in ("числовая", "буквенная", "постель"):
            values = buckets.get(grid, [])
            if grid == "числовая":
                values.sort(key=lambda x: float(x.replace(",", ".")))
            elif grid == "буквенная":
                values.sort(key=lambda x: (list(LETTERS).index(x.upper()) if x.upper() in LETTERS else 99, x))
            else:
                values.sort()
            for i, s in enumerate(values, start=1):
                rows.append({"сетка": grid, "размер": s, "порядок": i * 10})
        batch.append((SIZES[0], SIZES[1], rows))
        created["размеры"] = len(rows)
    if batch:
        store.write_sheets(batch)
    return created


def _client_list(me_company: str = "") -> list[str]:
    try:
        from server import read_table  # noqa: WPS433
    except Exception:
        return []
    out = []
    for u in read_table("users"):
        if _s(u.get("роль")) == "client" and _s(u.get("фио")):
            out.append(_s(u.get("фио")))
    return out


# ------------------------------------------------------------------- API
def _fail(ctx, message: str, code: int = 400):
    ctx["err"](message, code)


def _ok(ctx, data):
    ctx["json"]({"ok": True, "data": data})


def dispatch(ctx) -> None:
    try:
        _dispatch(ctx)
    except store.CexLocked as exc:
        ctx["err"](str(exc), 409)
    except store.CexSourceError as exc:
        ctx["err"](f"Файл Excel недоступен: {exc}", 503)
    except PermissionError:
        ctx["err"]("Файл занят другой программой. Закройте Excel и повторите.", 409)
    except KeyError as exc:
        ctx["err"](f"В книге не хватает листа: {exc}", 500)


def _dispatch(ctx) -> None:
    me = ctx.get("me")
    method = ctx["method"]
    path = ctx["path"]

    if not me:
        _fail(ctx, "Нужно войти заново", 401)
        return
    role = _s(me.get("роль"))
    if role not in CAN_VIEW:
        _fail(ctx, "Раздел доступен начальнику, менеджеру и технологу", 403)
        return

    if path == "/api/cex/bootstrap" and method == "GET":
        ensure_sheets()
        seed_refs()
        data = {
            "user": {"логин": _s(me.get("логин")), "фио": _s(me.get("фио")), "роль": role,
                     "цех": _s(me.get("цех"))},
            "права": {"создать": role in CAN_CREATE, "принимать": role in CAN_TECH,
                      "кроить": role in CAN_CUT, "работать": role in CAN_WORK,
                      "упаковывать": role in CAN_PACK, "зарплата": role in CAN_PAY},
            "refs": refs(),
            "заказы": orders() if role in {"admin", "manager", "technologist",
                                          "accountant", "storekeeper", "cutter"} else [],
            "клиенты": _client_list(),
            "поставщики": supplier_list(),
            "источник": str(store.source_path()),
        }
        _ok(ctx, data)
        return

    if path == "/api/cex/orders" and method == "GET":
        ensure_sheets()
        _ok(ctx, {"заказы": orders()})
        return

    if path == "/api/cex/orders" and method == "POST":
        if role not in CAN_CREATE:
            _fail(ctx, "Оформлять заказ может начальник или менеджер", 403)
            return
        body = ctx["body"]()
        items = body.get("позиции") or []
        if not isinstance(items, list) or not items:
            _fail(ctx, "Добавьте хотя бы одну позицию")
            return
        if len(items) > 300:
            _fail(ctx, "Слишком много позиций в одном заказе")
            return
        source = _s(body.get("источник")) or OWN
        if source not in (OWN, SUPPLIER):
            _fail(ctx, "Укажите, от кого заказываем: свой цех или поставщик")
            return
        supplier = _s(body.get("поставщик")) if source == SUPPLIER else ""
        if source == SUPPLIER and not supplier:
            _fail(ctx, "Укажите поставщика или надомника")
            return
        client = supplier or "Свой цех"
        prepared = []
        for it in items:
            qty = _int(it.get("количество"), 0)
            if qty <= 0:
                _fail(ctx, "Количество должно быть больше нуля")
                return
            if not _s(it.get("модель")) or not _s(it.get("цвет")):
                _fail(ctx, "В позиции не хватает модели или цвета")
                return
            prepared.append({
                "категория": _s(it.get("категория")),
                "модель": _s(it.get("модель")),
                "цвет": _s(it.get("цвет")),
                "размер": _norm_size(it.get("размер")),
                "количество": qty,
            })
        ensure_sheets()
        with ORDER_LOCK:
            num = next_number()
            now = datetime.now().strftime("%d.%m.%Y %H:%M")
            due = _s(body.get("срок"))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                due = datetime.strptime(due, "%Y-%m-%d").strftime("%d.%m.%Y")
            comment = _s(body.get("комментарий"))
            rows = [{
                "№ заказа": num, "дата": now, "клиент": client,
                "источник": source, "поставщик": supplier,
                "категория": p["категория"], "модель": p["модель"], "цвет": p["цвет"],
                "размер": p["размер"], "количество": p["количество"],
                "срок": due, "статус": NEW if source == OWN else AT_SUPPLIER,
                "создал": _s(me.get("логин")), "№ партии": "", "комментарий": comment,
            } for p in prepared]
            store.append_rows(ORDERS[0], ORDERS[1], rows)
        _ok(ctx, {"номер": num, "дата": now, "статус": NEW if source == OWN else AT_SUPPLIER})
        return

    if path.startswith("/api/cex/orders/") and method == "GET":
        num = path.rsplit("/", 1)[-1]
        for o in orders():
            if o["номер"] == num:
                _ok(ctx, o)
                return
        _fail(ctx, "Заказ не найден", 404)
        return

    if path == "/api/cex/tech" and method == "GET":
        ensure_sheets()
        all_orders = orders()
        log = decisions()
        reasons = {}
        for row in log:
            if _s(row.get("решение")) == "отклонён":
                reasons[_s(row.get("№ заказа"))] = _s(row.get("причина"))
        rejected = []
        for o in all_orders:
            if o["статус"] == "отклонён":
                o["причина"] = reasons.get(o["номер"], "")
                rejected.append(o)
        _ok(ctx, {
            "очередь": queue(),
            "отклонённые": rejected,
            "статистика": staff_stats(),
            "журнал": list(reversed(decisions()[-30:])),
        })
        return

    if path == "/api/cex/tech/decision" and method == "POST":
        if role not in CAN_TECH:
            _fail(ctx, "Принимать заказы может технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            result = apply_decision(me, ctx["body"]())
        except ValueError as exc:
            _fail(ctx, str(exc))
            return
        _ok(ctx, result)
        return

    if path == "/api/cex/summary" and method == "GET":
        ensure_sheets()
        _ok(ctx, summary(me))
        return

    if path == "/api/cex/payroll" and method == "GET":
        ensure_sheets()
        month = _s((ctx.get("query") or {}).get("месяц", [""])[0]) or datetime.now().strftime("%Y-%m")
        _ok(ctx, payroll_data(month, me))
        return

    if path == "/api/cex/payroll/close" and method == "POST":
        if role not in CAN_PAY:
            _fail(ctx, "Начислять зарплату может бухгалтер или начальник", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, close_payroll(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/staff/card" and method == "POST":
        if role not in CAN_PAY:
            _fail(ctx, "Менять карточку оплаты может бухгалтер или начальник", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, update_card(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/pack" and method == "GET":
        ensure_sheets()
        _ok(ctx, pack_state(me))
        return

    if path == "/api/cex/pack" and method == "POST":
        if role not in CAN_PACK:
            _fail(ctx, "Упаковывать может упаковщик, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, save_pack(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/items" and method == "GET":
        ensure_sheets()
        q = ctx.get("query") or {}
        num = _s((q.get("партия") or [""])[0])
        try:
            _ok(ctx, item_labels_print(num) if (q.get("svg") or [""])[0] == "1" else labels_state(num))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/items/generate" and method == "POST":
        if role not in CAN_TECH:
            _fail(ctx, "Генерирует этикетки технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, generate_labels(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/labels" and method == "GET":
        ensure_sheets()
        q = ctx.get("query") or {}
        _ok(ctx, labels_data(_s((q.get("партия") or [""])[0]),
                             _s((q.get("коробка") or [""])[0])))
        return

    if path == "/api/cex/work" and method == "GET":
        ensure_sheets()
        seed_route()
        q = ctx.get("query") or {}
        _ok(ctx, work_state(me, as_worker=(q.get("режим") or [""])[0] == "моя"))
        return

    if path == "/api/cex/work/take" and method == "POST":
        if role not in CAN_WORK:
            _fail(ctx, "Взять работу может швея, упаковщик или начальник", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, take_work(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/work/done" and method == "POST":
        ensure_sheets()
        try:
            _ok(ctx, finish_work(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/work/cancel" and method == "POST":
        ensure_sheets()
        try:
            _ok(ctx, cancel_work(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/cut" and method == "GET":
        ensure_sheets()
        _ok(ctx, cut_state())
        return

    if path == "/api/cex/cut/card" and method == "POST":
        if role not in CAN_CUT:
            _fail(ctx, "Крой вводит закройщик, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, save_card(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/cut" and method == "POST":
        if role not in CAN_CUT:
            _fail(ctx, "Крой вводит закройщик, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            result = save_cut(me, ctx["body"]())
        except ValueError as exc:
            _fail(ctx, str(exc))
            return
        _ok(ctx, result)
        return

    if path == "/api/cex/routes" and method == "GET":
        ensure_sheets()
        _ok(ctx, routes_state(me))
        return

    if path in ("/api/cex/routes/save", "/api/cex/routes/delete", "/api/cex/routes/bind") \
            and method == "POST":
        if role not in CAN_TECH:
            _fail(ctx, "Менять маршрут может технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        fn = {"/api/cex/routes/save": save_route, "/api/cex/routes/delete": delete_route,
              "/api/cex/routes/bind": bind_route}[path]
        try:
            _ok(ctx, fn(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/staff/roles" and method == "POST":
        if role not in CAN_TECH:
            _fail(ctx, "Назначать роли может технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, set_roles(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/assign" and method == "GET":
        if role not in CAN_TECH:
            _fail(ctx, "Распределяет работу технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        _ok(ctx, assign_state(me))
        return

    if path == "/api/cex/cut/fix" and method == "POST":
        if role not in CAN_TECH:
            _fail(ctx, "Исправлять крой может технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, fix_cut(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/assign" and method == "POST":
        if role not in CAN_TECH:
            _fail(ctx, "Распределяет работу технолог, начальник или менеджер", 403)
            return
        ensure_sheets()
        try:
            _ok(ctx, save_assign(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/parties" and method == "GET":
        ensure_sheets()
        _ok(ctx, {"партии": parties()})
        return

    _fail(ctx, "неизвестный запрос", 404)
