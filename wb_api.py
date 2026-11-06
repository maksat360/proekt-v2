# -*- coding: utf-8 -*-
"""Клиент Wildberries Marketplace API (только стандартная библиотека).

Токен передаётся аргументом и никогда не пишется в логи.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request

BASE = "https://marketplace-api.wildberries.ru"
STATS_BASE = "https://statistics-api.wildberries.ru"
_STATS_CACHE: dict[str, tuple[float, list]] = {}
STATS_TTL = 300
STATS_STATE: dict[str, dict] = {}
TIMEOUT = 20
RETRIES = 2

CA_CANDIDATES = [
    os.environ.get("V2_CA_BUNDLE", ""),
    "/etc/ssl/cert.pem",
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/usr/local/etc/openssl/cert.pem",
]


def _ssl_context():
    """На этом Mac у Python нет своих корневых сертификатов — берём системные."""
    for path in CA_CANDIDATES:
        if path and os.path.exists(path) and os.path.getsize(path) > 1024:
            try:
                return ssl.create_default_context(cafile=path)
            except Exception:
                continue
    return ssl.create_default_context()


class WbError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _request(path: str, token: str, method: str = "GET", payload=None) -> dict:
    if not token:
        raise WbError("не задан токен кабинета", 401)
    if not token.isascii():
        raise WbError("токен содержит не-латинские символы — проверьте его в настройках кабинета", 401)
    data = None
    headers = {"Authorization": token, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:4000]
            except Exception:
                pass
            detail = body
            try:
                parsed = json.loads(body)
                detail = str(parsed.get("detail") or parsed.get("title") or body)[:160]
            except Exception:
                pass
            if exc.code == 401:
                detail = "токен неверный или просрочен (" + detail[:120] + ")"
            last = WbError(f"WB {exc.code}: {detail}", exc.code)
            if exc.code == 429 and attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
            raise last from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            text = str(exc)
            if "CERTIFICATE_VERIFY_FAILED" in text:
                last = WbError("не удалось проверить сертификат WB (проблема с сертификатами на Mac)", 0)
            else:
                last = WbError(f"нет связи с WB: {text}", 0)
            if attempt < RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last from None
    raise last or WbError("неизвестная ошибка")


def new_orders(token: str) -> list[dict]:
    """Новые сборочные задания (раздел «Новые» в кабинете WB)."""
    data = _request("/api/v3/orders/new", token)
    return list(data.get("orders") or [])


def all_orders(token: str, max_pages: int = 6, limit: int = 1000) -> dict[str, dict]:
    """Все заказы кабинета: id → заказ (в нём есть supplyId — признак поставки)."""
    out: dict[str, dict] = {}
    nxt = 0
    for _ in range(max_pages):
        data = _request(f"/api/v3/orders?limit={limit}&next={nxt}", token)
        orders = data.get("orders") or []
        for o in orders:
            oid = str(o.get("id") or "")
            if oid:
                out[oid] = o
        nxt = data.get("next")
        if not nxt or not orders:
            break
    return out


def confirm_orders(token: str, order_ids: list[int]) -> dict:
    """Переводит заказы в сборку (статус confirm)."""
    if not order_ids:
        return {}
    return _request("/api/v3/orders/status", token, method="POST",
                    payload={"orders": [{"id": int(i), "status": "confirm"} for i in order_ids]})


def ping(token: str) -> dict:
    """Проверка токена: пробуем получить новые заказы."""
    return {"orders": len(new_orders(token))}


def statistics_orders(token: str, date_from: str) -> list[dict]:
    """Заказы из Статистики WB: точные отмены (isCancel, cancelDate).

    Лимит WB — 1 запрос в минуту, поэтому кэшируем на 2 минуты.
    """
    import hashlib
    key = hashlib.sha1(token.encode()).hexdigest()[:12]
    cached = _STATS_CACHE.get(key)
    if cached and time.time() - cached[0] < STATS_TTL:
        return cached[1]

    url = f"{STATS_BASE}/api/v1/supplier/orders?dateFrom={date_from}"
    req = urllib.request.Request(url, headers={"Authorization": token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            data = json.loads(resp.read() or b"[]")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            STATS_STATE[key] = {"ok": False, "error": "лимит WB: 1 запрос в минуту", "ts": time.time()}
            return cached[1] if cached else []
        STATS_STATE[key] = {"ok": False, "error": f"WB {exc.code}", "ts": time.time()}
        raise WbError(f"WB {exc.code}: статистика недоступна", exc.code) from None
    except Exception:
        return cached[1] if cached else []

    if not isinstance(data, list):
        data = []
    STATS_STATE[key] = {"ok": True, "error": "", "ts": time.time(), "rows": len(data)}
    _STATS_CACHE[key] = (time.time(), data)
    return data


def statistics_state(token: str) -> dict:
    import hashlib
    key = hashlib.sha1(token.encode()).hexdigest()[:12]
    st = dict(STATS_STATE.get(key) or {"ok": None, "rows": 0, "error": ""})
    cached = _STATS_CACHE.get(key)
    st["есть_кэш"] = bool(cached)
    st["кэш_возраст_сек"] = int(time.time() - cached[0]) if cached else None
    return st
