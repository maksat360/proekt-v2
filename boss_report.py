# -*- coding: utf-8 -*-
"""Отчёты начальника на «Сводке» (бывшие листы «отчет» и «Дашборд» книги цеха).

«Поставки» — сколько ушло на каждый ИП и каждому покупателю (заказы сотрудников) за неделю, по категориям.
«Продажи» — отгрузки на ИП, заказы WB FBS и покупателям: категория → артикул → размер, штуки, доля и остаток на складе."""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402

IP = {"ЖСК": "ЖСК", "ККМ": "ККМ", "ААТ": "Алтын"}  # получатель в базе → как называем в отчёте
CABINET_IP = {"zhsk": "ЖСК", "kkm": "ККМ", "altyn": "Алтын"}  # FBS-заказ (получатель «WB») — на ИП своего кабинета
ORDER = ["Брюки", "Постель", "Толстовка", "Футболка ХБ", "Футболка", "Худи", "Лонгслив"]  # как в Excel


def _week(ts: str) -> str:
    d = date.fromisoformat(str(ts)[:10])
    return (d - timedelta(days=d.weekday())).isoformat()  # понедельник


def _share(part: float, whole: float) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


def _key(v) -> str:
    return str(v or "").strip() or "—"


def build(con=None, stock: dict | None = None) -> dict:
    """stock — остаток по наименованию (по умолчанию fbs_stock.fact_by_name: приход − отгрузки)."""
    own = con is None
    con = con or sqldb.connect()
    try:
        rows = con.execute(
            """SELECT s.target, s.ts, s.qty, p.category, p.model, p.size, o.cabinet_id FROM shipments s
               JOIN products p ON p.id = s.product_id
               LEFT JOIN orders o ON o.id = s.order_ref
               WHERE s.status = 'ok'""").fetchall()
        products = con.execute("SELECT name, category, model, size FROM products").fetchall()
    finally:
        if own:
            con.close()
    if stock is None:
        import fbs_stock
        stock = fbs_stock.fact_by_name()

    weeks = defaultdict(lambda: defaultdict(float))  # (неделя, ИП или покупатель) → категория → штук
    buyers = set()
    tree = lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # noqa: E731
    sold, left = tree(), tree()  # категория → артикул → размер → штук
    cats = set()
    for r in rows:
        target, ts, qty = str(r["target"] or "").upper(), r["ts"], r["qty"]
        cat = str(r["category"] or "").strip() or "Без категории"
        ip = IP.get(target) or (CABINET_IP.get(r["cabinet_id"] or "") if target == "WB" else None)
        if not ip and target and target != "WB":  # любой другой получатель — покупатель (заказ сотрудника)
            ip = target.title()
            buyers.add(ip)
        if ip:  # FBS без кабинета в поставки не попадает, но это всё равно продажа
            weeks[(_week(ts), ip)][cat] += qty
            cats.add(cat)
        sold[cat][_key(r["model"])][_key(r["size"])] += qty
    for r in products:
        q = float(stock.get(r["name"], 0) or 0)
        if q:
            left[str(r["category"] or "").strip() or "Без категории"][_key(r["model"])][_key(r["size"])] += q

    categories = [c for c in ORDER if c in cats] + sorted(cats - set(ORDER))
    # свежие недели сверху; внутри недели сначала ИП, потом покупатели
    order = sorted(weeks, key=lambda k: (k[1] in buyers, k[1]))
    order.sort(key=lambda k: k[0], reverse=True)
    supply = [{"неделя": wk, "ип": ip, "покупатель": ip in buyers,
               "по_категориям": {c: round(v, 2) for c, v in weeks[(wk, ip)].items()},
               "итог": round(sum(weeks[(wk, ip)].values()), 2)} for wk, ip in order]

    def total(t, *path):
        node = t
        for k in path:
            node = node.get(k, {})
        if isinstance(node, float):
            return node
        return sum(total(node, k) for k in node)

    all_sold = total(sold)
    out = []
    for cat in set(sold) | set(left):
        cat_sold = total(sold, cat)
        arts = []
        for art in set(sold[cat]) | set(left[cat]):
            art_sold = total(sold, cat, art)
            sizes = set(sold[cat][art]) | set(left[cat][art])
            arts.append({"артикул": art, "штук": round(art_sold, 2), "доля": _share(art_sold, cat_sold),
                         "остаток": round(total(left, cat, art), 2),
                         "размеры": sorted(({"размер": z, "штук": round(sold[cat][art].get(z, 0), 2),
                                             "остаток": round(left[cat][art].get(z, 0), 2)} for z in sizes),
                                           key=lambda x: (-x["штук"], -x["остаток"]))})
        arts.sort(key=lambda a: (-a["штук"], -a["остаток"]))
        out.append({"категория": cat, "штук": round(cat_sold, 2), "доля": _share(cat_sold, all_sold),
                    "остаток": round(total(left, cat), 2), "артикулы": arts})
    out.sort(key=lambda c: (-c["штук"], -c["остаток"]))
    return {"категории": categories, "поставки": supply,
            "продажи": {"всего": round(all_sold, 2), "остаток": round(total(left), 2), "категории": out}}
