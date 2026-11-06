# -*- coding: utf-8 -*-
"""Права сотрудников: каталог разрешений, права ролей, индивидуальные права, журнал.

Право сотрудника = индивидуальная настройка, если есть; иначе настройка роли, если есть;
иначе стандартное значение из CATALOG. Стандартные значения повторяют то, как права
были зашиты в код раньше, — без настроек всё работает как прежде.

Хранится в data/permissions.json, журнал — data/журнал_прав.jsonl.
Роль «admin» не настраивается: у неё всегда все права (иначе можно запереть систему).

Роль одна на всё: служебные роли (ниже, за ними стоят экраны) и производственные роли —
операции цеха (Оверлок, Карман…) из листа «расценки». Какие роли у человека — решает цех
(основная в листе «сотрудники», остальные в «Сотрудники цеха».роли); разрешения — здесь.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILE = BASE / "data" / "permissions.json"
LOG = BASE / "data" / "журнал_прав.jsonl"

# служебные роли: названия как в портале и в листе «сотрудники» (по ним читается Excel — не менять)
ROLE_LABELS = {
    "admin": "Начальник",
    "accountant": "Бухгалтер",
    "manager": "Менеджер",
    "technologist": "Технолог",
    "storekeeper": "Складчик",
    "cutter": "Закройщик",
    "packer": "Упаковщик",
    "designer": "Конструктор",
    "supply": "Снабженец",
    "client": "Клиент",
}
LOCKED_ROLE = "admin"

_A, _M, _T = "admin", "manager", "technologist"
_STAFF = {"admin", "manager", "technologist", "accountant", "storekeeper", "cutter", "packer",
          "designer", "supply"}
# производственная роль по умолчанию: вход в цех и работа на своей операции; остальное — настройкой
PROD_DEFAULT = {"cex.view", "cex.work"}

# код, группа, название, роли по умолчанию
CATALOG: list[tuple[str, str, str, set[str]]] = [
    # управление: сотрудники, роли, права (коды stages.* оставлены ради сохранённых настроек)
    ("staff.view", "Сотрудники и роли", "Просмотр сотрудников и ролей", {_A, _M, _T}),
    ("staff.add", "Сотрудники и роли", "Добавление сотрудников", {_A, _M, _T}),
    ("staff.edit", "Сотрудники и роли", "Редактирование карточек сотрудников (ФИО, пароль)", {_A, _M, _T}),
    ("staff.delete", "Сотрудники и роли", "Отключение сотрудников", {_A, _M}),
    ("stages.create", "Сотрудники и роли", "Создание производственных ролей", {_A, _M, _T}),
    ("stages.edit", "Сотрудники и роли", "Изменение и отключение производственных ролей", {_A, _M, _T}),
    ("stages.delete", "Сотрудники и роли", "Удаление производственных ролей", {_A, _M}),
    ("stages.assign", "Сотрудники и роли", "Назначение и снятие ролей у сотрудников", {_A, _M, _T}),
    ("perms.users", "Сотрудники и роли", "Личные разрешения сотрудников", {_A}),
    ("perms.roles", "Сотрудники и роли", "Разрешения ролей", {_A}),
    # цех
    ("cex.view", "Цех", "Вход в раздел «Цех»", set(_STAFF)),
    ("cex.create", "Цех", "Оформление заказов на пошив", {_A, _M, "storekeeper"}),
    ("cex.design", "Цех", "Производственная карта заказа (конструктор)", {_A, _M, "designer"}),
    ("cex.supply", "Цех", "Снабжение: спецификации, сырьё, поступление рулонов", {_A, _M, "supply"}),
    ("cex.tech", "Цех", "Приёмка заказов, распределение работы, этикетки, исправление кроя", {_A, _M, _T}),
    ("cex.routes", "Цех", "Редактирование маршрутов партий", {_A, _M, _T}),
    ("cex.cut", "Цех", "Ввод кроя", {_A, _M, "cutter"}),
    ("cex.work", "Цех", "Работа на своих производственных ролях (брать и сдавать)", {_A, _M, _T}),
    ("cex.work.all", "Цех", "Видеть работу всего цеха", {_A, _M, _T}),
    ("cex.boss", "Цех", "Возвращать и сдавать чужую работу, брать несколько работ", {_A, _M}),
    ("cex.pack", "Цех", "Упаковка", {_A, _M, "packer"}),
    ("cex.pay", "Цех", "Зарплата цеха: начисление и карточки оплаты", {_A, _M, "accountant"}),
    # склад, магазин, WB
    ("wh.view", "Склад и магазин", "Просмотр склада", {_A, _M, "storekeeper", "accountant", _T}),
    ("wh.write", "Склад и магазин", "Операции склада (приход, адрес, отгрузка)", {_A, _M, "storekeeper"}),
    ("shop.sell", "Склад и магазин", "Продажи в магазине", {_A, _M, "storekeeper"}),
    ("shop.stock", "Склад и магазин", "Операции по остаткам магазина", {_A, _M, "storekeeper"}),
    ("shop.price", "Склад и магазин", "Изменение цен", {_A, _M}),
    ("wb.manage", "Склад и магазин", "Заказы Wildberries и кабинеты", {_A, _M, "storekeeper"}),
    ("orders.view", "Склад и магазин", "Заказы клиентов: просмотр и сборка", {_A, _M, "storekeeper"}),
    ("orders.create", "Склад и магазин", "Создание заказов клиентов", {"client", _A, _M}),
    # портал
    ("brand.manage", "Портал", "Оформление портала и логотип", {_A, _M}),
    ("announce.create", "Портал", "Объявления", {_A, _M}),
    # старый учёт партий (раздел скрыт в config.json, но API работает)
    ("batches.create", "Старый учёт партий", "Создание партий", {_A, _M, _T}),
    ("passes.take", "Старый учёт партий", "Взять проход", {_T, _A, _M}),
    ("checks.create", "Старый учёт партий", "Оценки технолога", {_T, _A, _M}),
    ("materials.view", "Старый учёт партий", "Материалы: просмотр", {_A, _M, "storekeeper", "accountant", _T}),
    ("materials.move", "Старый учёт партий", "Материалы: движение", {_A, _M, "storekeeper"}),
    ("finished.view", "Старый учёт партий", "Готовая продукция", {_A, _M, "storekeeper", "accountant"}),
    ("shipments.create", "Старый учёт партий", "Отгрузка партий", {_A, _M, "storekeeper"}),
    ("analytics.view", "Старый учёт партий", "Аналитика", {_A, _M, "accountant"}),
    ("payroll.all", "Старый учёт партий", "Зарплата всех сотрудников", {_A, _M, "accountant"}),
    ("report.build", "Старый учёт партий", "Отчёт Excel", {_A, _M, "accountant"}),
]
CODES = {c for c, *_ in CATALOG}
DEFAULTS = {c: roles for c, _g, _l, roles in CATALOG}
LABELS = {c: label for c, _g, label, _r in CATALOG}

_CACHE: dict = {"sig": None, "data": None}


class AccessError(ValueError):
    """Действие запрещено правилами защиты (не хватает прав, сам себе, последний админ)."""


# ------------------------------------------------------------------ хранение
def _empty() -> dict:
    return {"роли": {}, "сотрудники": {}}


def load() -> dict:
    try:
        st = FILE.stat()
        sig = (str(FILE), st.st_mtime_ns, st.st_size)
    except OSError:
        return _empty()
    if _CACHE["sig"] == sig:
        return _CACHE["data"]
    try:
        raw = json.loads(FILE.read_text(encoding="utf-8"))
        data = {"роли": dict(raw.get("роли") or {}), "сотрудники": dict(raw.get("сотрудники") or {})}
    except Exception:  # noqa: BLE001 — битый файл не должен ронять портал
        data = _empty()
    _CACHE.update(sig=sig, data=data)
    return data


def _save(data: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)
    _CACHE["sig"] = None


def _log(actor: dict, action: str, target: str, code: str, before, after) -> None:
    entry = {"дата": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
             "кто": str(actor.get("логин", "")), "кто_фио": str(actor.get("фио", "")),
             "действие": action, "кому": target, "право": code,
             "право_название": LABELS.get(code, code), "было": before, "стало": after}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_event(actor: dict, action: str, target: str, before="", after="") -> None:
    """Запись в журнал прав из других модулей (смена роли, этапы, отключение)."""
    _log(actor, action, target, "", before, after)


def journal(limit: int = 200) -> list[dict]:
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ роли
# Источники цеха подключаются лениво: perms не зависит от Excel, тесты подставляют свои.
SOURCES: dict = {}


def _source(name: str):
    if name not in SOURCES:
        import cex_api  # noqa: WPS433 — цех сам регистрирует источники при импорте
        cex_api.register_role_sources()
    return SOURCES[name]


def production_roles() -> dict[str, str]:
    """Производственные роли (операции цеха): код → название."""
    try:
        return {k: v for k, v in _source("prod")().items() if k not in ROLE_LABELS}
    except Exception:  # noqa: BLE001 — нет книги цеха: остаются служебные роли
        return {}


def all_roles() -> dict[str, str]:
    return {**ROLE_LABELS, **production_roles()}


def role_label(code: str) -> str:
    return all_roles().get(code, code)


def _default(role: str, code: str, prod: dict | None = None) -> bool:
    if role in ROLE_LABELS:
        return role in DEFAULTS.get(code, set())
    return code in PROD_DEFAULT and role in (production_roles() if prod is None else prod)


# ------------------------------------------------------------------ расчёт
def role_value(role: str, code: str, data: dict | None = None) -> bool:
    if role == LOCKED_ROLE:
        return code in CODES
    data = data or load()
    over = (data["роли"].get(role) or {})
    if code in over:
        return bool(over[code])
    return _default(role, code)


def allowed(user: dict | None, code: str, data: dict | None = None) -> bool:
    if not user or code not in CODES:
        return False
    data = data or load()
    login = str(user.get("логин", ""))
    own = data["сотрудники"].get(login) or {}
    if login and code in own:
        return bool(own[code])
    return any(role_value(r, code, data) for r in roles_of(user, data))


def extra_roles(login: str, data: dict | None = None) -> list[str]:
    """Роли сотрудника кроме основной (лист «Сотрудники цеха», колонка «роли»)."""
    try:
        raw = _source("extra")(str(login))
    except Exception:  # noqa: BLE001
        return []
    known = all_roles()
    return [r for r in raw if r in known and r != LOCKED_ROLE]


def roles_of(user: dict, data: dict | None = None) -> list[str]:
    """Основная роль + дополнительные: права сотрудника — объединение прав всех его ролей."""
    main = str(user.get("роль", ""))
    return [main] + [r for r in extra_roles(str(user.get("логин", "")), data) if r != main]


def effective(user: dict, data: dict | None = None) -> dict[str, bool]:
    data = data or load()
    return {c: allowed(user, c, data) for c in CODES}


def catalog() -> list[dict]:
    return [{"код": c, "группа": g, "название": label} for c, g, label, _r in CATALOG]


def role_matrix(data: dict | None = None) -> dict[str, dict[str, bool]]:
    data = data or load()
    return {r: {c: role_value(r, c, data) for c in CODES} for r in all_roles()}


def user_view(user: dict, data: dict | None = None) -> dict:
    """Права сотрудника с источником: роль или индивидуально."""
    data = data or load()
    own = data["сотрудники"].get(str(user.get("логин", ""))) or {}
    roles = roles_of(user, data)
    return {c: {"значение": allowed(user, c, data), "по_роли": any(role_value(r, c, data) for r in roles),
                "индивидуально": c in own} for c in CODES}


# ------------------------------------------------------------------ защита
def _active(u: dict) -> bool:
    return str(u.get("активен", "1")) in ("1", "True", "true")


def _is_full_admin(u: dict, data: dict) -> bool:
    return _active(u) and allowed(u, "perms.roles", data) and allowed(u, "perms.users", data)


def guard_last_admin(users: list[dict], data: dict) -> None:
    """Хотя бы один активный сотрудник должен управлять и ролями, и правами сотрудников."""
    if not any(_is_full_admin(u, data) for u in users):
        raise AccessError("Нельзя: в системе не останется ни одного сотрудника, "
                          "который может управлять правами")


def _check_code(code: str) -> None:
    if code not in CODES:
        raise ValueError(f"Неизвестное разрешение: {code}")


def set_role_perm(actor: dict, users: list[dict], role: str, code: str, on: bool) -> dict:
    _check_code(code)
    if not allowed(actor, "perms.roles"):
        raise AccessError("Нет права управлять правами ролей")
    if role not in all_roles():
        raise ValueError("Неизвестная роль")
    if role == LOCKED_ROLE:
        raise AccessError("Права администратора не настраиваются: у него всегда все права")
    if role == str(actor.get("роль", "")):
        raise AccessError("Нельзя менять права своей собственной роли")
    if not allowed(actor, code):
        raise AccessError("Нельзя выдавать или забирать право, которого нет у вас самих")
    data = load()
    before = role_value(role, code, data)
    new = json.loads(json.dumps(data))
    roles = new["роли"].setdefault(role, {})
    if _default(role, code) == bool(on):
        roles.pop(code, None)  # совпадает со стандартом — хранить нечего
    else:
        roles[code] = bool(on)
    if not roles:
        new["роли"].pop(role, None)
    guard_last_admin(users, new)
    if before != bool(on):
        _save(new)
        _log(actor, "роль", role_label(role), code, before, bool(on))
    return {"роль": role, "право": code, "значение": bool(on)}


def set_user_perm(actor: dict, users: list[dict], target: dict, code: str, on: bool | None) -> dict:
    """on=None — убрать индивидуальную настройку (вернуть как у роли)."""
    _check_code(code)
    if not allowed(actor, "perms.users"):
        raise AccessError("Нет права менять индивидуальные права сотрудников")
    login = str(target.get("логин", ""))
    if login == str(actor.get("логин", "")):
        raise AccessError("Нельзя менять собственные права")
    if str(target.get("роль")) == LOCKED_ROLE and str(actor.get("роль")) != LOCKED_ROLE:
        raise AccessError("Права администратора может менять только администратор")
    if not allowed(actor, code):
        raise AccessError("Нельзя выдавать или забирать право, которого нет у вас самих")
    data = load()
    before = allowed(target, code, data)
    new = json.loads(json.dumps(data))
    own = new["сотрудники"].setdefault(login, {})
    if on is None or bool(on) == any(role_value(r, code, new) for r in roles_of(target, new)):
        own.pop(code, None)
    else:
        own[code] = bool(on)
    if not own:
        new["сотрудники"].pop(login, None)
    guard_last_admin(users, new)
    after = allowed(target, code, new)
    if new != data:
        _save(new)
        _log(actor, "сотрудник", login, code, before, after)
    return {"логин": login, "право": code, "значение": after}


def check_role_grant(actor: dict, target: dict, role: str, add: bool) -> None:
    """Можно ли выдать (add) или снять роль сотруднику. Сами данные пишет цех."""
    if role not in all_roles():
        raise ValueError(f"Неизвестная роль: {role}")
    if str(target.get("логин", "")) == str(actor.get("логин", "")):
        raise AccessError("Нельзя менять собственные роли")
    if role == LOCKED_ROLE:
        raise AccessError("Начальника назначают только основной ролью")
    if str(target.get("роль")) == LOCKED_ROLE and str(actor.get("роль")) != LOCKED_ROLE:
        raise AccessError("Роли начальника может менять только начальник")
    if add and str(actor.get("роль")) != LOCKED_ROLE:
        data = load()  # роль не должна дать больше, чем есть у того, кто её выдаёт
        extra = [c for c in CODES if role_value(role, c, data) and not allowed(actor, c, data)]
        if extra:
            raise AccessError("У роли «%s» есть права, которых нет у вас: %s"
                              % (role_label(role), ", ".join(LABELS[c] for c in extra[:3])))


def check_role_change(actor: dict, users: list[dict], target: dict, new_role: str | None,
                      new_active: bool | None) -> None:
    """Проверки при смене роли или отключении сотрудника (сами данные пишет вызывающий)."""
    login = str(target.get("логин", ""))
    if new_role is not None and new_role not in all_roles():
        raise ValueError("Неизвестная роль")
    role_changes = new_role is not None and new_role != str(target.get("роль"))
    if (role_changes or new_active is False) and login == str(actor.get("логин", "")):
        raise AccessError("Нельзя менять собственную роль или отключать себя")
    is_admin_actor = str(actor.get("роль")) == LOCKED_ROLE
    if role_changes and (new_role == LOCKED_ROLE or str(target.get("роль")) == LOCKED_ROLE) \
            and not is_admin_actor:
        raise AccessError("Назначать и снимать администратора может только администратор")
    if role_changes and new_role != LOCKED_ROLE and not is_admin_actor:
        # роль не должна дать больше, чем есть у того, кто её назначает
        data = load()
        extra = [c for c in CODES if role_value(new_role, c, data) and not allowed(actor, c, data)]
        if extra:
            raise AccessError("У роли «%s» есть права, которых нет у вас: %s"
                              % (role_label(new_role), ", ".join(LABELS[c] for c in extra[:3])))
    future = []
    for u in users:
        if str(u.get("логин")) == login:
            u = dict(u)
            if new_role is not None:
                u["роль"] = new_role
            if new_active is not None:
                u["активен"] = 1 if new_active else 0
        future.append(u)
    guard_last_admin(future, load())
