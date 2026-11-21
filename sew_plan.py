# -*- coding: utf-8 -*-
"""План пошива (вспомогательный): сколько держать на складе по цветам и размерам и сколько дошить.

Норму (например 5000 штук модели) делим пропорционально заказам WB за последние N дней,
округляем до 10. Сравниваем с нашим складом: шить = норма − есть (если больше 0).
Цвет «не шьём»: если для него есть замена (substitutes.json) — его спрос уходит на замену,
иначе просто не считается. Лишний товар не шьём — он распродаётся, и склад сам приходит к норме.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta


def _round10(x: float) -> int:
    return int(round(x / 10.0)) * 10


def allocate(demand: dict, total: int) -> dict:
    """{ключ: заказов} → {ключ: норма}, кратно 10, сумма = total. Был хоть один заказ — минимум 10."""
    blocks = total // 10
    s = sum(demand.values())
    if not s or blocks <= 0:
        return {k: 0 for k in demand}
    raw = {k: v / s * blocks for k, v in demand.items() if v > 0}
    got = {k: max(1, int(x)) for k, x in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - got[k], reverse=True):  # остаток десятков — самым недобранным
        if sum(got.values()) >= blocks:
            break
        got[k] += 1
    while sum(got.values()) > blocks:  # минимумы перебрали — снимаем с самых больших
        k = max(got, key=got.get)
        got[k] -= 1
    return {k: got.get(k, 0) * 10 for k in demand}


def _size_key(s: str):
    return (0, int(s)) if str(s).isdigit() else (1, str(s))


def compute(names: list[str], demand: dict, stock: dict, total: int, off: list[str], subs: dict) -> dict:
    """names — наши товары модели «Кат/модель/цвет/размер»; demand — {(цвет, размер): заказов};
    stock — {наименование: штук}; off — цвета, которые не шьём; subs — замены «Кат/модель/цвет» → «…/цвет»."""
    off = {c.strip().lower() for c in off if c.strip()}
    prefix = {n.split("/")[2]: "/".join(n.split("/")[:3]) for n in names}
    folded = Counter()
    went = {}
    for (col, sz), q in demand.items():
        if col.lower() in off:
            to = subs.get(prefix.get(col, ""), "").split("/")[-1] if prefix.get(col) else ""
            if not to or to.lower() in off:
                continue
            went[col] = to
            col = to
        folded[(col, sz)] += q
    known = {(n.split("/")[2], n.split("/")[3]) for n in names}
    norm = allocate({k: v for k, v in folded.items() if k in known}, total)
    rows = []
    for n in names:
        col, sz = n.split("/")[2], n.split("/")[3]
        have = max(0, int(stock.get(n, 0) or 0))
        need = norm.get((col, sz), 0)
        rows.append({"цвет": col, "размер": sz, "не_шьём": col.lower() in off,
                     "заказали": demand.get((col, sz), 0), "норма": need, "есть": have,
                     "шить": max(0, _round10(need - have)), "лишнее": max(0, have - need)})
    order = Counter()
    for r in rows:
        order[r["цвет"]] += r["норма"]
    cols = sorted(order, key=lambda c: (-order[c], c))
    rows.sort(key=lambda r: (cols.index(r["цвет"]), _size_key(r["размер"])))
    colors = []
    for c in cols:
        rr = [r for r in rows if r["цвет"] == c]
        colors.append({"цвет": c, "не_шьём": rr[0]["не_шьём"], "замена": went.get(c, ""),
                       "плюс_заказы": sorted(k for k, v in went.items() if v == c),
                       **{k: sum(r[k] for r in rr) for k in ("заказали", "норма", "есть", "шить", "лишнее")}})
    sums = {k: sum(c[k] for c in colors) for k in ("заказали", "норма", "есть", "шить", "лишнее")}
    return {"цвета": colors, "строки": rows, "итого": sums, "после": sums["есть"] + sums["шить"]}


def build(model: str = "477", total: int = 5000, off=("бежевый", "синий"), days: int = 30) -> dict:
    """Живые данные: заказы WB (без отмен) за days дней, наш склад, замены."""
    import fbs_stock
    import substitutes
    import warehouse
    import wb_report
    model = str(model).strip()
    if not model:
        raise ValueError("Укажите модель")
    if not 10 <= int(total) <= 1_000_000:
        raise ValueError("Норма — от 10 штук")
    names = [n for n in warehouse.product_names() if n.count("/") >= 3 and n.split("/")[1] == model]
    if not names:
        raise ValueError(f"Модели «{model}» нет в справочнике")
    since = (date.today() - timedelta(days=days)).isoformat()
    con = wb_report._db()
    try:
        orders = con.execute("SELECT article, size, barcode, subject FROM wb_orders WHERE day >= ? AND cancel = 0",
                             (since,)).fetchall()
    finally:
        con.close()
    demand = Counter()
    for r in orders:
        _, mod, col, sz = wb_report.resolve(r["barcode"], r["article"], r["size"], r["subject"])
        if mod == model:
            demand[(col, sz)] += 1
    res = compute(names, demand, fbs_stock.fact_by_name() or {}, int(total), list(off), substitutes.load())
    res.update(модель=model, норма=int(total), не_шьём=[c for c in off if c.strip()], дней=days, с=since,
               категория=names[0].split("/")[0])
    return res


def xlsx(res: dict) -> bytes:
    """Excel для человека не в теме: «Что шить», «Подробно», «Как считали»."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    bold, big = Font(bold=True), Font(bold=True, size=14)
    grey, green = PatternFill("solid", fgColor="EEEEEE"), PatternFill("solid", fgColor="E2F0D9")
    title = f"{res['категория']} {res['модель']}"
    wb = Workbook()

    ws = wb.active
    ws.title = "Что шить"
    ws.append([f"Что нужно сшить — {title}"])
    ws["A1"].font = big
    ws.append([f"Всего сшить: {res['итого']['шить']} шт. Список только того, чего не хватает."])
    ws.append([])
    ws.append(["Цвет", "Размер", "Сшить, шт"])
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, grey
    for col in res["цвета"]:
        rr = [r for r in res["строки"] if r["цвет"] == col["цвет"] and r["шить"]]
        if not rr:
            continue
        for r in rr:
            ws.append([r["цвет"], r["размер"], r["шить"]])
        ws.append([f"Итого {col['цвет']}", "", col["шить"]])
        for c in ws[ws.max_row]:
            c.font, c.fill = bold, green
        ws.append([])
    ws.append(["ВСЕГО", "", res["итого"]["шить"]])
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, grey
    for k, w in {"A": 26, "B": 10, "C": 12}.items():
        ws.column_dimensions[k].width = w

    ws = wb.create_sheet("Подробно")
    ws.append([f"Все размеры — {title}"])
    ws["A1"].font = big
    head = ["Цвет", "Размер", f"Заказали за {res['дней']} дней", "Нужно держать на складе",
            "Сейчас на складе", "Сшить", "Лишнее (просто распродаётся)"]
    ws.append(head)
    for c in ws[2]:
        c.font, c.fill = bold, grey
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for col in res["цвета"]:
        for r in [r for r in res["строки"] if r["цвет"] == col["цвет"]]:
            ws.append([r["цвет"], r["размер"], r["заказали"], r["норма"], r["есть"], r["шить"] or None,
                       r["лишнее"] or None])
        note = " (не шьём)" if col["не_шьём"] else (f" (+ заказы: {', '.join(col['плюс_заказы'])})"
                                                     if col["плюс_заказы"] else "")
        ws.append([f"Итого {col['цвет']}{note}", "", col["заказали"], col["норма"], col["есть"], col["шить"],
                   col["лишнее"]])
        for c in ws[ws.max_row]:
            c.font, c.fill = bold, green
    t = res["итого"]
    ws.append(["ВСЕГО", "", t["заказали"], t["норма"], t["есть"], t["шить"], t["лишнее"]])
    for c in ws[ws.max_row]:
        c.font, c.fill = bold, grey
    ws.freeze_panes = "C3"
    for k, w in {"A": 28, "B": 9, "C": 14, "D": 14, "E": 12, "F": 9, "G": 16}.items():
        ws.column_dimensions[k].width = w

    ws = wb.create_sheet("Как считали")
    off = ", ".join(res["не_шьём"]) or "нет"
    moved = "; ".join(f"заказы на «{c['цвет']}» посчитаны как «{c['замена']}»" for c in res["цвета"] if c["замена"])
    lines = [
        f"Как считали — {title}", "",
        f"1. Цель: всегда держать на складе {res['норма']} шт. этой модели.",
        f"2. Смотрели, сколько заказали на Wildberries за последние {res['дней']} дней (с {res['с']}), отмены не считали.",
        "3. Чем больше заказывают цвет и размер, тем больше его держим. Числа округлены до 10.",
        f"4. Цвета, которые не шьём: {off}." + (f" Их {moved}." if moved else ""),
        "5. Из нормы вычли то, что уже лежит на складе. Разница — это «Сшить».",
        "6. Если на складе больше нормы — это «Лишнее». Его не шьём, он просто распродаётся.",
        f"7. Сейчас на складе {t['есть']} шт. После пошива будет около {res['после']} шт. — больше нормы из-за лишнего.",
        f"   Со временем лишнее продастся, и склад сам придёт к {res['норма']} шт.",
        "",
        "Важно: это подсказка, а не точный приказ. Сезон, акции и новые цвета расчёт не знает —",
        "поправляйте цифры по своему опыту. Где заказов мало (2–5 за месяц), цифры примерные.",
    ]
    for s in lines:
        ws.append([s])
    ws["A1"].font = big
    ws.column_dimensions["A"].width = 110

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
