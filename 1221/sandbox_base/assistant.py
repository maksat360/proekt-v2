# -*- coding: utf-8 -*-
"""Голосовой помощник «Джарвис» на сайте.

Модель — та же, что у OpenJarvis на этом Маке (Ollama, стиль из ~/.openjarvis/jarvis_style.md),
но БЕЗ инструментов OpenJarvis (shell, файлы, код). Вместо них — свои узкие инструменты, которые
сервер даёт по правам сотрудника: открыть раздел из его меню, остатки склада, заказы WB, обновить заказы.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

JARVIS_HOME = Path.home() / ".openjarvis"
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_STYLE = ("Ты — Джарвис, вежливый ИИ-ассистент. Отвечай только по-русски, коротко, 1–2 предложения, "
                 "обращайся «сэр», тон — спокойный английский дворецкий.")


def _style() -> str:
    try:
        return (JARVIS_HOME / "jarvis_style.md").read_text(encoding="utf-8").strip() or DEFAULT_STYLE
    except OSError:
        return DEFAULT_STYLE


def _model() -> str:
    try:
        import tomllib
        cfg = tomllib.loads((JARVIS_HOME / "config.toml").read_text(encoding="utf-8"))
        return cfg.get("intelligence", {}).get("default_model") or "qwen3.5:4b"
    except Exception:
        return "qwen3.5:4b"


def short_name(fio: str) -> str:
    """«Есенбаев Максат Замирбекович» → «Максат Замирбекович»."""
    parts = (fio or "").split()
    return " ".join(parts[1:3]) if len(parts) >= 2 else (fio or "").strip()


def greeting(fio: str, now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    part = "Доброе утро" if 5 <= h < 12 else "Добрый день" if h < 18 else "Добрый вечер" if h < 23 else "Доброй ночи"
    name = short_name(fio)
    return f"{part}, {name}, сэр. Джарвис к вашим услугам." if name else f"{part}, сэр. Джарвис к вашим услугам."


def farewell(fio: str, now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    wish = "Хорошего дня" if 5 <= h < 17 else "Хорошего вечера" if h < 23 else "Спокойной ночи"
    name = short_name(fio)
    return f"До свидания, {name}, сэр. {wish}." if name else f"До свидания, сэр. {wish}."


def _clean_sections(raw) -> list[dict]:
    out = []
    for s in raw or []:
        if isinstance(s, dict) and str(s.get("id", "")).strip() and str(s.get("label", "")).strip():
            out.append({"id": str(s["id"])[:40], "label": str(s["label"])[:80]})
    return out[:80]


def _norm(t: str) -> str:
    return re.sub(r"[^а-яa-z0-9 ]", " ", (t or "").lower().replace("ё", "е"))


def _match(text: str, sections: list[dict]) -> str:
    """Без модели: раздел, чьё название встречается в просьбе («открой склад»)."""
    words = set(_norm(text).split())
    best, score = "", 0
    for s in sections:
        lw = [w for w in _norm(s["label"]).split() if len(w) > 2]
        hit = sum(1 for w in lw if any(x.startswith(w[:5]) for x in words))
        if lw and hit > score:
            best, score = s["id"], hit
    return best


def _history(raw) -> list[dict]:
    """Последние реплики разговора (только текст, без системных сообщений от клиента)."""
    out = []
    for m in (raw or [])[-8:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip():
            out.append({"role": m["role"], "content": str(m["content"])[:400]})
    return out


def _chat(messages: list[dict], json_mode: bool = False, limit: int = 200) -> str:
    body = {"model": _model(), "stream": False, "think": False, "keep_alive": "30m",  # модель держим в памяти
            "options": {"temperature": 0.5, "num_predict": limit}, "messages": messages}
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))["message"].get("content", "")


def _clean_answer(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"[*#`_>|]", "", text)  # ответ читают вслух — без разметки
    return re.sub(r"\s+", " ", text).strip()[:500]


TALK = ("Говори живо и естественно, как человек в разговоре: одно-два коротких предложения, сразу к делу, "
        "без списков и канцелярита. Числа пиши цифрами (49, а не «сорок девять»). Не здоровайся — вы уже поздоровались.")


# пересказ данных — короткой ролью: с длинным стилем маленькая модель путает и «прописывает» числа
PLAIN = ("Ты Джарвис, вежливый помощник-дворецкий, обращаешься «сэр». " + TALK
         + " Отвечай только по данным, числа переписывай точно, цифрами.")

_TENS = {"сорок": 40, "пятьдесят": 50, "пятидесят": 50, "шестьдесят": 60, "шестидесят": 60, "тридцат": 30}
_UNITS = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8, "девят": 9}


def _spoken_numbers(text: str) -> str:
    """«сорок шестого» → «46», «пятьдесят второй» → «52» — размеры часто говорят словами."""
    words, out, i = _norm(text).split(), [], 0
    while i < len(words):
        tens = next((v for k, v in _TENS.items() if words[i].startswith(k)), None)
        if tens:
            unit = next((v for k, v in _UNITS.items() if i + 1 < len(words) and words[i + 1].startswith(k)), None)
            out.append(str(tens + (unit or 0)))
            i += 2 if unit else 1
            continue
        out.append(words[i])
        i += 1
    return " ".join(out)


def _intent(text: str, tools: dict) -> str:
    """Какие данные нужны — по словам вопроса: надёжнее и на один запрос к модели быстрее."""
    t = _norm(text)
    if re.search(r"откр|перейд|перейти|зайд|зайти|покажи раздел|вкладк", t) and not re.search(r"скольк|обнов", t):
        return ""  # «открой заказы ВБ» — это раздел, а не данные
    wb = re.search(r"вб|wb|вайлд|валдб|вилдб|фбс|fbs", t)
    if "wb_refresh" in tools and re.search(r"обнов|синхрон|подтян|загруз", t) and (wb or "заказ" in t):
        return "wb_refresh"
    if "wb_orders" in tools and "заказ" in t and (wb or re.search(r"пришл|новых|новые|сегодня|сколько", t)):
        return "wb_orders"
    if "stock" in tools and not re.search(r"стоит|цена|цену", t) and re.search(
            r"склад|остат|осталос|налич|сколько|есть ли|закончил|штук", t):
        return "stock"
    return ""


def ask(fio: str, role: str, text: str, sections, history=None, tools=None) -> dict:
    """Ответ помощника: {"ответ": текст для озвучки, "открыть": id раздела из меню или ""}.

    tools — {имя: (описание, параметры, функция)}: сервер даёт только то, на что у сотрудника есть право
    (остатки склада, заказы WB, обновить заказы). Модель только выбирает действие; данные берёт сервер,
    и второй короткий запрос пересказывает их по-человечески. Два быстрых шага вместо «размышлений» модели.
    """
    text = (text or "").strip()[:500]
    secs = _clean_sections(sections)
    ids = {s["id"] for s in secs}
    tools = tools or {}
    if not text:
        return {"ответ": "Слушаю вас, сэр.", "открыть": ""}
    menu = "\n".join(f"- {s['id']}: {s['label']}" for s in secs) or "- (разделов нет)"
    acts = "\n".join(f"- {n}: {d[0]}" for n, d in tools.items())
    system = (_style() + "\n\n" + TALK + "\n"
              f"Ты помощник на сайте швейного производства. С тобой говорит сотрудник {short_name(fio) or 'без имени'}, "
              f"роль: {role or 'не указана'}. Ты не знаешь устройство программы, её код, файлы и базы данных "
              "и никогда это не обсуждаешь. Цифры никогда не выдумывай.\n"
              "Разделы и вкладки, доступные этому сотруднику (id: название; «Раздел → вкладка» — вкладка внутри):\n"
              + menu + "\n"
              "Действия:\n- open: открыть раздел или вкладку из списка (id), когда сотрудник ищет раздел или хочет что-то "
              "там сделать (купить, заказать — «Магазин»); вкладку — именно вкладкой.\n"
              + (acts + "\n" if acts else "- данных (остатки, заказы) этому сотруднику не положено — так и скажи.\n")
              + "- none: просто ответить.\n"
              "Раздела нет в списке — скажи, что доступа нет. id вслух не произноси.\n"
              'Ответь строго JSON: {"действие": "open|' + "|".join(tools) + ('|' if tools else '') + 'none", '
              '"id": "id раздела для open", "запрос": "что искать для stock (модель, цвет, размер)", '
              '"ответ": "что сказать вслух (для stock/wb_* — коротко «сейчас посмотрю»)"}')
    messages = [{"role": "system", "content": system}, *_history(history), {"role": "user", "content": text}]
    act = _intent(text, tools)
    if act:  # данные понятны по словам — сразу к ним, без первого запроса
        return _answer_with_data(text, act, tools, {"запрос": _spoken_numbers(text)})
    try:
        data = json.loads(_chat(messages, json_mode=True, limit=160))
    except Exception:  # Ollama выключена или ответила не JSON — открываем по названию
        target = _match(text, secs)
        label = next((s["label"] for s in secs if s["id"] == target), "")
        return {"ответ": f"Открываю «{label}», сэр." if label else "Боюсь, сейчас я не на связи, сэр. Выберите раздел в меню.",
                "открыть": target, "без_модели": True}
    act = str(data.get("действие") or "none").strip()
    answer = _clean_answer(str(data.get("ответ") or ""))
    target = str(data.get("id") or "").strip() if act == "open" else ""
    if target not in ids:  # открываем только то, что сотрудник и так видит
        target = ""
    if act in tools:
        return _answer_with_data(text, act, tools, {"запрос": _spoken_numbers(str(data.get("запрос") or text))})
    if not answer:
        label = next((s["label"] for s in secs if s["id"] == target), "")
        answer = f"Открываю «{label}», сэр." if label else "Слушаю, сэр."
    return {"ответ": answer, "открыть": target}


def _answer_with_data(text: str, act: str, tools: dict, args: dict) -> dict:
    """Берём данные функцией сервера (по правам сотрудника) и пересказываем их по-человечески."""
    desc, props, fn = tools[act]
    try:
        facts = str(fn(**(args if props else {})))[:3000]
    except Exception as exc:  # noqa: BLE001
        facts = f"не получилось: {exc}"
    try:
        answer = _clean_answer(_chat([
            {"role": "system", "content": PLAIN},
            {"role": "user", "content": f"Вопрос: «{_spoken_numbers(text)}»\nДанные ({desc}): {facts}\nОтветь на вопрос по этим данным."}],
            limit=140))
    except Exception:  # noqa: BLE001
        answer = facts[:300]
    return {"ответ": answer or facts[:300], "открыть": ""}


# ------------------------------------------------ данные для инструментов (сервер даёт по правам)
def _word_hit(word: str, tokens: list[str]) -> bool:
    """«чёрных» ~ «черный», «брюк» ~ «брюки»: слова — по началу, числа (размер, модель) — точно."""
    if word.isdigit():
        return word in tokens
    stem = word[:4] if len(word) > 4 else word
    return any(t.startswith(stem) or (len(t) >= 3 and word.startswith(t)) for t in tokens)


_FILLER = ("скольк", "всег", "есть", "оста", "склад", "штук", "това", "размер", "цвет", "модел", "налич", "меньш",
           "больш", "всех", "как", "самы", "мало", "много", "законч", "нет", "пожалуй", "джарвис", "сэр", "покаж",
           "скаж", "нас", "мне", "там", "сейчас", "сегодня", "вообще", "ещё", "еще", "что", "где", "каких", "проверь",
           "посмотр", "узна", "готов", "продукц", "пар", "единиц")


def stock_summary(items: list[dict], запрос: str = "") -> str:
    """Остатки склада по словам запроса (модель, цвет, размер, категория) — кратко, для ответа вслух."""
    rows_tokens = [(it, _norm(" ".join(str(it.get(k, "")) for k in ("категория", "модель", "цвет", "размер"))).split())
                   for it in items]
    # служебные слова вопроса («сколько», «осталось», «на складе»…) не ищем; остальное — должно найтись
    words = [w for w in _norm(запрос).split()
             if (len(w) >= 3 or w.isdigit()) and not any(w.startswith(x) for x in _FILLER)]
    rows = [it for it, toks in rows_tokens if all(_word_hit(w, toks) for w in words)]
    if not rows:
        return f"по запросу «{запрос}» на складе ничего не найдено"
    qty = lambda it: float(it.get("остаток") or 0)  # noqa: E731
    name = lambda it: f"{it.get('категория')} модель {it.get('модель')} {it.get('цвет')} размер {it.get('размер')}"  # noqa: E731
    with_stock = sorted((it for it in rows if qty(it) > 0), key=qty)
    total = sum(qty(it) for it in with_stock) if with_stock else 0  # минус (пересорт) в «есть» не считаем
    if not with_stock:
        return f"найдено {len(rows)} позиций, но в наличии 0 шт"
    by = {}
    for it in with_stock:
        k = f"{it.get('категория')} модель {it.get('модель')} {it.get('цвет')}"
        by[k] = by.get(k, 0) + qty(it)
    groups = sorted(by.items(), key=lambda kv: -kv[1])
    out = [f"в наличии {total:g} шт: {len(with_stock)} позиций с остатком (подходящих позиций в каталоге {len(rows)})"]
    if len(with_stock) <= 12:
        out.append("по размерам: " + ", ".join(f"{name(it)} — {qty(it):g}" for it in with_stock))
    else:
        out.append("больше всего: " + ", ".join(f"{k} — {v:g}" for k, v in groups[:5]))
        out.append("меньше всего (из того, что есть): " + ", ".join(f"{name(it)} — {qty(it):g}" for it in with_stock[:5]))
    zero = len(rows) - len(with_stock)
    if zero:
        out.append(f"нет в наличии: {zero} позиций")
    return "; ".join(out)


def wb_summary(counts: dict, orders: list[dict], today: str) -> str:
    """Заказы Wildberries (FBS): сколько всего, по статусам, новые по кабинетам и что заказали."""
    labels = {"new": "новых", "processing": "на сборке", "picking": "собирается на складе",
              "picked": "собрано", "shipped": "в доставке", "done": "завершено", "cancelled": "отменено"}
    st = ", ".join(f"{labels.get(k, k)} {v}" for k, v in (counts.get("по_статусам") or {}).items())
    new = [o for o in orders if o.get("status") == "new"]
    by_cab, goods = {}, {}
    for o in new:
        by_cab[o.get("client") or "?"] = by_cab.get(o.get("client") or "?", 0) + 1
        for i in o.get("items_detail") or []:
            t = str(i.get("title") or "").rstrip("/")
            goods[t] = goods.get(t, 0) + 1
    top = sorted(goods.items(), key=lambda kv: -kv[1])[:8]
    got_today = sum(1 for o in orders if str(o.get("ts", "")).startswith(today))
    return (f"всего заказов {counts.get('всего', 0)} ({st}); сегодня пришло {got_today}. "
            f"Новые по кабинетам: {', '.join(f'{k} {v}' for k, v in by_cab.items()) or 'нет'}. "
            f"Чаще всего в новых: {', '.join(f'{k} — {v}' for k, v in top) or 'нет'}")
