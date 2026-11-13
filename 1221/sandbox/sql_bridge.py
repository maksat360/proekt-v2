# -*- coding: utf-8 -*-
"""Мост между приложением и SQL-слоем. Никогда не ломает основную операцию."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
_SQL = BASE / "sql"
if str(_SQL) not in sys.path:
    sys.path.insert(0, str(_SQL))


def shadow(kind: str, payload: dict, actor: str = "") -> dict | None:
    try:
        import shadow as shadow_mod
        return shadow_mod.mirror(kind, payload, actor)
    except Exception as exc:  # noqa: BLE001
        try:
            import db as sqldb
            con = sqldb.connect()
            try:
                sqldb.audit(con, actor, f"shadow_{kind}", "operation", "",
                            payload, f"bridge_error: {exc}")
            finally:
                con.close()
        except Exception:
            pass
        return None


def backend() -> str:
    try:
        import db as sqldb
        return sqldb.backend()
    except Exception:
        return "excel"
