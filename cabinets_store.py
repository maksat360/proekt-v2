# -*- coding: utf-8 -*-
"""Кабинеты Wildberries и их токены.

Токены НЕ хранятся в коде и НЕ попадают в логи.
  data/wb_cabinets.json   — список кабинетов (id, имя, активность)
  secrets/wb_tokens.json  — токены, права 600 (только владелец может читать)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
CABINETS = BASE / "data" / "wb_cabinets.json"
SECRETS_DIR = BASE / "secrets"
TOKENS = SECRETS_DIR / "wb_tokens.json"

DEFAULTS = [
    {"id": "zhsk", "name": "ЖСК", "wb_name": "", "active": 1},
    {"id": "kkm", "name": "ККМ", "wb_name": "", "active": 1},
    {"id": "altyn", "name": "Алтын", "wb_name": "", "active": 1},
]


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_private(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _tokens() -> dict:
    return _read(TOKENS, {})


def cabinets() -> list[dict]:
    """Список кабинетов без токенов, но с признаком «токен задан»."""
    items = _read(CABINETS, None)
    if not items:
        items = [dict(x) for x in DEFAULTS]
        _write_private(CABINETS, items)
    tokens = _tokens()
    out = []
    for c in items:
        token = tokens.get(c["id"], "")
        out.append({
            "id": c["id"],
            "name": c.get("name", c["id"]),
            "wb_name": c.get("wb_name", ""),
            "active": int(c.get("active", 1)),
            "token_set": bool(token),
            "token_hint": (token[:4] + "…" + token[-4:]) if len(token) > 12 else "",
            "last_sync_at": c.get("last_sync_at", ""),
        })
    return out


def clean_token(raw: str) -> str:
    """Убирает подписи, кавычки и пробелы. Токен WB — только латиница и цифры."""
    t = (raw or "").strip().strip('"').strip("'")
    low = t.lower()
    for prefix in ("bearer ", "token:", "token ", "токен:", "токен ", "токен"):
        if low.startswith(prefix):
            t = t[len(prefix):].strip()
            low = t.lower()
    t = t.replace("\u00a0", " ").strip()
    if not t:
        raise ValueError("токен пустой")
    bad = [(i, ch) for i, ch in enumerate(t) if not (ch.isascii() and (ch.isalnum() or ch in "-_.~+/="))]
    if bad:
        pos = bad[0][0]
        sample = "".join(ch for _, ch in bad[:6])
        raise ValueError(
            f"в токене есть недопустимые символы ({sample!r}, начиная с позиции {pos}). "
            "Токен Wildberries — только латинские буквы, цифры и дефис. "
            "Скопируйте его из кабинета WB заново, без слова «токен» и без пробелов.")
    return t


def save_cabinet(cid: str, name: str, token: str | None = None,
                 active: int | None = None) -> dict:
    cid = (cid or "").strip().lower()
    if not cid:
        raise ValueError("нужен id кабинета")
    if not name.strip():
        raise ValueError("нужно название кабинета")

    items = _read(CABINETS, None) or [dict(x) for x in DEFAULTS]
    found = None
    for c in items:
        if c["id"] == cid:
            found = c
            break
    if found is None:
        found = {"id": cid, "name": name.strip(), "wb_name": "", "active": 1}
        items.append(found)
    found["name"] = name.strip()
    if active is not None:
        found["active"] = 1 if active else 0
    _write_private(CABINETS, items)

    if token is not None and token.strip():
        tokens = _tokens()
        tokens[cid] = clean_token(token)
        _write_private(TOKENS, tokens)
    return {"id": cid, "name": found["name"], "active": found["active"]}


def remove_cabinet(cid: str) -> None:
    items = _read(CABINETS, None) or []
    items = [c for c in items if c["id"] != cid]
    _write_private(CABINETS, items)
    tokens = _tokens()
    tokens.pop(cid, None)
    _write_private(TOKENS, tokens)


def token(cid: str) -> str:
    return _tokens().get(cid, "")


def mark_sync(cid: str, error: str = "") -> None:
    items = _read(CABINETS, None) or []
    for c in items:
        if c["id"] == cid:
            c["last_sync_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            c["last_error"] = error
    _write_private(CABINETS, items)


def tokens_are_private() -> bool:
    try:
        return (TOKENS.stat().st_mode & 0o077) == 0
    except OSError:
        return True
