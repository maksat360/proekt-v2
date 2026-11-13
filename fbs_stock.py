# -*- coding: utf-8 -*-
"""Списания WB по данным SQL — чтобы склад показывал реальный остаток."""
from __future__ import annotations

import sys
import time
from pathlib import Path

_BASE = Path(__file__).resolve().parent
_SQL = _BASE / "sql"
if str(_SQL) not in sys.path:
    sys.path.insert(0, str(_SQL))

_CACHE = {"ts": 0.0, "data": {}}
_TTL = 2.0


def shipped_by_name() -> dict[str, float]:
    """Сколько списано по FBS на каждое наименование."""
    if time.time() - _CACHE["ts"] < _TTL:
        return _CACHE["data"]
    data: dict[str, float] = {}
    try:
        import db as sqldb
        con = sqldb.connect()
        try:
            rows = con.execute(
                """SELECT p.name AS name, SUM(s.qty) AS qty
                   FROM shipments s JOIN products p ON p.id = s.product_id
                   WHERE s.source_sheet = 'FBS'
                   GROUP BY p.name""").fetchall()
            data = {r["name"]: float(r["qty"] or 0) for r in rows}
        finally:
            con.close()
    except Exception:
        data = {}
    _CACHE.update(ts=time.time(), data=data)
    return data


_FACT = {"ts": 0.0, "data": None}


def fact_by_name() -> dict[str, float] | None:
    """Фактический остаток из SQL (размещено − отгружено, включая FBS).
    None — SQL не главный (config «db» не postgres) или база недоступна: склад считает по Excel."""
    if time.time() - _FACT["ts"] < _TTL:
        return _FACT["data"]
    data = None
    try:
        import db as sqldb
        if sqldb.use_pg():
            con = sqldb.connect()
            try:
                rows = con.execute(
                    """SELECT p.name AS name,
                              COALESCE((SELECT SUM(qty) FROM placements WHERE product_id = p.id), 0) -
                              COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id = p.id), 0) AS qty
                       FROM products p""").fetchall()
                data = {r["name"]: float(r["qty"] or 0) for r in rows}
            finally:
                con.close()
    except Exception:
        data = None
    _FACT.update(ts=time.time(), data=data)
    return data
