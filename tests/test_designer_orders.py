# -*- coding: utf-8 -*-
"""Заказы конструктора: кто оформляет заказ, карты по размерам, свобода в количестве,
история, передача снабженцу, запрет правок не-конструктору и граничные случаи."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tests"))

import cex_api  # noqa: E402
import perms  # noqa: E402
from test_order_flow import FakeStore  # noqa: E402

BOSS = {"логин": "boss", "фио": "Начальник", "роль": "admin"}


def user(role: str) -> dict:
    return {"логин": f"u_{role}", "фио": role, "роль": role, "активен": 1}


class DesignerBase(unittest.TestCase):
    """Книга в памяти + права по умолчанию (временный пустой permissions.json)."""

    def setUp(self):
        self._store = cex_api.store
        cex_api.store = self.st = FakeStore()
        self.tmp = tempfile.TemporaryDirectory()
        self._perm = (perms.FILE, perms.LOG, dict(perms.SOURCES))
        perms.FILE = Path(self.tmp.name) / "permissions.json"
        perms.LOG = Path(self.tmp.name) / "log.jsonl"
        perms._CACHE.update(sig=None, data=None)
        perms.SOURCES.clear()  # без Excel: швейная роль одна, доп. ролей нет
        perms.SOURCES.update(prod=lambda: {"ОВЕРЛ": "Оверлок"}, extra=lambda login: [])

    def tearDown(self):
        cex_api.store = self._store
        perms.FILE, perms.LOG = self._perm[0], self._perm[1]
        perms.SOURCES.clear()
        perms.SOURCES.update(self._perm[2])
        perms._CACHE.update(sig=None, data=None)
        self.tmp.cleanup()

    def call(self, me: dict, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        """Запрос к API цеха так же, как его шлёт сайт: (код ответа, ответ)."""
        out: dict = {}
        ctx = {"me": me, "method": method, "path": path, "query": {}, "body": lambda: body or {},
               "json": lambda data: out.update(code=200, data=data),
               "err": lambda msg, code=400: out.update(code=code, data={"error": msg})}
        cex_api.dispatch(ctx)
        return out.get("code", 0), out.get("data", {})

    def new_order(self, me: dict = BOSS) -> tuple[int, dict]:
        return self.call(me, "POST", "/api/cex/orders", {
            "клиент": "Свой цех", "источник": cex_api.OWN, "срок": "2026-11-30", "позиции": [
                {"категория": "Платья", "модель": "479", "цвет": "Чёрный", "размер": "48", "количество": 10},
                {"категория": "Платья", "модель": "479", "цвет": "Чёрный", "размер": "50", "количество": 5}]})

    def order(self, num: str = "1") -> dict:
        return next(o for o in cex_api.orders() if o["номер"] == num)

    def ordered_total(self) -> int:
        return sum(r["количество"] for r in self.st.sheets[cex_api.ORDERS[0]])


def row(card, size, qty, color="Чёрный", model="479", chars=""):
    return {"карта": card, "модель": model, "цвет": color, "размер": size, "итог": qty, "характеристики": chars}


class WhoCreatesOrderTests(DesignerBase):
    def test_boss_manager_and_storekeeper_can_create(self):
        for role in ("admin", "manager", "storekeeper"):
            with self.subTest(role=role):
                code, data = self.new_order(user(role))
                self.assertEqual(code, 200, data)
                self.assertEqual(data["data"]["статус"], cex_api.DESIGN)  # свой заказ сразу у конструктора

    def test_other_roles_cannot_create(self):
        for role in ("designer", "technologist", "cutter", "supply", "packer", "accountant", "ОВЕРЛ"):
            with self.subTest(role=role):
                code, _ = self.new_order(user(role))
                self.assertIn(code, (401, 403))
        self.assertEqual(self.st.sheets.get(cex_api.ORDERS[0], []), [])  # ни одной строки не записано

    def test_empty_order_rejected(self):
        code, data = self.call(BOSS, "POST", "/api/cex/orders", {"клиент": "Свой цех", "позиции": []})
        self.assertEqual(code, 400)
        self.assertIn("хотя бы одну позицию", data["error"])


class DesignerCardTests(DesignerBase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.new_order()[0], 200)

    def test_card_by_sizes_and_several_cards(self):
        res = cex_api.save_design(BOSS, {"номер": "1", "позиции": [
            row(1, "48", 6, chars="длина 110"), row(1, "50", 5),
            row(2, "48", 4), row(2, "52", 3, color="Синий")]})
        self.assertEqual(res["штук"], 18)
        saved = {(r["карта"], r["цвет"], r["размер"]): r["итог"] for r in self.st.sheets[cex_api.PCARD[0]]}
        self.assertEqual(saved, {("1", "Чёрный", "48"): 6, ("1", "Чёрный", "50"): 5,
                                 ("2", "Чёрный", "48"): 4, ("2", "Синий", "52"): 3})
        self.assertEqual(self.order()["карты"], {"1": cex_api.DESIGN, "2": cex_api.DESIGN})
        chars = {r["характеристики"] for r in self.st.sheets[cex_api.PCARD[0]] if r["размер"] == "48" and r["карта"] == "1"}
        self.assertEqual(chars, {"длина 110"})

    def test_quantity_free_and_order_kept_apart(self):
        # больше заказа по 48, меньше по 50, новый размер 54 — без запретов
        cex_api.save_design(BOSS, {"номер": "1", "готово": True, "позиции": [
            row(1, "48", 14), row(1, "50", 2), row(1, "54", 4)]})
        o = self.order()
        self.assertEqual((o["заказано"], o["штук"]), (15, 20))  # заказ начальника и карта — отдельно
        self.assertEqual(self.ordered_total(), 15)              # строки заказа не тронуты
        boss = {p["размер"]: p["количество"] for p in o["в_заказе"]}
        self.assertEqual(boss, {"48": 10, "50": 5})

    def test_history_written(self):
        cex_api.save_design(BOSS, {"номер": "1", "позиции": [row(1, "48", 12), row(1, "50", 5)]})
        cex_api.save_design(BOSS, {"номер": "1", "комментарий": "мало ткани", "позиции": [row(1, "48", 11)]})
        cex_api.save_design(BOSS, {"номер": "1", "передать": [1], "позиции": [row(1, "48", 11)]})
        hist = cex_api.card_history(["1"])["1"]
        moves = [(h["размер"], h["было"], h["стало"]) for h in hist if h["размер"]]
        self.assertIn(("48", "10", "12"), moves)   # первое сохранение — от количества заказа
        self.assertIn(("48", "12", "11"), moves)
        self.assertIn(("50", "5", "0"), moves)     # строку убрали
        removed = next(h for h in hist if h["размер"] == "50" and h["стало"] == "0")
        self.assertIn("строка удалена", removed["комментарий"])
        self.assertIn("мало ткани", removed["комментарий"])
        self.assertTrue(any("передана снабженцу" in h["комментарий"] for h in hist))
        self.assertTrue(all(h["кто"] == "boss" for h in hist))

    def test_done_goes_to_supply_and_card_locks(self):
        res = cex_api.save_design(BOSS, {"номер": "1", "готово": True, "позиции": [row(1, "48", 10), row(2, "50", 5)]})
        self.assertEqual((res["статус"], res["передано"]), (cex_api.SUPPLYING, ["1", "2"]))
        self.assertEqual(self.order()["статус"], cex_api.SUPPLYING)
        queue = cex_api.supply_state()["очередь"]
        self.assertEqual([(q["номер"], q["карта_номер"]) for q in queue], [("1", "1"), ("1", "2")])
        code, data = self.call(BOSS, "GET", "/api/cex/design")
        self.assertEqual((code, data["data"]["очередь"]), (200, []))  # у конструктора заказа больше нет
        with self.assertRaisesRegex(ValueError, "у конструктора карт нет"):  # повторное завершение
            cex_api.save_design(BOSS, {"номер": "1", "готово": True, "позиции": [row(1, "48", 10)]})


class DesignerAccessTests(DesignerBase):
    def setUp(self):
        super().setUp()
        self.new_order()
        self.body = {"номер": "1", "позиции": [row(1, "48", 7)]}

    def test_designer_and_boss_can_edit(self):
        for me in (user("designer"), BOSS, user("manager")):
            with self.subTest(role=me["роль"]):
                code, data = self.call(me, "POST", "/api/cex/design", self.body)
                self.assertEqual(code, 200, data)

    def test_non_designer_cannot_edit_or_open(self):
        for role in ("technologist", "cutter", "storekeeper", "supply", "ОВЕРЛ"):
            with self.subTest(role=role):
                self.assertEqual(self.call(user(role), "POST", "/api/cex/design", self.body)[0], 403)
                self.assertEqual(self.call(user(role), "GET", "/api/cex/design")[0], 403)
        self.assertEqual(self.st.sheets.get(cex_api.PCARD[0], []), [])  # карта так и не записалась

    def test_not_logged_in(self):
        self.assertEqual(self.call(None, "POST", "/api/cex/design", self.body)[0], 401)


class DesignerEdgeTests(DesignerBase):
    def setUp(self):
        super().setUp()
        self.new_order()

    def save(self, **body):
        return cex_api.save_design(BOSS, {"номер": "1", **body})

    def test_empty_card(self):
        with self.assertRaisesRegex(ValueError, "нет ни одной строки"):
            self.save(позиции=[])

    def test_zero_allowed_card_is_sizes_not_quantity(self):
        # количество в карте примерное: факт впишет закройщик — карту с включёнными размерами можно передать
        self.assertEqual(self.save(позиции=[row(1, "48", 0)])["штук"], 0)
        with self.assertRaisesRegex(ValueError, "Карты 3 нет"):  # без включённых размеров карты нет
            self.save(передать=[3], позиции=[row(1, "48", 5), row(2, "50", 0)])
        res = self.save(передать=[2], позиции=[row(1, "48", 5), row(2, "50", 0)])
        self.assertEqual(res["передано"], ["2"])
        self.assertEqual(self.order()["карты"], {"1": cex_api.DESIGN, "2": cex_api.SUPPLYING})

    def test_negative_and_broken_rows(self):
        with self.assertRaisesRegex(ValueError, "отрицательным"):
            self.save(позиции=[row(1, "48", -3)])
        with self.assertRaisesRegex(ValueError, "отрицательным"):  # не число — тоже отказ
            self.save(позиции=[row(1, "48", "много")])
        with self.assertRaisesRegex(ValueError, "не хватает модели или цвета"):
            self.save(позиции=[row(1, "48", 5, color="")])
        with self.assertRaisesRegex(ValueError, "повторяется"):
            self.save(позиции=[row(1, "48", 5), row(1, "48", 2)])
        self.assertEqual(self.st.sheets.get(cex_api.PCARD[0], []), [])  # при ошибке ничего не записано

    def test_send_unknown_card_and_unknown_order(self):
        with self.assertRaisesRegex(ValueError, "Карты 3 нет"):
            self.save(передать=[3], позиции=[row(1, "48", 5)])
        with self.assertRaisesRegex(ValueError, "Заказ не найден"):
            cex_api.save_design(BOSS, {"номер": "99", "позиции": [row(1, "48", 5)]})

    def test_sent_card_cannot_be_changed_but_others_can(self):
        self.save(передать=[1], позиции=[row(1, "48", 10), row(2, "50", 5)])
        with self.assertRaisesRegex(ValueError, "Карта 1 уже"):
            self.save(позиции=[row(1, "48", 99), row(2, "50", 5)])
        self.save(позиции=[row(2, "50", 6)])  # карта 2 ещё у конструктора
        rows = {(r["карта"], r["размер"]): r["итог"] for r in self.st.sheets[cex_api.PCARD[0]]}
        self.assertEqual(rows, {("1", "48"): 10, ("2", "50"): 6})  # переданная карта не потерялась

    def test_rejected_order_not_in_design_queue(self):
        for r in self.st.sheets[cex_api.ORDERS[0]]:
            r["статус"] = "отклонён"
        code, data = self.call(BOSS, "GET", "/api/cex/design")
        self.assertEqual((code, data["data"]["очередь"]), (200, []))


if __name__ == "__main__":
    unittest.main()
