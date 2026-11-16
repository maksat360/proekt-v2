# -*- coding: utf-8 -*-
"""Цех: разбор HTTP-запросов /api/cex/… (dispatch) — права и вызов функций цеха.

Вынесено из cex_api.py. Общие данные и функции цеха — через cex_api (C.…):
так подмены в тестах и вызовы из других разделов идут через один модуль.
Импортировать этот модуль напрямую не нужно: cex_api сам отдаёт его функции."""
from __future__ import annotations

import re
from datetime import datetime
import perms
from cex_labels import labels_state, generate_labels, item_labels_print, labels_data
from cex_payroll import payroll_data, close_payroll, update_card
from cex_summary import summary

import cex_api as C


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
    order = next((o for o in C.orders() if o["номер"] == num), None)
    if not order:
        raise ValueError("Заказ не найден")
    day = C._s(order.get("дата"))
    qty = C._int(order.get("штук"))

    # --- ткань: рулоны, закреплённые за картами заказа
    fabric: dict[tuple, dict] = {}
    for r in C._rows(C.CARD_ROLLS):
        if C._norm_size(r.get("№ заказа")) != num or not C._s(r.get("вид")):
            continue
        k = (C._s(r.get("вид")), C._s(r.get("цвет")))
        g = fabric.setdefault(k, {"вид": k[0], "цвет": k[1], "шт": 0, "кг": 0.0})
        g["шт"] += C._int(r.get("шт"))
        g["кг"] += C._num(r.get("вес кг"))
    # остаток рулонов, который закройщик сдал после кроя (кг): вычитаем из выданного — в цене только ушедшее в крой
    back_kg: dict[str, float] = {}
    for m in C.moves():
        if m["документ"] == "возврат из кроя" and m["заказ"] == num:
            kg = m.get("вес") or (m["количество"] if C._s(m.get("ед")).lower() == "кг" else 0)
            if kg > 0:
                back_kg[C._s(m.get("цвет")).lower()] = back_kg.get(C._s(m.get("цвет")).lower(), 0) + kg
    left_kg = 0.0
    for color, kg in back_kg.items():
        same = [g for g in fabric.values() if g["цвет"].lower() == color and g["кг"] > 0]
        if same:
            for g in same:
                take = min(g["кг"], kg * g["кг"] / sum(x["кг"] for x in same))
                g["возврат_кг"] = g.get("возврат_кг", 0) + take
        else:
            left_kg += kg  # цвет остатка не указан или не совпал — делим на все рулоны по весу
    issued = sum(g["кг"] for g in fabric.values())
    for g in fabric.values():
        if left_kg and issued:
            g["возврат_кг"] = g.get("возврат_кг", 0) + left_kg * g["кг"] / issued
        g["выдано_кг"] = g["кг"]
        g["кг"] = max(0.0, g["кг"] - g.get("возврат_кг", 0))
    fabric_lines = []
    fabric_sum = 0.0
    for g in sorted(fabric.values(), key=lambda x: (x["вид"], x["цвет"])):
        g["возврат_кг"] = round(g.get("возврат_кг", 0), 3)
        price, ok = C.price_kg(g["вид"], g["цвет"], day)
        total = round(g["кг"] * price, 2) if ok else None
        fabric_sum += total or 0
        fabric_lines.append({**g, "кг": round(g["кг"], 3), "цена_кг": price if ok else None,
                             "сумма": total, "нет_цены": not ok, "нет_веса": g["кг"] <= 0})

    # --- материалы: нормы спецификации по картам заказа
    bom, cards = C.boms(), C.pcards()
    need: dict[tuple, dict] = {}
    for card in sorted({C._card_no(c["карта"]) for c in C.card_of(order, cards)}):
        lines, _ = C.supply_need(C._card_rows(order, card, cards), bom)
        for n in lines:
            k = (n["материал"], n["цвет"], n["ед"])
            g = need.setdefault(k, {"материал": k[0], "цвет": k[1], "ед": k[2], "количество": 0.0})
            g["количество"] += n["нужно"]
    mat_lines = []
    mat_sum = 0.0
    for g in sorted(need.values(), key=lambda x: (x["материал"], x["цвет"])):
        price, ok = C.mat_price(g["материал"], g["цвет"], day)
        total = round(g["количество"] * price, 2) if ok else None
        mat_sum += total or 0
        mat_lines.append({**g, "количество": round(g["количество"], 3),
                          "цена": price if ok else None, "сумма": total, "нет_цены": not ok})

    # --- работа: факт по выдачам партий заказа; план — по маршрутам на дату заказа
    my_parties = [p for p in C.cut_state()["партии"] if C._norm_size(p.get("заказ")) == num]
    pmodel = {p["номер"]: C._s(p.get("модель")) for p in my_parties}
    pplan = {p["номер"]: C._int(p.get("план")) for p in my_parties}
    routes = C.party_routes(my_parties) if my_parties else {}
    names = C._route_ops()
    work_fact = 0.0
    fact_lines = []
    for r in C._rows(C.OUT):
        if C._s(r.get("партия")) not in pmodel or C._s(r.get("статус")) != "готово":
            continue
        amount = C._num(r.get("сумма"))
        work_fact += amount
        code = C._s(r.get("этап"))
        fact_lines.append({"партия": C._s(r.get("партия")), "этап": code,
                           "название": C._s((names.get(code) or {}).get("название")) or code,
                           "шт": C._int(r.get("количество")), "ставка": C._num(r.get("ставка")),
                           "сумма": round(amount, 2)})
    work_plan = 0.0
    plan_lines = []
    for p in my_parties:
        pnum = p["номер"]
        stages = [{"код": C.START_STAGE, "название": C._s((names.get(C.START_STAGE) or {}).get("название")) or "Раскрой"}]
        stages += (routes.get(pnum) or {}).get("этапы") or []
        for st in stages:
            rate = C.stage_rate(st["код"], pmodel[pnum], day)
            if st["код"] == C.START_STAGE and not rate:
                rate = C.rate_of(C.START_STAGE, 15.0)  # как при раскрое
            amount = round(rate * pplan[pnum], 2)
            work_plan += amount
            plan_lines.append({"партия": pnum, "этап": st["код"],
                               "название": C._s(st.get("название")) or st["код"],
                               "шт": pplan[pnum], "ставка": rate, "сумма": amount})

    # --- накладные (работа склада, окладники): сом на штуку из настроек книги
    per_piece = C.cex_setting("накладные сом/шт")
    overhead = round(per_piece * qty, 2)

    work_total = round(work_fact if work_fact > 0 else work_plan, 2)
    total = round(fabric_sum + mat_sum + work_total + overhead, 2)

    # --- по размерам: ткань делим по штукам × % расхода размера, остальное — поровну на штуку
    pct = C.fabric_pct()
    pieces: dict[tuple, int] = {}
    for r in C._rows(C.CUT):  # факт кроя; пока не кроили — по карте заказа
        pnum = C._s(r.get("№ партии"))
        if pnum in pmodel and C._s(r.get("приёмка")) != C.RETURNED:
            k = (pmodel[pnum], C._norm_size(r.get("размер")))
            pieces[k] = pieces.get(k, 0) + C._int(r.get("факт шт"))
    if not pieces:
        for c in C.card_of(order, cards):
            k = (C._s(c["модель"]), C._norm_size(c["размер"]))
            pieces[k] = pieces.get(k, 0) + C._int(c["итог"])
    pieces = {k: v for k, v in pieces.items() if v > 0}
    weight = {k: v * pct.get(k[0], {}).get(k[1], 100) / 100 for k, v in pieces.items()}
    wsum, psum = sum(weight.values()), sum(pieces.values())
    rest_pc = (total - fabric_sum) / psum if psum else 0
    fabric_kg = sum(l["кг"] for l in fabric_lines)
    by_size = []
    for k in sorted(pieces, key=lambda k: (k[0], C._size_key(k[1]))):
        share = weight[k] / wsum if wsum else 0
        fab = fabric_sum * share
        by_size.append({"модель": k[0], "размер": k[1], "шт": pieces[k],
                        "процент": pct.get(k[0], {}).get(k[1], 100),
                        "ткань_кг": round(fabric_kg * share / pieces[k], 3),
                        "ткань_сом": round(fab / pieces[k], 2),
                        "за_шт": round(fab / pieces[k] + rest_pc, 2)})
    incomplete = (any(l["нет_цены"] or l["нет_веса"] for l in fabric_lines)
                  or any(l["нет_цены"] for l in mat_lines))
    return {
        "заказ": num, "дата": day, "клиент": order["клиент"], "штук": qty,
        "модели": sorted({C._s(p["модель"]) for p in order["позиции"] if C._s(p["модель"])}),
        "ткань": {"строки": fabric_lines, "сумма": round(fabric_sum, 2)},
        "материалы": {"строки": mat_lines, "сумма": round(mat_sum, 2)},
        "работа": {"факт": round(work_fact, 2), "план": round(work_plan, 2),
                   "использован": "факт" if work_fact > 0 else "план",
                   "по_факту": fact_lines, "по_плану": plan_lines},
        "накладные": {"сом_шт": per_piece, "сумма": overhead},
        "итого": total,
        "за_шт": round(total / qty, 2) if qty else None,
        "по_размерам": by_size,
        "неполная": incomplete,
    }


def _ok(ctx, data):
    ctx["json"]({"ok": True, "data": data})


def dispatch(ctx) -> None:
    try:
        C._dispatch(ctx)
    except C.store.CexLocked as exc:
        ctx["err"](str(exc), 409)
    except C.store.CexSourceError as exc:
        ctx["err"](f"Книга цеха недоступна: {exc}", 503)
    except KeyError as exc:
        ctx["err"](f"В книге не хватает листа: {exc}", 500)


def _dispatch(ctx) -> None:
    me = ctx.get("me")
    method = ctx["method"]
    path = ctx["path"]

    if not me:
        C._fail(ctx, "Нужно войти заново", 401)
        return
    role = C._s(me.get("роль"))
    if not C._can(me, "cex.view"):
        C._deny(ctx, "cex.view")
        return

    if path == "/api/cex/bootstrap" and method == "GET":
        C.ensure_sheets()
        C.seed_refs()
        data = {
            "user": {"логин": C._s(me.get("логин")), "фио": C._s(me.get("фио")), "роль": role,
                     "роли": perms.roles_of(me), "роли_названия": perms.all_roles(),
                     "производственные": C.roles_of(me),
                     "цех": C._s(me.get("цех"))},
            "права": {"создать": C._can(me, "cex.create"), "принимать": C._can(me, "cex.tech"),
                      "кроить": C._can(me, "cex.cut"), "работать": C._can_work(me),
                      "зарплата": C._can(me, "cex.pay"),
                      "маршрут": C._can(me, "cex.routes"), "вся_работа": C._can(me, "cex.work.all"),
                      "чужая_работа": C._can(me, "cex.boss"),
                      "карта": C._can(me, "cex.design"), "снабжение": C._can(me, "cex.supply"),
                      "сотрудники": C._can(me, "staff.view"),
                      "этапы": any(C._can(me, c) for c in ("stages.create", "stages.edit",
                                                         "stages.delete", "stages.assign")),
                      "права": C._can(me, "perms.roles") or C._can(me, "perms.users")},
            "все_права": perms.effective(me),
            "refs": C.refs(),
            "заказы": C.orders() if set(perms.roles_of(me)) & {"admin", "manager", "technologist", "accountant",
                                                             "storekeeper", "cutter", "designer", "supply"} else [],
            "клиенты": C._client_list(),
            "поставщики": C._all_suppliers(),
            "источник": "база данных",
        }
        C._ok(ctx, data)
        return

    if path == "/api/cex/orders" and method == "GET":
        C.ensure_sheets()
        C._ok(ctx, {"заказы": C.orders()})
        return

    if path == "/api/cex/stock" and method == "GET":  # «Новый заказ»: склад по модели — только смотреть
        if not C._can(me, "cex.create"):
            C._deny(ctx, "cex.create")
            return
        C._ok(ctx, C.model_stock(C._s(((ctx.get("query") or {}).get("модель") or [""])[0])))
        return

    if path == "/api/cex/production" and method == "GET":  # «Новый заказ»: сколько уже шьётся по модели
        if not C._can(me, "cex.create"):
            C._deny(ctx, "cex.create")
            return
        C._ok(ctx, C.model_production(C._s(((ctx.get("query") or {}).get("модель") or [""])[0])))
        return

    if path == "/api/cex/orders" and method == "POST":
        if not C._can(me, "cex.create"):
            C._deny(ctx, "cex.create")
            return
        body = ctx["body"]()
        items = body.get("позиции") or []
        if not isinstance(items, list) or not items:
            C._fail(ctx, "Добавьте хотя бы одну позицию")
            return
        if len(items) > 300:
            C._fail(ctx, "Слишком много позиций в одном заказе")
            return
        source = C._s(body.get("источник")) or C.OWN
        if source not in (C.OWN, C.SUPPLIER):
            C._fail(ctx, "Укажите, от кого заказываем: свой цех или поставщик")
            return
        supplier = C._s(body.get("поставщик")) if source == C.SUPPLIER else ""
        if source == C.SUPPLIER and not supplier:
            C._fail(ctx, "Укажите поставщика или надомника")
            return
        client = supplier or "Свой цех"
        prepared = []
        for it in items:
            qty = C._int(it.get("количество"), 0)
            if qty <= 0:
                C._fail(ctx, "Количество должно быть больше нуля")
                return
            if not C._s(it.get("модель")) or not C._s(it.get("цвет")):
                C._fail(ctx, "В позиции не хватает модели или цвета")
                return
            prepared.append({
                "категория": C._s(it.get("категория")),
                "модель": C._s(it.get("модель")),
                "цвет": C._s(it.get("цвет")),
                "размер": C._norm_size(it.get("размер")),
                "количество": qty,
            })
        C.ensure_sheets()
        with C.ORDER_LOCK:
            num = C.next_number()
            now = datetime.now().strftime("%d.%m.%Y %H:%M")
            due = C._s(body.get("срок"))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                due = datetime.strptime(due, "%Y-%m-%d").strftime("%d.%m.%Y")
            comment = C._s(body.get("комментарий"))
            rows = [{
                "№ заказа": num, "дата": now, "клиент": client,
                "источник": source, "поставщик": supplier,
                "категория": p["категория"], "модель": p["модель"], "цвет": p["цвет"],
                "размер": p["размер"], "количество": p["количество"],
                "срок": due, "статус": C.DESIGN if source == C.OWN else C.AT_SUPPLIER,
                "создал": C._s(me.get("логин")), "№ партии": "", "комментарий": comment,
            } for p in prepared]
            C.store.append_rows(C.ORDERS[0], C.ORDERS[1], rows)
        C._ok(ctx, {"номер": num, "дата": now, "статус": C.DESIGN if source == C.OWN else C.AT_SUPPLIER})
        return

    if path.startswith("/api/cex/orders/") and path.endswith("/cost") and method == "GET":
        if not (C._can(me, "cex.pay") or C._can(me, "cex.boss")):
            C._deny(ctx, "cex.pay")
            return
        C.ensure_sheets()
        num = path[len("/api/cex/orders/"):-len("/cost")]
        try:
            C._ok(ctx, C.order_cost(num))
        except ValueError as exc:
            C._fail(ctx, str(exc), 404)
        return

    if path == "/api/cex/supplies" and method == "GET":
        if not (C._can(me, "cex.supply") or C._can(me, "cex.pay")):
            C._deny(ctx, "cex.supply")
            return
        C.ensure_sheets()
        C._ok(ctx, {"поставки": C.supplies()})
        return

    if path.startswith("/api/cex/orders/") and method == "GET":
        num = path.rsplit("/", 1)[-1]
        for o in C.orders():
            if o["номер"] == num:
                C._ok(ctx, o)
                return
        C._fail(ctx, "Заказ не найден", 404)
        return

    if path == "/api/cex/tech" and method == "GET":
        C.ensure_sheets()
        all_orders = C.orders()
        log = C.decisions()
        reasons = {}
        for row in log:
            if C._s(row.get("решение")) == "отклонён":
                reasons[C._s(row.get("№ заказа"))] = C._s(row.get("причина"))
        rejected = []
        for o in all_orders:
            if o["статус"] == "отклонён":
                o["причина"] = reasons.get(o["номер"], "")
                rejected.append(o)
        tq = C.queue()
        sup = {}
        for r in C._rows(C.SUPPLY_SH):
            sup.setdefault(C._norm_size(r.get("№ заказа")), []).append(
                {"карта": C._card_no(r.get("карта")),
                 "материал": C._s(r.get("материал")), "цвет": C._s(r.get("цвет")), "ед": C._s(r.get("ед.")),
                 "нужно": C._num(r.get("нужно")), "есть": C._num(r.get("есть")),
                 "статус": C._s(r.get("статус")), "комментарий": C._s(r.get("комментарий"))})
        C._ok(ctx, {
            "очередь": tq,
            "сырьё": {o["номер"]: sup.get(o["номер"], []) for o in tq},
            "история": C.card_history(o["номер"] for o in tq),
            "отклонённые": rejected,
            "крой": C.cut_review(),
            "статистика": C.staff_stats(),
            "журнал": list(reversed(C.decisions()[-30:])),
        })
        return

    if path == "/api/cex/tech/decision" and method == "POST":
        if not C._can(me, "cex.tech"):
            C._deny(ctx, "cex.tech")
            return
        C.ensure_sheets()
        try:
            result = C.apply_decision(me, ctx["body"]())
        except ValueError as exc:
            C._fail(ctx, str(exc))
            return
        C._ok(ctx, result)
        return

    flow_get = {"/api/cex/design": "cex.design", "/api/cex/supply": "cex.supply"}
    if path in flow_get and method == "GET":
        if not C._can(me, flow_get[path]):
            C._deny(ctx, flow_get[path])
            return
        C.ensure_sheets()
        if path == "/api/cex/design":
            cards = C.pcards()
            q = [o for o in C.orders() if C.DESIGN in o["карты"].values() and o["статус"] != "отклонён"]
            for o in q:
                o["карта"] = C.card_of(o, cards)
                o["карта_сохранена"] = o["номер"] in cards
            rolls = C.card_rolls()
            for o in q:
                o["рулоны"] = [{"карта": c, **r} for (n, c), lst in rolls.items() if n == o["номер"] for r in lst]
            C._ok(ctx, {"очередь": q, "история": C.card_history(o["номер"] for o in q), "виды_рулонов": C.roll_kinds(),
                      "рулоны_склад": C.rolls_in_stock()})
        else:
            C._ok(ctx, C.supply_state())
        return

    if path in ("/api/cex/nom/counterparties", "/api/cex/nom/counterparty"):
        if not C._can(me, "cex.supply"):
            C._deny(ctx, "cex.supply")
            return
        import counterparties
        try:
            if method == "POST":
                C._ok(ctx, counterparties.save(C._s(me.get("фио")) or C._s(me.get("логин")), ctx["body"]()))
            else:
                C._ok(ctx, {"категории": counterparties.CATEGORIES,
                          "контрагенты": counterparties.list_all(C._counterparty_seed())})
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    flow_post = {"/api/cex/design": ("cex.design", C.save_design),
                 "/api/cex/supply": ("cex.supply", C.save_supply),
                 "/api/cex/supply/bom": ("cex.supply", C.save_bom),
                 "/api/cex/supply/roll": ("cex.supply", C.add_roll),
                 "/api/cex/supplies": ("cex.supply", C.add_supply),
                 "/api/cex/supply/material": ("cex.supply", C.save_material),
                 "/api/cex/nom/product": ("cex.supply", C.save_product),
                 "/api/cex/supply/move": ("cex.supply", C.add_move),
                 "/api/cex/supply/move/delete": ("cex.supply", C.delete_move),
                 "/api/cex/supply/rename": ("cex.supply", C.rename_material),
                 "/api/cex/supply/roll/delete": ("cex.supply", C.delete_roll)}
    if path in flow_post and method == "POST":
        code, fn = flow_post[path]
        if not C._can(me, code):
            C._deny(ctx, code)
            return
        C.ensure_sheets()
        try:
            with C.ORDER_LOCK:
                C._ok(ctx, fn(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/summary" and method == "GET":
        C.ensure_sheets()
        C._ok(ctx, summary(me))
        return

    if path == "/api/cex/payroll" and method == "GET":
        C.ensure_sheets()
        month = C._s((ctx.get("query") or {}).get("месяц", [""])[0]) or datetime.now().strftime("%Y-%m")
        C._ok(ctx, payroll_data(month, me))
        return

    if path == "/api/cex/payroll/close" and method == "POST":
        if not C._can(me, "cex.pay"):
            C._deny(ctx, "cex.pay")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, close_payroll(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/staff/card" and method == "POST":
        if not C._can(me, "cex.pay"):
            C._deny(ctx, "cex.pay")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, update_card(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/items" and method == "GET":
        C.ensure_sheets()
        q = ctx.get("query") or {}
        num = C._s((q.get("партия") or [""])[0])
        try:
            C._ok(ctx, item_labels_print(num) if (q.get("svg") or [""])[0] == "1" else labels_state(num))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/items/generate" and method == "POST":
        if not C._can(me, "cex.tech"):
            C._deny(ctx, "cex.tech")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, generate_labels(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/labels" and method == "GET":
        C.ensure_sheets()
        q = ctx.get("query") or {}
        C._ok(ctx, labels_data(C._s((q.get("партия") or [""])[0]),
                             C._s((q.get("коробка") or [""])[0])))
        return

    if path == "/api/cex/work" and method == "GET":
        C.ensure_sheets()
        C.seed_route()
        q = ctx.get("query") or {}
        C._ok(ctx, C.work_state(me, as_worker=(q.get("режим") or [""])[0] == "моя"))
        return

    if path == "/api/cex/work/take" and method == "POST":
        if not C._can_work(me):
            C._deny(ctx, "cex.work")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.take_work(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/work/done" and method == "POST":
        C.ensure_sheets()
        try:
            C._ok(ctx, C.finish_work(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/work/cancel" and method == "POST":
        C.ensure_sheets()
        try:
            C._ok(ctx, C.cancel_work(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/cut" and method == "GET":
        C.ensure_sheets()
        C._ok(ctx, C.cut_state())
        return

    if path == "/api/cex/cut/party" and method == "POST":
        if not C._can(me, "cex.cut"):
            C._deny(ctx, "cex.cut")
            return
        C.ensure_sheets()
        try:
            with C.ORDER_LOCK:
                C._ok(ctx, C.create_party(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/tech/cut" and method == "POST":  # приёмка кроя технологом
        if not C._can(me, "cex.tech"):
            C._deny(ctx, "cex.tech")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.review_cut(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/cut/resubmit" and method == "POST":  # закройщик исправил возвращённое
        if not C._can(me, "cex.cut"):
            C._deny(ctx, "cex.cut")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.resubmit_cut(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/cut/card" and method == "POST":
        if not C._can(me, "cex.cut"):
            C._deny(ctx, "cex.cut")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.save_card(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/cut" and method == "POST":
        if not C._can(me, "cex.cut"):
            C._deny(ctx, "cex.cut")
            return
        C.ensure_sheets()
        try:
            result = C.save_cut(me, ctx["body"]())
        except ValueError as exc:
            C._fail(ctx, str(exc))
            return
        C._ok(ctx, result)
        return

    if path == "/api/cex/routes" and method == "GET":
        C.ensure_sheets()
        try:
            kind = C._kind(((ctx.get("query") or {}).get("вид") or [""])[0])
        except ValueError as exc:
            C._fail(ctx, str(exc))
            return
        C._ok(ctx, C.routes_state(me, kind))
        return

    if path in ("/api/cex/routes/save", "/api/cex/routes/delete", "/api/cex/routes/bind") \
            and method == "POST":
        if not C._can(me, "cex.routes"):
            C._deny(ctx, "cex.routes")
            return
        C.ensure_sheets()
        fn = {"/api/cex/routes/save": C.save_route, "/api/cex/routes/delete": C.delete_route,
              "/api/cex/routes/bind": C.bind_route}[path]
        try:
            C._ok(ctx, fn(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/routes/step" and method == "POST":
        C.ensure_sheets()
        try:
            C._ok(ctx, C.mark_order_step(me, ctx["body"]()))
        except perms.AccessError as exc:
            C._fail(ctx, str(exc), 403)
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/staff/roles" and method == "POST":
        if not C._can(me, "stages.assign"):
            C._deny(ctx, "stages.assign")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.set_roles(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/assign" and method == "GET":
        if not C._can(me, "cex.tech"):
            C._deny(ctx, "cex.tech")
            return
        C.ensure_sheets()
        C._ok(ctx, C.assign_state(me))
        return

    if path == "/api/cex/cut/fix" and method == "POST":
        if not C._can(me, "cex.tech"):
            C._deny(ctx, "cex.tech")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.fix_cut(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/assign" and method == "POST":
        if not C._can(me, "cex.tech"):
            C._deny(ctx, "cex.tech")
            return
        C.ensure_sheets()
        try:
            C._ok(ctx, C.save_assign(me, ctx["body"]()))
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/access" and method == "GET":
        if not (C._can(me, "staff.view") or C._can(me, "perms.roles") or C._can(me, "perms.users")
                or any(C._can(me, c) for c in ("stages.create", "stages.edit", "stages.delete",
                                             "stages.assign"))):
            C._deny(ctx, "staff.view")
            return
        C.ensure_sheets()
        C._ok(ctx, C.access_state(me))
        return

    access_post = {"/api/cex/access/role": C.set_role_perm, "/api/cex/access/user": C.set_user_perm,
                   "/api/cex/access/account": C.save_account, "/api/cex/access/stage": C.save_stage,
                   "/api/cex/access/account/delete": C.delete_account,
                   "/api/cex/access/stage/delete": C.delete_stage,
                   "/api/cex/access/stage/toggle": C.toggle_stage,
                   "/api/cex/access/roles": C.set_roles,
                   "/api/cex/access/role/save": C.save_role, "/api/cex/access/role/delete": C.delete_role}
    if path in access_post and method == "POST":
        C.ensure_sheets()
        try:
            C._ok(ctx, access_post[path](me, ctx["body"]()))
        except perms.AccessError as exc:
            C._fail(ctx, str(exc), 403)
        except ValueError as exc:
            C._fail(ctx, str(exc))
        return

    if path == "/api/cex/parties" and method == "GET":
        C.ensure_sheets()
        C._ok(ctx, {"партии": C.parties()})
        return

    C._fail(ctx, "неизвестный запрос", 404)
