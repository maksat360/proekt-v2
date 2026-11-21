# -*- coding: utf-8 -*-
"""Замена похожим товаром: если своего цвета не осталось, отправляем похожий того же размера.

data/substitutes.json: {"Брюки/477/синий": "Брюки/477/темно-синий"} — категория/модель/цвет → замена.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / "data" / "substitutes.json"


def load() -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in json.loads(PATH.read_text(encoding="utf-8")).items()}
    except Exception:
        return {}


def for_name(name: str, rules: dict | None = None) -> str | None:
    """«Брюки/477/синий/58» → «Брюки/477/темно-синий/58» (или None, если замены нет)."""
    parts = str(name or "").split("/")
    if len(parts) < 4:
        return None
    sub = (load() if rules is None else rules).get("/".join(parts[:3]))
    return f"{sub}/{'/'.join(parts[3:])}" if sub else None
