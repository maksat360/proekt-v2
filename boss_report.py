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

IP = {"ЖСК": "ЖСК", "ККМ": "ККМ", "ААТ": "Алтын", "АЛТЫН": "Алтын"}  # получатель в базе → как в отчёте
NOT_SALE = {"РЕВИЗИЯ"}  # списание недостачи ревизией — не поставка и не продажа
CABINET_IP = {"zhsk": "ЖСК", "kkm": "ККМ", "altyn": "Алтын"}  # FBS-заказ (получатель «WB») — на ИП своего кабинета
ORDER = ["Брюки", "Постель", "Толстовка", "Футболка ХБ", "Футболка", "Худи", "Лонгслив"]  # как в Excel


def _week(ts: str) -> str:
    d = date.fromisoformat(str(ts)[:10])
    return (d - timedelta(days=d.weekday())).isoformat()  # понедельник


def _share(part: float, whole: float) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


def _key(v) -> str:
    return str(v or "").strip() or "—"


def _ip(target: str, cabinet: str | None) -> str | None:
    """Кому поставка: ИП (ЖСК/ККМ/Алтын, FBS — по кабинету заказа) или покупатель (заказ сотрудника)."""
    ip = IP.get(target) or (CABINET_IP.get(cabinet or "") if target == "WB" else None)
    if not ip and target and target != "WB":
        ip = target.title()
    return ip


_MONTHS = ("янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек.")


def _week_label(monday: str) -> str:
    """«16–22 нояб.» — как на сайте; неделя через месяц: «30 нояб. – 6 дек.»."""
    a = date.fromisoformat(monday)
    b = a + timedelta(days=6)
    if a.month == b.month:
        return f"{a.day}–{b.day} {_MONTHS[b.month - 1]}"
    return f"{a.day} {_MONTHS[a.month - 1]} – {b.day} {_MONTHS[b.month - 1]}"


def supply_xlsx(weeks=(), ips=(), con=None, stock: dict | None = None) -> bytes:
    """Поставки по неделям в Excel: по товарам (модель, цвет, размер) и сводкой «неделя × ИП».
    weeks — понедельники недель (ГГГГ-ММ-ДД), ips — ИП или покупатели; пусто — все."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    own = con is None
    con = con or sqldb.connect()
    try:
        rows = con.execute(
            """SELECT s.target, s.ts, s.qty, p.name, p.category, p.model, p.color, p.size, o.cabinet_id
               FROM shipments s JOIN products p ON p.id = s.product_id
               LEFT JOIN orders o ON o.id = s.order_ref
               WHERE s.status = 'ok' ORDER BY s.ts""").fetchall()
    finally:
        if own:
            con.close()
    weeks, ips = set(weeks), set(ips)
    det, agg = [], defaultdict(float)
    for r in rows:
        target = str(r["target"] or "").upper()
        ip = None if target in NOT_SALE else _ip(target, r["cabinet_id"])
        wk = _week(r["ts"])
        if not ip or (weeks and wk not in weeks) or (ips and ip not in ips):
            continue
        cat = str(r["category"] or "").strip() or "Без категории"
        det.append([wk, str(r["ts"])[:10], ip, "ИП" if ip in IP.values() else "покупатель", cat,
                    _key(r["model"]), _key(r["color"]), _key(r["size"]), r["name"], r["qty"]])
        agg[(wk, ip, cat, _key(r["model"]), _key(r["color"]), _key(r["size"]))] += r["qty"]
    if not det:
        raise ValueError("За выбранные недели поставок нет")
    # остаток на складе по категориям — как в нижней строке таблицы на сайте
    rep = build(con, stock) if not own else build(stock=stock)
    left = {c["категория"]: c["остаток"] for c in rep["продажи"]["категории"]}
    cats_sold = {k[2] for k in agg}
    cats = [c for c in rep["категории"] if c in cats_sold] + sorted(cats_sold - set(rep["категории"]))
    cats += [c for c in left if left[c] and c not in cats]
    table = defaultdict(lambda: defaultdict(float))  # (неделя, ИП) → категория → штук
    for k, q in agg.items():
        table[(k[0], k[1])][k[2]] += q
    buyers = {k[1] for k in agg if k[1] not in IP.values()}
    keys = sorted(table, key=lambda k: (k[1] in buyers, k[1]))
    keys.sort(key=lambda k: k[0], reverse=True)  # свежие недели сверху, внутри — сначала ИП

    wb = Workbook()
    ws = wb.active
    ws.title = "Поставки по неделям"
    bold, grey = Font(bold=True), PatternFill("solid", fgColor="EEEEEE")
    ws.append(["Неделя", "ИП / покупатель", *cats, "Итог"])
    for wk, ip in keys:
        row = table[(wk, ip)]
        ws.append([_week_label(wk), ip + (" · покупатель" if ip in buyers else ""),
                   *[round(row[c], 2) or None for c in cats], round(sum(row.values()), 2)])
        if ip not in buyers:
            ws.cell(ws.max_row, 2).font = bold
        ws.cell(ws.max_row, len(cats) + 3).font = bold
    ws.append(["Всего", "", *[round(sum(table[k][c] for k in keys), 2) or None for c in cats],
               round(sum(agg.values()), 2)])
    ws.append(["Остаток на складе", "", *[round(left.get(c, 0), 2) for c in cats], rep["продажи"]["остаток"]])
    for r in (ws.max_row - 1, ws.max_row):
        for c in ws[r]:
            c.font, c.fill = bold, grey
    for c in ws[1]:
        c.font, c.fill = bold, grey
    ws.freeze_panes = "C2"
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 20, 26
    for i in range(len(cats) + 1):
        ws.column_dimensions[chr(67 + i)].width = 12

    t = wb.create_sheet("По товарам")
    t.append(["Неделя", "ИП / покупатель", "Категория", "Модель", "Цвет", "Размер", "Штук"])
    for k in sorted(agg, key=lambda k: (k[0], k[1], k[2], k[3], k[4], str(k[5]))):
        t.append([_week_label(k[0]), *k[1:], round(agg[k], 2)])
    t.append(["Итого", "", "", "", "", "", round(sum(agg.values()), 2)])
    d = wb.create_sheet("Каждая отгрузка")
    d.append(["Неделя", "Дата", "ИП / покупатель", "Кто", "Категория", "Модель", "Цвет", "Размер",
              "Полное наименование", "Штук"])
    for row in det:
        d.append([_week_label(row[0]), *row[1:]])
    for sh, widths in ((t, (20, 18, 12, 18, 22, 8, 8)), (d, (20, 11, 18, 11, 12, 18, 22, 8, 40, 7))):
        for c in sh[1]:
            c.font, c.fill = bold, grey
        sh.freeze_panes = "A2"
        sh.auto_filter.ref = f"A1:{chr(64 + len(widths))}{sh.max_row}"
        for i, w in enumerate(widths):
            sh.column_dimensions[chr(65 + i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build(con=None, stock: dict | None = None) -> dict:
    """stock — остаток по наименованию (по умолчанию fbs_stock.fact_by_name: приход − отгрузки)."""
    own = con is None
    con = con or sqldb.connect()
    try:
        rows = con.execute(
            """SELECT s.target, s.ts, s.qty, p.name, p.category, p.model, p.color, p.size, o.cabinet_id FROM shipments s
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
        if target in NOT_SALE:
            continue
        cat = str(r["category"] or "").strip() or "Без категории"
        ip = _ip(target, r["cabinet_id"])
        if ip and ip not in IP.values():
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
