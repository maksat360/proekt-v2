# -*- coding: utf-8 -*-
"""Поток заказа: конструктор (карта + история) → снабженец (спецификация, сырьё, рулоны) → технолог."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import cex_api  # noqa: E402


class FakeStore:
    """Рабочая книга в памяти: настоящий Excel не трогается."""
    CexLocked = cex_api.store.CexLocked
    CexSourceError = cex_api.store.CexSourceError

    def __init__(self):
        self.sheets: dict[str, list[dict]] = {}

    def read_sheet(self, name):
        return [dict(r) for r in self.sheets.get(name, [])]

    def write_sheet(self, name, headers, rows):
        self.sheets[name] = [{h: r.get(h, "") for h in headers} for r in rows]

    def write_sheets(self, items):
        for name, headers, rows in items:
            self.write_sheet(name, headers, rows)

    def append_rows(self, name, headers, rows):
        self.write_sheet(name, headers, self.read_sheet(name) + list(rows))

    def ensure_sheets(self, specs):
        return []

    def first_row(self, name):
        return []


ME = {"логин": "boss", "фио": "Тест", "роль": "admin"}


class OrderFlowTests(unittest.TestCase):
    def setUp(self):
        self._old = cex_api.store
        cex_api.store = self.st = FakeStore()
        base = {"№ заказа": 7, "дата": "01.11.2026", "клиент": "Свой цех", "источник": cex_api.OWN,
                "категория": "Платья", "модель": "П1", "цвет": "Красный", "статус": cex_api.DESIGN}
        self.st.sheets[cex_api.ORDERS[0]] = [dict(base, размер="42", количество=10),
                                             dict(base, размер="44", количество=5)]

    def tearDown(self):
        cex_api.store = self._old

    def order(self):
        return next(o for o in cex_api.orders() if o["номер"] == "7")

    def test_full_flow(self):
        # технолог заказ у конструктора пока не видит
        self.assertEqual(cex_api.queue(), [])

        cex_api.save_design(ME, {"номер": "7", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "итог": 12, "характеристики": "длина 110"},
            {"модель": "П1", "цвет": "Красный", "размер": "44", "итог": 3},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "итог": 4},
        ]})
        self.assertEqual(self.order()["статус"], cex_api.DESIGN)
        # второе сохранение — тоже в истории
        res = cex_api.save_design(ME, {"номер": "7", "готово": True, "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "итог": 13, "характеристики": "длина 110"},
            {"модель": "П1", "цвет": "Красный", "размер": "44", "итог": 3},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "итог": 4},
        ]})
        self.assertEqual(res["статус"], cex_api.SUPPLYING)
        o = self.order()
        self.assertEqual((o["заказано"], o["штук"]), (15, 20))  # исходное и итоговое — отдельно
        hist = cex_api.card_history(["7"])["7"]
        moves = [(h["размер"], h["было"], h["стало"]) for h in hist if h["размер"]]
        self.assertIn(("42", "10", "12"), moves)
        self.assertIn(("42", "12", "13"), moves)
        self.assertIn(("44", "5", "3"), moves)
        self.assertIn(("46", "0", "4"), moves)
        with self.assertRaises(ValueError):  # карта закрыта — заказ уже у снабженца
            cex_api.save_design(ME, {"номер": "7", "позиции": [{"модель": "П1", "цвет": "К", "итог": 1}]})

        cex_api.save_bom(ME, {"модель": "П1", "строки": [
            {"материал": "Ткань", "цвет": "", "норма": 1.5, "ед": "м"},
            {"материал": "Нитки", "цвет": "Белый", "норма": 0.1, "ед": "бобина"}]})
        st = cex_api.supply_state()
        need = {(x["материал"], x["цвет"]): x["нужно"] for x in st["очередь"][0]["сырьё"]}
        self.assertEqual(need[("Ткань", "Красный")], 30.0)  # 1.5 × 20, цвет изделия
        self.assertEqual(need[("Нитки", "Белый")], 2.0)

        cex_api.add_roll(ME, {"код": "R-1", "материал": "Ткань", "цвет": "Красный", "граммы": 180, "вес": 25})
        with self.assertRaises(ValueError):
            cex_api.add_roll(ME, {"код": "R-1", "вес": 1})
        self.assertIn("R-1", cex_api.roll_registry())

        cloth = {"материал": "Ткань", "цвет": "Красный", "ед": "м", "нужно": 30, "есть": 30,
                 "статус": "есть на складе"}
        thread = {"материал": "Нитки", "цвет": "Белый", "ед": "бобина", "нужно": 2, "есть": 0}
        with self.assertRaisesRegex(ValueError, "Отметьте статус сырья: Нитки"):
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread]})
        with self.assertRaisesRegex(ValueError, "не хватает"):
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [
                cloth, {**thread, "статус": "не хватает"}]})
        self.assertEqual(cex_api.queue(), [])  # заказ остался у снабженца
        cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [
            cloth, {**thread, "статус": "заказано"}]})
        self.assertEqual([q["номер"] for q in cex_api.queue()], ["7"])

        # технолог передаёт карту в крой — партии ещё нет, её создаёт закройщик
        res = cex_api.apply_decision(ME, {"номер": "7"})
        self.assertEqual((res["карта"], res["статус"]), ("1", cex_api.CUTQ))
        self.assertEqual(cex_api.queue(), [])
        self.assertEqual(self.st.sheets.get(cex_api.PARTIES[0], []), [])
        self.assertEqual([(c["заказ"], c["карта"], c["остаток"]) for c in cex_api.cut_queue()], [("7", "1", 20)])

        # закройщик берёт часть карты — карта остаётся «ждёт кроя»
        part = cex_api.create_party(ME, {"заказ": "7", "карта": "1", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "количество": 13},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "количество": 4}]})
        self.assertEqual((part["штук"], part["вся_карта"]), (17, False))
        self.assertEqual(self.order()["статус"], cex_api.CUTQ)
        with self.assertRaisesRegex(ValueError, "осталось 0 шт"):
            cex_api.create_party(ME, {"заказ": "7", "карта": "1", "позиции": [
                {"модель": "П1", "цвет": "Красный", "размер": "42", "количество": 1}]})
        rest = cex_api.create_party(ME, {"заказ": "7", "карта": "1"})  # без списка — весь остаток
        self.assertEqual((rest["штук"], rest["вся_карта"]), (3, True))
        o = self.order()
        self.assertEqual((o["статус"], o["карты"], o["остаток"]), ("принят", {"1": cex_api.IN_PARTY}, 0))
        self.assertEqual(cex_api.cut_queue(), [])

    def test_old_orders_stay_with_technologist(self):
        for r in self.st.sheets[cex_api.ORDERS[0]]:
            r["статус"] = cex_api.NEW
        self.assertEqual(self.order()["штук"], 15)
        self.assertEqual([q["номер"] for q in cex_api.queue()], ["7"])
        cex_api.apply_decision(ME, {"номер": "7"})  # карты не было — создаётся из позиций заказа
        self.assertEqual(cex_api.create_party(ME, {"заказ": "7", "карта": "1"})["штук"], 15)
        self.assertEqual(self.order()["статус"], "принят")


class SeveralCardsTests(OrderFlowTests):
    """Конструктор делит заказ на карты как хочет; технолог принимает каждую карту отдельной партией."""

    def test_full_flow(self):  # общий поток уже проверен в OrderFlowTests
        pass

    def test_old_orders_stay_with_technologist(self):
        pass

    def test_cards_pass_separately(self):
        bom = [{"материал": "Ткань", "цвет": "", "норма": 1, "ед": "м"}]
        cex_api.save_bom(ME, {"модель": "П1", "строки": bom})
        cex_api.save_bom(ME, {"модель": "Б2", "строки": bom})
        card1 = [{"карта": 1, "модель": "П1", "цвет": "Красный", "размер": "42", "итог": 8},
                 {"карта": 1, "модель": "П1", "цвет": "Красный", "размер": "44", "итог": 5}]
        card2 = [{"карта": 2, "модель": "П1", "цвет": "Красный", "размер": "42", "итог": 6},
                 {"карта": 2, "модель": "Б2", "цвет": "Чёрный", "размер": "XL", "итог": 3}]
        # карта 1 уходит снабженцу, карта 2 остаётся у конструктора
        res = cex_api.save_design(ME, {"номер": "7", "передать": [1], "позиции": card1 + card2})
        self.assertEqual((res["передано"], res["статус"]), (["1"], cex_api.DESIGN))
        card = {(r["карта"], r["модель"], r["размер"]): r for r in self.st.sheets[cex_api.PCARD[0]]}
        self.assertEqual(card[("1", "П1", "42")]["заказано"], 10)
        self.assertEqual(card[("2", "П1", "42")]["заказано"], 0)  # «заказано» не двоится
        self.assertEqual(self.order()["карты"], {"1": cex_api.SUPPLYING, "2": cex_api.DESIGN})

        sup = cex_api.supply_state()["очередь"]
        self.assertEqual([(q["номер"], q["карта_номер"], q["штук"]) for q in sup], [("7", "1", 13)])
        with self.assertRaisesRegex(ValueError, "Карта 1 уже"):
            cex_api.save_design(ME, {"номер": "7", "позиции": card1 + card2})
        with self.assertRaisesRegex(ValueError, "не у снабженца"):
            cex_api.save_supply(ME, {"номер": "7", "карта": 2, "строки": []})

        cloth = {"материал": "Ткань", "цвет": "Красный", "ед": "м", "статус": "есть на складе"}
        cex_api.save_supply(ME, {"номер": "7", "карта": 1, "готово": True, "строки": [cloth]})
        q = cex_api.queue()
        self.assertEqual([(o["номер"], o["карты_этапа"], o["штук"]) for o in q], [("7", ["1"], 13)])

        # технолог передаёт карту 1 в крой, закройщик создаёт партию — карта 2 всё ещё у конструктора
        cex_api.apply_decision(ME, {"номер": "7", "карта": 1})
        p1 = cex_api.create_party(ME, {"заказ": "7", "карта": "1"})
        self.assertEqual(self.order()["карты"], {"1": cex_api.IN_PARTY, "2": cex_api.DESIGN})

        # теперь карта 2: конструктор передаёт, снабженец, технолог, закройщик
        cex_api.save_design(ME, {"номер": "7", "готово": True, "позиции": card2})
        black = {"материал": "Ткань", "цвет": "Чёрный", "ед": "м", "статус": "заказано"}
        cex_api.save_supply(ME, {"номер": "7", "карта": 2, "готово": True, "строки": [cloth, black]})
        cex_api.apply_decision(ME, {"номер": "7"})  # одна карта у технолога — номер не обязателен
        p2 = cex_api.create_party(ME, {"заказ": "7", "карта": "2"})
        self.assertNotEqual(p1["партия"], p2["партия"])
        parties = self.st.sheets[cex_api.PARTIES[0]]
        self.assertEqual({(str(r["№ партии"]), r["карта"]) for r in parties},
                         {(str(p1["партия"]), "1"), (str(p2["партия"]), "2")})
        o = self.order()
        self.assertEqual((o["статус"], o["штук"], o["остаток"]), ("принят", 22, 0))
        self.assertEqual(sum(r["количество"] for r in self.st.sheets[cex_api.ORDERS[0]]), 15)  # заказ не тронут


class MaterialsTests(unittest.TestCase):
    """Справочник материалов (категория → вид) и норма расхода по размерам."""

    def setUp(self):
        self._old = cex_api.store
        cex_api.store = self.st = FakeStore()

    def tearDown(self):
        cex_api.store = self._old

    def test_catalog_and_size_norms(self):
        cex_api.save_material(ME, {"категория": "Рулон"})
        self.assertEqual(cex_api.materials(), [{"категория": "Рулон", "вид": "", "ед": "м", "параметры": ""}])
        cex_api.save_material(ME, {"категория": "Рулон", "вид": "Габардин", "ед": "кг", "параметры": "220 г/м²"})
        self.assertEqual([m["вид"] for m in cex_api.materials()], ["Габардин"])  # заглушка категории ушла
        with self.assertRaisesRegex(ValueError, "есть виды"):
            cex_api.save_material(ME, {"категория": "Рулон", "удалить": True})

        cex_api.save_bom(ME, {"модель": "П1", "строки": [
            {"категория": "Рулон", "материал": "Габардин", "ед": "кг", "норма": 0.3, "по_размерам": {"46": 0.4}}]})
        with self.assertRaisesRegex(ValueError, "есть в спецификации"):
            cex_api.save_material(ME, {"категория": "Рулон", "вид": "Габардин", "удалить": True})
        need, missing = cex_api.supply_need([
            {"модель": "П1", "цвет": "Чёрный", "размер": "42", "итог": 10},
            {"модель": "П1", "цвет": "Чёрный", "размер": "46", "итог": 5}], cex_api.boms())
        self.assertEqual(missing, [])
        self.assertEqual(need, [{"материал": "Габардин", "цвет": "Чёрный", "ед": "кг", "нужно": 5.0}])  # 10×0.3 + 5×0.4
        with self.assertRaisesRegex(ValueError, "укажите норму"):
            cex_api.save_bom(ME, {"модель": "П1", "строки": [{"материал": "Габардин"}]})


class PackOrderStatusTests(unittest.TestCase):
    """Упаковали последнюю партию заказа — заказ из «принят» становится «упакован»."""

    def setUp(self):
        self._old = (cex_api.store, cex_api.pack_state)
        cex_api.store = self.st = FakeStore()
        self.st.sheets[cex_api.ORDERS[0]] = [{"№ заказа": 9, "размер": "42", "статус": "принят"},
                                             {"№ заказа": 8, "размер": "42", "статус": "принят"}]
        self.st.sheets[cex_api.PARTIES[0]] = [
            {"№ партии": 1, "№ заказа": 9, "статус": "в производстве"},
            {"№ партии": 2, "№ заказа": 9, "статус": "в производстве"},
            {"№ партии": 3, "№ заказа": 8, "статус": "в производстве"}]
        cex_api.pack_state = lambda me: {"партии": [
            {"номер": n, "остаток": 5, "готово_к_упаковке": 5, "статус": "в производстве",
             "коробка_следующая": 1, "строки": [{"цвет": "К", "размер": "42", "остаток": 5}]}
            for n in ("1", "2", "3")]}

    def tearDown(self):
        cex_api.store, cex_api.pack_state = self._old

    def status(self, num):
        return next(r["статус"] for r in self.st.sheets[cex_api.ORDERS[0]] if str(r["№ заказа"]) == num)

    def pack(self, party):
        cex_api.save_pack(ME, {"партия": party, "позиции": [{"цвет": "К", "размер": "42", "количество": 5}]})

    def test_order_packed_after_last_party(self):
        self.pack("1")
        self.assertEqual(self.status("9"), "принят")  # партия 2 ещё не упакована
        self.pack("2")
        self.assertEqual(self.status("9"), "упакован")
        self.assertEqual(self.status("8"), "принят")  # чужой заказ не тронут


if __name__ == "__main__":
    unittest.main()
