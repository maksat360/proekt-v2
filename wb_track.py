# -*- coding: utf-8 -*-
"""Анализ чужих артикулов WB: оценка продаж по отзывам.

WB не публикует продажи. Публично доступны последние 1000 отзывов карточки (с датой и артикулом)
и недельная история цены. Отзывы по дням копятся в data/wb_track/<артикул>.json, так что история
растёт дальше 1000 отзывов, если обновлять каждый день (cron запускает скрипт без аргументов —
обновляются все артикулы, которые когда-либо смотрели).
Продажи ≈ отзывы × K: отзыв оставляют примерно 5–10% выкупивших (K = 10–20).

Запуск:  python3 wb_track.py                 — обновить все отслеживаемые
         python3 wb_track.py 227657342 ...   — отчёт по артикулам в консоль
         python3 wb_track.py --serve [8790]  — страница http://localhost:8790
"""
from __future__ import annotations

import gzip
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from wb_api import _ssl_context

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "wb_track"
PAGE = BASE / "static" / "wb_track.html"
K_LOW, K_HIGH = 10, 20
UA = {"User-Agent": "Mozilla/5.0"}
SSL = _ssl_context()  # грузить сертификаты на каждый запрос дорого


def get(url: str):
    for attempt in (1, 2):  # WB иногда подвисает на минуту — второй запрос обычно проходит сразу
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12,
                                        context=SSL) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError:
            raise  # 404 и т.п. — повтор не поможет
        except OSError:
            if attempt == 2:
                raise
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)  # отзывы WB шлёт в gzip без спроса


def feedbacks(imt: int) -> dict:
    try:
        return get(f"https://feedbacks1.wb.ru/feedbacks/v1/{imt}")
    except OSError:
        return get(f"https://feedbacks2.wb.ru/feedbacks/v1/{imt}")


def basket(nm: int, cached: str | None) -> str:
    path = f"/vol{nm // 100000}/part{nm // 1000}/{nm}/info"
    if cached:
        try:
            get(cached + path + "/ru/card.json")
            return cached
        except Exception:
            pass

    def probe(h):
        try:
            get(h + path + "/ru/card.json")
            return h
        except Exception:
            return None
    # сервер карточки заранее не известен — опрашиваем все разом, берём первый ответивший, молчащих не ждём
    ex = ThreadPoolExecutor(40)
    try:
        for fut in as_completed([ex.submit(probe, f"https://basket-{i:02d}.wbbasket.ru") for i in range(1, 41)]):
            if fut.result():
                return fut.result()
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    raise RuntimeError(f"артикул {nm} не найден на WB")


def merge(days: dict, reviews: list, nm: int) -> dict:
    """Дни, целиком покрытые выгрузкой, перезаписываются свежим счётом; более старые остаются из прошлых запусков."""
    mine = [r["createdDate"][:10] for r in reviews if r.get("nmId") == nm]
    if not reviews:
        return days
    oldest = min(r["createdDate"][:10] for r in reviews)  # этот день выгружен не полностью
    fresh = Counter(d for d in mine if d > oldest)
    out = {d: c for d, c in days.items() if d <= oldest}
    out.update(fresh)
    d = date.fromisoformat(oldest) + timedelta(days=1)
    while d <= date.today():  # дни без отзывов — ноль, а не пропуск
        out.setdefault(d.isoformat(), 0)
        d += timedelta(days=1)
    return dict(sorted(out.items()))


def periods(days: dict, price: float) -> list[dict]:
    """Вчера / 7 / 30 дней: отзывы и вилка продаж и выручки. Сегодня не считаем — день не закончился."""
    today, out = date.today(), []
    for label, n in (("вчера", 1), ("7 дней", 7), ("30 дней", 30)):
        span = [(today - timedelta(days=i)).isoformat() for i in range(1, n + 1)]
        if span[-1] not in days:
            out.append({"label": label, "reviews": None})
            continue
        rv = sum(days.get(d, 0) for d in span)
        out.append({"label": label, "reviews": rv, "sales": [rv * K_LOW, rv * K_HIGH],
                    "revenue": [round(rv * K_LOW * price), round(rv * K_HIGH * price)]})
    return out


def track(nm: int) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    f = DATA / f"{nm}.json"
    st = json.loads(f.read_text()) if f.exists() else {"days": {}}
    host = basket(nm, st.get("basket"))
    path = f"{host}/vol{nm // 100000}/part{nm // 1000}/{nm}/info"
    card = get(path + "/ru/card.json")
    try:
        seller = get(path + "/sellers.json")
    except Exception:
        seller = {}
    fb = feedbacks(card["imt_id"])
    try:
        prices = get(path + "/price-history.json")
    except Exception:  # у новых карточек истории цены ещё нет
        prices = []
    reviews = fb.get("feedbacks") or []
    st.update(nm=nm, basket=host, imt=card["imt_id"], name=card.get("imt_name") or card.get("subj_name"),
              seller=seller.get("supplierName"), brand=seller.get("trademark"),
              photo=f"{host}/vol{nm // 100000}/part{nm // 1000}/{nm}/images/c246x328/1.webp",
              price=prices[-1]["price"]["RUB"] / 100 if prices else 0.0,
              prices=[[datetime.fromtimestamp(p["dt"], timezone.utc).date().isoformat(), p["price"]["RUB"] / 100]
                      for p in prices],
              rating=fb.get("valuation"), feedbackCount=fb.get("feedbackCount"),
              colors=Counter(r.get("nmId") for r in reviews).most_common(),  # доля цветов в последних отзывах
              days=merge(st["days"], reviews, nm),
              checked=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    f.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    return st


def report(st: dict) -> str:
    lines = [f"Артикул {st['nm']} «{st['name']}» ({st['seller']}): цена ~{st['price']:.0f} ₽, "
             f"отзывов у карточки {st['feedbackCount']}",
             f"{'период':<12}{'отзывы':>8}{'продажи, шт':>18}{'выручка, ₽':>26}"]
    for p in periods(st["days"], st["price"]):
        if p["reviews"] is None:
            lines.append(f"{p['label']:<12}{'мало истории':>8}")
            continue
        (lo, hi), (rlo, rhi) = p["sales"], p["revenue"]
        lines.append(f"{p['label']:<12}{p['reviews']:>8}{f'{lo}–{hi}':>18}"
                     f"{f'{rlo:,}–{rhi:,}'.replace(',', ' '):>26}")
    lines.append("Оценка грубая: процент выкупа по публичным данным не узнать.")
    return "\n".join(lines)


def tracked() -> list[dict]:
    out = []
    for f in sorted(DATA.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = json.loads(f.read_text())
        out.append({k: st.get(k) for k in ("nm", "name", "seller", "price", "photo", "checked")} | {"nm": int(f.stem)})
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/list":
            return self._json(200, tracked())
        if u.path == "/api/track":
            raw = (parse_qs(u.query).get("nm") or [""])[0].strip()
            if not raw.isdigit() or not 0 < int(raw) < 10**12:  # артикул попадает в путь к файлу — только цифры
                return self._json(400, {"error": "артикул — только цифры"})
            try:
                st = track(int(raw))
            except Exception as e:
                return self._json(502, {"error": str(e)})
            return self._json(200, st | {"periods": periods(st["days"], st["price"]), "k": [K_LOW, K_HIGH]})
        self._send(404, b"not found", "text/plain")

    def log_message(self, *a):
        pass


def _selfcheck():
    rv = [{"nmId": 1, "createdDate": "2026-01-01T10:00:00Z"},  # самый старый день — неполный
          {"nmId": 1, "createdDate": "2026-01-02T10:00:00Z"},
          {"nmId": 1, "createdDate": "2026-01-02T11:00:00Z"},
          {"nmId": 2, "createdDate": "2026-01-03T11:00:00Z"}]  # другой цвет — не считаем
    out = merge({"2025-12-31": 5, "2026-01-01": 7, "2026-01-02": 99}, rv, 1)
    assert out["2025-12-31"] == 5 and out["2026-01-01"] == 7, out  # старое не трогаем
    assert out["2026-01-02"] == 2 and out["2026-01-03"] == 0, out  # свежее перезаписано, пустой день = 0
    y = (date.today() - timedelta(days=1)).isoformat()
    p = periods({y: 3}, 100.0)[0]
    assert p["sales"] == [30, 60] and p["revenue"] == [3000, 6000], p


if __name__ == "__main__":
    _selfcheck()
    args = sys.argv[1:]
    if args[:1] == ["--serve"]:
        port = int(args[1]) if len(args) > 1 else 8790
        print(f"http://localhost:{port}")
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    for a in args or [str(t["nm"]) for t in tracked()]:
        try:
            print(report(track(int(a))), end="\n\n")
        except Exception as e:  # один битый артикул не должен останавливать остальные
            print(f"Артикул {a}: ошибка — {e}\n")
