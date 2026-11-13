# -*- coding: utf-8 -*-
"""Адресное хранение (Склад → Адрес). Надстройка над остатком: показывает, ГДЕ лежит товар.
Остаток по-прежнему считается в PostgreSQL (приход − отгрузки); товар без адреса — нормальное состояние.

Коды (латиница — штрихкод кириллицу не кодирует):
  P1-3-05  ячейка внутри: стеллаж 1, этаж 3, ячейка 5 — открытый товар, отсюда собирают
  N-3-17   ячейка снаружи (N2-… для второго стеллажа) — в ней стоят коробки
  K-0001   коробка: всегда стоит в ячейке N, переезжает целиком
  M-0001   мешок: без адреса, из него снимают частями
Коды коробок и мешков выдаются только новые и никогда не повторяются."""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

_SQL = Path(__file__).resolve().parent / "sql"
if str(_SQL) not in sys.path:
    sys.path.insert(0, str(_SQL))

import db as sqldb  # noqa: E402

KINDS = {"P": "ячейка внутри", "N": "ячейка снаружи", "K": "коробка", "M": "мешок"}
_READY: set[str] = set()
# сканер в русской раскладке печатает З/Т/Л/Ь вместо P/N/K/M; плюс похожие кириллические буквы
_LAYOUT = str.maketrans({"З": "P", "Т": "N", "Л": "K", "Ь": "M", "Р": "P", "Н": "N", "К": "K", "М": "M"})
_CELL = re.compile(r"^(P|N)(\d*)-(\d{1,2})-(\d{1,3})$")
_UNIT = re.compile(r"^(K|M)-(\d{1,6})$")


def _stock() -> dict[str, float]:
    import fbs_stock
    return fbs_stock.fact_by_name()


def _con():
    con = sqldb.connect()
    key = type(con).__name__ + str(getattr(sqldb, "DB_PATH", ""))
    if key not in _READY:
        sqldb.migrate(con)
        _READY.add(key)
    return con


def norm(code) -> str:
    return str(code or "").strip().upper().translate(_LAYOUT).replace(" ", "")


def is_code(code) -> bool:
    c = norm(code)
    return bool(_CELL.match(c) or _UNIT.match(c))


def cell_code(zone: str, rack: int, floor: int, cell: int) -> str:
    rk = "" if zone == "N" and rack == 1 else str(rack)  # наружный стеллаж №1 печатался как N-3-17
    return f"{zone}{rk}-{floor}-{cell:02d}"


def route_key(code: str) -> tuple:
    """Порядок обхода: сначала внутри (P), потом снаружи (N); стеллаж → этаж → ячейка по возрастанию."""
    m = _CELL.match(code)
    if not m:
        return (9, 0, 0, 0, code)
    return (0 if m[1] == "P" else 1, int(m[2] or 1), int(m[3]), int(m[4]), code)


def _place(con, code: str):
    return con.execute("SELECT * FROM wh_places WHERE code=?", (code,)).fetchone()


def _need(con, code, kinds: str, what: str):
    c = norm(code)
    row = _place(con, c)
    if not row:
        raise ValueError(f"Код {c or '—'} не заведён на сайте")
    if row["status"] != "active":
        tail = f" — теперь {row['replaced_by']}" if row["replaced_by"] else ""
        raise ValueError(f"Код {c} списан{tail}")
    if row["kind"] not in kinds:
        raise ValueError(f"{c} — {KINDS[row['kind']]}, а нужна {what}")
    return row


def _contents(con, code: str) -> list[dict]:
    rows = con.execute("SELECT product, qty FROM wh_contents WHERE place=? AND qty > 0", (code,)).fetchall()
    return sorted(({"наименование": r["product"], "количество": r["qty"]} for r in rows),
                  key=lambda x: x["наименование"])


def _add(con, place: str, product: str, qty: float) -> None:
    row = con.execute("SELECT qty FROM wh_contents WHERE place=? AND product=?", (place, product)).fetchone()
    left = round((row["qty"] if row else 0) + qty, 3)
    if left < 0:
        raise ValueError(f"В {place} нет столько «{product}»: есть {row['qty'] if row else 0:g} шт")
    if row and left <= 0:
        con.execute("DELETE FROM wh_contents WHERE place=? AND product=?", (place, product))
    elif row:
        con.execute("UPDATE wh_contents SET qty=?, updated_at=? WHERE place=? AND product=?",
                    (left, sqldb.now(), place, product))
    elif left > 0:
        con.execute("INSERT INTO wh_contents(place, product, qty, updated_at) VALUES (?,?,?,?)",
                    (place, product, left, sqldb.now()))


def _free_box_if_empty(con, code: str) -> None:
    """Опустевшая коробка освобождает ячейку — её наполняют заново тем же кодом."""
    if code.startswith("K-") and not _contents(con, code):
        con.execute("UPDATE wh_places SET at=NULL, updated_at=? WHERE code=?", (sqldb.now(), code))


def located() -> dict[str, float]:
    con = _con()
    try:
        out: dict[str, float] = {}
        for r in con.execute("SELECT product, SUM(qty) AS q FROM wh_contents GROUP BY product"):
            out[r["product"]] = round(r["q"] or 0, 3)
        return out
    finally:
        con.close()


def _free(con, product: str) -> float:
    """Сколько этого товара в остатке ещё без адреса."""
    row = con.execute("SELECT SUM(qty) AS q FROM wh_contents WHERE product=?", (product,)).fetchone()
    return round(_stock().get(product, 0.0) - ((row["q"] if row else 0) or 0), 3)


def _tx(con, fn):
    con.execute("BEGIN IMMEDIATE")
    try:
        res = fn()
        con.execute("COMMIT")
        return res
    except Exception:
        con.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------- справочник кодов
def create_rack(actor: str, zone: str, rack: int, floors: int, cells: int) -> list[str]:
    zone = norm(zone)
    if zone not in ("P", "N"):
        raise ValueError("Зона: P — внутри или N — снаружи")
    if not (1 <= rack <= 99 and 1 <= floors <= 20 and 1 <= cells <= 99):
        raise ValueError("Стеллаж 1–99, этажей 1–20, ячеек на этаже 1–99")
    con = _con()
    try:
        def run():
            made = []
            for fl in range(1, floors + 1):
                for c in range(1, cells + 1):
                    code = cell_code(zone, rack, fl, c)
                    if not _place(con, code):
                        con.execute("INSERT INTO wh_places(code, kind, rack, floor, cell, created_at) "
                                    "VALUES (?,?,?,?,?,?)", (code, zone, rack, fl, c, sqldb.now()))
                        made.append(code)
            sqldb.audit(con, actor, "addr_rack", "wh_places", f"{zone}{rack}",
                        {"этажей": floors, "ячеек": cells, "создано": len(made)})
            return made
        return _tx(con, run)
    finally:
        con.close()


def issue(actor: str, kind: str, count: int) -> list[str]:
    """Новые коды коробок/мешков — следующие номера; старые не выдаются повторно (строки не удаляются)."""
    kind = norm(kind)
    if kind not in ("K", "M"):
        raise ValueError("Тип: K — коробка или M — мешок")
    if not 1 <= count <= 500:
        raise ValueError("За раз — от 1 до 500 кодов")
    con = _con()
    try:
        def run():
            nums = [int(r["code"][2:]) for r in con.execute("SELECT code FROM wh_places WHERE kind=?", (kind,))]
            start = max(nums, default=0) + 1
            codes = [f"{kind}-{n:04d}" for n in range(start, start + count)]
            for code in codes:
                con.execute("INSERT INTO wh_places(code, kind, created_at) VALUES (?,?,?)", (code, kind, sqldb.now()))
            sqldb.audit(con, actor, "addr_issue", "wh_places", kind, {"с": codes[0], "по": codes[-1]})
            return codes
        return _tx(con, run)
    finally:
        con.close()


def places(kind: str = "", rack: int = 0) -> list[dict]:
    con = _con()
    try:
        rows = con.execute("SELECT * FROM wh_places").fetchall()
        qty = {r["place"]: r["q"] for r in con.execute("SELECT place, SUM(qty) AS q FROM wh_contents GROUP BY place")}
        boxes: dict[str, int] = {}
        for r in rows:
            if r["kind"] == "K" and r["at"]:
                boxes[r["at"]] = boxes.get(r["at"], 0) + 1
        out = [{"код": r["code"], "тип": r["kind"], "стеллаж": r["rack"], "этаж": r["floor"], "ячейка": r["cell"],
                "где": r["at"] or "", "статус": r["status"], "заменён_на": r["replaced_by"] or "",
                "штук": round(qty.get(r["code"], 0) or 0, 3), "коробок": boxes.get(r["code"], 0)}
               for r in rows
               if (not kind or r["kind"] == kind) and (not rack or r["rack"] == rack)]
        return sorted(out, key=lambda x: (route_key(x["код"]) if x["тип"] in "PN" else (5 + "KM".index(x["тип"]), 0, 0, 0, x["код"])))
    finally:
        con.close()


def summary() -> dict:
    rows = places()
    racks: dict[str, dict] = {}
    for r in rows:
        if r["тип"] in "PN":
            key = cell_code(r["тип"], r["стеллаж"], 1, 1).split("-")[0]
            g = racks.setdefault(key, {"стеллаж": key, "зона": r["тип"], "номер": r["стеллаж"], "этажей": 0, "ячеек": 0, "занято": 0})
            g["этажей"] = max(g["этажей"], r["этаж"])
            g["ячеек"] += 1
            g["занято"] += 1 if (r["штук"] or r["коробок"]) else 0
    units = {k: [r for r in rows if r["тип"] == k] for k in "KM"}
    return {"стеллажи": sorted(racks.values(), key=lambda g: (g["зона"] != "P", g["номер"])),
            **{("коробки" if k == "K" else "мешки"): {
                "всего": sum(1 for r in v if r["статус"] == "active"),
                "с_товаром": sum(1 for r in v if r["статус"] == "active" and r["штук"]),
                "последний": v[-1]["код"] if v else ""} for k, v in units.items()}}


def codes_xlsx(rows: list[dict], title: str = "Адреса") -> bytes:
    """Excel для печати этикеток: по порядку маршрута."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(["№", "Код", "Тип", "Стеллаж", "Этаж", "Ячейка"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, r in enumerate(rows, 1):
        ws.append([i, r["код"], KINDS.get(r["тип"], ""), r.get("стеллаж") or "", r.get("этаж") or "", r.get("ячейка") or ""])
    for col, w in zip("ABCDEF", (7, 14, 16, 9, 7, 8)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- что где лежит
def state(code) -> dict:
    c = norm(code)
    con = _con()
    try:
        row = _place(con, c)
        if not row:
            raise ValueError(f"Код {c or '—'} не заведён на сайте")
        boxes = [{"код": r["code"], "штук": round(r["q"] or 0, 3)} for r in con.execute(
            "SELECT p.code, (SELECT SUM(qty) FROM wh_contents WHERE place=p.code) AS q "
            "FROM wh_places p WHERE p.kind='K' AND p.at=?", (c,))] if row["kind"] == "N" else []
        return {"код": c, "тип": row["kind"], "тип_название": KINDS[row["kind"]], "статус": row["status"],
                "заменён_на": row["replaced_by"] or "", "где": row["at"] or "",
                "содержимое": _contents(con, c), "коробки": sorted(boxes, key=lambda b: b["код"])}
    finally:
        con.close()


def where(product: str) -> dict:
    con = _con()
    try:
        rows = con.execute("SELECT c.place, c.qty, p.at FROM wh_contents c JOIN wh_places p ON p.code=c.place "
                           "WHERE c.product=? AND c.qty > 0", (product,)).fetchall()
        lst = [{"код": r["place"], "количество": r["qty"], "где": r["at"] or ""} for r in rows]
        lst.sort(key=lambda x: route_key(x["где"] or x["код"]) if not x["код"].startswith("M-") else (8, 0, 0, 0, x["код"]))
        return {"наименование": product, "адреса": lst, "без_адреса": _free(con, product),
                "остаток": round(_stock().get(product, 0.0), 3)}
    finally:
        con.close()


def where_map() -> dict[str, list[str]]:
    """Наименование → коды мест (для колонки «Адрес» в остатках)."""
    con = _con()
    try:
        out: dict[str, list] = {}
        for r in con.execute("SELECT c.product, c.place, p.at FROM wh_contents c JOIN wh_places p ON p.code=c.place WHERE c.qty > 0"):
            out.setdefault(r["product"], []).append(f"{r['place']}@{r['at']}" if r["at"] else r["place"])
        return {k: sorted(v, key=route_key) for k, v in out.items()}
    finally:
        con.close()


# ---------------------------------------------------------------- операции
def put(actor: str, place, product: str, qty: float) -> dict:
    """Положить товар «без адреса» в ячейку P, коробку K или мешок M (комплектация)."""
    product = str(product or "").strip()
    if not product:
        raise ValueError("Не выбран товар")
    if qty <= 0:
        raise ValueError("Количество должно быть больше нуля")
    con = _con()
    try:
        def run():
            row = _need(con, place, "PKM", "ячейка внутри, коробка или мешок")
            free = _free(con, product)
            if qty > free:
                raise ValueError(f"Без адреса только {max(free, 0):g} шт «{product}» — остальное уже лежит по адресам")
            _add(con, row["code"], product, qty)
            sqldb.audit(con, actor, "addr_put", "wh_places", row["code"], {"товар": product, "шт": qty})
            return {"код": row["code"], "содержимое": _contents(con, row["code"])}
        return _tx(con, run)
    finally:
        con.close()


def box_to(actor: str, box, cell) -> dict:
    """Коробка → ячейка. Снаружи (N): коробка переезжает целиком, старая ячейка освобождается сама.
    Внутри (P): коробку вскрыли — всё содержимое переходит в ячейку, коробка пустая."""
    con = _con()
    try:
        def run():
            b = _need(con, box, "K", "коробка")
            c = _need(con, cell, "PN", "ячейка")
            if c["kind"] == "N":
                if not _contents(con, b["code"]):
                    raise ValueError(f"{b['code']} пустая — снаружи стоят только полные коробки")
                con.execute("UPDATE wh_places SET at=?, updated_at=? WHERE code=?", (c["code"], sqldb.now(), b["code"]))
                sqldb.audit(con, actor, "addr_box_move", "wh_places", b["code"], {"было": b["at"] or "", "стало": c["code"]})
                return {"действие": "переставлена", "коробка": b["code"], "ячейка": c["code"], "было": b["at"] or ""}
            items = _contents(con, b["code"])
            if not items:
                raise ValueError(f"{b['code']} пустая — нечего выкладывать")
            for it in items:
                _add(con, b["code"], it["наименование"], -it["количество"])
                _add(con, c["code"], it["наименование"], it["количество"])
            _free_box_if_empty(con, b["code"])
            sqldb.audit(con, actor, "addr_box_open", "wh_places", b["code"], {"в": c["code"], "позиций": len(items)})
            return {"действие": "вскрыта", "коробка": b["code"], "ячейка": c["code"],
                    "штук": sum(i["количество"] for i in items)}
        return _tx(con, run)
    finally:
        con.close()


def move(actor: str, src, dst, items: list[dict]) -> dict:
    """Переложить часть товара: из мешка, коробки или ячейки — в ячейку P, коробку K или мешок M."""
    con = _con()
    try:
        def run():
            s = _need(con, src, "PKM", "ячейка внутри, коробка или мешок")
            d = _need(con, dst, "PKM", "ячейка внутри, коробка или мешок")
            if s["code"] == d["code"]:
                raise ValueError("Откуда и куда — одно и то же место")
            moved = 0.0
            for it in items or []:
                name, q = str(it.get("наименование") or "").strip(), float(it.get("количество") or 0)
                if not name or q <= 0:
                    continue
                _add(con, s["code"], name, -q)
                _add(con, d["code"], name, q)
                moved += q
            if not moved:
                raise ValueError("Укажите, сколько взяли")
            _free_box_if_empty(con, s["code"])
            sqldb.audit(con, actor, "addr_move", "wh_places", s["code"], {"в": d["code"], "шт": moved})
            return {"из": s["code"], "в": d["code"], "штук": moved, "осталось": _contents(con, s["code"])}
        return _tx(con, run)
    finally:
        con.close()


def relabel(actor: str, old, new) -> dict:
    """Потеряли этикетку: содержимое и место переходят на новый код, старый списывается."""
    con = _con()
    try:
        def run():
            o = _need(con, old, "KM", "коробка или мешок")
            n = _need(con, new, o["kind"], KINDS[o["kind"]])
            if o["code"] == n["code"]:
                raise ValueError("Старый и новый код совпадают")
            if _contents(con, n["code"]) or n["at"]:
                raise ValueError(f"{n['code']} уже используется — нужен новый, пустой код")
            for it in _contents(con, o["code"]):
                _add(con, o["code"], it["наименование"], -it["количество"])
                _add(con, n["code"], it["наименование"], it["количество"])
            con.execute("UPDATE wh_places SET at=?, updated_at=? WHERE code=?", (o["at"], sqldb.now(), n["code"]))
            con.execute("UPDATE wh_places SET status='retired', replaced_by=?, at=NULL, updated_at=? WHERE code=?",
                        (n["code"], sqldb.now(), o["code"]))
            sqldb.audit(con, actor, "addr_relabel", "wh_places", o["code"], {"новый": n["code"]})
            return {"старый": o["code"], "новый": n["code"], "содержимое": _contents(con, n["code"]), "где": o["at"] or ""}
        return _tx(con, run)
    finally:
        con.close()


def journal(limit: int = 40) -> list[dict]:
    import json
    con = _con()
    try:
        rows = con.execute("SELECT ts, actor, action, entity_id, payload_json FROM audit_log "
                           "WHERE action LIKE 'addr_%' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        names = {"addr_put": "положил", "addr_box_move": "переставил коробку", "addr_box_open": "вскрыл коробку",
                 "addr_move": "переложил", "addr_relabel": "заменил этикетку", "addr_rack": "создал стеллаж",
                 "addr_issue": "выдал коды"}
        return [{"когда": r["ts"], "кто": r["actor"] or "", "что": names.get(r["action"], r["action"]),
                 "код": r["entity_id"], "данные": json.loads(r["payload_json"] or "{}")} for r in rows]
    finally:
        con.close()
