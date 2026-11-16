# -*- coding: utf-8 -*-
"""Инструменты Джарвиса: что он может смотреть и делать на портале — строго по правам сотрудника.

Вынесено из server.py. Права (can) и блокировку записи (WRITE_LOCK) передаёт сервер:
так у сервера и Джарвиса одна и та же блокировка, а модуль не импортирует server
(иначе при запуске server.py как __main__ появилась бы вторая копия с другой блокировкой)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import quote

import perms


def tools_for(me: dict, can, WRITE_LOCK) -> dict:
    """Инструменты Джарвиса — строго по правам сотрудника (как у кнопок на сайте)."""
    import assistant
    tools = {}

    def capabilities():
        return assistant.capabilities_summary(knowledge_for(me, can))

    tools["capabilities"] = ("что может этот сотрудник: его доступы и возможности на портале",
                             {}, capabilities)
    if can(me, "wh.view"):
        def stock(запрос: str = ""):
            import warehouse
            return assistant.stock_summary(warehouse.stock_items(), str(запрос))

        def wb_orders():
            import wb_sync
            return assistant.wb_summary(wb_sync.counts(), wb_sync.list_orders(None, None),
                                        datetime.now().strftime("%Y-%m-%d"))

        tools["stock"] = ("остатки готовой продукции на складе: сколько есть, чего больше или меньше всего, "
                          "что закончилось; запрос — модель, цвет, размер или категория",
                          {"запрос": {"type": "string", "description": "например «477 чёрный 46» или пусто — весь склад"}},
                          stock)
        tools["wb_orders"] = ("заказы Wildberries FBS: сколько всего, новых, сегодня, по кабинетам и что заказали", {},
                              wb_orders)
    if can(me, "wb.manage"):
        def wb_refresh():
            import wb_sync
            with WRITE_LOCK:  # как кнопка «Обновить из WB» — пишет заказы
                res = wb_sync.sync(actor=str(me.get("фио", "")))
            err = "; ".join(str(e) for e in res.get("ошибки") or [])
            return f"обновлено из WB: новых {res.get('создано', 0)}, изменено {res.get('обновлено', 0)}" + (
                f"; ошибки: {err}" if err else "")

        tools["wb_refresh"] = ("обновить заказы из Wildberries по API (как кнопка «Обновить из WB» в «Заказы WB»)", {},
                               wb_refresh, "Обновить заказы из Wildberries?")
    if can(me, "wh.view"):
        def _days(запрос: str) -> int:
            t = str(запрос).lower()
            return 1 if "сегодня" in t else 30 if "месяц" in t else 2 if "вчера" in t else 7

        def wh_moves(запрос: str = ""):
            days = _days(запрос)
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            import fbs_stock  # noqa: F401 — кладёт sql/ в путь
            import db as sqldb
            con = sqldb.connect()
            try:
                placed = [dict(r) for r in con.execute(
                    """SELECT p.name AS name, SUM(pl.qty) AS qty FROM placements pl JOIN products p ON p.id = pl.product_id
                       WHERE pl.ts >= ? GROUP BY p.name""", (since,)).fetchall()]
                shipped = [dict(r) for r in con.execute(
                    """SELECT p.name AS name, s.target AS target, SUM(s.qty) AS qty FROM shipments s
                       JOIN products p ON p.id = s.product_id WHERE s.ts >= ? GROUP BY p.name, s.target""",
                    (since,)).fetchall()]
            finally:
                con.close()
            for r in placed + shipped:
                r["qty"] = float(r["qty"] or 0)
            return assistant.wh_moves_summary(placed, shipped, days)

        def show_stock(запрос: str = ""):  # переход: Склад → Главная уже с фильтрами
            import warehouse
            f = assistant.stock_filter(warehouse.stock_items(), str(запрос))
            what = ", ".join(v for vals in f.values() for v in vals) or "весь склад"
            return {"ответ": f"Открываю склад: {what}, сэр.", "открыть": "wh", "фильтр": f}

        def stock_excel(запрос: str = ""):  # как кнопка «Скачать Excel» с теми же фильтрами
            import warehouse
            f = assistant.stock_filter(warehouse.stock_items(), str(запрос))
            q = "&".join(f"{k}={quote(v)}" for k, vals in f.items() for v in vals)
            what = ", ".join(v for vals in f.values() for v in vals) or "весь склад"
            return {"ответ": f"Скачиваю Excel: {what}, сэр.", "скачать": "/api/wh/model.xlsx" + (f"?{q}" if q else "")}

        def model_info(модель: str = ""):  # одна модель целиком: склад по цветам, в производстве, спецификация
            import cex_api
            import warehouse
            want = str(модель).strip().lower()
            items = [i for i in warehouse.stock_items() if str(i.get("модель", "")).lower() == want]
            if not items:
                return f"модели «{модель}» на складе нет в справочнике"
            by: dict[str, float] = {}
            for i in items:
                by[i["цвет"]] = by.get(i["цвет"], 0) + max(0.0, float(i.get("остаток") or 0))
            prod = sum(cex_api.model_production(items[0]["модель"]).values()) if can(me, "cex.view") else None
            spec = bool(cex_api.boms().get(items[0]["модель"]))
            return (f"{items[0]['категория']} {items[0]['модель']}: на складе {sum(by.values()):g} шт — "
                    + ", ".join(f"{c} {q:g}" for c, q in sorted(by.items(), key=lambda x: -x[1]))
                    + (f"; в производстве {prod} шт" if prod is not None else "")
                    + f"; спецификация {'есть' if spec else 'нет'}")

        tools["model_info"] = ("одна модель целиком: остаток по цветам, сколько в производстве, есть ли спецификация",
                               {"модель": {"type": "string", "description": "модель, например 477"}}, model_info)
        tools["wh_moves"] = ("движение склада: что пришло и что ушло за сегодня, неделю или месяц, куда отгружали",
                             {"запрос": {"type": "string", "description": "период: сегодня, вчера, неделя, месяц"}}, wh_moves)
        tools["show_stock"] = ("открыть склад с фильтром по модели, цвету, размеру или категории (показать на экране)",
                               {"запрос": {"type": "string", "description": "например «477 серый 46»"}}, show_stock)
        tools["stock_excel"] = ("скачать Excel остатков по модели, цвету, размеру или категории",
                                {"запрос": {"type": "string", "description": "например «постель» или «477 чёрный»"}}, stock_excel)
    if can(me, "wh.write"):
        def revision_start(запрос: str = ""):
            import revision
            import warehouse
            cats = assistant.stock_filter(warehouse.stock_items(), str(запрос))["cat"]
            with WRITE_LOCK:
                revision.start(cats[0] if cats else "", str(me.get("фио") or me.get("логин") or ""))
            return f"ревизия начата: {cats[0] if cats else 'весь склад'}. Откройте Склад → Ревизия и сканируйте товар"

        def revision_question(запрос: str = ""):
            import warehouse
            cats = assistant.stock_filter(warehouse.stock_items(), str(запрос))["cat"]
            return f"Начать ревизию: {cats[0] if cats else 'весь склад'}?"

        tools["revision_start"] = ("начать ревизию склада (пересчёт товара) по категории или всего склада",
                                   {"запрос": {"type": "string", "description": "категория, например «постель», или пусто"}},
                                   revision_start, revision_question)
    if can(me, "report.build"):
        def wb_sales():
            import wb_report
            return assistant.wb_sales_summary(wb_report.report("all"), datetime.now().month)

        tools["wb_sales"] = ("продажи Wildberries за 30 дней по моделям и кабинетам, остатки на складах WB, "
                             "сезон на ближайшие месяцы: что продаётся, что шить и везти", {}, wb_sales)
    if can(me, "cex.supply"):
        def materials():
            import cex_api
            st = cex_api.supply_state()
            return assistant.materials_summary(st.get("остатки") or [], st.get("материалы") or [])

        tools["materials"] = ("склад сырья: остатки ткани, ниток, фурнитуры и что ниже минимума", {}, materials)
    if can(me, "cex.view"):
        def cex_status():
            import cex_api
            return assistant.cex_summary(cex_api.summary(me))

        tools["cex_status"] = ("состояние цеха: сколько партий и заказов в пошиве, что ждёт по этапам, "
                               "недостачи кроя", {}, cex_status)

        def cex_orders():
            import cex_api
            return assistant.cex_orders_summary(cex_api.orders(), cex_api.supply_state().get("очередь") or [])

        tools["cex_orders"] = ("заказы цеха по номерам: где сейчас каждый заказ и почему стоит "
                               "(нет спецификации, не хватает сырья)", {}, cex_orders)

        def order_detail(номер: str = ""):
            import cex_api
            num = re.sub(r"\D", "", str(номер))
            o = next((x for x in cex_api.orders() if str(x["номер"]) == num), None)
            if not o:
                return f"заказа №{num or '?'} нет"
            bom = cex_api.boms()
            pos = {}
            for p in o["позиции"]:
                pos.setdefault((p["модель"], p["цвет"]), []).append(f"{p['размер']}:{p['количество']}")
            lines = [f"заказ №{num}, {o.get('клиент', '')}, от {o.get('дата', '')}, срок {o.get('срок', '') or '—'}, "
                     f"всего {o.get('штук', 0)} шт, статус «{o.get('статус', '')}»",
                     "карты: " + (", ".join(f"{k} — {v}" for k, v in (o.get('карты') or {}).items()) or "—"),
                     "позиции: " + "; ".join(f"{m} {c} ({', '.join(z)})" for (m, c), z in pos.items()),
                     "спецификации: " + ", ".join(f"{m} — {'есть' if bom.get(m) else 'НЕТ'}"
                                                  for m in sorted({p['модель'] for p in o['позиции']}))]
            for q in cex_api.supply_state().get("очередь") or []:
                if str(q.get("номер")) == num:
                    short = [f"{s['материал']} {s.get('цвет', '')} нужно {s['нужно']:g}, есть {s.get('на_складе', 0):g}"
                             for s in q.get("сырьё") or [] if not s.get("есть")]
                    lines.append(f"снабжение карты {q.get('карта_номер')}: "
                                 + ("не хватает: " + "; ".join(short) if short else "сырья хватает"))
            return ". ".join(lines)

        tools["order_detail"] = ("подробно один заказ цеха по номеру: позиции, этап каждой карты, есть ли спецификации, "
                                 "хватает ли сырья", {"номер": {"type": "string", "description": "номер заказа"}},
                                 order_detail)
    if can(me, "cex.work"):
        def my_work():
            import cex_api
            return assistant.my_work_summary(cex_api.work_state(me, as_worker=True))

        tools["my_work"] = ("моя работа в цехе: что у меня в работе, что можно взять, сколько я сдал сегодня",
                            {}, my_work)
    if can(me, "cex.pay") or can(me, "cex.work"):  # payroll_data сама режет «только своё» без права cex.pay
        def salary():
            import cex_api
            return assistant.payroll_summary(cex_api.payroll_data(datetime.now().strftime("%Y-%m"), me))

        tools["salary"] = ("зарплата за текущий месяц: своя; у бухгалтера и начальника — всего цеха",
                           {}, salary)
    if can(me, "orders.view"):
        def shop_orders():
            import warehouse
            return assistant.shop_orders_summary(warehouse.orders())

        tools["shop_orders"] = ("заказы магазина от клиентов: сколько новых, собрано, отменено, по клиентам",
                                {}, shop_orders)
    elif can(me, "orders.create"):  # клиент и все, кто заказывает от себя, — только свои заказы
        def my_orders():
            import warehouse
            return assistant.shop_orders_summary(warehouse.orders(author=str(me.get("фио") or "")), "ваших ")

        tools["my_orders"] = ("мои заказы в магазине: статусы моих заказов", {}, my_orders)
    if can(me, "staff.view"):
        def staff():
            import cex_api
            people = cex_api.staff_people(str(me.get("цех") or ""))
            for p in people:
                p["должность"] = perms.role_label(str(p.get("должность") or ""))
            return assistant.staff_summary(people)

        tools["staff"] = ("сотрудники: кто работает и в какой должности", {}, staff)
    return tools

def knowledge_for(me: dict, can) -> list[str]:
    """Что может этот сотрудник — из каталога прав (perms.CATALOG): ответы на «как…» и «где…»
    только в рамках его доступов. Скрытый старый учёт партий не рассказываем."""
    groups: dict[str, list[str]] = {}
    for code, group, label, _roles in perms.CATALOG:
        if group == "Старый учёт партий" or not can(me, code):
            continue
        groups.setdefault(group, []).append(label[0].lower() + label[1:])
    return [f"{g}: {', '.join(items)}" for g, items in groups.items()]
