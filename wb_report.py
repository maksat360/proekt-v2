# -*- coding: utf-8 -*-
"""Аналитика Wildberries на «Сводке»: заказы, выкупы, возвраты, остатки на складах WB и сезонность.

Данные берутся ключом аналитики кабинета (только чтение), без него — основным токеном.
Заказы и выкупы каждый час дописываются в базу (wb_orders, wb_sales) — история копится и не пропадает,
когда WB перестаёт их отдавать. Старые продажи (с 29.01.2024) — из отчёта о реализации (раздел «Финансы»).
Артикулы WB переводятся в наши категория/модель/цвет/размер по баркоду (лист «главный», колонка T).
WB разрешает ~1 запрос в минуту на метод, за частые запросы закрывает на часы — всё идёт в фоне,
время ожидания берём из ответа WB."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import cabinets_store
import wb_api

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402

CACHE = BASE / "data" / "wb_analytics"
if sqldb._testing():  # тесты не трогают ни рабочую базу, ни data/
    CACHE = Path(tempfile.mkdtemp(prefix="v2-wb-"))
DAYS = 30
TTL = 3600  # сек: WB даёт выкупы раз в пару часов, остатки — раз в несколько минут
HISTORY_TTL = 7 * 86400  # отчёт о реализации еженедельный
HISTORY_FROM = "2024-01-29"  # раньше WB не хранит
STATS = "https://statistics-api.wildberries.ru"
ANALYTICS = "https://seller-analytics-api.wildberries.ru"
FINANCE = "https://finance-api.wildberries.ru"
SCOPE = {STATS: "Статистика", ANALYTICS: "Аналитика", FINANCE: "Финансы"}
# строки отчёта остатков, которые не склады
ON_WB, TO_CLIENT, FROM_CLIENT = "Всего находится на складах", "В пути до получателей", "В пути возвраты на склад WB"
PARTS = ("заказы", "выкупы", "остатки", "история")
# коды цвета в старых артикулах WB (483-пт, 28б-ч); пт и с подтвердил владелец
COLOR_CODES = {"ч": "чёрный", "б": "бежевый", "с": "серый", "пт": "синий", "мп": "мята пыльная",
               "ссм": "светло-серый меланж"}
REAL_FIELDS = ["rrdId", "srid", "sellerOperName", "saleDt", "vendorCode", "techSize", "sku",
               "subjectName", "quantity", "forPay", "currency"]

_BUSY: set = set()
_LOCK = threading.Lock()
_READY: set = set()
_CAT = {"ts": 0.0, "data": None}


class Limited(wb_api.WbError):
    """WB назвал, через сколько секунд можно повторить."""
    def __init__(self, retry: int):
        super().__init__(f"лимит WB — разрешит через ~{max(1, round(retry / 60))} мин", 429)
        self.retry = retry


def _get(url: str, token: str, body: dict | None = None, tries: int = 3):
    """GET, или POST с JSON, если есть body. 204 (нет данных) → None."""
    for i in range(tries):
        req = urllib.request.Request(url, headers={"Authorization": token, "Accept": "application/json",
                                                   "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=180, context=wb_api._ssl_context()) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry = int(e.headers.get("X-Ratelimit-Retry") or 60)
                if retry <= 70 and i < tries - 1:
                    time.sleep(retry + 2)
                    continue
                raise Limited(retry) from None  # долгое ожидание — не держим поток, запомним время
            host = next((h for h in SCOPE if url.startswith(h)), "")
            raise wb_api.WbError({401: "ключ неверный или просрочен",
                                  403: f"в ключе нет раздела «{SCOPE.get(host, '?')}»"}.get(e.code, f"WB ответил {e.code}"),
                                 e.code) from None


# ------------------------------------------------------------------ история в базе
def _db():
    if sqldb.use_pg():
        con, key = sqldb.connect(), "pg"
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / "wb.sqlite"
        con, key = sqldb.connect(path), str(path)
    if key not in _READY:
        con.execute("""CREATE TABLE IF NOT EXISTS wb_orders (
            cabinet TEXT NOT NULL, srid TEXT NOT NULL, day TEXT NOT NULL, article TEXT, size TEXT,
            barcode TEXT, subject TEXT, cancel INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (cabinet, srid))""")
        con.execute("""CREATE TABLE IF NOT EXISTS wb_sales (
            cabinet TEXT NOT NULL, srid TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL, article TEXT,
            size TEXT, barcode TEXT, subject TEXT, qty INTEGER NOT NULL DEFAULT 1, for_pay REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT '', PRIMARY KEY (cabinet, srid, kind))""")
        if key == "pg":  # sqlite-файл теста может быть пересоздан — для него проверяем всегда
            _READY.add(key)
    return con


def _bulk(sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    con = _db()
    try:
        con.execute("BEGIN")
        for r in rows:
            con.execute(sql, r)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return len(rows)


def store_orders(cid: str, data) -> int:
    rows = [(cid, str(o["srid"]), str(o.get("date", ""))[:10], str(o.get("supplierArticle") or ""),
             str(o.get("techSize") or ""), str(o.get("barcode") or ""), str(o.get("subject") or ""),
             1 if o.get("isCancel") else 0) for o in data or [] if o.get("srid")]
    return _bulk("""INSERT INTO wb_orders(cabinet, srid, day, article, size, barcode, subject, cancel)
                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (cabinet, srid) DO UPDATE SET cancel = excluded.cancel""", rows)


def store_sales(cid: str, data) -> int:
    """Выкупы из Статистики: saleID «S…» — продажа, «R…» — возврат."""
    rows = [(cid, str(s["srid"]), "return" if str(s.get("saleID", "")).startswith("R") else "sale",
             str(s.get("date", ""))[:10], str(s.get("supplierArticle") or ""), str(s.get("techSize") or ""),
             str(s.get("barcode") or ""), str(s.get("subject") or ""), 1, abs(float(s.get("forPay") or 0)), "")
            for s in data or [] if s.get("srid")]
    return _bulk("""INSERT INTO wb_sales(cabinet, srid, kind, day, article, size, barcode, subject, qty, for_pay, currency)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (cabinet, srid, kind) DO NOTHING""", rows)


def store_realization(cid: str, data) -> int:
    """Отчёт о реализации: берём только строки «Продажа» и «Возврат» (логистика, штрафы — не товар)."""
    kinds = {"Продажа": "sale", "Возврат": "return"}
    rows = [(cid, str(x["srid"]), kinds[x.get("sellerOperName")], str(x.get("saleDt") or "")[:10],
             str(x.get("vendorCode") or ""), str(x.get("techSize") or ""), str(x.get("sku") or ""),
             str(x.get("subjectName") or ""), int(x.get("quantity") or 1), abs(float(x.get("forPay") or 0)),
             str(x.get("currency") or ""))
            for x in data or [] if x.get("srid") and x.get("sellerOperName") in kinds and x.get("saleDt")]
    return _bulk("""INSERT INTO wb_sales(cabinet, srid, kind, day, article, size, barcode, subject, qty, for_pay, currency)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (cabinet, srid, kind)
                    DO UPDATE SET qty = excluded.qty, for_pay = excluded.for_pay, currency = excluded.currency""", rows)


# ------------------------------------------------------------------ перевод артикулов WB
def _catalog():
    """(баркоды → наименование, (артикул, размер) → наименование, наименование → поля товара); кэш 10 мин."""
    if _CAT["data"] is None or time.time() - _CAT["ts"] > 600:
        import warehouse
        idx = warehouse.article_index()
        con = sqldb.connect()
        try:
            prods = {r["name"]: (r["category"], r["model"], r["color"], r["size"])
                     for r in con.execute("SELECT name, category, model, color, size FROM products").fetchall()}
        finally:
            con.close()
        _CAT.update(ts=time.time(), data=(idx["barcodes"], idx["pairs"], prods, warehouse._norm, warehouse._size))
    return _CAT["data"]


def resolve(barcode: str, article: str, size: str, subject: str = "") -> tuple[str, str, str, str]:
    """→ (категория, модель, цвет, размер). Не нашли в справочнике — категория WB, артикул как модель."""
    barcodes, pairs, prods, norm, sz = _catalog()
    name = barcodes.get(str(barcode or "").strip()) or pairs.get((norm(article), sz(size)))
    p = prods.get(name)
    if p and p[1]:
        return tuple(str(v or "—").strip() or "—" for v in p)
    # «483-пт», «477-ч-сред»: модель — цифры, цвет — код после дефиса; неизвестный код — без цвета
    m = re.match(r"\d+", str(article or ""))
    code = str(article or "").lower().split("-")[1:2]
    return (subject or "Нет в справочнике", m.group(0) if m else (article or "—"),
            COLOR_CODES.get(code[0], "—") if code else "—", str(size or "—"))


# ------------------------------------------------------------------ выгрузка из WB
def _remains(token: str) -> list:
    url = f"{ANALYTICS}/api/v1/warehouse_remains?groupBySa=true&groupBySize=true&groupByBarcode=true"
    task = _get(url, token)["data"]["taskId"]
    for _ in range(30):
        time.sleep(6)
        st = _get(f"{ANALYTICS}/api/v1/warehouse_remains/tasks/{task}/status", token)["data"]["status"]
        if st == "done":
            return _get(f"{ANALYTICS}/api/v1/warehouse_remains/tasks/{task}/download", token) or []
        if st in ("canceled", "purged"):
            break
    raise wb_api.WbError("WB не успел собрать отчёт об остатках")


def _history(cid: str, token: str, part: dict, save) -> None:
    """Отчёт о реализации страницами (1 в минуту), с продолжением после перезапуска."""
    if not part.get("идёт"):
        done = part.get("загружено_до")
        part.update(с=(date.fromisoformat(done) - timedelta(days=14)).isoformat() if done else HISTORY_FROM,
                    курсор=0, идёт=True, строк=0)
    today = date.today().isoformat()
    while True:
        rows = _get(f"{FINANCE}/api/finance/v1/sales-reports/detailed", token,
                    {"dateFrom": part["с"], "dateTo": today, "limit": 100000, "rrdId": part["курсор"],
                     "period": "weekly", "fields": REAL_FIELDS})
        if not rows:
            break
        store_realization(cid, rows)
        part.update(курсор=rows[-1]["rrdId"], строк=part.get("строк", 0) + len(rows))
        save()
        time.sleep(62)  # лимит метода — 1 запрос в минуту
    part.update(идёт=False, курсор=0, загружено_до=today)


def _load(cid: str) -> dict:
    try:
        data = json.loads((CACHE / f"{cid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {n: v for n, v in data.items() if n in PARTS}  # старый формат кэша отбрасываем


def _due(name: str, part: dict | None, ttl: int) -> bool:
    part = part or {}
    if time.time() < part.get("ждать_до", 0):
        return False
    if name == "история":
        return part.get("идёт") or time.time() - part.get("ts", 0) > max(ttl, HISTORY_TTL)
    return time.time() - part.get("ts", 0) > ttl


def refresh(cid: str, ttl: int = TTL) -> None:
    """Докачать устаревшие части кабинета. Не скачалось — остаётся прошлое, пишем причину."""
    token = cabinets_store.analytics_token(cid)
    since = (date.today() - timedelta(days=DAYS)).isoformat()
    cache = _load(cid)

    def save():
        CACHE.mkdir(parents=True, exist_ok=True)  # пишем после каждой части — страница видит прогресс
        tmp = CACHE / f"{cid}.tmp"
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE / f"{cid}.json")

    for name in PARTS:
        part = cache.setdefault(name, {})
        if not _due(name, part, ttl):
            continue
        print(f"wb_report: {cid} {name} — запрос в WB", file=sys.stderr, flush=True)
        try:
            if name == "заказы":
                part["строк"] = store_orders(cid, _get(f"{STATS}/api/v1/supplier/orders?dateFrom={since}", token))
            elif name == "выкупы":
                part["строк"] = store_sales(cid, _get(f"{STATS}/api/v1/supplier/sales?dateFrom={since}", token))
            elif name == "остатки":
                part["data"] = _remains(token) or []
            else:
                _history(cid, token, part, save)
            part.update(ts=time.time(), ошибка="", ждать_до=0)
        except Limited as exc:
            until = time.time() + exc.retry
            part.update(ошибка="лимит WB — разрешит в " + datetime.fromtimestamp(until).strftime("%d.%m %H:%M"),
                        ждать_до=until)
        except Exception as exc:  # noqa: BLE001 — показываем текст на странице
            wait = 6 * 3600 if getattr(exc, "status", 0) in (401, 403) else 300
            part.update(ошибка=str(exc), ждать_до=time.time() + wait)
        save()


def _run(cid: str, ttl: int) -> None:
    try:
        refresh(cid, ttl)
    finally:
        with _LOCK:
            _BUSY.discard(cid)


def _kick(cabs: list[dict], ttl: int) -> None:
    """Запустить фоновую докачку кабинетов, у которых что-то устарело."""
    for c in cabs:
        if not cabinets_store.analytics_token(c["id"]):
            continue
        cache = _load(c["id"])
        with _LOCK:
            if c["id"] not in _BUSY and any(_due(n, cache.get(n), ttl) for n in PARTS):
                _BUSY.add(c["id"])
                threading.Thread(target=_run, args=(c["id"], ttl), daemon=True).start()


def loop() -> None:
    """Раз в час докачиваем все кабинеты — история копится, даже если Сводку никто не открывает."""
    time.sleep(120)
    while True:
        try:
            _kick([c for c in cabinets_store.cabinets() if c["active"]], TTL)
        except Exception as exc:  # noqa: BLE001
            print(f"wb_report: фоновая докачка: {exc}", file=sys.stderr, flush=True)
        time.sleep(3600)


# ------------------------------------------------------------------ отчёт
def _row():
    return {"заказы_7": 0, "заказы_30": 0, "отмены_30": 0, "выкупы_30": 0, "возвраты_30": 0,
            "к_перечислению": 0.0, "на_wb": 0, "к_клиенту": 0, "от_клиента": 0}


def build(cids: list[str], remains: dict, today: date | None = None) -> tuple[list[dict], str]:
    """Строки отчёта по нашим категория/модель/цвет/размер + продажи по месяцам; и валюта выплат."""
    today = today or date.today()
    d30, d7 = (today - timedelta(days=DAYS)).isoformat(), (today - timedelta(days=7)).isoformat()
    out = defaultdict(_row)
    months = defaultdict(lambda: defaultdict(int))
    arts = defaultdict(set)

    def key(barcode, article, size, subject):
        k = resolve(barcode, article, size, subject)
        if article:
            arts[k].add(article)
        return k

    currency = ""
    if cids:
        marks = ",".join("?" * len(cids))
        con = _db()
        try:
            orders = con.execute(f"""SELECT article, size, barcode, subject, day, cancel FROM wb_orders
                                     WHERE cabinet IN ({marks}) AND day >= ?""", (*cids, d30)).fetchall()
            sales = con.execute(f"""SELECT article, size, barcode, subject, day, kind, qty, for_pay FROM wb_sales
                                    WHERE cabinet IN ({marks}) AND day >= ?""", (*cids, d30)).fetchall()
            monthly = con.execute(f"""SELECT article, size, barcode, subject, substr(day, 1, 7) AS m, SUM(qty) AS q
                                      FROM wb_sales WHERE cabinet IN ({marks}) AND kind = 'sale'
                                      GROUP BY article, size, barcode, subject, substr(day, 1, 7)""", cids).fetchall()
            cur = con.execute(f"""SELECT currency, COUNT(*) AS n FROM wb_sales WHERE cabinet IN ({marks})
                                  AND currency <> '' GROUP BY currency ORDER BY COUNT(*) DESC""", cids).fetchall()
            currency = cur[0]["currency"] if cur else ""
        finally:
            con.close()
        for o in orders:
            r = out[key(o["barcode"], o["article"], o["size"], o["subject"])]
            if o["cancel"]:
                r["отмены_30"] += 1
                continue
            r["заказы_30"] += 1
            r["заказы_7"] += o["day"] >= d7
        for s in sales:
            r = out[key(s["barcode"], s["article"], s["size"], s["subject"])]
            ret = s["kind"] == "return"
            r["возвраты_30" if ret else "выкупы_30"] += s["qty"]
            r["к_перечислению"] += -s["for_pay"] if ret else s["for_pay"]
        for m in monthly:
            months[key(m["barcode"], m["article"], m["size"], m["subject"])][m["m"]] += int(m["q"] or 0)
    for x in remains:
        r = out[key(x.get("barcode"), x.get("vendorCode"), x.get("techSize"), "")]
        for w in x.get("warehouses") or []:
            k = {ON_WB: "на_wb", TO_CLIENT: "к_клиенту", FROM_CLIENT: "от_клиента"}.get(w.get("warehouseName"))
            if k:
                r[k] += int(w.get("quantity") or 0)
    rows = []
    for k in set(out) | set(months):
        cat, model, color, size = k
        rows.append({"категория": cat, "модель": model, "цвет": color, "размер": size,
                     "артикулы_wb": sorted(arts[k]), **{n: round(v, 2) for n, v in out[k].items()},
                     "месяцы": dict(months[k])})
    return rows, currency


def report(cab: str = "all", force: bool = False) -> dict:
    """cab — код кабинета или «all» (все активные вместе). Устаревшее докачивается в фоне."""
    active = [c for c in cabinets_store.cabinets() if c["active"]]
    cabs = [c for c in active if cab == "all" or c["id"] == cab]
    _kick(cabs, 600 if force else TTL)  # «Обновить» не чаще раза в 10 мин: за частые запросы WB закрывает на часы
    info, remains, have = [], [], []
    for c in cabs:
        has_key = bool(cabinets_store.analytics_token(c["id"]))
        cache = _load(c["id"])
        remains += (cache.get("остатки") or {}).get("data") or []
        if has_key:
            have.append(c["id"])
        parts = {}
        for n in PARTS:
            part = cache.get(n) or {}
            parts[n] = {"обновлено": datetime.fromtimestamp(part["ts"]).strftime("%d.%m %H:%M") if part.get("ts") else "",
                        "ошибка": part.get("ошибка", ""),
                        "идёт": bool(part.get("идёт")), "строк": part.get("строк", 0)}
        with _LOCK:
            busy = c["id"] in _BUSY
        info.append({"id": c["id"], "name": c["name"], "ключ": has_key, "обновляется": busy, "части": parts,
                     "остатки": (cache.get("остатки") or {}).get("data") is not None})
    rows, currency = build(have, remains)
    return {"дней": DAYS, "все": [{"id": c["id"], "name": c["name"]} for c in active],
            "кабинеты": info, "строки": rows, "валюта": currency}
