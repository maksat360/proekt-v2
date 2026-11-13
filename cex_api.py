# -*- coding: utf-8 -*-
"""Модуль «Заказ»: логика поверх листов рабочей книги."""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta

import cex_store as store
import perms

MODELS = ("Справочник модели",
          ["категория", "модель", "название", "размерная сетка", "цена", "активна", "размер от", "размер до", "цвета"],
          [14, 10, 30, 16, 10, 9, 9, 9, 40])
LETTER_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL", "6XL"]


def size_range(grid: str, lo, hi, sheet: list[str] | None = None) -> list[str]:
    """Размеры модели «от–до»: числовые идут через 2 (42, 44 … 64), буквенные — по порядку XS…6XL,
    остальные сетки (постель) — по порядку из справочника размеров. Пусто — диапазон не задан или неверен."""
    lo, hi = _norm_size(lo), _norm_size(hi)
    if not lo or not hi:
        return []
    if grid == "числовая":
        a, b = _int(lo, 0), _int(hi, 0)
        return [str(x) for x in range(a, b + 1, 2)] if 0 < a <= b else []
    seq = LETTER_ORDER if grid == "буквенная" else list(sheet or [])
    up = [x.upper() for x in seq]
    if lo.upper() not in up or hi.upper() not in up:
        return []
    i, j = up.index(lo.upper()), up.index(hi.upper())
    return seq[i:j + 1] if i <= j else []
COLORS = ("Справочник цвета", ["цвет", "код тона", "активен"], [22, 16, 9])
SIZES = ("Справочник размеров", ["сетка", "размер", "порядок"], [14, 10, 9])
PARTIES = ("Партии",
           ["№ партии", "№ заказа", "дата", "клиент", "категория", "модель",
            "цвет", "размер", "план шт", "статус", "технолог", "срок", "карта"],
           [9, 9, 12, 18, 14, 10, 16, 9, 10, 14, 10, 12, 8])
# «роли» — все роли человека кроме основной (служебные и производственные), через «;».
# До переноса данных колонка называлась «этап» — _rows читает её как «роли».
STAFF = ("Сотрудники цеха",
         ["логин", "ФИО", "должность", "роли", "тип оплаты", "ставка", "периодичность",
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
# Ещё два маршрута по тем же правилам: шаблоны → привязка к модели → копия в партию.
# «заказ» — шаги между приёмкой технологом и кроем (отмечаются выполненными),
# «гп» — шаги после швейного маршрута до упаковки (работа по настилам, как швейные этапы).
ROUTE_ORD = ("Маршрут заказа", ROUTE[1], ROUTE[2])
ROUTE_ORD_MODEL = ("Маршрут заказа модели", ROUTE_MODEL[1], ROUTE_MODEL[2])
ROUTE_ORD_PARTY = ("Маршрут заказа партии", ROUTE_PARTY[1] + ["выполнено", "кто отметил", "когда"],
                   ROUTE_PARTY[2] + [11, 18, 16])
ROUTE_FIN = ("Маршрут ГП", ROUTE[1], ROUTE[2])
ROUTE_FIN_MODEL = ("Маршрут ГП модели", ROUTE_MODEL[1], ROUTE_MODEL[2])
ROUTE_FIN_PARTY = ("Маршрут ГП партии", ROUTE_PARTY[1], ROUTE_PARTY[2])
# «приёмка»: «ждёт» — технолог ещё не проверил крой, «возврат» — вернул закройщику, «принято»/пусто — принято
# (пусто — крой, сделанный до приёмки после кроя: он уже в работе). В работу идут только принятые настилы.
CUT = ("крой",
       ["№ партии", "настил", "цвет", "размер", "план шт", "факт шт",
        "закройщик", "дата", "комментарий", "карта", "приёмка", "замечание", "принял"],
       [9, 8, 16, 9, 10, 10, 14, 14, 26, 8, 10, 30, 18])
WAIT, RETURNED, ACCEPTED = "ждёт", "возврат", "принято"
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

# Поток своего заказа: конструктор (карта) → снабженец (сырьё) → технолог (приёмка) → партия.
# Заказы, созданные до этого потока, остаются «у технолога» и идут как раньше.
DESIGN = "у конструктора"
SUPPLYING = "у снабженца"
NEW = "у технолога"
# Каждая карта идёт по потоку сама: этап хранится в строках карты, заказ показывает самый ранний.
CUTQ = "ждёт кроя"      # технолог передал карту закройщику, партии ещё нет
IN_PARTY = "в партии"   # закройщик создал партию на всю карту
CARD_STAGES = (DESIGN, SUPPLYING, NEW, CUTQ, IN_PARTY)
PCARD = ("Производственная карта",
         ["№ заказа", "карта", "модель", "цвет", "размер", "заказано", "итог", "характеристики",
          "изменил", "когда", "этап"],
         [10, 8, 12, 16, 9, 10, 9, 34, 14, 16, 14])
PCARD_LOG = ("История карты",
             ["№ заказа", "карта", "дата", "кто", "модель", "цвет", "размер", "было", "стало", "комментарий"],
             [10, 8, 16, 14, 12, 16, 9, 8, 8, 34])
BOM = ("Спецификация",
       ["модель", "материал", "цвет", "норма на 1 шт", "ед.", "параметры", "категория", "по размерам"],
       [12, 26, 18, 13, 8, 30, 16, 30])
# Справочник материалов: категории (рулон, карман, нитки…) и виды внутри них.
# Строка с пустым «вид» — сама категория, пока в ней нет видов.
MATERIALS = ("Материалы",
             ["категория", "вид", "ед.", "параметры", "код", "тип", "поставщик", "цена", "мин. остаток"],
             [18, 30, 8, 34, 10, 14, 20, 10, 12])
MAT_TYPES = ("сырьё", "материал", "фурнитура", "упаковка", "полуфабрикат")
# Журнал движения номенклатуры: остаток = сумма «количество» (приход +, расход −).
MOVES = ("Движение материалов",
         ["id", "дата", "документ", "материал", "цвет", "ед.", "количество", "цена", "поставщик",
          "№ заказа", "карта", "кто", "комментарий", "вес кг"],
         [6, 16, 20, 26, 18, 8, 11, 10, 20, 10, 8, 14, 30, 9])
MOVE_DOCS = {"поступление": 1, "расход в производство": -1, "возврат поставщику": -1, "инвентаризация": 0,
             "возврат из кроя": 1}  # закройщик сдаёт снабжению остатки/обрезки отдельным видом сырья
SUPPLY_SH = ("Снабжение",
             ["№ заказа", "материал", "цвет", "ед.", "нужно", "есть", "статус", "комментарий",
              "кто", "когда", "карта"],
             [10, 26, 18, 8, 10, 10, 16, 30, 14, 16, 8])
STOCK_ROLLS = ("Поступление рулонов",
               ["код рулона", "дата", "материал", "цвет", "граммаж г", "вес кг", "№ заказа",
                "поставщик", "внёс"],
               [16, 16, 24, 18, 11, 9, 10, 20, 14])
# Поставка рулонов: штуки, общий вес и сумма → цена за кг считается автоматически.
# Рулоны не взвешиваем поштучно, поэтому себестоимость ткани — по средней цене кг (вид, цвет).
SUPPLIES = ("Поставки сырья",
            ["№", "дата", "материал", "цвет", "рулонов", "вес кг", "сумма", "цена кг",
             "поставщик", "внёс"],
            [8, 16, 24, 18, 9, 10, 12, 10, 20, 12])
# Рулоны, которые конструктор закрепил за картой заказа: вид из номенклатуры (категория «рулоны») и цвет.
# Строк — сколько угодно; снабженец по каждой строке вписывает код рулона и вес, кг.
CARD_ROLLS = ("Рулоны карты заказа", ["№ заказа", "карта", "вид", "цвет", "код рулона", "вес кг", "шт"],
              [10, 8, 24, 18, 16, 9, 6])
OWN = "свой цех"
SUPPLIER = "поставщик"
AT_SUPPLIER = "заказан у поставщика"
ORDER_LOCK = threading.Lock()


def _can(me: dict | None, code: str) -> bool:
    """Право из perms.py: роль + индивидуальные настройки сотрудника."""
    return perms.allowed(me, code)


def _can_work(me: dict | None) -> bool:
    """Швейный этап — это роль: назначенный этап сам даёт право работать,
    если начальник не забрал это право у человека лично."""
    if not me:
        return False
    own = (perms.load()["сотрудники"].get(_s(me.get("логин"))) or {})
    if "cex.work" in own:
        return bool(own["cex.work"])
    return _can(me, "cex.work") or bool(roles_of(me))


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
             STAFF, SHIFTS, RATES, SALARY, ROUTE_MODEL, ROUTE_PARTY, ASSIGN, ITEM_LABELS, CARDS, ROLLS, PATTERNS,
             ROUTE_ORD, ROUTE_ORD_MODEL, ROUTE_ORD_PARTY, ROUTE_FIN, ROUTE_FIN_MODEL, ROUTE_FIN_PARTY,
             PCARD, PCARD_LOG, BOM, SUPPLY_SH, STOCK_ROLLS, MATERIALS, MOVES, CARD_ROLLS, SUPPLIES]
    store.ensure_sheets(specs)
    for name, headers, _ in specs:
        if store.first_row(name) != headers:
            if not store.read_sheet(name):
                store.write_sheet(name, headers, [])


# ------------------------------------------------------------------ данные
def _rows(spec) -> list[dict]:
    name, headers, _ = spec
    rows = [{h: r.get(h, "") for h in headers} for r in store.read_sheet(name)]
    if spec is STAFF:  # старая колонка «этап» — те же роли, переименуется при первой записи
        raw = store.read_sheet(name)
        for row, src in zip(rows, raw):
            if not _s(row.get("роли")) and _s(src.get("этап")):
                row["роли"] = src.get("этап")
    return rows


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

    grid_of = lambda r: _s(r.get("размерная сетка")) or "числовая"
    return {
        "категории": categories,
        "модели": [{
            "категория": _s(r.get("категория")),
            "модель": _s(r.get("модель")),
            "название": _s(r.get("название")) or _s(r.get("модель")),
            "сетка": grid_of(r),
            "цена": r.get("цена", ""),
            "от": _norm_size(r.get("размер от")), "до": _norm_size(r.get("размер до")),
            "цвета": [c.strip() for c in _s(r.get("цвета")).split(",") if c.strip()],
            "размеры": size_range(grid_of(r), r.get("размер от"), r.get("размер до"),
                                  [x["размер"] for x in size_map.get(grid_of(r), [])]),
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
    cards = pcards()
    catalog = {_s(r.get("модель")): _s(r.get("категория")) for r in _rows(MODELS)} if cards else {}
    for o in out:
        o["заказано"] = o["штук"]
        saved = cards.get(o["номер"])
        stored = {c["карта"]: c["этап"] for c in saved or [] if c["этап"]}
        # после конструктора дальше идёт итоговое количество из карты, а не из заказа
        if saved and (o["статус"] != DESIGN or any(v != DESIGN for v in stored.values())):
            # артикул, добавленный конструктором, берёт категорию из справочника моделей
            cats = {**catalog, **{p["модель"]: p["категория"] for p in o["позиции"] if p["категория"]}}
            o["в_заказе"] = o["позиции"]  # заказ начальника — подсказка конструктору
            o["позиции"] = [{"категория": cats.get(c["модель"], ""), "карта": c["карта"], "модель": c["модель"],
                             "цвет": c["цвет"], "размер": c["размер"], "количество": c["итог"],
                             "заказано": c["заказано"], "характеристики": c["характеристики"]}
                            for c in saved]
            o["штук"] = sum(p["количество"] for p in o["позиции"])
            o["по_карте"] = True
        o["_этапы"] = stored
        o["_сохранены"] = [c["карта"] for c in saved or []]
    accepted = accepted_map()
    for o in out:
        o["позиций"] = len(o["позиции"])
        o["принято"] = 0
        o["остаток"] = 0
        left: dict[str, int] = {}
        for p in o["позиции"]:
            p.setdefault("карта", "1")
            key = (o["номер"], p["карта"], p["модель"], p["цвет"], p["размер"])
            done = accepted.get(key, 0)
            p["принято"] = done
            p["остаток"] = max(0, p["количество"] - done)
            o["принято"] += done
            o["остаток"] += p["остаток"]
            left[p["карта"]] = left.get(p["карта"], 0) + p["остаток"]
        stored = o.pop("_этапы")
        for c in o.pop("_сохранены"):  # пока все карты у конструктора, в позициях — заказ начальника
            left.setdefault(c, 0)
        o["карты"] = {c: stored.get(c) or _legacy_stage(o["статус"], left[c])
                      for c in sorted(left, key=_int)}
        for p in o["позиции"]:
            p["этап"] = o["карты"][p["карта"]]
    return out


def _legacy_stage(status: str, left: int) -> str:
    """Этап карты, у которой он не записан (заказы до раздельной передачи карт)."""
    if status in (DESIGN, SUPPLYING, NEW, "отклонён"):
        return NEW if status == "отклонён" else status
    return NEW if status == "принят частично" and left > 0 else IN_PARTY


def _order_status(stages) -> str:
    """Статус заказа = самый ранний этап его карт; все карты в партиях — «принят»."""
    stages = set(stages)
    return next((s for s in CARD_STAGES[:-1] if s in stages), "принят")


def _stage_writes(num: str, stages: dict[str, str], card_rows: list[dict] | None = None) -> list[tuple]:
    """Записать этапы карт заказа и пересчитать статус заказа.
    card_rows — уже готовые строки карты этого заказа; иначе берутся сохранённые
    (у старых заказов без сохранённой карты она создаётся из позиций)."""
    order = next((o for o in orders() if o["номер"] == num), None)
    if not order:
        raise ValueError("Заказ не найден")
    all_rows = _rows(PCARD)
    others = [r for r in all_rows if _norm_size(r.get("№ заказа")) != num]
    mine = card_rows if card_rows is not None else [r for r in all_rows if _norm_size(r.get("№ заказа")) == num]
    if not mine:
        mine = [{"№ заказа": num, "карта": c["карта"], "модель": c["модель"], "цвет": c["цвет"],
                 "размер": c["размер"], "заказано": c["заказано"], "итог": c["итог"],
                 "характеристики": c["характеристики"], "изменил": "", "когда": _now()}
                for c in card_of(order)]
    final = dict(order["карты"])
    for r in mine:
        c = _card_no(r.get("карта"))
        r["этап"] = stages.get(c) or _s(r.get("этап")) or final.get(c, DESIGN)
        final[c] = r["этап"]
    final = {c: v for c, v in final.items() if any(_card_no(r.get("карта")) == c for r in mine)}
    orders_rows = _rows(ORDERS)
    for r in orders_rows:
        if _norm_size(r.get("№ заказа")) == num and _s(r.get("статус")) != "отклонён":
            r["статус"] = _order_status(final.values())
    return [(PCARD[0], PCARD[1], others + mine), (ORDERS[0], ORDERS[1], orders_rows)]


def _card_no(value) -> str:
    """Номер производственной карты; старые строки без номера — карта 1."""
    return str(_int(value, 0) or 1)


def accepted_map() -> dict[tuple, int]:
    """Сколько уже принято в партии по каждой позиции заказа."""
    out: dict[tuple, int] = {}
    for r in _rows(PARTIES):
        key = (_s(r.get("№ заказа")), _card_no(r.get("карта")), _s(r.get("модель")), _s(r.get("цвет")),
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
    seam = [u for u in users if roles_of(u)  # у кого есть производственная роль
            and str(u.get("активен", 1)) not in ("0", "False", "нет")]
    busy = set()
    try:
        for r in store.read_sheet("Выдачи"):
            if _s(r.get("статус")) == "в работе":
                busy.add(_s(r.get("логин")))
    except Exception:
        pass
    return {"швей": len(seam), "занято": len(busy), "свободно": max(0, len(seam) - len(busy))}


def _only_cards(o: dict, stage: str) -> dict | None:
    """Заказ, в котором оставлены только карты на этом этапе; None — таких карт нет."""
    pos = [p for p in o["позиции"] if p["этап"] == stage]
    if not pos:
        return None
    return {**o, "позиции": pos, "позиций": len(pos), "штук": sum(p["количество"] for p in pos),
            "остаток": sum(p["остаток"] for p in pos),
            "карты_этапа": sorted({p["карта"] for p in pos}, key=_int)}


def queue() -> list[dict]:
    """Заказы с картами, которые снабженец передал технологу; в заказе — только эти карты."""
    out = []
    for o in orders():
        if o["статус"] == "отклонён" or o["источник"] == SUPPLIER:  # заказ у поставщика идёт мимо цеха
            continue
        q = _only_cards(o, NEW)
        if q:
            out.append(q)
    return out


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

    # принять: технолог передаёт карту закройщику; партию создаёт закройщик
    current = {o["номер"]: o for o in orders()}.get(num)
    if not current:
        raise ValueError("Заказ не найден")
    ready = sorted((c for c, st in current["карты"].items() if st == NEW), key=_int)
    card = _card_no(body.get("карта")) if _s(body.get("карта")) else (ready[0] if len(ready) == 1 else "")
    if not card:
        raise ValueError("Укажите, какую карту принять" if ready else "У технолога нет карт этого заказа")
    if card not in ready:
        raise ValueError(f"Карта {card} сейчас «{current['карты'].get(card, 'нет такой карты')}» — принять её нельзя")
    tech_rows.append({
        "№ заказа": num, "дата": now, "решение": f"карта {card} передана в крой",
        "причина": "", "сырьё": _s(body.get("сырьё")) or "хватает",
        "свободных швей": _free(body),
        "проверил": _s(me.get("логин")), "комментарий": _s(body.get("комментарий")),
    })
    writes = _stage_writes(num, {card: CUTQ})
    store.write_sheets(writes + [(TECH[0], TECH[1], tech_rows)])
    status = next(r["статус"] for r in writes[1][2] if _norm_size(r.get("№ заказа")) == num)
    return {"статус": status, "карта": card}


def cut_queue() -> list[dict]:
    """Карты, которые технолог передал в крой: закройщик создаёт из них партии."""
    out, rolls = [], card_rolls()
    for o in orders():
        if o["статус"] == "отклонён":
            continue
        q = _only_cards(o, CUTQ)
        if not q:
            continue
        for c in q["карты_этапа"]:
            pos = [p for p in q["позиции"] if p["карта"] == c]
            out.append({"заказ": o["номер"], "карта": c, "клиент": o["клиент"], "срок": o["срок"],
                        "позиции": pos, "остаток": sum(p["остаток"] for p in pos),
                        "рулоны": rolls.get((o["номер"], c), [])})
    return out


def cut_review() -> list[dict]:
    """Карты кроя на приёмке («ждёт») и возвращённые закройщику («возврат»)."""
    parties = {_s(r.get("№ партии")): r for r in _rows(PARTIES)}
    out: dict[tuple, dict] = {}
    for r in _rows(CUT):
        st = _s(r.get("приёмка"))
        if st not in (WAIT, RETURNED):
            continue
        num, card = _norm_size(r.get("№ партии")), _norm_size(r.get("карта"))
        p = parties.get(num, {})
        g = out.setdefault((num, card), {
            "партия": num, "карта": card, "заказ": _norm_size(p.get("№ заказа")), "категория": _s(p.get("категория")),
            "модель": _s(p.get("модель")), "закройщик": _s(r.get("закройщик")), "дата": _s(r.get("дата")),
            "статус": st, "замечание": _s(r.get("замечание")), "строки": [], "штук": 0})
        g["строки"].append({"настил": _s(r.get("настил")), "цвет": _s(r.get("цвет")),
                            "размер": _norm_size(r.get("размер")), "факт": _int(r.get("факт шт"))})
        g["штук"] += _int(r.get("факт шт"))
    return sorted(out.values(), key=lambda g: (_int(g["партия"]), _int(g["карта"])))


def _review_rows(rows: list[dict], num: str, card: str, status: str) -> dict[tuple, dict]:
    hit = {(_s(r.get("настил")), _s(r.get("цвет")), _norm_size(r.get("размер"))): r for r in rows
           if _norm_size(r.get("№ партии")) == num and _norm_size(r.get("карта")) == card
           and _s(r.get("приёмка")) == status}
    if not hit:
        raise ValueError(f"Карта кроя {card} партии №{num} не {'на приёмке' if status == WAIT else 'возвращена'}")
    return hit


def review_cut(me: dict, body: dict) -> dict:
    """Технолог после кроя: «принять» (принятое количество, несоответствия) или «вернуть» закройщику."""
    num, card = _norm_size(body.get("партия")), _norm_size(body.get("карта"))
    decision = _s(body.get("решение"))
    note = _s(body.get("замечание"))
    rows = _rows(CUT)
    hit = _review_rows(rows, num, card, WAIT)
    who = _s(me.get("фио")) or _s(me.get("логин"))
    now = _now()
    if decision == "вернуть":
        if not note:
            raise ValueError("Напишите, что исправить закройщику")
        for r in hit.values():
            r.update({"приёмка": RETURNED, "замечание": note, "принял": f"{who} {now}"})
        store.write_sheets([(CUT[0], CUT[1], rows)])
        perms.log_event(me, "крой возвращён", f"партия {num}, карта кроя {card}", "", note)
        return {"партия": num, "карта": card, "статус": RETURNED}
    if decision != "принять":
        raise ValueError("Решение: принять или вернуть")
    given = {(_s(i.get("настил")), _s(i.get("цвет")), _norm_size(i.get("размер"))): _int(i.get("принято"), -1)
             for i in body.get("строки") or []}
    diffs = []
    for k, r in hit.items():
        got = given.get(k, _int(r.get("факт шт")))
        if got < 0:
            raise ValueError(f"{k[1]} / {k[2]}: принятое количество не может быть отрицательным")
        was = _int(r.get("факт шт"))
        if got != was:  # в работу идёт принятое: факт становится принятым, раскроенное — в комментарии
            diffs.append(f"{k[1]} {k[2]}: крой {was}, принято {got}")
            r["комментарий"] = (_s(r.get("комментарий")) + "; " if _s(r.get("комментарий")) else "") + \
                f"приёмка {now}: крой {was}, принято {got}"
            r["факт шт"] = got
        r.update({"приёмка": ACCEPTED, "замечание": note, "принял": f"{who} {now}"})
    store.write_sheets([(CUT[0], CUT[1], rows)])
    perms.log_event(me, "крой принят", f"партия {num}, карта кроя {card}", "; ".join(diffs), note or "без замечаний")
    return {"партия": num, "карта": card, "статус": ACCEPTED, "расхождений": len(diffs)}


def resubmit_cut(me: dict, body: dict) -> dict:
    """Закройщик исправил возвращённую карту кроя и снова сдаёт её на приёмку."""
    num, card = _norm_size(body.get("партия")), _norm_size(body.get("карта"))
    rows = _rows(CUT)
    hit = _review_rows(rows, num, card, RETURNED)
    for i in body.get("строки") or []:
        r = hit.get((_s(i.get("настил")), _s(i.get("цвет")), _norm_size(i.get("размер"))))
        val = _int(i.get("факт"), -1)
        if r is None or val < 0:
            raise ValueError("Проверьте строки карты кроя")
        r["факт шт"] = val
    for r in hit.values():
        r["приёмка"] = WAIT
    store.write_sheets([(CUT[0], CUT[1], rows)])
    perms.log_event(me, "крой исправлен", f"партия {num}, карта кроя {card}", "", "снова на приёмке")
    return {"партия": num, "карта": card, "статус": WAIT}


def model_stock(model: str) -> dict[str, float]:
    """Фактический остаток готовой продукции по модели: «цвет|размер» → штук (склад, лист «главный»).
    Только чтение: заказ на пошив склад не меняет и не резервирует."""
    import warehouse  # noqa: WPS433
    want = _s(model).lower()
    out: dict[str, float] = {}
    for it in warehouse.stock_items():
        if _s(it.get("модель")).lower() == want:
            k = f"{_s(it.get('цвет'))}|{_norm_size(it.get('размер'))}"
            out[k] = out.get(k, 0) + float(it.get("остаток") or 0)
    return out


def create_party(me: dict, body: dict) -> dict:
    """Закройщик создаёт партию из карты «ждёт кроя»: всю карту, часть или больше карты."""
    num = _s(body.get("заказ"))
    card = _card_no(body.get("карта"))
    current = {o["номер"]: o for o in orders()}.get(num)
    if not current:
        raise ValueError("Заказ не найден")
    if current["карты"].get(card) != CUTQ:
        raise ValueError(f"Карта {card} заказа №{num} не ждёт кроя")
    remaining = {(p["модель"], p["цвет"], p["размер"]): p["остаток"]
                 for p in current["позиции"] if p["карта"] == card}
    wanted = body.get("позиции")
    if not wanted:  # без списка — вся карта
        wanted = [{"модель": k[0], "цвет": k[1], "размер": k[2], "количество": v} for k, v in remaining.items()]
    accepted: dict[tuple, int] = {}
    for it in wanted:
        qty = _int(it.get("количество"), 0)
        if qty <= 0:
            continue
        key = (_s(it.get("модель")), _s(it.get("цвет")), _norm_size(it.get("размер")))
        name = " / ".join(key)
        if key not in remaining:  # цвета и размеры — от конструктора, количество — любое
            raise ValueError(f"Позиции {name} нет в карте {card}")
        accepted[key] = accepted.get(key, 0) + qty
    if not accepted:  # количество примерное: без чисел — партия на все размеры карты, факт впишет закройщик
        accepted = dict(remaining)
    total = sum(accepted.values())
    if not accepted:
        raise ValueError(f"В карте {card} нет размеров")

    party_num = next_party_number()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    bypos = {(p["модель"], p["цвет"], p["размер"]): p for p in current["позиции"] if p["карта"] == card}
    newparty = [{"№ партии": party_num, "№ заказа": num, "дата": now,
                 "клиент": current["клиент"], "категория": bypos[k]["категория"],
                 "модель": k[0], "цвет": k[1], "размер": k[2],
                 "план шт": qty, "статус": "крой", "технолог": _s(me.get("логин")),
                 "срок": current["срок"], "карта": card}
                for k, qty in accepted.items()]
    full = all(accepted.get(k, 0) >= v for k, v in remaining.items())
    writes = _stage_writes(num, {card: IN_PARTY} if full else {})
    for r in writes[1][2]:
        if _norm_size(r.get("№ заказа")) == num and (_s(r.get("модель")), _s(r.get("цвет")),
                                                     _norm_size(r.get("размер"))) in accepted:
            _add_party_ref(r, party_num)
    seed_route()
    # все три маршрута копируются в партию: потом правка шаблонов её не меняет
    snaps = [(KINDS[k]["party"][0], KINDS[k]["party"][1],
              _rows(KINDS[k]["party"]) + snapshot_rows(party_num, newparty[0]["модель"], k))
             for k in ("шв", "гп", "заказ")]
    store.write_sheets(writes + [(PARTIES[0], PARTIES[1], _rows(PARTIES) + newparty)] + snaps)
    return {"партия": party_num, "штук": total, "карта": card, "вся_карта": full}


# ------------------------------------------- конструктор → снабженец → технолог
def _now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def _key(model, color, size) -> tuple:
    return (_s(model), _s(color), _norm_size(size))


def pcards() -> dict[str, list[dict]]:
    """№ заказа → строки производственной карты (сохранённые конструктором)."""
    out: dict[str, list[dict]] = {}
    for r in _rows(PCARD):
        num = _norm_size(r.get("№ заказа"))
        if num and _s(r.get("модель")):
            out.setdefault(num, []).append({
                "карта": _card_no(r.get("карта")),
                "модель": _s(r.get("модель")), "цвет": _s(r.get("цвет")),
                "размер": _norm_size(r.get("размер")), "заказано": _int(r.get("заказано")),
                "итог": _int(r.get("итог")), "характеристики": _s(r.get("характеристики")),
                "этап": _s(r.get("этап"))})
    return out


def card_of(order: dict, cards: dict | None = None) -> list[dict]:
    """Карта заказа: сохранённая или черновик из позиций заказа (итог = заказано)."""
    saved = (cards if cards is not None else pcards()).get(order["номер"])
    if saved:
        return saved
    return [{"карта": "1", "модель": p["модель"], "цвет": p["цвет"], "размер": p["размер"],
             "заказано": p.get("заказано", p["количество"]), "итог": p["количество"],
             "характеристики": p.get("характеристики", ""), "этап": p.get("этап", "")}
            for p in order["позиции"]]


def card_rolls() -> dict[tuple[str, str], list[dict]]:
    """(№ заказа, карта) → [{вид, цвет}] — рулоны, закреплённые конструктором."""
    out: dict[tuple[str, str], list[dict]] = {}
    for r in _rows(CARD_ROLLS):
        num, card = _norm_size(r.get("№ заказа")), _card_no(r.get("карта"))
        if num and _s(r.get("вид")):
            out.setdefault((num, card), []).append({"вид": _s(r.get("вид")), "цвет": _s(r.get("цвет")),
                                                    "код": _s(r.get("код рулона")), "вес": _num(r.get("вес кг")),
                                                    "шт": max(1, _int(r.get("шт"), 1))})  # старые строки — 1 рулон
    return out


def roll_kinds() -> list[str]:
    return [m["вид"] for m in materials() if "рулон" in m["категория"].lower() and m["вид"]]


def is_vdm(kind: str) -> bool:
    """ВДМ принимают с кодом каждого рулона; остальные рулоны — штуками, без кодов."""
    k = _s(kind).lower()
    return "вдм" in k or any("вдм" in m["категория"].lower() for m in materials() if m["вид"].lower() == k)


def rolls_in_stock(mv: list[dict] | None = None) -> list[dict]:
    """Рулоны на складе сырья по виду и цвету: обычные — штуки по журналу движения, ВДМ — коды в реестре."""
    kinds = {k.lower(): k for k in roll_kinds()}
    pcs: dict = {}
    for m in (moves() if mv is None else mv):  # только строки в штуках: старые приходы рулонов в кг — не штуки
        k = _mkey(m["материал"], m["цвет"])
        if k[0] in kinds and m["ед"] == "шт" and not is_vdm(kinds[k[0]]):
            pcs[k] = pcs.get(k, 0) + m["количество"]
    out = {}
    for (mat, color), qty in pcs.items():
        if qty > 0:
            out[(kinds[mat], color)] = {"вид": kinds[mat], "цвет": color, "шт": qty}
    for r in roll_registry().values():
        k = (r["материал"], r["цвет"].lower())
        out.setdefault(k, {"вид": r["материал"], "цвет": r["цвет"].lower(), "шт": 0, "вдм": True})["шт"] += 1
    return sorted(out.values(), key=lambda x: (x["вид"], x["цвет"]))


def card_history(nums) -> dict[str, list[dict]]:
    want = {str(n) for n in nums}
    out: dict[str, list[dict]] = {}
    for r in _rows(PCARD_LOG):
        num = _norm_size(r.get("№ заказа"))
        if num in want:
            out.setdefault(num, []).append({k: _norm_size(v) if k == "размер" else _s(v)
                                            for k, v in r.items()})
    return out


def save_design(me: dict, body: dict) -> dict:
    """Конструктор сохраняет карты. Итог может быть любым (больше, меньше, 0) — без запретов.
    «передать»: номера карт, которые уходят снабженцу; «готово» — передать все свои карты.
    Уже переданные карты не меняются: конструктор правит только карты на своём этапе."""
    num = _s(body.get("номер"))
    order = next((o for o in orders() if o["номер"] == num), None)
    if not order:
        raise ValueError("Заказ не найден")
    if DESIGN not in order["карты"].values():
        raise ValueError(f"Заказ сейчас «{order['статус']}» — у конструктора карт нет")
    ordered: dict[tuple, int] = {}
    for r in _rows(ORDERS):
        if _norm_size(r.get("№ заказа")) == num:
            k = _key(r.get("модель"), r.get("цвет"), r.get("размер"))
            ordered[k] = ordered.get(k, 0) + _int(r.get("количество"))
    prev_all = {(c["карта"],) + _key(c["модель"], c["цвет"], c["размер"]): c for c in card_of(order)}
    locked = {c for c, st in order["карты"].items() if st != DESIGN}
    new: dict[tuple, dict] = {}  # (карта, модель, цвет, размер) → строка
    for it in body.get("позиции") or []:
        k = (_card_no(it.get("карта")),) + _key(it.get("модель"), it.get("цвет"), it.get("размер"))
        if k[0] in locked:
            raise ValueError(f"Карта {k[0]} уже «{order['карты'][k[0]]}» — менять её нельзя")
        if not k[1] or not k[2]:
            raise ValueError(f"Карта {k[0]}: в строке не хватает модели или цвета")
        if k in new:
            raise ValueError(f"Карта {k[0]}: строка {k[1]} / {k[2]} / {k[3]} повторяется")
        qty = _int(it.get("итог"), -1)
        if qty < 0:
            raise ValueError(f"{k[1]} / {k[2]} / {k[3]}: количество не может быть отрицательным")
        new[k] = {"итог": qty, "характеристики": _s(it.get("характеристики"))}
    if not new and not locked:
        raise ValueError("В карте нет ни одной строки")
    mine = sorted({k[0] for k in new}, key=_int)
    send = mine if body.get("готово") else [_card_no(c) for c in body.get("передать") or []]
    for c in send:
        if c not in mine:
            raise ValueError(f"Карты {c} нет среди карт конструктора")
        if not any(k[0] == c for k in new):
            raise ValueError(f"В карте {c} не включено ни одного размера")

    prev = {k: v for k, v in prev_all.items() if k[0] not in locked}
    who, now, note = _s(me.get("логин")), _now(), _s(body.get("комментарий"))
    log = _rows(PCARD_LOG)
    for k in list(prev) + [k for k in new if k not in prev]:
        was, cur = prev.get(k), new.get(k)
        was_q = was["итог"] if was else 0
        cur_q = cur["итог"] if cur else 0
        chars_changed = (was or {}).get("характеристики", "") != (cur or {}).get("характеристики", "")
        if was_q != cur_q or chars_changed or not cur:
            what = "строка удалена" if not cur else ("новая строка" if not was else "")
            if chars_changed and cur:
                what = (what + "; " if what else "") + "характеристики: " + (cur["характеристики"] or "—")
            log.append({"№ заказа": num, "карта": k[0], "дата": now, "кто": who, "модель": k[1],
                        "цвет": k[2], "размер": k[3], "было": was_q, "стало": cur_q,
                        "комментарий": "; ".join(x for x in (what, note) if x)})
    for c in send:
        log.append({"№ заказа": num, "карта": c, "дата": now, "кто": who, "модель": "", "цвет": "",
                    "размер": "", "было": "", "стало": sum(v["итог"] for k, v in new.items() if k[0] == c),
                    "комментарий": f"карта {c} утверждена и передана снабженцу"})

    rows = [{"№ заказа": num, "карта": k[0], "модель": k[1], "цвет": k[2], "размер": k[3],
             "итог": v["итог"], "характеристики": v["характеристики"], "изменил": v.get("изменил", ""),
             "когда": v.get("когда", ""), "этап": order["карты"][k[0]]}
            for k, v in prev_all.items() if k[0] in locked]
    rows += [{"№ заказа": num, "карта": k[0], "модель": k[1], "цвет": k[2], "размер": k[3],
              "итог": v["итог"], "характеристики": v["характеристики"], "изменил": who, "когда": now,
              "этап": SUPPLYING if k[0] in send else DESIGN}
             for k, v in new.items()]
    rows.sort(key=lambda r: _int(r["карта"]))
    left = dict(ordered)  # «заказано» — в первую строку позиции, чтобы суммы по картам не двоились
    for r in rows:
        r["заказано"] = left.pop(_key(r["модель"], r["цвет"], r["размер"]), 0)
    writes = _stage_writes(num, {}, rows) + [(PCARD_LOG[0], PCARD_LOG[1], log)]
    if "рулоны" in body:
        kept = [r for r in _rows(CARD_ROLLS)
                if _norm_size(r.get("№ заказа")) != num or _card_no(r.get("карта")) in locked]
        for r in body.get("рулоны") or []:
            card, kind = _card_no(r.get("карта")), _s(r.get("вид"))
            if not kind:
                continue
            if card in locked or card not in mine:
                raise ValueError(f"Рулоны можно закрепить только за своей картой (карта {card})")
            kept.append({"№ заказа": num, "карта": card, "вид": kind, "цвет": _s(r.get("цвет")),
                         "шт": max(1, _int(r.get("шт"), 1))})
        writes.append((CARD_ROLLS[0], CARD_ROLLS[1], kept))
    store.write_sheets(writes)
    status = next((r["статус"] for r in writes[1][2] if _norm_size(r.get("№ заказа")) == num), "")
    return {"номер": num, "статус": status, "передано": send,
            "штук": sum(v["итог"] for v in new.values())}


def boms() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in _rows(BOM):
        if _s(r.get("модель")) and _s(r.get("материал")):
            out.setdefault(_s(r.get("модель")), []).append({
                "категория": _s(r.get("категория")),
                "материал": _s(r.get("материал")), "цвет": _s(r.get("цвет")),
                "норма": _num(r.get("норма на 1 шт")), "ед": _s(r.get("ед.")),
                "параметры": _s(r.get("параметры")),
                "по_размерам": _parse_sizes(r.get("по размерам"))})
    return out


def _parse_sizes(text) -> dict[str, float]:
    """«42:1,1; 44:1,2» → {"42": 1.1, "44": 1.2} — норма расхода по размерам."""
    out = {}
    for part in _s(text).split(";"):
        size, _, val = part.partition(":")
        if _norm_size(size) and _num(val) > 0:
            out[_norm_size(size)] = _num(val)
    return out


def materials() -> list[dict]:
    return [{"категория": _s(r.get("категория")), "вид": _s(r.get("вид")),
             "ед": _s(r.get("ед.")), "параметры": _s(r.get("параметры")),
             "код": _s(r.get("код")), "тип": _s(r.get("тип")), "поставщик": _s(r.get("поставщик")),
             "цена": _num(r.get("цена")), "мин": _num(r.get("мин. остаток"))}
            for r in _rows(MATERIALS) if _s(r.get("категория"))]


def _next_code(rows: list[dict]) -> str:
    """Код позиции как в 1С: М-00001, следующий после самого большого."""
    nums = [int(c[2:]) for c in (_s(r.get("код")) for r in rows) if c[:2] == "М-" and c[2:].isdigit()]
    return f"М-{max(nums, default=0) + 1:05d}"


def save_material(me: dict, body: dict) -> dict:
    """Добавить/изменить категорию или вид материала; «удалить» — убрать вид (или пустую категорию)."""
    cat, kind = _s(body.get("категория")), _s(body.get("вид"))
    if not cat:
        raise ValueError("Укажите категорию")
    rows = _rows(MATERIALS)
    same = lambda r: _s(r.get("категория")).lower() == cat.lower() and _s(r.get("вид")).lower() == kind.lower()
    if body.get("удалить"):
        if not kind and any(_s(r.get("категория")).lower() == cat.lower() and _s(r.get("вид")) for r in rows):
            raise ValueError(f"В категории «{cat}» есть виды — сначала удалите их")
        used = [m for m, lines in boms().items() for b in lines if kind and b["материал"].lower() == kind.lower()]
        if used:
            raise ValueError(f"«{kind}» есть в спецификации: {', '.join(sorted(set(used)))}")
        if kind and any(_s(r.get("материал")).lower() == kind.lower() for r in _rows(MOVES)):
            raise ValueError(f"По «{kind}» есть движения — удалить нельзя, остатки и история пропадут")
        rows = [r for r in rows if not same(r)]
    else:
        typ = _s(body.get("тип"))
        if typ and typ not in MAT_TYPES:
            raise ValueError(f"Неизвестный тип «{typ}»")
        if kind and any(_s(r.get("вид")).lower() == kind.lower() and _s(r.get("категория")).lower() != cat.lower()
                        for r in rows):
            raise ValueError(f"«{kind}» уже есть в другой группе — названия позиций не должны повторяться")
        old = next((r for r in rows if same(r)), {})
        row = {"категория": cat, "вид": kind, "ед.": _s(body.get("ед")) or "м", "параметры": _s(body.get("параметры")),
               "код": _s(body.get("код")) or _s(old.get("код")) or (_next_code(rows) if kind else ""),
               "тип": typ, "поставщик": _s(body.get("поставщик")),
               "цена": _num(body.get("цена")) or "", "мин. остаток": _num(body.get("мин")) or ""}
        rows = [r for r in rows if not same(r)] + [row]
        for r in rows:  # позициям, заведённым до кодов, — код при первой записи справочника
            if _s(r.get("вид")) and not _s(r.get("код")):
                r["код"] = _next_code(rows)
        if kind:  # заглушка категории больше не нужна, когда в ней появился вид
            rows = [r for r in rows if not (_s(r.get("категория")).lower() == cat.lower() and not _s(r.get("вид")))]
    rows.sort(key=lambda r: (_s(r.get("категория")).lower(), _s(r.get("вид")).lower()))
    store.write_sheet(MATERIALS[0], MATERIALS[1], rows)
    return {"категория": cat, "вид": kind}


def save_product(me: dict, body: dict) -> dict:
    """Готовая продукция: модель, название, категория и размеры «от–до» (числовые или буквенные)."""
    model, cat = _s(body.get("модель")), _s(body.get("категория"))
    if not model:
        raise ValueError("Укажите модель (артикул)")
    if not cat:
        raise ValueError("Укажите категорию товара")
    grid = _s(body.get("сетка")) or "числовая"
    lo, hi = _norm_size(body.get("от")), _norm_size(body.get("до"))
    if not lo or not hi:
        raise ValueError("Укажите размеры: от какого и до какого")
    sheet = next((b["размеры"] for b in refs()["размеры"] if b["сетка"] == grid), [])
    sizes = size_range(grid, lo, hi, [x["размер"] for x in sheet])
    if not sizes:
        raise ValueError(f"Размеры {lo}–{hi} не подходят: «от» должен быть не больше «до»"
                         + (", числовые — числами" if grid == "числовая" else ""))
    rows = _rows(MODELS)
    old = next((r for r in rows if _s(r.get("модель")).lower() == model.lower()), None)
    if old and not body.get("изменить"):
        raise ValueError(f"Модель «{model}» уже есть — откройте её в списке, чтобы изменить")
    row = {**(old or {"цена": "", "активна": 1}), "категория": cat, "модель": _s(old.get("модель")) if old else model,
           "название": _s(body.get("название")) or model, "размерная сетка": grid, "размер от": lo, "размер до": hi}
    colors = []
    for c in body.get("цвета") or []:  # «/» ломает наименование «Категория/модель/цвет/размер»
        c = _s(c).replace("/", "-")
        if c and c.lower() not in [x.lower() for x in colors]:
            colors.append(c)
    row["цвета"] = ", ".join(colors)
    rows = [r for r in rows if r is not old] + [row]
    store.write_sheet(MODELS[0], MODELS[1], rows)
    added = 0
    if colors:  # позиции склада: без них модель не видна в «Приходе»
        import warehouse
        added = warehouse.add_products(cat, row["модель"], colors, sizes)
    return {"модель": row["модель"], "позиций": added, "refs": refs()}


def save_bom(me: dict, body: dict) -> dict:
    """Спецификация одного артикула целиком (пустой список — удалить)."""
    model = _s(body.get("модель"))
    if not model:
        raise ValueError("Укажите модель (артикул)")
    lines = []
    for i, it in enumerate(body.get("строки") or [], start=1):
        mat = _s(it.get("материал"))
        if not mat:
            continue
        norm = _num(it.get("норма"))
        sizes = it.get("по_размерам") or {}
        sizes = _parse_sizes(sizes if isinstance(sizes, str) else "; ".join(f"{k}:{v}" for k, v in sizes.items()))
        if norm <= 0 and not sizes:
            raise ValueError(f"Строка {i} ({mat}): укажите норму расхода — общую или по размерам")
        unit = next((m["ед"] for m in materials() if m["вид"] == mat and m["ед"]), "")  # ед. — из номенклатуры
        lines.append({"модель": model, "материал": mat, "цвет": _s(it.get("цвет")),
                      "норма на 1 шт": norm or "", "ед.": unit or _s(it.get("ед")) or "шт",
                      "параметры": _s(it.get("параметры")), "категория": _s(it.get("категория")),
                      "по размерам": "; ".join(f"{k}:{v:g}" for k, v in sizes.items())})
    rows = [r for r in _rows(BOM) if _s(r.get("модель")) != model] + lines
    store.write_sheet(BOM[0], BOM[1], rows)
    return {"модель": model, "строк": len(lines)}


def _part_color(bom_color: str, item_color: str) -> str:
    """«» = 1-й цвет изделия, «цвет 2» = 2-й: «зелёный, бежевый» → бежевый. Иначе — цвет как записан."""
    m = re.fullmatch(r"цвет (\d)", bom_color)
    if bom_color and not m:
        return bom_color
    parts = [x.strip() for x in re.split(r"[,/;]+", item_color or "") if x.strip()] or [item_color]
    return parts[min(int(m.group(1)) if m else 1, len(parts)) - 1]


def supply_need(card: list[dict], bom: dict) -> tuple[list[dict], list[str]]:
    """Сколько сырья нужно на карту: норма × итог. Пустой цвет в спецификации = в цвет изделия."""
    need: dict[tuple, float] = {}
    missing: list[str] = []
    rolls = {k.lower() for k in roll_kinds()}  # рулоны не по норме — их закрепляет конструктор
    for c in card:
        lines = bom.get(c["модель"])
        if not lines:
            if c["модель"] not in missing:
                missing.append(c["модель"])
            continue
        for b in lines:
            if b["материал"].lower() in rolls:
                continue
            k = (b["материал"], _part_color(b["цвет"], c["цвет"]), b["ед"])
            norm = b.get("по_размерам", {}).get(_norm_size(c["размер"]), b["норма"])  # своя норма размера, иначе общая
            need[k] = need.get(k, 0) + norm * c["итог"]
    return ([{"материал": k[0], "цвет": k[1], "ед": k[2], "нужно": round(v, 3)}
             for k, v in need.items()], missing)


def _supply_rows(num: str, card: str) -> list[dict]:
    return [r for r in _rows(SUPPLY_SH)
            if _norm_size(r.get("№ заказа")) == num and _card_no(r.get("карта")) == card]


def _card_rows(order: dict, card: str, cards: dict | None = None) -> list[dict]:
    return [c for c in card_of(order, cards) if c["карта"] == card]


def supply_lines(order: dict, card: str, bom: dict, cards: dict,
                 mv: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    need, missing = supply_need(_card_rows(order, card, cards), bom)
    mv = moves() if mv is None else mv
    bal = stock(mv)
    spent: dict[tuple, float] = {}  # уже списано в производство по этой карте
    for m in mv:
        if m["документ"] == "расход в производство" and m["заказ"] == order["номер"] and m["карта"] == card:
            k = _mkey(m["материал"], m["цвет"])
            spent[k] = spent.get(k, 0) - m["количество"]
    saved = {(_s(r.get("материал")), _s(r.get("цвет")), _s(r.get("ед."))): r
             for r in _supply_rows(order["номер"], card)}
    for n in need:
        r = saved.pop((n["материал"], n["цвет"], n["ед"]), {})
        n["комментарий"] = _s(r.get("комментарий"))
    for (mat, color, unit), r in saved.items():  # добавленное снабженцем вручную
        need.append({"материал": mat, "цвет": color, "ед": unit, "нужно": _num(r.get("нужно")),
                     "комментарий": _s(r.get("комментарий"))})
    for n in need:
        k = _mkey(n["материал"], n["цвет"])
        n["на_складе"], n["списано"] = bal.get(k, 0), round(spent.get(k, 0), 3)
        n["есть"] = n["нужно"] - n["списано"] <= n["на_складе"] + 1e-9
    return need, missing


def moves() -> list[dict]:
    return [{"id": _int(r.get("id")), "дата": _s(r.get("дата")), "документ": _s(r.get("документ")), "материал": _s(r.get("материал")),
             "цвет": _s(r.get("цвет")), "ед": _s(r.get("ед.")), "количество": _num(r.get("количество")),
             "цена": _num(r.get("цена")), "поставщик": _s(r.get("поставщик")),
             "заказ": _norm_size(r.get("№ заказа")), "карта": _card_no(r.get("карта")) if _s(r.get("карта")) else "",
             "кто": _s(r.get("кто")), "комментарий": _s(r.get("комментарий")), "вес": _num(r.get("вес кг"))}
            for r in _rows(MOVES) if _s(r.get("материал"))]


def _mkey(mat: str, color: str) -> tuple[str, str]:
    return (_s(mat).lower(), _s(color).lower())


def stock(mv: list[dict] | None = None) -> dict[tuple[str, str], float]:
    """Остаток по (материал, цвет) — сумма движений."""
    out: dict[tuple[str, str], float] = {}
    for m in moves() if mv is None else mv:
        k = _mkey(m["материал"], m["цвет"])
        out[k] = round(out.get(k, 0) + m["количество"], 3)
    return out


def add_move(me: dict, body: dict) -> dict:
    """Документ движения: поступление, расход в производство, возврат поставщику, инвентаризация.
    В инвентаризации «количество» — фактический остаток; в журнал пишется разница."""
    doc = _s(body.get("документ"))
    if doc not in MOVE_DOCS:
        raise ValueError(f"Неизвестный документ «{doc}»")
    known = {m["вид"].lower(): m for m in materials() if m["вид"]}
    # обычные рулоны (не ВДМ) на складе сырья — только штуками, иначе штуки и кг складываются в один остаток
    pcs_rolls = {k.lower() for k in roll_kinds() if not is_vdm(k)}
    bal = stock()
    sign = MOVE_DOCS[doc]
    who, now = _s(me.get("логин")), _now()
    next_id = max((_int(r.get("id")) for r in _rows(MOVES)), default=0)
    out, short = [], []
    for i, it in enumerate(body.get("строки") or [], start=1):
        mat = _s(it.get("материал"))
        if not mat:
            continue
        ref = known.get(mat.lower())
        if not ref:
            raise ValueError(f"Строка {i}: «{mat}» нет в номенклатуре — сначала заведите позицию")
        color, qty = _s(it.get("цвет")), _num(it.get("количество"))
        roll = ref["вид"].lower() in pcs_rolls
        if roll and qty != int(qty):
            raise ValueError(f"Строка {i} ({mat}): рулоны считаются штуками — укажите целое число. "
                             "Остаток рулона сдайте отдельным видом сырья (например «Остатки рулона»)")
        k = _mkey(ref["вид"], color)
        have = bal.get(k, 0)
        if sign == 0:
            if qty < 0:
                raise ValueError(f"Строка {i} ({mat}): фактический остаток не может быть меньше нуля")
            delta = round(qty - have, 3)
            if not delta:
                continue
        else:
            if qty <= 0:
                raise ValueError(f"Строка {i} ({mat}): укажите количество больше нуля")
            delta = sign * qty
            if delta < 0 and have + delta < -1e-9:
                short.append(f"{ref['вид']} {color}".strip() + f": есть {have:g}, нужно {qty:g}")
        bal[k] = round(have + delta, 3)
        next_id += 1
        out.append({"id": next_id, "дата": now, "документ": doc, "материал": ref["вид"], "цвет": color,
                    "ед.": "шт" if roll else (_s(it.get("ед")) or ref["ед"]), "вес кг": _num(it.get("вес")) or "",  # рулоны — штуками, вес по желанию
                    "количество": delta, "цена": _num(it.get("цена")) or "",
                    "поставщик": _s(body.get("поставщик")), "№ заказа": _s(body.get("заказ")),
                    "карта": _s(body.get("карта")), "кто": who, "комментарий": _s(body.get("комментарий"))})
    if short:
        raise ValueError("Не хватает на складе — " + "; ".join(short)
                         + ". Сначала проведите поступление или инвентаризацию")
    if not out:
        raise ValueError("Нет строк для проведения")
    store.append_rows(MOVES[0], MOVES[1], out)
    return {"документ": doc, "строк": len(out)}


def delete_move(me: dict, body: dict) -> dict:
    """Отменить строку журнала (как отмена проведения в 1С). Остаток не должен уйти в минус."""
    mid = _int(body.get("id"))
    rows = _rows(MOVES)
    gone = next((r for r in rows if _int(r.get("id")) == mid), None)
    if not mid or not gone:
        raise ValueError("Строка журнала не найдена")
    rows = [r for r in rows if r is not gone]
    k = _mkey(gone.get("материал"), gone.get("цвет"))
    left = sum(_num(r.get("количество")) for r in rows if _mkey(r.get("материал"), r.get("цвет")) == k)
    if left < -1e-9:
        raise ValueError(f"Нельзя: остаток «{_s(gone.get('материал'))} {_s(gone.get('цвет'))}» станет {left:g}"
                         " — сначала отмените расход")
    store.write_sheet(MOVES[0], MOVES[1], rows)
    return {"id": mid}


def rename_material(me: dict, body: dict) -> dict:
    """Переименовать группу или позицию (и перенести позицию в другую группу).
    Новое название позиции подставляется везде: спецификации, движения, снабжение заказов, рулоны."""
    old_cat, old_kind = _s(body.get("категория_было")), _s(body.get("вид_было"))
    cat, kind = _s(body.get("категория")) or old_cat, _s(body.get("вид")) or old_kind
    low = str.lower
    rows = _rows(MATERIALS)
    if not any(low(_s(r.get("категория"))) == low(old_cat) for r in rows):
        raise ValueError(f"Группа «{old_cat}» не найдена")
    bom = _rows(BOM)
    if not old_kind:  # переименование группы
        if low(cat) != low(old_cat) and any(low(_s(r.get("категория"))) == low(cat) for r in rows):
            raise ValueError(f"Группа «{cat}» уже есть")
        for r in rows + bom:
            if low(_s(r.get("категория"))) == low(old_cat):
                r["категория"] = cat
        store.write_sheets([(MATERIALS[0], MATERIALS[1], rows), (BOM[0], BOM[1], bom)])
        return {"категория": cat}
    row = next((r for r in rows if low(_s(r.get("категория"))) == low(old_cat) and low(_s(r.get("вид"))) == low(old_kind)), None)
    if not row:
        raise ValueError(f"Позиция «{old_kind}» не найдена")
    if low(kind) != low(old_kind) and any(low(_s(r.get("вид"))) == low(kind) for r in rows):
        raise ValueError(f"Позиция «{kind}» уже есть")
    if not any(low(_s(r.get("категория"))) == low(cat) for r in rows):
        raise ValueError(f"Группа «{cat}» не найдена — сначала создайте её")
    cat = next(_s(r.get("категория")) for r in rows if low(_s(r.get("категория"))) == low(cat))  # написание группы
    row["категория"], row["вид"] = cat, kind
    rows = [r for r in rows if not (low(_s(r.get("категория"))) == low(cat) and not _s(r.get("вид")))]  # заглушка группы
    if not any(low(_s(r.get("категория"))) == low(old_cat) for r in rows):  # старая группа опустела — остаётся пустой
        rows.append({"категория": old_cat, "вид": ""})
    rows.sort(key=lambda r: (low(_s(r.get("категория"))), low(_s(r.get("вид")))))
    writes = [(MATERIALS[0], MATERIALS[1], rows)]
    for spec in (BOM, MOVES, SUPPLY_SH, STOCK_ROLLS):
        data = bom if spec is BOM else _rows(spec)
        for r in data:
            if low(_s(r.get("материал"))) == low(old_kind):
                r["материал"] = kind
                if spec is BOM:
                    r["категория"] = cat
        writes.append((spec[0], spec[1], data))
    store.write_sheets(writes)
    return {"категория": cat, "вид": kind}


def delete_roll(me: dict, body: dict) -> dict:
    code = _norm_size(body.get("код"))
    if any(_norm_size(r.get("код рулона")) == code for r in _rows(ROLLS)):
        raise ValueError(f"Рулон {code} уже в карте кроя — удалить нельзя")
    rows = _rows(STOCK_ROLLS)
    keep = [r for r in rows if _norm_size(r.get("код рулона")) != code]
    if len(keep) == len(rows):
        raise ValueError(f"Рулон {code} не найден")
    store.write_sheet(STOCK_ROLLS[0], STOCK_ROLLS[1], keep)
    return {"код": code}


def roll_registry() -> dict[str, dict]:
    out = {}
    for r in _rows(STOCK_ROLLS):
        code = _norm_size(r.get("код рулона"))
        if code:
            out[code] = {"код": code, "дата": _s(r.get("дата")), "материал": _s(r.get("материал")),
                         "цвет": _s(r.get("цвет")), "граммы": _s(r.get("граммаж г")),
                         "вес": _s(r.get("вес кг")), "заказ": _norm_size(r.get("№ заказа")),
                         "поставщик": _s(r.get("поставщик")), "внёс": _s(r.get("внёс"))}
    return out


def _rolls_ready(rolls: list[dict], reg: dict, mv: list[dict]) -> list[dict]:
    have = {(_s(x["вид"]).lower(), x["цвет"]): x["шт"] for x in rolls_in_stock(mv) if not x.get("вдм")}
    need: dict = {}
    out = []
    for r in rolls:
        vdm = is_vdm(r["вид"])
        k = (_s(r["вид"]).lower(), _s(r["цвет"]).lower())
        need[k] = need.get(k, 0) + (0 if vdm else max(1, _int(r.get("шт"), 1)))
        out.append({**r, "вдм": vdm, "на_складе": have.get(k, 0),
                    "есть": (_norm_size(r["код"]) in reg) if vdm else have.get(k, 0) >= need[k]})
    return out


def supply_state() -> dict:
    bom, cards, mv, plan_rolls, reg = boms(), pcards(), moves(), card_rolls(), roll_registry()
    queue_ = []
    for o in orders():
        if o["статус"] == "отклонён":
            continue
        for c in sorted((c for c, st in o["карты"].items() if st == SUPPLYING), key=_int):
            item = {**o, "карта_номер": c, "карта": _card_rows(o, c, cards)}
            item["штук"] = sum(x["итог"] for x in item["карта"])
            item["рулоны"] = _rolls_ready(plan_rolls.get((o["номер"], c), []), reg, mv)
            item["сырьё"], item["без_спецификации"] = supply_lines(o, c, bom, cards, mv)
            queue_.append(item)
    left = [{"материал": "", "цвет": "", "остаток": v, "_k": k} for k, v in stock(mv).items()]
    names = {}
    for m in mv:  # исходное написание названия и цвета
        names.setdefault(_mkey(m["материал"], m["цвет"]), (m["материал"], m["цвет"]))
    for x in left:
        x["материал"], x["цвет"] = names[x.pop("_k")]
    return {"очередь": queue_, "спецификации": bom, "материалы": materials(),
            "рулоны": list(roll_registry().values())[::-1][:300],
            "рулоны_склад": rolls_in_stock(mv),
            "приёмки_рулонов": [m for m in mv if m["документ"] == "поступление" and m["ед"] == "шт"
                                and m["материал"].lower() in {k.lower() for k in roll_kinds()}][::-1][:100],
            "поставки": supplies()[::-1][:100],
            "типы": list(MAT_TYPES), "документы": list(MOVE_DOCS),
            "остатки": left, "движения": mv[::-1][:500]}


def _check_supply_ready(order: dict, card: str) -> None:
    """Технологу — только когда всё сырьё по спецификации есть на складе сырья."""
    need, missing = supply_lines(order, card, boms(), pcards())
    if missing:
        raise ValueError("Нет спецификации для модели: " + ", ".join(missing) + " — заполните её во вкладке «Спецификации»")
    short = [f'{n["материал"]} {n["цвет"]}'.strip() for n in need if not n["есть"]]
    if short:
        raise ValueError("Нет на складе сырья: " + ", ".join(short) + " — сначала проведите поступление")


def save_supply(me: dict, body: dict) -> dict:
    """Снабженец пишет комментарии и коды рулонов; «готово» — карта уходит технологу, если всё есть."""
    num = _s(body.get("номер"))
    card = _card_no(body.get("карта"))
    order = next((o for o in orders() if o["номер"] == num), None)
    if not order:
        raise ValueError("Заказ не найден")
    if order["карты"].get(card) != SUPPLYING:
        raise ValueError(f"Карта {card} заказа №{num} не у снабженца")
    who, now = _s(me.get("логин")), _now()
    lines = []
    for it in body.get("строки") or []:
        mat = _s(it.get("материал"))
        if not mat:
            continue
        lines.append({"№ заказа": num, "карта": card, "материал": mat, "цвет": _s(it.get("цвет")),
                      "ед.": _s(it.get("ед")), "нужно": _num(it.get("нужно")),
                      "комментарий": _s(it.get("комментарий")), "кто": who, "когда": now})
    done = bool(body.get("готово"))
    if done:
        _check_supply_ready(order, card)
    all_rolls, reg = _rows(CARD_ROLLS), roll_registry()
    mine = [r for r in all_rolls if _norm_size(r.get("№ заказа")) == num and _card_no(r.get("карта")) == card]
    given = body.get("рулоны") or []
    ready = _rolls_ready([{"вид": _s(r.get("вид")), "цвет": _s(r.get("цвет")), "код": _s(r.get("код рулона")),
                           "шт": r.get("шт")} for r in mine], reg, moves())
    for i, r in enumerate(mine):
        g = given[i] if i < len(given) else {}
        vdm = is_vdm(r.get("вид"))
        if vdm and ("код" in g or "вес" in g):  # код — только у ВДМ
            r["код рулона"], r["вес кг"] = _norm_size(g.get("код")), _num(g.get("вес")) or ""
        elif "вес" in g:  # обычные рулоны: принимаем штуками, а вес пишем при передаче закройщику
            r["вес кг"] = _num(g.get("вес")) or ""
        label = f"Рулон {i + 1} ({_s(r.get('вид'))} {_s(r.get('цвет'))}".rstrip() + ")"
        if done and vdm and not (_s(r.get("код рулона")) and _num(r.get("вес кг")) > 0):
            raise ValueError(f"{label}: у ВДМ впишите код рулона и вес, кг")
        if done and vdm and _norm_size(r.get("код рулона")) not in reg:
            raise ValueError(f"{label}: рулона {_s(r.get('код рулона'))} нет на складе — внесите ВДМ во вкладке «Рулоны»")
        if done and not vdm and not ready[i]["есть"]:
            raise ValueError(f"{label}: на складе сырья {ready[i]['на_складе']:g} шт этого цвета — "
                             "примите рулоны во вкладке «Рулоны»")
    for i, r in enumerate(mine):  # вес — после проверки штук: сначала «хватает ли рулонов», потом «сколько кг»
        if done and not is_vdm(r.get("вид")) and _num(r.get("вес кг")) <= 0:
            raise ValueError(f"Рулон {i + 1} ({_s(r.get('вид'))} {_s(r.get('цвет'))}): "
                             "впишите вес, кг — сколько уходит закройщику")
    codes = [_s(r.get("код рулона")) for r in mine if _s(r.get("код рулона"))]
    if len(codes) != len(set(codes)):
        raise ValueError("Один код рулона вписан дважды")
    rows = [r for r in _rows(SUPPLY_SH)
            if not (_norm_size(r.get("№ заказа")) == num and _card_no(r.get("карта")) == card)] + lines
    writes = [(SUPPLY_SH[0], SUPPLY_SH[1], rows), (CARD_ROLLS[0], CARD_ROLLS[1], all_rolls)]
    spent = []
    if done:
        spent = _writeoff_card(me, order, card, mine)  # сырьё уходит закройщику — списываем сразу
        writes += _stage_writes(num, {card: CUTQ})  # дальше крой; технолог принимает уже раскроенное
    store.write_sheets(writes)
    return {"номер": num, "карта": card, "статус": CUTQ if done else SUPPLYING, "списано": spent}


def _writeoff_card(me: dict, order: dict, card: str, rolls: list[dict]) -> list[dict]:
    """«Сырьё готово — передать закройщику»: расход в производство по спецификации (что ещё не списано)
    и рулоны карты — по одному на строку (ВДМ с кодами в складе сырья не числятся)."""
    lines, _ = supply_lines(order, card, boms(), pcards())
    out = [{"материал": n["материал"], "цвет": n["цвет"], "количество": round(n["нужно"] - n["списано"], 3)}
           for n in lines if round(n["нужно"] - n["списано"], 3) > 0]
    pcs: dict = {}
    for r in rolls:
        if _s(r.get("вид")) and not is_vdm(r.get("вид")):
            k = (_s(r.get("вид")), _s(r.get("цвет")))
            n, kg = pcs.get(k, (0, 0.0))
            pcs[k] = (n + max(1, _int(r.get("шт"), 1)), kg + _num(r.get("вес кг")))
    out += [{"материал": k[0], "цвет": k[1], "количество": n, "ед": "шт", "вес": round(kg, 3)}
            for k, (n, kg) in pcs.items()]
    if out:
        add_move(me, {"документ": "расход в производство", "заказ": order["номер"], "карта": card,
                      "комментарий": "автоматически при передаче закройщику", "строки": out})
    return out


def add_roll(me: dict, body: dict) -> dict:
    code = _norm_size(body.get("код"))
    if not code:
        raise ValueError("Укажите код рулона")
    if code in roll_registry():
        raise ValueError(f"Рулон {code} уже внесён")
    weight = _num(body.get("вес"))
    if weight <= 0:
        raise ValueError("Укажите вес рулона, кг")
    row = {"код рулона": code, "дата": _now(), "материал": _s(body.get("материал")),
           "цвет": _s(body.get("цвет")), "граммаж г": _num(body.get("граммы")) or "",
           "вес кг": weight, "№ заказа": _s(body.get("заказ")),
           "поставщик": _s(body.get("поставщик")), "внёс": _s(me.get("логин"))}
    store.append_rows(STOCK_ROLLS[0], STOCK_ROLLS[1], [row])
    return {"код": code}


def supplies() -> list[dict]:
    return _rows(SUPPLIES)


def add_supply(me: dict, body: dict) -> dict:
    """Приход поставки рулонов: штуки, общий вес и сумма → цена за кг считается сама."""
    mat, color = _s(body.get("материал")), _s(body.get("цвет"))
    if not mat:
        raise ValueError("Укажите материал (вид рулона)")
    rolls = _int(body.get("рулонов"), 0)
    kg = _num(body.get("вес"))
    total = _num(body.get("сумма"))
    if rolls <= 0:
        raise ValueError("Укажите, сколько рулонов в поставке")
    if kg <= 0:
        raise ValueError("Укажите общий вес поставки, кг")
    if total <= 0:
        raise ValueError("Укажите сумму поставки, сом")
    num = max([_int(r.get("№")) for r in supplies()] or [0]) + 1
    row = {"№": num, "дата": _now(), "материал": mat, "цвет": color, "рулонов": rolls,
           "вес кг": round(kg, 3), "сумма": round(total, 2), "цена кг": round(total / kg, 4),
           "поставщик": _s(body.get("поставщик")), "внёс": _s(me.get("логин"))}
    store.append_rows(SUPPLIES[0], SUPPLIES[1], [row])
    return {"№": num, "цена кг": row["цена кг"]}


def price_kg(mat: str, color: str, on: str = "") -> tuple[float, bool]:
    """Средняя цена кг рулона (вид, цвет) на дату `on`: суммы поставок / их общий вес."""
    day = _rate_day(on) or datetime.now()
    kg = total = 0.0
    key = _mkey(mat, color)
    for r in supplies():
        if _mkey(r.get("материал"), r.get("цвет")) != key:
            continue
        d = _rate_day(r.get("дата"))
        if d and d > day:
            continue  # поставка ещё впереди — в себестоимость ранних заказов не входит
        kg += _num(r.get("вес кг"))
        total += _num(r.get("сумма"))
    return (round(total / kg, 4), True) if kg > 0 else (0.0, False)


def mat_price(mat: str, color: str, on: str = "") -> tuple[float, bool]:
    """Средняя цена единицы материала на дату `on`: поступления с ценой, средневзвешенно."""
    day = _rate_day(on) or datetime.now()
    qty = total = 0.0
    key = _mkey(mat, color)
    for m in moves():
        if m["документ"] != "поступление" or _mkey(m["материал"], m["цвет"]) != key:
            continue
        price = _num(m.get("цена"))
        if price <= 0:
            continue
        d = _rate_day(m.get("дата"))
        if d and d > day:
            continue
        qty += m["количество"]
        total += m["количество"] * price
    return (round(total / qty, 4), True) if qty > 0 else (0.0, False)


def cex_setting(name: str, default: float = 0.0) -> float:
    """Числовая настройка цеха из листа «настройки» рабочей книги (параметр/значение)."""
    try:
        for row in store.read_sheet("настройки"):
            if _s(row.get("параметр")) == name:
                return _num(row.get("значение"))
    except Exception:
        pass
    return default


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
                "карта_заказа": _card_no(r.get("карта")),
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
                     "закройщик": _s(r.get("закройщик")), "шт": 0, "строки": [], "ждёт": False, "возврат": False}
            g["настилы"].append(found)
        found["ждёт"] = found["ждёт"] or _s(r.get("приёмка")) == WAIT
        found["возврат"] = found["возврат"] or _s(r.get("приёмка")) == RETURNED
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
    pending = {num: [x["название"] for x in order_steps(num, rows=rows) if not x["выполнено"]]
               for num, rows in _party_snapshots("заказ").items()}
    plan_rolls = card_rolls()
    for g in out:
        g["рулоны_карты"] = plan_rolls.get((_norm_size(g["заказ"]), g.pop("карта_заказа")), [])
        g["карты"] = cards_of(g["номер"])
        g["ждёт_шагов"] = pending.get(g["номер"], [])
    return {"партии": out, "к_крою": cut_queue(), "ставка": rate_of("РАСКР", 15.0), "лекала": patterns(),
            "возвраты": [g for g in cut_review() if g["статус"] == RETURNED],
            "рулоны_склад": list(roll_registry().values()),
            "материалы": [{"вид": m["вид"], "категория": m["категория"],  # обычные рулоны возвращают штуками
                           "ед": "шт" if "рулон" in m["категория"].lower() and not is_vdm(m["вид"]) else m["ед"]}
                          for m in materials() if m["вид"]]}


# --------------------------------------------------- карта кроя (закройщик)
# Карта = один настил по длине: лекало, длина; рулоны необязательны — их ведёт снабженец
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


# «готово к упаковке» значит: раскроенные настилы прошли маршрут; недокроенный остаток кроить можно
CUTTABLE = ("крой", "в производстве", "готово к упаковке")


def save_card(me: dict, body: dict) -> dict:
    num = _s(body.get("партия"))
    state = cut_state()
    party = next((p for p in state["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError(f"Партии №{num} нет")
    if party["статус"] not in CUTTABLE:
        raise ValueError(f"Партия в статусе «{party['статус']}» — крой недоступен")
    if party.get("ждёт_шагов"):
        raise ValueError("Сначала выполните шаги маршрута заказа: " + ", ".join(party["ждёт_шагов"]))
    length = _num(body.get("длина"))
    if length <= 0:
        raise ValueError("Укажите длину настила, м")
    pattern = _s(body.get("лекало"))
    rolls = []
    registry = roll_registry()
    for i, r in enumerate(body.get("рулоны") or [], start=1):
        code = _s(r.get("код"))
        weight = _num(r.get("вес"))
        if not code and weight <= 0 and not _s(r.get("цвет")):
            continue
        if not code:
            raise ValueError(f"Рулон {i}: укажите код рулона")
        # рулоны вносит снабженец: цвет и граммаж берём из его записи, не со слов закройщика
        known = registry.get(code)
        if not known:
            raise ValueError(f"Рулон {code} не внесён снабженцем — его добавляют во вкладке «Снабжение»")
        rolls.append({"код": code, "граммы": _num(known["граммы"]), "цвет": known["цвет"],
                      "вес": weight or _num(known["вес"])})

    known = {m["вид"].lower() for m in state["материалы"]}
    back = [b for b in body.get("возврат") or [] if _s(b.get("материал"))]
    for b in back:  # проверяем до записи карты, чтобы не сохранить карту без возврата
        if _s(b.get("материал")).lower() not in known:
            raise ValueError(f"Возврат: «{_s(b.get('материал'))}» нет в номенклатуре")
        if _num(b.get("количество")) <= 0:
            raise ValueError(f"Возврат: укажите количество для «{_s(b.get('материал'))}»")
        pcs = {m["вид"].lower(): m["ед"] for m in state["материалы"]}.get(_s(b.get("материал")).lower()) == "шт"
        if pcs and _num(b.get("количество")) != int(_num(b.get("количество"))):
            raise ValueError(f"Возврат: «{_s(b.get('материал'))}» — целое число штук "
                             "(остаток рулона сдайте отдельным видом сырья)")

    index = {(r["цвет"], r["размер"]): r for r in party["строки"]}
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
            # план — подсказка: закройщик может раскроить больше, чем осталось по плану
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
                             "карта": card_no, "приёмка": WAIT})
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
    if back:
        add_move(me, {"документ": "возврат из кроя", "строки": back, "заказ": party["заказ"],
                      "комментарий": f"партия {num}, карта кроя {card_no}"})
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
    if party["статус"] not in CUTTABLE:
        raise ValueError(f"Партия в статусе «{party['статус']}» — крой недоступен")
    if party.get("ждёт_шагов"):
        raise ValueError("Сначала выполните шаги маршрута заказа: " + ", ".join(party["ждёт_шагов"]))

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
            "закройщик": who, "дата": now, "комментарий": _s(body.get("комментарий")), "приёмка": WAIT,
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
PACK_STAGE = "УПАК"  # упаковка — последний этап швейного маршрута, как оверлок или краска
START_STAGE = "РАСКР"
DONE_PARTY = ("упакован", "на складе", "отгружен", "отгружена")

# вид маршрута → листы и «старт» (условный первый узел графа)
KINDS = {
    "шв": {"route": ROUTE, "model": ROUTE_MODEL, "party": ROUTE_PARTY, "старт": START_STAGE,
           "старт_название": "Крой", "пусто": "сразу после кроя", "название": "Швейный маршрут"},
    "гп": {"route": ROUTE_FIN, "model": ROUTE_FIN_MODEL, "party": ROUTE_FIN_PARTY, "старт": "ПОШИВ",
           "старт_название": "Пошив", "пусто": "сразу после швейного маршрута",
           "название": "Маршрут готовой продукции"},
    "заказ": {"route": ROUTE_ORD, "model": ROUTE_ORD_MODEL, "party": ROUTE_ORD_PARTY, "старт": "ПРИЁМКА",
              "старт_название": "Приёмка технологом", "пусто": "сразу после приёмки технологом",
              "название": "Маршрут заказа"},
}


def _kind(v) -> str:
    v = _s(v) or "шв"
    if v not in KINDS:
        raise ValueError("Неизвестный вид маршрута")
    return v


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
                          "ставка": rate, "порядок": _int(r.get("порядок"), 500),
                          "отключён": _yes(r.get("отключён"))}
    except Exception:
        pass
    base.setdefault(PACK_STAGE, {"код": PACK_STAGE, "название": "Упаковка", "ставка": 0.0,
                                 "порядок": 900, "отключён": False})
    return base


def _wh_ops() -> dict[str, dict]:
    """Этапы маршрута ГП — роли складского процесса (приёмка → хранение → сборка → поставка)."""
    out: dict[str, dict] = {}
    for i, (code, name) in enumerate(perms.all_roles().items()):
        if code != perms.LOCKED_ROLE and perms.role_process(code) == "склад":
            out[code] = {"код": code, "название": name, "ставка": 0.0, "порядок": 1000 + i, "отключён": False}
    return out


def _route_ops() -> dict[str, dict]:
    """Все известные этапы маршрутов: операции цеха + складские роли (названия, проверка, партии)."""
    return {**_wh_ops(), **_ops()}


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


def route_templates(kind: str = "шв") -> dict[str, list[dict]]:
    """Сырые строки листа маршрута по шаблонам (пустой шаблон = «Основной»)."""
    out: dict[str, list[dict]] = {}
    for r in _rows(KINDS[kind]["route"]):
        if not _s(r.get("этап")):
            continue
        out.setdefault(_s(r.get("шаблон")) or MAIN_ROUTE, []).append(r)
    return out


def model_routes(kind: str = "шв") -> dict[str, str]:
    out = {}
    for r in _rows(KINDS[kind]["model"]):
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


def _party_snapshots(kind: str = "шв") -> dict[str, list[dict]]:
    snap: dict[str, list[dict]] = {}
    for r in _rows(KINDS[kind]["party"]):
        num = _s(r.get("№ партии"))
        if num.endswith(".0"):
            num = num[:-2]
        if num and _s(r.get("этап")):
            snap.setdefault(num, []).append(r)
    return snap


def party_routes(parties: list[dict], kind: str = "шв", with_fin: bool = True) -> dict[str, dict]:
    """№ партии → {шаблон, своя (есть копия в листе партии), этапы}.

    «шв» без своей копии берёт шаблон модели (так было всегда). «гп» и «заказ» — только
    копия партии: партии, принятые до появления этих маршрутов, не меняются.
    Для «шв» к швейным этапам дописываются этапы готовой продукции (with_fin) — дальше
    они работают как обычные этапы по настилам, а упаковка ждёт их окончания.
    """
    ops = _route_ops()
    snap = _party_snapshots(kind)
    fin = _party_snapshots("гп") if kind == "шв" and with_fin else {}
    templates = route_templates(kind) if kind == "шв" else {}
    bind = model_routes(kind) if kind == "шв" else {}
    cache: dict[str, list[dict]] = {}
    out: dict[str, dict] = {}
    for p in parties:
        num = _s(p.get("номер"))
        if num in snap:
            rows = snap[num]
            info = {"шаблон": _s(rows[0].get("шаблон")) or MAIN_ROUTE, "своя": True,
                    "этапы": _stage_items(rows, ops)}
        elif kind != "шв":
            info = {"шаблон": "", "своя": False, "этапы": []}
        else:
            t = _pick_template(_s(p.get("модель")), templates, bind)
            if t not in cache:
                cache[t] = _stage_items(templates.get(t, []), ops)
            info = {"шаблон": t, "своя": False, "этапы": cache[t]}
        if fin.get(num):
            info = dict(info, этапы=_with_fin(info["этапы"], fin[num], ops))
        out[num] = info
    return out


def _with_fin(sew: list[dict], fin_rows: list[dict], ops: dict) -> list[dict]:
    """Швейные этапы + этапы готовой продукции: «пусто/ПОШИВ» = после последних швейных."""
    finals = _finals(sew)
    codes = {s["код"] for s in sew}
    out = list(sew)
    for st in _stage_items(fin_rows, ops):
        if st["код"] in codes:
            continue  # такой этап уже есть в швейном маршруте
        deps = [d for d in st["зависимости"] if d != KINDS["гп"]["старт"]]
        out.append(dict(st, зависимости=deps or list(finals), гп=True))
    return _topo(out)


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


def check_route(stages: list[dict], known: dict | None = None, kind: str = "шв") -> dict:
    """Проверка маршрута. stages: [{код, зависимости, активен?}]."""
    start = KINDS[kind]["старт"]
    errors: list[str] = []
    warnings: list[str] = []
    active = [s for s in stages if s.get("активен", True)]
    codes: list[str] = []
    for s in active:
        c = _s(s.get("код"))
        if not c:
            errors.append("Есть этап без кода")
            continue
        if c in (start, START_STAGE):
            errors.append(f"{c} — это старт маршрута, его не нужно добавлять этапом")
        if c in codes:
            errors.append(f"Этап {c} указан дважды")
        codes.append(c)
    if not active and kind == "шв":
        errors.append("В маршруте нет ни одного этапа")
    cs = set(codes)
    for s in active:
        c = _s(s.get("код"))
        for d in s.get("зависимости") or []:
            if d == c:
                errors.append(f"{c} не может идти после самого себя")
            elif d not in cs and d != start:
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
        missing = [c for c in codes if c not in known and c != start]
        if missing:
            warnings.append("Нет ставки в листе «расценки»: " + ", ".join(missing)
                            + " — швея получит 0 сом/шт")
    return {"ошибки": errors, "предупреждения": warnings, "финал": finals}


def _clean_stage_input(raw: list) -> list[dict]:
    out = []
    # коды операций — заглавными, коды ролей склада (wh_picker, storekeeper) — как есть
    canon = {k.upper(): k for k in _route_ops()}
    norm = lambda c: canon.get(_s(c).upper(), _s(c).upper())  # noqa: E731
    for s in raw or []:
        code = norm(s.get("код") or s.get("этап"))
        if not code:
            continue
        out.append({"код": code, "зависимости": [norm(d) for d in _deps(s.get("после") or s.get("зависимости"))],
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


def routes_state(me: dict, kind: str = "шв") -> dict:
    K = KINDS[kind]
    if kind == "шв":
        seed_route()
    ops = _route_ops()
    templates = route_templates(kind)
    bind = model_routes(kind)
    models = [m for m in refs()["модели"]]
    if kind != "шв" and MAIN_ROUTE not in templates:
        templates[MAIN_ROUTE] = []  # пустой основной: шагов нет, пока их не добавят
    tpl_out = []
    names = list(templates)
    if MAIN_ROUTE in names:
        names.remove(MAIN_ROUTE)
        names.insert(0, MAIN_ROUTE)
    for name in names:
        stages = _editor_stages(templates[name], ops)
        tpl_out.append({
            "имя": name, "этапы": stages,
            "проверка": check_route(stages_for_check(stages), ops, kind),
            "модели": [m["модель"] for m in models
                       if _pick_template(m["модель"], templates, bind) == name],
        })

    parties_all = cut_state()["партии"]
    routes = party_routes(parties_all, kind, with_fin=False)
    snap = _party_snapshots(kind)
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
        rows = snap.get(num) or (templates.get(info["шаблон"], []) if kind == "шв" else [])
        item = {
            "номер": num, "модель": p["модель"], "клиент": p["клиент"],
            "статус": p["статус"], "план": p["план"], "раскроено": p["раскроено"],
            "шаблон": info["шаблон"] or MAIN_ROUTE, "своя": info["своя"],
            "этапы": _editor_stages(rows, ops),
            "сдано": {st["код"]: done.get((num, st["код"]), 0) for st in info["этапы"]},
            "в_работе": {st["код"]: inwork.get((num, st["код"]), 0) for st in info["этапы"]},
        }
        if kind == "заказ":
            item["шаги"] = {x["код"]: x for x in order_steps(num, me, rows)}
        party_out.append(item)

    out = {
        "вид": kind, "название": K["название"], "старт": K["старт"],
        "старт_название": K["старт_название"], "пусто": K["пусто"],
        "шаблоны": tpl_out,
        # на выбор: маршрут ГП — складские роли, остальные маршруты — операции цеха
        "операции": sorted((_wh_ops() if kind == "гп" else _ops()).values(), key=lambda x: (x["порядок"], x["код"])),
        "модели": [{"модель": m["модель"], "название": m["название"],
                    "категория": m["категория"],
                    "шаблон": _pick_template(m["модель"], templates, bind),
                    "назначен": m["модель"] in bind} for m in models],
        "партии": party_out,
        "сотрудники": staff_people(_s(me.get("цех"))),
        "можно": _can(me, "cex.routes"),
    }
    if kind == "заказ":
        out["ожидают"] = [{"номер": x["номер"], "модель": x["модель"], "клиент": x["клиент"],
                           "раскроено": x["раскроено"], "шаги": list(x["шаги"].values())}
                          for x in party_out if any(not st["выполнено"] for st in x["шаги"].values())]
    return out


# ------------------------------------------------- шаги маршрута заказа
def order_steps(num: str, me: dict | None = None, rows: list[dict] | None = None) -> list[dict]:
    """Шаги заказа партии (из её копии) с отметками. «можно» — текущему пользователю отметить."""
    if rows is None:
        rows = _party_snapshots("заказ").get(num, [])
    ops = _ops()
    start = KINDS["заказ"]["старт"]
    done = {_s(r.get("этап")) for r in rows if _yes(r.get("выполнено"))}
    mine = set(roles_of(me)) if me else set()
    out = []
    for st in _stage_items(rows, ops):
        r = next((x for x in rows if _s(x.get("этап")) == st["код"]), {})
        deps = [d for d in st["зависимости"] if d != start]
        ready = all(d in done for d in deps)
        is_done = st["код"] in done
        out.append({"код": st["код"], "название": st["название"], "после": deps,
                    "выполнено": is_done, "кто": _s(r.get("кто отметил")), "когда": _s(r.get("когда")),
                    "готов": ready,
                    "можно": bool(me) and not is_done and ready
                    and (st["код"] in mine or _can(me, "cex.tech"))})
    return out


def order_pending(num: str) -> list[str]:
    """Названия невыполненных шагов заказа — пока они есть, партию не кроят."""
    return [x["название"] for x in order_steps(num) if not x["выполнено"]]


def mark_order_step(me: dict, body: dict) -> dict:
    num = _norm_size(body.get("партия"))
    code = _s(body.get("шаг")).upper()
    want = bool(body.get("выполнено", True))
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    rows = _rows(ROUTE_ORD_PARTY)
    row = next((r for r in rows if _norm_size(r.get("№ партии")) == num and _s(r.get("этап")) == code), None)
    if row is None:
        raise ValueError("Такого шага нет в маршруте заказа этой партии")
    step = next(x for x in order_steps(num, me) if x["код"] == code)
    if want:
        if step["выполнено"]:
            return {"шаг": code, "выполнено": True}
        if not step["готов"]:
            raise ValueError("Сначала выполните предыдущие шаги: " + ", ".join(step["после"]))
        if not step["можно"]:
            raise perms.AccessError("Отметить шаг может сотрудник с этим этапом или технолог")
        row.update({"выполнено": 1, "кто отметил": _s(me.get("фио")) or _s(me.get("логин")),
                    "когда": datetime.now().strftime("%d.%m.%Y %H:%M")})
    else:
        if not _can(me, "cex.tech"):
            raise perms.AccessError("Снять отметку может технолог")
        if party["раскроено"] > 0:
            raise ValueError("Партию уже начали кроить — отметку снять нельзя")
        row.update({"выполнено": "", "кто отметил": "", "когда": ""})
    store.write_sheets([(ROUTE_ORD_PARTY[0], ROUTE_ORD_PARTY[1], rows)])
    return {"шаг": code, "выполнено": want}


def stages_for_check(stages: list[dict]) -> list[dict]:
    return [{"код": s["код"], "зависимости": s.get("после") or [],
             "активен": s.get("активен", True)} for s in stages]


def _route_rows(template: str, stages: list[dict]) -> list[dict]:
    return [{"шаблон": template, "этап": s["код"],
             "после каких этапов": ";".join(s["зависимости"]),
             "на склад ГП": 1 if s["склад_гп"] else 0, "кто может": s["кто"],
             "активен": 1 if s["активен"] else 0} for s in stages]


def save_route(me: dict, body: dict) -> dict:
    kind = _kind(body.get("вид"))
    K = KINDS[kind]
    stages = _clean_stage_input(body.get("этапы"))
    ops = _route_ops()
    check = check_route(stages, ops, kind)
    if check["ошибки"]:
        raise ValueError(check["ошибки"][0])
    party = _s(body.get("партия"))
    # отключённый этап остаётся там, где уже был, но в новые маршруты не добавляется
    had = {_s(r.get("этап")).upper() for r in (_party_snapshots(kind).get(party, []) if party else
           route_templates(kind).get(_s(body.get("старое_имя")) or _s(body.get("шаблон")), []))}
    off = [st["код"] for st in stages if (ops.get(st["код"]) or {}).get("отключён") and st["код"].upper() not in had]
    if off:
        raise ValueError(f"Роль {off[0]} отключена — в новый маршрут её не добавить")
    # маршрут строится только из ролей: новых кодов «на лету» больше нет
    unknown = [st["код"] for st in stages if st["код"] not in ops and st["код"].upper() not in had]
    if unknown:
        raise ValueError(f"Роли {unknown[0]} нет — создайте её во вкладке «Сотрудники и роли»")
    if party:
        return _save_party_route(party, _s(body.get("шаблон")) or MAIN_ROUTE, stages, check, kind)

    name = _s(body.get("шаблон"))
    old = _s(body.get("старое_имя")) or name
    if not name:
        raise ValueError("Назовите шаблон")
    if len(name) > 40:
        raise ValueError("Слишком длинное название шаблона")
    templates = route_templates(kind)
    if name != old and name in templates:
        raise ValueError(f"Шаблон «{name}» уже есть")
    if old == MAIN_ROUTE and name != MAIN_ROUTE:
        raise ValueError("Основной шаблон нельзя переименовать")
    rows = [r for r in _rows(K["route"]) if (_s(r.get("шаблон")) or MAIN_ROUTE) not in (old, name)]
    for r in rows:
        if not _s(r.get("шаблон")):
            r["шаблон"] = MAIN_ROUTE
    rows += _route_rows(name, stages)
    items = [(K["route"][0], K["route"][1], rows)]
    if name != old:
        bind_rows = _rows(K["model"])
        for r in bind_rows:
            if _s(r.get("шаблон")) == old:
                r["шаблон"] = name
        items.append((K["model"][0], K["model"][1], bind_rows))
    store.write_sheets(items)
    return {"шаблон": name, "этапов": len(stages), "предупреждения": check["предупреждения"]}


def _save_party_route(num: str, template: str, stages: list[dict], check: dict,
                      kind: str = "шв") -> dict:
    K = KINDS[kind]
    parties_all = cut_state()["партии"]
    party = next((p for p in parties_all if p["номер"] == num), None)
    if not party:
        raise ValueError("Партия не найдена")
    codes = {s["код"] for s in stages if s["активен"]}
    warn = list(check["предупреждения"])
    if kind == "заказ" and party["раскроено"] > 0:
        raise ValueError("Партию уже начали кроить — шаги заказа менять поздно")
    # этапы другого вида той же партии тоже «свои»: их работа не считается выпавшей
    other = "гп" if kind == "шв" else "шв"
    if kind != "заказ":
        codes |= {st["код"] for st in (party_routes([party], other, with_fin=False).get(num) or {}).get("этапы", [])}
    for r in (_rows(OUT) if kind != "заказ" else []):
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
    old = {_s(r.get("этап")): r for r in _rows(K["party"]) if _norm_size(r.get("№ партии")) == num}
    rows = [r for r in _rows(K["party"]) if _norm_size(r.get("№ партии")) != num]
    new = [{"№ партии": num, "шаблон": template, "этап": s["код"],
            "после каких этапов": ";".join(s["зависимости"]),
            "на склад ГП": 1 if s["склад_гп"] else 0, "кто может": s["кто"]}
           for s in stages if s["активен"]]
    for r in new:  # отметки выполненных шагов заказа сохраняются
        for col in ("выполнено", "кто отметил", "когда"):
            if col in K["party"][1]:
                r[col] = (old.get(r["этап"]) or {}).get(col, "")
    store.write_sheets([(K["party"][0], K["party"][1], rows + new)])
    return {"партия": num, "этапов": len(new), "предупреждения": warn}


def delete_route(me: dict, body: dict) -> dict:
    K = KINDS[_kind(body.get("вид"))]
    name = _s(body.get("шаблон"))
    if not name or name == MAIN_ROUTE:
        raise ValueError("Основной шаблон удалить нельзя")
    rows = [r for r in _rows(K["route"]) if (_s(r.get("шаблон")) or MAIN_ROUTE) != name]
    for r in rows:
        if not _s(r.get("шаблон")):
            r["шаблон"] = MAIN_ROUTE
    bind_rows = [r for r in _rows(K["model"]) if _s(r.get("шаблон")) != name]
    store.write_sheets([(K["route"][0], K["route"][1], rows), (K["model"][0], K["model"][1], bind_rows)])
    return {"ok": True}


def bind_route(me: dict, body: dict) -> dict:
    kind = _kind(body.get("вид"))
    K = KINDS[kind]
    model = _s(body.get("модель"))
    name = _s(body.get("шаблон"))
    if not model:
        raise ValueError("Не выбрана модель")
    if name and name != MAIN_ROUTE and name not in route_templates(kind):
        raise ValueError(f"Шаблона «{name}» нет")
    rows = [r for r in _rows(K["model"]) if _s(r.get("модель")) != model]
    if name and name != MAIN_ROUTE:
        rows.append({"модель": model, "шаблон": name})
    store.write_sheets([(K["model"][0], K["model"][1], rows)])
    return {"модель": model, "шаблон": name or MAIN_ROUTE}


def snapshot_rows(num, model: str, kind: str = "шв") -> list[dict]:
    """Строки листа партии для новой партии — копия шаблона её модели."""
    templates = route_templates(kind)
    t = _pick_template(model, templates, model_routes(kind))
    return [{"№ партии": num, "шаблон": t, "этап": _s(r.get("этап")),
             "после каких этапов": _s(r.get("после каких этапов")),
             "на склад ГП": r.get("на склад ГП", 0), "кто может": _s(r.get("кто может"))}
            for r in templates.get(t, []) if _flag(r.get("активен"), True)]


# ------------------------------------------------------- роли сотрудников
# Доступ к этапам. В листе «Сотрудники цеха» колонка «этап» хранит коды через «;»:
# «ОВЕРЛ;КАРМАН;СБОРКА». Каждый код — отдельный доступ; пусто — этапов нет, работу
# на этапах взять нельзя. Это не права системы (они в perms.py), а то, что человек шьёт.
BOSSES = ("admin", "manager")


def production_roles() -> dict[str, str]:
    """Производственные роли = операции из листа «расценки» (кроме кроя — это роль «Закройщик»)."""
    return {c: o["название"] for c, o in _ops().items() if c != START_STAGE}


def _norm_role(code) -> str:
    c = _s(code)
    return c.upper() if c.upper() in production_roles() or c.upper() == c else c


def extra_roles_of(login: str) -> list[str]:
    for r in _rows(STAFF):
        if _s(r.get("логин")) == login:
            return [_norm_role(c) for c in _deps(r.get("роли"))]
    return []


def register_role_sources() -> None:
    perms.SOURCES.update(prod=production_roles, extra=extra_roles_of)


def roles_of(me: dict) -> list[str]:
    """Производственные роли человека: на каких операциях он работает."""
    prod = production_roles()
    mine = perms.roles_of(me)
    out = [r for r in mine if r in prod]
    # Упаковщик работает на этапе «Упаковка» и получает его ставку
    if "packer" in mine and PACK_STAGE in prod and PACK_STAGE not in out:
        out.append(PACK_STAGE)
    return out


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
    prod = production_roles()
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
        mine = [item["должность"]] + [_norm_role(x) for x in _deps((cards.get(login) or {}).get("роли"))]
        item["этапы"] = [x for x in mine if x in prod]
        res.append(item)
    res.sort(key=lambda x: (x["должность"] in BOSSES, x["ФИО"].lower()))
    return res


def set_roles(me: dict, body: dict) -> dict:
    """Выдать/снять роль сотруднику: {логин, роль, можно} или весь список {логин, роли: [...]}.
    Любая роль — служебная или производственная; основная роль меняется в карточке."""
    _need(me, "stages.assign")
    login = _s(body.get("логин"))
    target = _find_user(login, _s(me.get("цех")))
    if not target:
        raise ValueError("Сотрудник не найден в этом цехе")
    rows = _rows(STAFF)
    row = next((r for r in rows if _s(r.get("логин")) == login), None)
    if row is None:
        row = {"логин": login, "ФИО": _s(target.get("фио")) or login,
               "должность": _s(target.get("роль")), "роли": "", "тип оплаты": "сдельная",
               "ставка": 0, "периодичность": "месяц", "модели": "", "телефон": "", "активен": 1}
        rows.append(row)
    current = [_norm_role(c) for c in _deps(row.get("роли"))]
    if "роли" in body:
        new = [_norm_role(c) for c in _deps(body.get("роли"))]
    else:
        code = _norm_role(body.get("роль") or body.get("этап"))
        if not code:
            raise ValueError("Не выбрана роль")
        new = [c for c in current if c != code] + ([code] if body.get("можно") else [])
    main = _s(target.get("роль"))
    new = [c for c in new if c != main]  # основная роль и так есть
    if START_STAGE in new:
        raise ValueError("Крой — это роль «Закройщик»")
    ops = _ops()
    added = [c for c in new if c not in current]
    removed = [c for c in current if c not in new]
    for c in added:
        perms.check_role_grant(me, target, c, True)
        if c in ops and ops[c].get("отключён"):
            raise ValueError(f"Роль «{ops[c]['название']}» отключена — новым людям её не выдать")
    for c in removed:
        if c in perms.all_roles():
            perms.check_role_grant(me, target, c, False)
    row["роли"] = ";".join(new)
    store.write_sheets([(STAFF[0], STAFF[1], rows)])
    if added or removed:
        perms.log_event(me, "роли", login, ", ".join(perms.role_label(c) for c in removed),
                        ", ".join(perms.role_label(c) for c in added))
    prod = production_roles()
    return {"логин": login, "роли": new, "этапы": [c for c in [main] + new if c in prod]}


# ------------------------------------------- сотрудники, этапы и права (раздел «Доступ»)
ACCOUNTS = "сотрудники"          # лист рабочей книги — источник учёток портала
RATES_SHEET = ("расценки", ["код", "операция", "расценка за шт", "порядок", "обязательная", "отключён"])
_LOGIN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_.\-]{2,32}")
_CODE_RE = re.compile(r"[A-ZА-ЯЁ0-9_]{2,12}")


def _all_users() -> list[dict]:
    from server import staff_users  # noqa: WPS433 — учётки: лист «сотрудники» + users.xlsx
    return staff_users()


def _same_company(u: dict, company: str) -> bool:
    return not company or not _s(u.get("цех")) or _s(u.get("цех")) == company


def _find_user(login: str, company: str) -> dict | None:
    for u in _all_users():
        if _s(u.get("логин")) == login and _same_company(u, company):
            return u
    return None


def _need(me: dict, code: str) -> None:
    if not _can(me, code):
        raise perms.AccessError(f"Нет права «{perms.LABELS.get(code, code)}»")


def _readable_pw(stored: str) -> str:
    """Пароль для показа админу; «» — старый зашифрованный, узнать нельзя (задайте новый)."""
    from server import hash_password  # noqa: WPS433
    if len(stored) != 64:
        return "" if stored.lower() in ("изменён", "изменен", "changed") else stored
    return "123456" if stored == hash_password("123456") else ""


def logins_xlsx(me: dict) -> bytes:
    """Логины и пароли сотрудников цеха — как в карточке: видит тот, кто правит сотрудников;
    пароль администратора — только администратору. Зашифрованный старый пароль узнать нельзя."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    if not _can(me, "staff.edit"):
        raise PermissionError("Выгрузка логинов — у кого есть право «Изменение сотрудников»")
    state = access_state(me)
    wb = Workbook()
    ws = wb.active
    ws.title = "Логины"
    ws.append(["ФИО", "Логин", "Пароль", "Роль", "Все роли", "Цех", "Активен"])
    for c in ws[1]:
        c.font = Font(bold=True)
    labels = perms.all_roles()
    for p in state["люди"]:
        pw = p.get("пароль")
        ws.append([p["ФИО"], p["логин"],
                   pw if pw else ("скрыт — пароль администратора" if "пароль" not in p else "зашифрован — задайте новый"),
                   p["роль_название"], ", ".join(labels.get(r, r) for r in p.get("роли") or []),
                   p["цех"], "да" if p["активен"] else "нет"])
    for col, w in zip("ABCDEFG", (30, 16, 16, 18, 30, 10, 9)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    perms.log_event(me, "выгрузил логины и пароли", "все", "", f"{ws.max_row - 1} сотрудников")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def access_state(me: dict) -> dict:
    """Сотрудники, все роли (служебные и производственные), разрешения и журнал."""
    comp = _s(me.get("цех"))
    data = perms.load()
    see_perms = _can(me, "perms.roles") or _can(me, "perms.users")
    see_pw = _can(me, "staff.edit")
    users = [u for u in _all_users() if _same_company(u, comp)]
    labels = perms.all_roles()
    people = []
    for u in users:
        login = _s(u.get("логин"))
        item = {"логин": login, "ФИО": _s(u.get("фио")) or login, "роль": _s(u.get("роль")),
                "роль_название": labels.get(_s(u.get("роль")), _s(u.get("роль"))),
                "роли": perms.roles_of(u, data),
                "цех": _s(u.get("цех")), "активен": _flag(u.get("активен"), True)}
        if see_perms:
            item["права"] = perms.user_view(u, data)
        if see_pw and (_s(u.get("роль")) != perms.LOCKED_ROLE or _s(me.get("роль")) == perms.LOCKED_ROLE):
            item["пароль"] = _readable_pw(_s(u.get("пароль")))
        people.append(item)
    people.sort(key=lambda p: (not p["активен"], p["роль"] == "client", p["ФИО"].lower()))
    ops = _ops()
    used = _stages_in_use()
    matrix = perms.role_matrix(data) if see_perms else {}
    by_model = model_rates()
    roles = []
    for code, label in perms.ROLE_LABELS.items():
        roles.append({"код": code, "название": label, "вид": "служебная"})
    for code, label in perms.custom_roles(data).items():
        roles.append({"код": code, "название": label, "вид": "служебная", "своя": True})
    pack = ops.get(PACK_STAGE)
    for r in roles:  # Упаковщик = этап «Упаковка»: его цена за штуку — ставка этапа
        if r["код"] == "packer" and pack:
            r.update({"ставка": pack["ставка"], "порядок": pack["порядок"], "этап": PACK_STAGE,
                      "этап_название": pack["название"], "по_моделям": by_model.get(PACK_STAGE, {})})
    for code, op in sorted(ops.items(), key=lambda kv: (kv[1]["порядок"], kv[0])):
        if code == START_STAGE:
            continue  # крой — служебная роль «Закройщик»
        if code == PACK_STAGE:
            continue  # упаковка — это роль «Упаковщик», отдельной ролью не показываем
        roles.append({"код": code, "название": op["название"], "вид": "производственная",
                      "ставка": op["ставка"], "порядок": op["порядок"],
                      "по_моделям": by_model.get(code, {}),
                      "используется": used.get(code, ""), "отключён": op.get("отключён", False)})
    for r in roles:
        r["процесс"] = perms.role_process(r["код"], data)
        r["люди"] = [p["логин"] for p in people if r["код"] in p["роли"]]
        if see_perms:
            r["права"] = matrix.get(r["код"], {})
    out = {"я": _s(me.get("логин")), "мои_права": perms.effective(me, data),
           "люди": people, "роли": roles, "каталог": perms.catalog(),
           "роли_названия": labels, "закрытая_роль": perms.LOCKED_ROLE, "процессы": perms.PROCESSES}
    if see_perms:
        out["журнал"] = perms.journal(150)
    return out


def save_role(me: dict, body: dict) -> dict:
    return perms.save_role(me, _s(body.get("код")), _s(body.get("название")), _s(body.get("процесс")))


def delete_role(me: dict, body: dict) -> dict:
    code = _s(body.get("код"))
    # роль общая на все цеха — считаем людей всех цехов
    return perms.delete_role(me, code, sum(1 for u in _all_users() if code in perms.roles_of(u)))


def set_role_perm(me: dict, body: dict) -> dict:
    return perms.set_role_perm(me, _all_users(), _s(body.get("роль")), _s(body.get("право")),
                               bool(body.get("значение")))


def set_user_perm(me: dict, body: dict) -> dict:
    target = _find_user(_s(body.get("логин")), _s(me.get("цех")))
    if not target:
        raise ValueError("Сотрудник не найден в этом цехе")
    value = body.get("значение")
    return perms.set_user_perm(me, _all_users(), target, _s(body.get("право")),
                               None if value is None else bool(value))


def save_account(me: dict, body: dict) -> dict:
    """Добавить сотрудника или изменить его карточку: ФИО, роль, пароль, активен.
    Пароль хранится открыто — так решил владелец, чтобы админ видел действующий пароль."""
    comp = _s(me.get("цех"))
    login = _s(body.get("логин"))
    users = _all_users()
    target = next((u for u in users if _s(u.get("логин")) == login), None)
    if target is not None and not _same_company(target, comp):
        raise ValueError("Сотрудник не найден в этом цехе")
    create = target is None
    if create:
        _need(me, "staff.add")
        if not _LOGIN_RE.fullmatch(login):
            raise ValueError("Логин: 2–32 буквы, цифры, точка, дефис или подчёркивание")
        fio = _s(body.get("ФИО") or body.get("фио"))
        if not fio:
            raise ValueError("Укажите ФИО")
        password = _s(body.get("пароль"))
        if len(password) < 4:
            raise ValueError("Пароль — не короче 4 символов")
        role = _s(body.get("роль"))
        if not role:
            raise ValueError("Выберите роль")
        newbie = {"логин": login, "роль": "", "цех": comp, "активен": 1}
        perms.check_role_change(me, users + [newbie], newbie, role, None)
        _write_account(login, {"фио": fio, "роль": role, "активен": True,
                               "пароль": password, "цех": comp}, create=True)
        perms.log_event(me, "новый сотрудник", login, "", perms.role_label(role))
        return {"логин": login, "создан": True}

    if _s(target.get("роль")) == perms.LOCKED_ROLE and _s(me.get("роль")) != perms.LOCKED_ROLE:
        raise perms.AccessError("Карточку администратора может менять только администратор")
    fields: dict = {}
    if "ФИО" in body or "фио" in body:
        fio = _s(body.get("ФИО") or body.get("фио"))
        if not fio:
            raise ValueError("ФИО не может быть пустым")
        if fio != _s(target.get("фио")):
            fields["фио"] = fio
    new_role = _s(body.get("роль")) or None
    if new_role == _s(target.get("роль")):
        new_role = None
    if new_role is not None:
        fields["роль"] = new_role
    new_active = None
    if "активен" in body and bool(body.get("активен")) != _flag(target.get("активен"), True):
        new_active = bool(body.get("активен"))
        fields["активен"] = new_active
    if _s(body.get("пароль")):
        if len(_s(body.get("пароль"))) < 4:
            raise ValueError("Пароль — не короче 4 символов")
        if login == _s(me.get("логин")):
            raise ValueError("Свой пароль здесь не меняется")
        fields["пароль"] = _s(body.get("пароль"))
    if not fields:
        return {"логин": login, "изменено": 0}
    if new_active is False:
        _need(me, "staff.delete")
    if set(fields) - {"активен", "роль"} or new_active:
        _need(me, "staff.edit")
    if "роль" in fields:
        _need(me, "stages.assign")
    perms.check_role_change(me, users, target, new_role, new_active)
    _write_account(login, fields, create=False)
    if new_role is not None:
        perms.log_event(me, "роль", login, perms.role_label(_s(target.get("роль"))),
                        perms.role_label(new_role))
    if new_active is not None:
        perms.log_event(me, "включён" if new_active else "отключён", login)
    if "пароль" in fields:
        perms.log_event(me, "пароль сброшен", login)
    return {"логин": login, "изменено": len(fields)}


def _write_account(login: str, fields: dict, create: bool) -> None:
    """Пишет учётку туда, откуда портал её читает: лист «сотрудники» или data/users.xlsx."""
    sheet_rows = store.read_sheet(ACCOUNTS) if ACCOUNTS in store.sheet_names() else None
    if sheet_rows is not None:
        headers = [_s(h) for h in store.first_row(ACCOUNTS)]
        while headers and not headers[-1]:
            headers.pop()
        col = {h.lower(): h for h in headers if h}
        row = next((r for r in sheet_rows if _s(r.get(col.get("логин", "логин"))) == login), None)
        if row is not None or (create and "логин" in col):
            if row is None:
                row = {h: "" for h in headers}
                row[col["логин"]] = login
                sheet_rows.append(row)
            for key, value in fields.items():
                if key == "активен":
                    value = "да" if value else "нет"
                if key in col:
                    row[col[key]] = value
                if key == "роль" and "должность" in col:
                    row[col["должность"]] = perms.role_label(value)
            store.write_sheet(ACCOUNTS, headers, sheet_rows)
            return
    from server import read_table, write_table  # noqa: WPS433
    rows = read_table("users")
    row = next((r for r in rows if _s(r.get("логин")) == login), None)
    if row is None:
        row = {"логин": login, "ставка_час": 0}
        rows.append(row)
    for key, value in fields.items():
        row[key] = (1 if value else 0) if key == "активен" else value
    write_table("users", rows)


def delete_account(me: dict, body: dict) -> dict:
    """Удалить сотрудника совсем: учётка, карточка цеха и личные права.
    Сделанная им работа и зарплата за прошлое остаются в журналах (по логину)."""
    _need(me, "staff.delete")
    login = _s(body.get("логин"))
    users = _all_users()
    target = next((u for u in users if _s(u.get("логин")) == login), None)
    if target is None or not _same_company(target, _s(me.get("цех"))):
        raise ValueError("Сотрудник не найден в этом цехе")
    if _s(target.get("роль")) == perms.LOCKED_ROLE and _s(me.get("роль")) != perms.LOCKED_ROLE:
        raise perms.AccessError("Удалить администратора может только администратор")
    perms.check_role_change(me, users, target, None, False)  # не себя и не последнего админа
    if ACCOUNTS in store.sheet_names():
        headers = [_s(h) for h in store.first_row(ACCOUNTS)]
        while headers and not headers[-1]:
            headers.pop()
        key = {h.lower(): h for h in headers if h}.get("логин", "логин")
        rows = store.read_sheet(ACCOUNTS)
        left = [r for r in rows if _s(r.get(key)) != login]
        if len(left) != len(rows):
            store.write_sheet(ACCOUNTS, headers, left)
    staff = _rows(STAFF)
    left = [r for r in staff if _s(r.get("логин")) != login]
    if len(left) != len(staff):
        store.write_sheet(STAFF[0], STAFF[1], left)
    from server import read_table, write_table  # noqa: WPS433
    rows = read_table("users")
    left = [r for r in rows if _s(r.get("логин")) != login]
    if len(left) != len(rows):
        write_table("users", left)
    perms.forget_user(login)
    perms.log_event(me, "удалён", login, _s(target.get("фио")), "")
    return {"логин": login, "удалён": True}


def _stages_in_use() -> dict[str, str]:
    """Где этап уже участвует — такой нельзя удалить."""
    where: dict[str, str] = {}
    for label, sheet, col in (("маршрут", ROUTE, "этап"), ("маршрут партии", ROUTE_PARTY, "этап"),
                              ("маршрут заказа", ROUTE_ORD, "этап"), ("маршрут ГП", ROUTE_FIN, "этап"),
                              ("маршрут заказа партии", ROUTE_ORD_PARTY, "этап"),
                              ("маршрут ГП партии", ROUTE_FIN_PARTY, "этап"),
                              ("выдачи работы", OUT, "этап"), ("распределение", ASSIGN, "этап")):
        for r in _rows(sheet):
            code = _s(r.get(col)).upper()
            if code and code not in where:
                where[code] = label
    return where


def save_stage(me: dict, body: dict) -> dict:
    """Создать или изменить этап: код, название, ставка за шт, порядок."""
    code = _s(body.get("код")).upper()
    ops = _ops()
    create = code not in ops
    _need(me, "stages.create" if create else "stages.edit")
    if create and not _CODE_RE.fullmatch(code):
        raise ValueError("Код роли: 2–12 заглавных букв или цифр, например ПЕТЛЯ")
    name = _s(body.get("название")) or (ops.get(code) or {}).get("название", "")
    if not name:
        raise ValueError("Укажите название роли")
    try:
        rate = float(_s(body.get("ставка", (ops.get(code) or {}).get("ставка", 0))).replace(",", ".") or 0)
    except ValueError:
        raise ValueError("Ставка — число") from None
    if rate < 0:
        raise ValueError("Ставка не может быть отрицательной")
    order = _int(body.get("порядок"), (ops.get(code) or {}).get("порядок", 0)) \
        or max([o["порядок"] for o in ops.values()] + [0]) + 10
    rows = store.read_sheet(RATES_SHEET[0]) if RATES_SHEET[0] in store.sheet_names() else []
    row = next((r for r in rows if _s(r.get("код")).upper() == code), None)
    if row is None:
        row = {"код": code, "обязательная": "нет"}
        rows.append(row)
    row.update({"операция": name, "расценка за шт": rate, "порядок": order})
    if RATES_SHEET[0] not in store.sheet_names():
        store.ensure_sheets([(RATES_SHEET[0], RATES_SHEET[1], [10, 30, 15, 10, 13])])
    writes = [(RATES_SHEET[0], RATES_SHEET[1], rows)]
    if isinstance(body.get("по_моделям"), dict):  # цена роли по моделям — с историей по «с даты»
        by_model = {}
        for model, val in body["по_моделям"].items():
            model, raw = _s(model), _s(val).replace(",", ".")
            if not model or not raw:
                continue
            try:
                by_model[model] = float(raw)
            except ValueError:
                raise ValueError(f"Цена для модели {model} — число") from None
            if by_model[model] < 0:
                raise ValueError(f"Цена для модели {model} не может быть отрицательной")
        today = _now()[:10]
        old = _rows(RATES)
        # действующие сейчас цены этой роли: последняя строка модели по «с даты»
        current: dict[str, tuple[datetime, str]] = {}
        for r in old:
            if _s(r.get("этап")).upper() != code:
                continue
            m = _s(r.get("модель"))
            if not m:
                continue
            d = _rate_day(r.get("с даты")) or datetime(2000, 1, 1)
            if m not in current or d >= current[m][0]:  # при равной дате выигрывает нижняя строка
                current[m] = (d, _s(r.get("ставка")).replace(",", "."))
        rates_rows = list(old)  # историю не затираем — изменения добавляются новыми строками
        for m, v in by_model.items():
            cur = current.get(m)
            try:
                same = bool(cur and cur[1]) and float(cur[1]) == v
            except ValueError:
                same = False
            if same:
                continue  # цена не менялась — сохраняем исходную «с даты»
            rates_rows.append({"модель": m, "этап": code, "ставка": v, "с даты": today})
        for m, (_, raw) in current.items():
            if m not in by_model and raw:  # особую цену убрали — закрываем её с сегодняшнего дня
                rates_rows.append({"модель": m, "этап": code, "ставка": "", "с даты": today})
        writes.append((RATES[0], RATES[1], rates_rows))
    store.write_sheets(writes)
    _sync_process(code, {"название": name, "тариф": rate, "порядок": order})
    before = ops.get(code)
    perms.log_event(me, "новая роль" if create else "роль изменена", code,
                    "" if create else f"{before['название']} · {before['ставка']:g}",
                    f"{name} · {rate:g}")
    return {"код": code, "создан": create}


def toggle_stage(me: dict, body: dict) -> dict:
    """Отключить/включить этап. Отключённый доводит начатые партии, но не назначается заново."""
    _need(me, "stages.edit")
    code = _s(body.get("код")).upper()
    if code == START_STAGE:
        raise ValueError("Крой — роль «Закройщик», её не отключить")
    off = bool(body.get("отключён"))
    rows = store.read_sheet(RATES_SHEET[0])
    row = next((r for r in rows if _s(r.get("код")).upper() == code), None)
    if row is None:
        raise ValueError("Роль не найдена")
    row["отключён"] = "да" if off else ""
    store.write_sheet(RATES_SHEET[0], RATES_SHEET[1], rows)
    _sync_process(code, {"отключён": 1 if off else 0})
    perms.log_event(me, "роль отключена" if off else "роль включена", code)
    return {"код": code, "отключён": off}


def delete_stage(me: dict, body: dict) -> dict:
    _need(me, "stages.delete")
    code = _s(body.get("код")).upper()
    if code == START_STAGE:
        raise ValueError("Крой удалить нельзя")
    if code not in _ops():
        raise ValueError("Роль не найдена")
    where = _stages_in_use().get(code)
    if where:
        raise ValueError(f"Роль уже используется ({where}) — удалить нельзя, её можно отключить")
    if any(_s(u.get("роль")) == code for u in _all_users()):
        raise ValueError("Это основная роль у сотрудника — сначала смените её в его карточке")
    rows = [r for r in store.read_sheet(RATES_SHEET[0]) if _s(r.get("код")).upper() != code]
    staff = _rows(STAFF)
    for r in staff:
        codes = [_norm_role(c) for c in _deps(r.get("роли"))]
        if code in codes:
            r["роли"] = ";".join(c for c in codes if c != code)
    store.write_sheets([(RATES_SHEET[0], RATES_SHEET[1], rows), (STAFF[0], STAFF[1], staff)])
    _sync_process(code, None)
    perms.log_event(me, "роль удалена", code)
    return {"код": code, "удалён": True}


def _sync_process(code: str, fields: dict | None) -> None:
    """data/processes.xlsx — из него выгрузка склада пересобирает лист «расценки»."""
    from server import read_table, write_table  # noqa: WPS433
    rows = read_table("processes")
    row = next((r for r in rows if _s(r.get("код")).upper() == code), None)
    if fields is None:
        if row is not None:
            rows.remove(row)
            write_table("processes", rows)
        return
    if row is None:
        # активен=0: в старом учёте партий (server.chain_for) новый этап не появляется сам
        row = {"код": code, "артикул": "", "обязательный": 0, "зависимости": "", "склад_гп": 0,
               "активен": 0}
        rows.append(row)
    row.update(fields)
    write_table("processes", rows)


def _rate_day(v) -> datetime | None:
    """Дата из «с даты»: «дд.мм.гггг» или «дд.мм.гггг чч:мм»."""
    try:
        return datetime.strptime(_s(v).split(" ")[0], "%d.%m.%Y")
    except ValueError:
        return None


def model_rates(on: str = "") -> dict[str, dict[str, float]]:
    """Код роли → {модель: цена за шт} — цены, действующие на дату `on` (по умолчанию сегодня).

    Строка «Ставки артикул» действует со своей «с даты»; берётся самая поздняя
    из действующих. Пустая ставка закрывает особую цену — модель снова на общей.
    Модели без своей цены платятся по общей ставке роли."""
    day = _rate_day(on) or datetime.now()
    best: dict[tuple[str, str], tuple[datetime, str]] = {}
    for r in _rows(RATES):
        code, model = _s(r.get("этап")).upper(), _s(r.get("модель"))
        if not code or not model:
            continue
        start = _rate_day(r.get("с даты")) or datetime(2000, 1, 1)
        if start > day:
            continue  # будущая ставка ещё не действует
        key = (code, model)
        if key not in best or start >= best[key][0]:  # при равной дате выигрывает нижняя строка
            best[key] = (start, _s(r.get("ставка")))
    out: dict[str, dict[str, float]] = {}
    for (code, model), (_, raw) in best.items():
        if raw:
            out.setdefault(code, {})[model] = _num(raw)
    return out


def stage_rate(code: str, model: str = "", on: str = "") -> float:
    """Ставка этапа для модели на дату `on` («дд.мм.гггг», по умолчанию — сегодня).

    «Ставки артикул»: строка действует со своей «с даты»; берётся самая поздняя
    из действующих на дату. Пустая ставка = особая цена отменена → общая расценка."""
    if model:
        try:
            day = _rate_day(on) or datetime.now()
            best: tuple[datetime, str] | None = None
            for r in store.read_sheet("Ставки артикул"):
                if _s(r.get("модель")) != model or _s(r.get("этап")) != code:
                    continue
                start = _rate_day(r.get("с даты")) or datetime(2000, 1, 1)
                if start <= day and (best is None or start >= best[0]):
                    best = (start, _s(r.get("ставка")).replace(",", "."))
            if best is not None and best[1]:
                return float(best[1])
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
    """Настилы, принятые технологом после кроя (только они идут в работу и распределение)."""
    out = []
    for n in p.get("настилы") or []:
        if n.get("ждёт") or n.get("возврат"):
            continue
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
    boss = _can(me, "cex.work.all") and not as_worker
    my_stages = set(roles_of(me))
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
                if not boss and (who != login or code not in my_stages):
                    continue  # швея видит только свои этапы, даже если раздел закреплён за ней
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
                can = (status == "можно" and (boss or code not in locked) and (boss or who == login)
                       and code in my_stages)
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
    my_roles = roles_of(me)
    ops = _route_ops()
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
    parties = [p for p in cut_state()["партии"]  # в распределение — только принятое технологом после кроя
               if _nastils(p) and p["статус"] not in DONE_PARTY]
    parties.sort(key=_fifo_key)
    routes = party_routes(parties)
    assign = assignments()
    done, inwork, _ = _work_index()
    people = [p for p in staff_people(_s(me.get("цех"))) if p["этапы"]]
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
            raise ValueError(f"Настила {n} или операции {code} нет в партии")
        if login and login not in people:
            raise ValueError(f"Сотрудник {login} не найден в этом цехе")
        if login and code not in people[login]["этапы"]:
            raise ValueError(f"У сотрудника {people[login]['ФИО']} нет роли {code}. "
                             "Сначала выдайте ему эту роль во вкладке «Сотрудники и роли»")
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
    if code not in roles_of(me):
        raise ValueError("У вас нет этой роли — её выдают во вкладке «Сотрудники и роли»")
    if not _can(me, "cex.boss") and any(
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
    if _s(row.get("логин")) != _s(me.get("логин")) and not _can(me, "cex.boss"):
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
    writes = [(OUT[0], OUT[1], rows), (PARTIES[0], PARTIES[1], party_rows)]
    if _party_done(num, rows):
        writes += _mark_packed(num, party_rows)
    store.write_sheets(writes)
    return {"сумма": row["сумма"], "количество": qty, "статус": _s(row.get("статус"))}


def _party_done(num: str, issued: list[dict]) -> bool:
    """Партия готова к упаковке: все её настилы прошли маршрут (недокрой не держит партию)."""
    party = next((p for p in cut_state()["партии"] if p["номер"] == num), None)
    if not party or party["раскроено"] <= 0:
        return False
    stages = party_routes([party]).get(num, {}).get("этапы") or []
    done, _, _ = _work_index(issued)
    if any(n.get("ждёт") or n.get("возврат") for n in party["настилы"]):
        return False  # часть кроя ещё на приёмке — партия не готова
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
    if not _can(me, "cex.boss") and _s(row.get("логин")) != _s(me.get("логин")):
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


# -------------------------------------------- упаковано → склад (упаковка — этап маршрута)
PACK_RECEIVED = "на складе"


def _mark_packed(num: str, party_rows: list[dict]) -> list[tuple]:
    """Партия «упакован»; если упакованы все партии принятого заказа — заказ тоже «упакован»."""
    order_num = ""
    for r in party_rows:
        if _s(r.get("№ партии")) == num:
            r["статус"] = "упакован"
            order_num = _norm_size(r.get("№ заказа"))
    if not order_num or not all(_s(r.get("статус")) in DONE_PARTY for r in party_rows
                                if _norm_size(r.get("№ заказа")) == order_num):
        return []
    orders_rows = _rows(ORDERS)
    hit = [r for r in orders_rows if _norm_size(r.get("№ заказа")) == order_num and _s(r.get("статус")) == "принят"]
    for r in hit:
        r["статус"] = "упакован"
    return [(ORDERS[0], ORDERS[1], orders_rows)] if hit else []


def _route_ready() -> dict[tuple, int]:
    """(партия, цвет, размер) → штук в настилах, прошедших весь швейный маршрут (с упаковкой)."""
    parties = [p for p in cut_state()["партии"] if p["раскроено"] > 0]
    routes = party_routes(parties)
    done, _, _ = _work_index()
    out: dict[tuple, int] = {}
    for p in parties:
        stages = (routes.get(p["номер"]) or {}).get("этапы") or []
        for n in _nastils(p):
            if _nastil_complete(p["номер"], n, stages, done):
                for r in n["строки"]:
                    k = (p["номер"], r["цвет"], _norm_size(r["размер"]))
                    out[k] = out.get(k, 0) + _int(r.get("факт"))
    return out


def pack_awaiting() -> list[dict]:
    """Прошло маршрут, но ещё не принято складом: по (партия, цвет) с размерами.
    Лист «Упаковка» — журнал переданного складу (и старые упаковки с экрана упаковщика)."""
    parties = {_s(r.get("№ партии")): r for r in _rows(PARTIES)}
    out: dict[tuple, dict] = {}
    passed: dict[tuple, int] = {}

    def add(num, color, size, qty, box=""):
        p = parties.get(num, {})
        item = out.setdefault((num, color), {
            "партия": num, "заказ": _norm_size(p.get("№ заказа")), "категория": _s(p.get("категория")),
            "модель": _s(p.get("модель")), "цвет": color, "размеры": {}, "коробки": [], "штук": 0})
        item["размеры"][size] = item["размеры"].get(size, 0) + qty
        item["штук"] += qty
        if box and box not in item["коробки"]:
            item["коробки"].append(box)

    for r in _rows(PACK):
        k = (_s(r.get("партия")), _s(r.get("цвет")), _norm_size(r.get("размер")))
        passed[k] = passed.get(k, 0) + _int(r.get("количество"), 0)
        if _s(r.get("статус")) != PACK_RECEIVED:
            add(*k, _int(r.get("количество"), 0), _s(r.get("коробка")))
    for k, qty in _route_ready().items():
        if qty > passed.get(k, 0):
            add(*k, qty - passed.get(k, 0))
    return list(out.values())


def pack_received(num: str, color: str) -> int:
    """Склад принял (партия, цвет): всё ждущее → «на складе»; вся партия принята → партия «на складе»."""
    waiting = next((w for w in pack_awaiting() if w["партия"] == num and w["цвет"] == color), None)
    if not waiting:
        return 0
    rows = _rows(PACK)
    hit = 0
    for r in rows:
        if _s(r.get("партия")) == num and _s(r.get("цвет")) == color and _s(r.get("статус")) != PACK_RECEIVED:
            r["статус"] = PACK_RECEIVED
            waiting["размеры"][_norm_size(r.get("размер"))] -= _int(r.get("количество"), 0)
            hit += 1
    new_id = max([_int(r.get("id")) for r in rows] or [0])
    for size, qty in waiting["размеры"].items():  # прошло маршрут без экрана упаковщика
        if qty > 0:
            new_id += 1
            rows.append({"id": new_id, "дата": _now(), "партия": num, "цвет": color, "размер": size,
                         "коробка": "", "количество": qty, "этикеток": 0, "кто": "маршрут",
                         "статус": PACK_RECEIVED})
            hit += 1
    writes = [(PACK[0], PACK[1], rows)]
    party_rows = _rows(PARTIES)
    left = any(w["партия"] == num and w["цвет"] != color for w in pack_awaiting())
    if not left and any(_s(r.get("№ партии")) == num and _s(r.get("статус")) in ("упакован", "готово к упаковке")
                        for r in party_rows):
        order_num = ""
        for r in party_rows:
            if _s(r.get("№ партии")) == num:
                r["статус"] = PACK_RECEIVED
                order_num = _norm_size(r.get("№ заказа"))
        writes.append((PARTIES[0], PARTIES[1], party_rows))
        # склад принял все партии упакованного заказа — заказ тоже «на складе»
        if order_num and all(_s(r.get("статус")) in (PACK_RECEIVED, "отгружен", "отгружена") for r in party_rows
                             if _norm_size(r.get("№ заказа")) == order_num):
            orders_rows = _rows(ORDERS)
            hit_o = [r for r in orders_rows if _norm_size(r.get("№ заказа")) == order_num
                     and _s(r.get("статус")) == "упакован"]
            for r in hit_o:
                r["статус"] = PACK_RECEIVED
            if hit_o:
                writes.append((ORDERS[0], ORDERS[1], orders_rows))
    store.write_sheets(writes)
    return hit


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
              "accountant": "бухгалтер", "storekeeper": "складчик",
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
            "должность": role, "роли": "",
            "тип оплаты": "сдельная" if role in ("cutter", "packer") or role in production_roles() else "оклад",
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
    only_me = not _can(me, "cex.pay")

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
                                             ("cutter", "packer", *production_roles()) else "оклад")
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
            "периодичность": periodicity, "этап": ", ".join(perms.role_label(c) for c in _deps(card.get("роли"))),
            "должность": ROLE_NAMES.get(_s(card.get("должность"))) or perms.role_label(_s(card.get("должность"))),
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


def _counterparty_seed() -> list[tuple[str, str]]:
    """Кто уже встречается в данных — первое заполнение справочника контрагентов."""
    out: list[tuple[str, str]] = []
    try:
        import warehouse
        out += [(n, "Поставщики") for n in warehouse.load_master().get("suppliers", [])]
    except Exception:  # noqa: BLE001 — склад недоступен: заведут вручную
        pass
    out += [(n, "Поставщики") for n in supplier_list()]
    out += [(m["поставщик"], "Поставщики") for m in materials() if m.get("поставщик")]
    out += [(n, "Собственные компании") for n in _client_list()]
    try:
        from server import read_table  # noqa: WPS433
        out += [(_s(c.get("название")), "Собственные цеха") for c in read_table("companies")]
    except Exception:  # noqa: BLE001
        pass
    return out


def _all_suppliers() -> list[str]:
    try:
        import counterparties
        extra = counterparties.names("Поставщики")
    except Exception:  # noqa: BLE001 — база недоступна: только из заказов
        extra = []
    return sorted(set(supplier_list()) | set(extra), key=str.lower)


# ------------------------------------------------------------------- API
def _fail(ctx, message: str, code: int = 400):
    ctx["err"](message, code)


def _deny(ctx, code: str):
    ctx["err"](f"Нет права «{perms.LABELS.get(code, code)}». Его выдаёт администратор в разделе «Роли и права»", 403)


def order_cost(num: str) -> dict:
    """Калькуляция себестоимости заказа.

    Ткань: рулоны карт заказа (кг) × средняя цена кг поставок на дату заказа.
    Материалы: нормы спецификации × средняя цена поступлений на дату заказа.
    Работа: факт по выдачам (ставка хранится в момент выдачи); если выдач ещё нет —
    план по маршруту партии со ставками на дату заказа. Накладные — сом/шт из настроек.
    """
    order = next((o for o in orders() if o["номер"] == num), None)
    if not order:
        raise ValueError("Заказ не найден")
    day = _s(order.get("дата"))
    qty = _int(order.get("штук"))

    # --- ткань: рулоны, закреплённые за картами заказа
    fabric: dict[tuple, dict] = {}
    for r in _rows(CARD_ROLLS):
        if _norm_size(r.get("№ заказа")) != num or not _s(r.get("вид")):
            continue
        k = (_s(r.get("вид")), _s(r.get("цвет")))
        g = fabric.setdefault(k, {"вид": k[0], "цвет": k[1], "шт": 0, "кг": 0.0})
        g["шт"] += _int(r.get("шт"))
        g["кг"] += _num(r.get("вес кг"))
    fabric_lines = []
    fabric_sum = 0.0
    for g in sorted(fabric.values(), key=lambda x: (x["вид"], x["цвет"])):
        price, ok = price_kg(g["вид"], g["цвет"], day)
        total = round(g["кг"] * price, 2) if ok else None
        fabric_sum += total or 0
        fabric_lines.append({**g, "кг": round(g["кг"], 3), "цена_кг": price if ok else None,
                             "сумма": total, "нет_цены": not ok, "нет_веса": g["кг"] <= 0})

    # --- материалы: нормы спецификации по картам заказа
    bom, cards = boms(), pcards()
    need: dict[tuple, dict] = {}
    for card in sorted({_card_no(c["карта"]) for c in card_of(order, cards)}):
        lines, _ = supply_need(_card_rows(order, card, cards), bom)
        for n in lines:
            k = (n["материал"], n["цвет"], n["ед"])
            g = need.setdefault(k, {"материал": k[0], "цвет": k[1], "ед": k[2], "количество": 0.0})
            g["количество"] += n["нужно"]
    mat_lines = []
    mat_sum = 0.0
    for g in sorted(need.values(), key=lambda x: (x["материал"], x["цвет"])):
        price, ok = mat_price(g["материал"], g["цвет"], day)
        total = round(g["количество"] * price, 2) if ok else None
        mat_sum += total or 0
        mat_lines.append({**g, "количество": round(g["количество"], 3),
                          "цена": price if ok else None, "сумма": total, "нет_цены": not ok})

    # --- работа: факт по выдачам партий заказа; план — по маршрутам на дату заказа
    my_parties = [p for p in cut_state()["партии"] if _norm_size(p.get("заказ")) == num]
    pmodel = {p["номер"]: _s(p.get("модель")) for p in my_parties}
    pplan = {p["номер"]: _int(p.get("план")) for p in my_parties}
    routes = party_routes(my_parties) if my_parties else {}
    names = _route_ops()
    work_fact = 0.0
    fact_lines = []
    for r in _rows(OUT):
        if _s(r.get("партия")) not in pmodel or _s(r.get("статус")) != "готово":
            continue
        amount = _num(r.get("сумма"))
        work_fact += amount
        code = _s(r.get("этап"))
        fact_lines.append({"партия": _s(r.get("партия")), "этап": code,
                           "название": _s((names.get(code) or {}).get("название")) or code,
                           "шт": _int(r.get("количество")), "ставка": _num(r.get("ставка")),
                           "сумма": round(amount, 2)})
    work_plan = 0.0
    plan_lines = []
    for p in my_parties:
        pnum = p["номер"]
        stages = [{"код": START_STAGE, "название": _s((names.get(START_STAGE) or {}).get("название")) or "Раскрой"}]
        stages += (routes.get(pnum) or {}).get("этапы") or []
        for st in stages:
            rate = stage_rate(st["код"], pmodel[pnum], day)
            if st["код"] == START_STAGE and not rate:
                rate = rate_of(START_STAGE, 15.0)  # как при раскрое
            amount = round(rate * pplan[pnum], 2)
            work_plan += amount
            plan_lines.append({"партия": pnum, "этап": st["код"],
                               "название": _s(st.get("название")) or st["код"],
                               "шт": pplan[pnum], "ставка": rate, "сумма": amount})

    # --- накладные (работа склада, окладники): сом на штуку из настроек книги
    per_piece = cex_setting("накладные сом/шт")
    overhead = round(per_piece * qty, 2)

    work_total = round(work_fact if work_fact > 0 else work_plan, 2)
    total = round(fabric_sum + mat_sum + work_total + overhead, 2)
    incomplete = (any(l["нет_цены"] or l["нет_веса"] for l in fabric_lines)
                  or any(l["нет_цены"] for l in mat_lines))
    return {
        "заказ": num, "дата": day, "клиент": order["клиент"], "штук": qty,
        "модели": sorted({_s(p["модель"]) for p in order["позиции"] if _s(p["модель"])}),
        "ткань": {"строки": fabric_lines, "сумма": round(fabric_sum, 2)},
        "материалы": {"строки": mat_lines, "сумма": round(mat_sum, 2)},
        "работа": {"факт": round(work_fact, 2), "план": round(work_plan, 2),
                   "использован": "факт" if work_fact > 0 else "план",
                   "по_факту": fact_lines, "по_плану": plan_lines},
        "накладные": {"сом_шт": per_piece, "сумма": overhead},
        "итого": total,
        "за_шт": round(total / qty, 2) if qty else None,
        "неполная": incomplete,
    }


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
    if not _can(me, "cex.view"):
        _deny(ctx, "cex.view")
        return

    if path == "/api/cex/bootstrap" and method == "GET":
        ensure_sheets()
        seed_refs()
        data = {
            "user": {"логин": _s(me.get("логин")), "фио": _s(me.get("фио")), "роль": role,
                     "роли": perms.roles_of(me), "роли_названия": perms.all_roles(),
                     "производственные": roles_of(me),
                     "цех": _s(me.get("цех"))},
            "права": {"создать": _can(me, "cex.create"), "принимать": _can(me, "cex.tech"),
                      "кроить": _can(me, "cex.cut"), "работать": _can_work(me),
                      "зарплата": _can(me, "cex.pay"),
                      "маршрут": _can(me, "cex.routes"), "вся_работа": _can(me, "cex.work.all"),
                      "чужая_работа": _can(me, "cex.boss"),
                      "карта": _can(me, "cex.design"), "снабжение": _can(me, "cex.supply"),
                      "сотрудники": _can(me, "staff.view"),
                      "этапы": any(_can(me, c) for c in ("stages.create", "stages.edit",
                                                         "stages.delete", "stages.assign")),
                      "права": _can(me, "perms.roles") or _can(me, "perms.users")},
            "все_права": perms.effective(me),
            "refs": refs(),
            "заказы": orders() if set(perms.roles_of(me)) & {"admin", "manager", "technologist", "accountant",
                                                             "storekeeper", "cutter", "designer", "supply"} else [],
            "клиенты": _client_list(),
            "поставщики": _all_suppliers(),
            "источник": str(store.source_path()),
        }
        _ok(ctx, data)
        return

    if path == "/api/cex/orders" and method == "GET":
        ensure_sheets()
        _ok(ctx, {"заказы": orders()})
        return

    if path == "/api/cex/stock" and method == "GET":  # «Новый заказ»: склад по модели — только смотреть
        if not _can(me, "cex.create"):
            _deny(ctx, "cex.create")
            return
        _ok(ctx, model_stock(_s(((ctx.get("query") or {}).get("модель") or [""])[0])))
        return

    if path == "/api/cex/orders" and method == "POST":
        if not _can(me, "cex.create"):
            _deny(ctx, "cex.create")
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
                "срок": due, "статус": DESIGN if source == OWN else AT_SUPPLIER,
                "создал": _s(me.get("логин")), "№ партии": "", "комментарий": comment,
            } for p in prepared]
            store.append_rows(ORDERS[0], ORDERS[1], rows)
        _ok(ctx, {"номер": num, "дата": now, "статус": DESIGN if source == OWN else AT_SUPPLIER})
        return

    if path.startswith("/api/cex/orders/") and path.endswith("/cost") and method == "GET":
        if not (_can(me, "cex.pay") or _can(me, "cex.boss")):
            _deny(ctx, "cex.pay")
            return
        ensure_sheets()
        num = path[len("/api/cex/orders/"):-len("/cost")]
        try:
            _ok(ctx, order_cost(num))
        except ValueError as exc:
            _fail(ctx, str(exc), 404)
        return

    if path == "/api/cex/supplies" and method == "GET":
        if not (_can(me, "cex.supply") or _can(me, "cex.pay")):
            _deny(ctx, "cex.supply")
            return
        ensure_sheets()
        _ok(ctx, {"поставки": supplies()})
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
        tq = queue()
        sup = {}
        for r in _rows(SUPPLY_SH):
            sup.setdefault(_norm_size(r.get("№ заказа")), []).append(
                {"карта": _card_no(r.get("карта")),
                 "материал": _s(r.get("материал")), "цвет": _s(r.get("цвет")), "ед": _s(r.get("ед.")),
                 "нужно": _num(r.get("нужно")), "есть": _num(r.get("есть")),
                 "статус": _s(r.get("статус")), "комментарий": _s(r.get("комментарий"))})
        _ok(ctx, {
            "очередь": tq,
            "сырьё": {o["номер"]: sup.get(o["номер"], []) for o in tq},
            "история": card_history(o["номер"] for o in tq),
            "отклонённые": rejected,
            "крой": cut_review(),
            "статистика": staff_stats(),
            "журнал": list(reversed(decisions()[-30:])),
        })
        return

    if path == "/api/cex/tech/decision" and method == "POST":
        if not _can(me, "cex.tech"):
            _deny(ctx, "cex.tech")
            return
        ensure_sheets()
        try:
            result = apply_decision(me, ctx["body"]())
        except ValueError as exc:
            _fail(ctx, str(exc))
            return
        _ok(ctx, result)
        return

    flow_get = {"/api/cex/design": "cex.design", "/api/cex/supply": "cex.supply"}
    if path in flow_get and method == "GET":
        if not _can(me, flow_get[path]):
            _deny(ctx, flow_get[path])
            return
        ensure_sheets()
        if path == "/api/cex/design":
            cards = pcards()
            q = [o for o in orders() if DESIGN in o["карты"].values() and o["статус"] != "отклонён"]
            for o in q:
                o["карта"] = card_of(o, cards)
                o["карта_сохранена"] = o["номер"] in cards
            rolls = card_rolls()
            for o in q:
                o["рулоны"] = [{"карта": c, **r} for (n, c), lst in rolls.items() if n == o["номер"] for r in lst]
            _ok(ctx, {"очередь": q, "история": card_history(o["номер"] for o in q), "виды_рулонов": roll_kinds(),
                      "рулоны_склад": rolls_in_stock()})
        else:
            _ok(ctx, supply_state())
        return

    if path in ("/api/cex/nom/counterparties", "/api/cex/nom/counterparty"):
        if not _can(me, "cex.supply"):
            _deny(ctx, "cex.supply")
            return
        import counterparties
        try:
            if method == "POST":
                _ok(ctx, counterparties.save(_s(me.get("фио")) or _s(me.get("логин")), ctx["body"]()))
            else:
                _ok(ctx, {"категории": counterparties.CATEGORIES,
                          "контрагенты": counterparties.list_all(_counterparty_seed())})
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    flow_post = {"/api/cex/design": ("cex.design", save_design),
                 "/api/cex/supply": ("cex.supply", save_supply),
                 "/api/cex/supply/bom": ("cex.supply", save_bom),
                 "/api/cex/supply/roll": ("cex.supply", add_roll),
                 "/api/cex/supplies": ("cex.supply", add_supply),
                 "/api/cex/supply/material": ("cex.supply", save_material),
                 "/api/cex/nom/product": ("cex.supply", save_product),
                 "/api/cex/supply/move": ("cex.supply", add_move),
                 "/api/cex/supply/move/delete": ("cex.supply", delete_move),
                 "/api/cex/supply/rename": ("cex.supply", rename_material),
                 "/api/cex/supply/roll/delete": ("cex.supply", delete_roll)}
    if path in flow_post and method == "POST":
        code, fn = flow_post[path]
        if not _can(me, code):
            _deny(ctx, code)
            return
        ensure_sheets()
        try:
            with ORDER_LOCK:
                _ok(ctx, fn(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
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
        if not _can(me, "cex.pay"):
            _deny(ctx, "cex.pay")
            return
        ensure_sheets()
        try:
            _ok(ctx, close_payroll(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/staff/card" and method == "POST":
        if not _can(me, "cex.pay"):
            _deny(ctx, "cex.pay")
            return
        ensure_sheets()
        try:
            _ok(ctx, update_card(me, ctx["body"]()))
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
        if not _can(me, "cex.tech"):
            _deny(ctx, "cex.tech")
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
        if not _can_work(me):
            _deny(ctx, "cex.work")
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

    if path == "/api/cex/cut/party" and method == "POST":
        if not _can(me, "cex.cut"):
            _deny(ctx, "cex.cut")
            return
        ensure_sheets()
        try:
            with ORDER_LOCK:
                _ok(ctx, create_party(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/tech/cut" and method == "POST":  # приёмка кроя технологом
        if not _can(me, "cex.tech"):
            _deny(ctx, "cex.tech")
            return
        ensure_sheets()
        try:
            _ok(ctx, review_cut(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/cut/resubmit" and method == "POST":  # закройщик исправил возвращённое
        if not _can(me, "cex.cut"):
            _deny(ctx, "cex.cut")
            return
        ensure_sheets()
        try:
            _ok(ctx, resubmit_cut(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/cut/card" and method == "POST":
        if not _can(me, "cex.cut"):
            _deny(ctx, "cex.cut")
            return
        ensure_sheets()
        try:
            _ok(ctx, save_card(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/cut" and method == "POST":
        if not _can(me, "cex.cut"):
            _deny(ctx, "cex.cut")
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
        try:
            kind = _kind(((ctx.get("query") or {}).get("вид") or [""])[0])
        except ValueError as exc:
            _fail(ctx, str(exc))
            return
        _ok(ctx, routes_state(me, kind))
        return

    if path in ("/api/cex/routes/save", "/api/cex/routes/delete", "/api/cex/routes/bind") \
            and method == "POST":
        if not _can(me, "cex.routes"):
            _deny(ctx, "cex.routes")
            return
        ensure_sheets()
        fn = {"/api/cex/routes/save": save_route, "/api/cex/routes/delete": delete_route,
              "/api/cex/routes/bind": bind_route}[path]
        try:
            _ok(ctx, fn(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/routes/step" and method == "POST":
        ensure_sheets()
        try:
            _ok(ctx, mark_order_step(me, ctx["body"]()))
        except perms.AccessError as exc:
            _fail(ctx, str(exc), 403)
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/staff/roles" and method == "POST":
        if not _can(me, "stages.assign"):
            _deny(ctx, "stages.assign")
            return
        ensure_sheets()
        try:
            _ok(ctx, set_roles(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/assign" and method == "GET":
        if not _can(me, "cex.tech"):
            _deny(ctx, "cex.tech")
            return
        ensure_sheets()
        _ok(ctx, assign_state(me))
        return

    if path == "/api/cex/cut/fix" and method == "POST":
        if not _can(me, "cex.tech"):
            _deny(ctx, "cex.tech")
            return
        ensure_sheets()
        try:
            _ok(ctx, fix_cut(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/assign" and method == "POST":
        if not _can(me, "cex.tech"):
            _deny(ctx, "cex.tech")
            return
        ensure_sheets()
        try:
            _ok(ctx, save_assign(me, ctx["body"]()))
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/access" and method == "GET":
        if not (_can(me, "staff.view") or _can(me, "perms.roles") or _can(me, "perms.users")
                or any(_can(me, c) for c in ("stages.create", "stages.edit", "stages.delete",
                                             "stages.assign"))):
            _deny(ctx, "staff.view")
            return
        ensure_sheets()
        _ok(ctx, access_state(me))
        return

    access_post = {"/api/cex/access/role": set_role_perm, "/api/cex/access/user": set_user_perm,
                   "/api/cex/access/account": save_account, "/api/cex/access/stage": save_stage,
                   "/api/cex/access/account/delete": delete_account,
                   "/api/cex/access/stage/delete": delete_stage,
                   "/api/cex/access/stage/toggle": toggle_stage,
                   "/api/cex/access/roles": set_roles,
                   "/api/cex/access/role/save": save_role, "/api/cex/access/role/delete": delete_role}
    if path in access_post and method == "POST":
        ensure_sheets()
        try:
            _ok(ctx, access_post[path](me, ctx["body"]()))
        except perms.AccessError as exc:
            _fail(ctx, str(exc), 403)
        except ValueError as exc:
            _fail(ctx, str(exc))
        return

    if path == "/api/cex/parties" and method == "GET":
        ensure_sheets()
        _ok(ctx, {"партии": parties()})
        return

    _fail(ctx, "неизвестный запрос", 404)

# ------------------------------------------------- перенос на единую систему ролей
OLD_SEW = ("user", "швея")  # прежняя роль «Швея» (код и подпись в Excel)
VIRTUAL_STARTS = {START_STAGE} | {k["старт"] for k in KINDS.values()}


def _old_seamstresses() -> list[str]:
    """Логины с прежней ролью «Швея»: лист «сотрудники» и запасной users.xlsx."""
    out, in_sheet = [], set()
    if ACCOUNTS in store.sheet_names():
        for r in store.read_sheet(ACCOUNTS):
            in_sheet.add(_s(r.get("логин")))
            if _s(r.get("роль")).lower() in OLD_SEW and _s(r.get("логин")):
                out.append(_s(r.get("логин")))
    try:
        from server import read_table  # noqa: WPS433
        for r in read_table("users"):  # запасной файл — только для тех, кого нет в листе
            login = _s(r.get("логин"))
            if _s(r.get("роль")).lower() in OLD_SEW and login and login not in in_sheet and login not in out:
                out.append(login)
    except Exception:  # noqa: BLE001
        pass
    return out


def migrate_roles(assign: dict | None = None, dry: bool = False) -> dict:
    """Этапы → производственные роли, «Швея» → её производственные роли, все роли человека —
    в «Сотрудники цеха».роли. Повторный запуск ничего не меняет.
    assign: логин → [коды ролей] для «Швей», у которых не было ни одного этапа."""
    assign = {k: [_norm_role(c) for c in v] for k, v in (assign or {}).items()}
    if not dry:
        ensure_sheets()
    report: dict = {"швеи": {}, "без_ролей": [], "новые_роли": [], "доп_роли": {}, "права_швеи": []}
    ops = _ops()
    # 1. коды из маршрутов и истории, которых нет в «расценках», становятся ролями (история не теряется)
    used = set()
    for spec in (ROUTE, ROUTE_PARTY, ROUTE_ORD, ROUTE_ORD_PARTY, ROUTE_FIN, ROUTE_FIN_PARTY, OUT, ASSIGN):
        used |= {_s(r.get("этап")).upper() for r in _rows(spec) if _s(r.get("этап"))}
    report["новые_роли"] = sorted(c for c in used - set(ops) - VIRTUAL_STARTS)
    prod = set(production_roles()) | set(report["новые_роли"])

    staff = _rows(STAFF)  # «этап» читается как «роли»
    by_login = {_s(r.get("логин")): r for r in staff if _s(r.get("логин"))}
    raw = {}
    try:
        raw = json.loads(perms.FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raw = {}
    extras_json = {k: [x for x in v if x not in OLD_SEW and x != perms.LOCKED_ROLE]
                   for k, v in (raw.get("доп_роли") or {}).items()}
    users = {_s(u.get("логин")): u for u in _all_users()}

    def roles_in_row(login):
        return [_norm_role(c) for c in _deps((by_login.get(login) or {}).get("роли"))]

    # 2. «Швея» → основная роль = первая её производственная роль
    mains = {}
    for login in _old_seamstresses():
        mine = [c for c in roles_in_row(login) + assign.get(login, []) if c in prod]
        if not mine:
            report["без_ролей"].append(login)
            continue
        mains[login] = mine[0]
        report["швеи"][login] = mine
    if report["без_ролей"] or dry:
        report["готово"] = False
        return report

    # 3. все роли человека — в одной колонке «роли»
    for login in set(extras_json) | set(assign) | set(by_login):
        row = by_login.get(login)
        if row is None:
            u = users.get(login) or {}
            row = {"логин": login, "ФИО": _s(u.get("фио")) or login, "должность": _s(u.get("роль")),
                   "роли": "", "тип оплаты": "сдельная", "ставка": 0, "периодичность": "месяц",
                   "модели": "", "телефон": "", "активен": 1}
            staff.append(row)
            by_login[login] = row
        main = mains.get(login) or _s((users.get(login) or {}).get("роль"))
        merged = []
        for c in roles_in_row(login) + extras_json.get(login, []) + assign.get(login, []):
            if c and c != main and c not in OLD_SEW and c not in merged:
                merged.append(c)
        if merged != roles_in_row(login):
            report["доп_роли"][login] = merged
        row["роли"] = ";".join(merged)
        if login in mains:
            row["должность"] = mains[login]

    rate_rows = store.read_sheet(RATES_SHEET[0]) if RATES_SHEET[0] in store.sheet_names() else []
    for c in report["новые_роли"]:
        rate_rows.append({"код": c, "операция": c, "расценка за шт": 0, "порядок": 900, "обязательная": "нет"})
    store.write_sheets([(STAFF[0], STAFF[1], staff)]
                       + ([(RATES_SHEET[0], RATES_SHEET[1], rate_rows)] if report["новые_роли"] else []))
    for c in report["новые_роли"]:
        _sync_process(c, {"название": c, "тариф": 0, "порядок": 900})
    for login, main in mains.items():
        _write_account(login, {"роль": main}, create=False)

    # 4. права прежней роли «Швея» переходят ко всем производственным ролям; доп. роли — уже в листе
    roles_cfg = dict(raw.get("роли") or {})
    sew = roles_cfg.pop("user", None) or {}
    for c in prod:
        for code, val in sew.items():
            roles_cfg.setdefault(c, {}).setdefault(code, val)
    report["права_швеи"] = sorted(sew)
    if sew or "доп_роли" in raw:
        perms._save({"роли": roles_cfg, "сотрудники": dict(raw.get("сотрудники") or {})})
    report["готово"] = True
    return report



register_role_sources()
