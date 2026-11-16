# -*- coding: utf-8 -*-
"""Цех: сводка — партии, этапы, сдано, заработано, показатели для Сводки портала.

Вынесено из cex_api.py. Общие данные и функции цеха — через cex_api (C.…):
так подмены в тестах и вызовы из других разделов идут через один модуль.
Импортировать этот модуль напрямую не нужно: cex_api сам отдаёт его функции."""
from __future__ import annotations

from datetime import datetime, timedelta
from cex_payroll import _date_of

import cex_api as C


# --------------------------------------------------------- сводка (модуль 7)


def summary(me: dict) -> dict:
    parties = C.cut_state()["партии"]
    routes = C.party_routes(parties)
    stages = C._union_stages(routes)
    issued = C._rows(C.OUT)
    packed = C._rows(C.PACK)

    done: dict[tuple, int] = {}
    inwork: dict[tuple, int] = {}
    for r in issued:
        key = (C._s(r.get("партия")), C._s(r.get("этап")))
        qty = C._int(r.get("количество"))
        if C._s(r.get("статус")) == "готово":
            done[key] = done.get(key, 0) + qty
        elif C._s(r.get("статус")) == "в работе":
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
            src = C._source_qty(num, own, route, done, p["раскроено"])
            left = max(0, src - done.get((num, st["код"]), 0))
            waiting += left
            if left > 0:
                active += 1
        stage_rows.append({"код": st["код"], "название": st["название"],
                           "ждёт": waiting, "партий": active})

    packed_by_party: dict[str, int] = {}
    for r in packed:
        num = C._s(r.get("партия"))
        packed_by_party[num] = packed_by_party.get(num, 0) + C._int(r.get("количество"))

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
        if C._s(r.get("статус")) != "готово":
            continue
        model = next((p["модель"] for p in parties if p["номер"] == C._s(r.get("партия"))), "")
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
        if C._s(r.get("статус")) != "готово":
            continue
        dt = _date_of(r.get("дата"))
        if not dt:
            continue
        key = dt.strftime("%d.%m")
        if key in index:
            index[key]["шт"] += C._int(r.get("количество"))
            index[key]["сумма"] += float(str(r.get("сумма") or 0).replace(",", ".") or 0)

    orders_rows = C._rows(C.ORDERS)
    waiting_orders = len({C._s(r.get("№ заказа")) for r in orders_rows
                          if C._s(r.get("статус")) == "у технолога"})
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
