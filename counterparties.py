# -*- coding: utf-8 -*-
"""Контрагенты (Номенклатура → Контрагенты): поставщики, покупатели, собственные компании и цеха.
Хранятся в SQL (PostgreSQL), таблица counterparties."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

_SQL = Path(__file__).resolve().parent / "sql"
if str(_SQL) not in sys.path:
    sys.path.insert(0, str(_SQL))

import db as sqldb  # noqa: E402

CATEGORIES = ["Поставщики", "Покупатели", "Собственные компании", "Собственные цеха"]
_READY: set[str] = set()


def _con():
    con = sqldb.connect()
    key = type(con).__name__ + str(getattr(sqldb, "DB_PATH", ""))
    if key not in _READY:
        sqldb.migrate(con)
        _READY.add(key)
    return con


def _find(con, name: str, skip_id: str = ""):
    """id контрагента с таким названием без учёта регистра (SQLite lower() кириллицу не знает)."""
    key = name.casefold()
    return next((r["id"] for r in con.execute("SELECT id, name FROM counterparties")
                 if r["name"].casefold() == key and r["id"] != skip_id), None)


def _row(r) -> dict:
    return {"id": r["id"], "название": r["name"], "категория": r["category"],
            "телефон": r["phone"] or "", "комментарий": r["note"] or ""}


def list_all(seed: list[tuple[str, str]] | None = None) -> list[dict]:
    """Все контрагенты. seed — (название, категория) для первого заполнения: один раз, пока справочник не заведён."""
    con = _con()
    try:
        if seed and not sqldb.get_meta(con, "counterparties_seeded"):
            for name, cat in seed:
                name = str(name or "").strip()
                if name and not _find(con, name):
                    con.execute("INSERT INTO counterparties(id, name, category, created_at) VALUES (?,?,?,?)",
                                (uuid.uuid4().hex[:12], name, cat, sqldb.now()))
            sqldb.set_meta(con, "counterparties_seeded", sqldb.now())
        rows = con.execute("SELECT * FROM counterparties").fetchall()
        return sorted((_row(r) for r in rows), key=lambda x: (x["категория"], x["название"].casefold()))
    finally:
        con.close()


def save(actor: str, body: dict) -> dict:
    """Добавить (без id), изменить (с id) или удалить («удалить»: true)."""
    cid = str(body.get("id") or "").strip()
    con = _con()
    try:
        if body.get("удалить"):
            if not cid:
                raise ValueError("Не выбран контрагент")
            row = con.execute("SELECT name FROM counterparties WHERE id=?", (cid,)).fetchone()
            if not row:
                raise ValueError("Контрагент не найден")
            con.execute("DELETE FROM counterparties WHERE id=?", (cid,))
            sqldb.audit(con, actor, "counterparty_delete", "counterparties", cid, {"название": row["name"]})
            return {"удалён": row["name"]}
        name = str(body.get("название") or "").strip()
        cat = str(body.get("категория") or "").strip()
        if not name:
            raise ValueError("Укажите название")
        if not cat:
            raise ValueError("Укажите категорию")
        if _find(con, name, cid):
            raise ValueError(f"«{name}» уже есть в справочнике")
        phone, note = str(body.get("телефон") or "").strip(), str(body.get("комментарий") or "").strip()
        if cid:
            cur = con.execute("UPDATE counterparties SET name=?, category=?, phone=?, note=?, updated_at=? WHERE id=?",
                              (name, cat, phone, note, sqldb.now(), cid))
            if not cur.rowcount:
                raise ValueError("Контрагент не найден")
            action = "counterparty_edit"
        else:
            cid = uuid.uuid4().hex[:12]
            con.execute("INSERT INTO counterparties(id, name, category, phone, note, created_at) VALUES (?,?,?,?,?,?)",
                        (cid, name, cat, phone, note, sqldb.now()))
            action = "counterparty_add"
        sqldb.audit(con, actor, action, "counterparties", cid, {"название": name, "категория": cat})
        row = con.execute("SELECT * FROM counterparties WHERE id=?", (cid,)).fetchone()
        return _row(row)
    finally:
        con.close()


def names(category: str) -> list[str]:
    con = _con()
    try:
        return sorted((r["name"] for r in con.execute(
            "SELECT name FROM counterparties WHERE category=?", (category,))), key=str.casefold)
    finally:
        con.close()
