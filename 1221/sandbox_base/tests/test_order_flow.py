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
_REAL_LOG = cex_api.perms.log_event


def setUpModule():  # рабочий журнал действий (data/журнал_прав.jsonl) тесты не трогают
    cex_api.perms.log_event = lambda *a, **k: None


def tearDownModule():
    cex_api.perms.log_event = _REAL_LOG


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

        cex_api.save_material(ME, {"категория": "рулоны", "вид": "Габардин", "ед": "кг"})
        self.assertEqual(cex_api.roll_kinds(), ["Габардин"])
        cex_api.save_design(ME, {"номер": "7", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "итог": 12, "характеристики": "длина 110"},
            {"модель": "П1", "цвет": "Красный", "размер": "44", "итог": 3},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "итог": 4},
        ], "рулоны": [{"карта": "1", "вид": "Габардин", "цвет": "Красный"},
                      {"карта": "1", "вид": "Габардин", "цвет": "Красный"}, {"карта": "1", "вид": ""}]})
        self.assertEqual(len(cex_api.card_rolls()[("7", "1")]), 2)  # без лимита, пустые строки отброшены
        with self.assertRaisesRegex(ValueError, "своей картой"):
            cex_api.save_design(ME, {"номер": "7", "позиции": [
                {"модель": "П1", "цвет": "Красный", "размер": "42", "итог": 12}],
                "рулоны": [{"карта": "5", "вид": "Габардин"}]})
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
            {"материал": "Нитки", "цвет": "Белый", "норма": 0.1, "ед": "бобина"},
            {"материал": "Габардин", "цвет": "", "норма": 0.4}]})
        st = cex_api.supply_state()
        self.assertEqual([(r["вид"], r["вдм"], r["есть"]) for r in st["очередь"][0]["рулоны"]], [("Габардин", False, False)] * 2)
        self.assertNotIn("Габардин", [x["материал"] for x in st["очередь"][0]["сырьё"]])  # рулон — не по спецификации
        need = {(x["материал"], x["цвет"]): x["нужно"] for x in st["очередь"][0]["сырьё"]}
        self.assertEqual(need[("Ткань", "Красный")], 30.0)  # 1.5 × 20, цвет изделия
        self.assertEqual(need[("Нитки", "Белый")], 2.0)

        cex_api.add_roll(ME, {"код": "R-1", "материал": "Ткань", "цвет": "Красный", "граммы": 180, "вес": 25})
        with self.assertRaises(ValueError):
            cex_api.add_roll(ME, {"код": "R-1", "вес": 1})
        self.assertIn("R-1", cex_api.roll_registry())

        # есть/нет — сам по складу сырья, статуса «заказано» больше нет
        cloth = {"материал": "Ткань", "цвет": "Красный", "ед": "м", "нужно": 30, "комментарий": "от Ткани+"}
        thread = {"материал": "Нитки", "цвет": "Белый", "ед": "бобина", "нужно": 2}
        with self.assertRaisesRegex(ValueError, "Нет на складе сырья: Ткань Красный, Нитки Белый"):
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread]})
        cex_api.save_material(ME, {"категория": "Ткани", "вид": "Ткань", "ед": "м"})
        cex_api.save_material(ME, {"категория": "Нитки", "вид": "Нитки", "ед": "бобина"})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [
            {"материал": "Ткань", "цвет": "Красный", "количество": 30},
            {"материал": "Нитки", "цвет": "Белый", "количество": 1}]})
        with self.assertRaisesRegex(ValueError, "сырья: Нитки Белый —"):
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread]})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [{"материал": "Нитки", "цвет": "Белый", "количество": 1}]})
        self.assertTrue(all(x["есть"] for x in cex_api.supply_state()["очередь"][0]["сырьё"]))
        self.assertEqual(cex_api.queue(), [])  # заказ остался у снабженца
        # обычные рулоны — штуками, без кодов: снабженец принимает партию одним действием
        with self.assertRaisesRegex(ValueError, "примите рулоны"):
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread]})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [  # 1 рулон, веса нет — не хватает на 2
            {"материал": "Габардин", "цвет": "Красный", "количество": 1, "ед": "шт"}]})
        with self.assertRaisesRegex(ValueError, "1 шт этого цвета"):
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread]})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [  # ещё 10 рулонов, общий вес 250 кг
            {"материал": "Габардин", "цвет": "Красный", "количество": 10, "ед": "шт", "вес": 250}]})
        self.assertEqual([x for x in cex_api.rolls_in_stock() if not x.get("вдм")],  # R-1 выше — рулон с кодом
                         [{"вид": "Габардин", "цвет": "красный", "шт": 11.0}])
        self.assertEqual([m["вес"] for m in cex_api.moves()][-2:], [0.0, 250.0])
        self.assertEqual([r["есть"] for r in cex_api.supply_state()["очередь"][0]["рулоны"]], [True, True])
        with self.assertRaisesRegex(ValueError, "впишите вес"):  # вес рулонов пишут при передаче закройщику
            cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread]})
        cex_api.save_supply(ME, {"номер": "7", "готово": True, "строки": [cloth, thread], "рулоны": [{"вес": 25}, {"вес": "24,5"}]})
        # «Сырьё готово — передать закройщику» само списывает сырьё по спецификации и рулоны карты
        st_now = cex_api.stock()
        self.assertEqual((st_now[cex_api._mkey("Ткань", "Красный")], st_now[cex_api._mkey("Нитки", "Белый")]), (0, 0))
        self.assertEqual(st_now[cex_api._mkey("Габардин", "Красный")], 9)
        roll_out = [m for m in cex_api.moves() if m["документ"] == "расход в производство" and m["материал"] == "Габардин"]
        self.assertEqual([(m["количество"], m["ед"], m["вес"]) for m in roll_out], [(-2, "шт", 49.5)])  # 2 рулона, 49,5 кг
        self.assertTrue(all(m["комментарий"] == "автоматически при передаче закройщику"
                            for m in cex_api.moves() if m["документ"] == "расход в производство"))
        # снабжение отдаёт карту прямо закройщику: технолог принимает уже раскроенное
        self.assertEqual(cex_api.queue(), [])
        self.assertEqual(self.order()["карты"], {"1": cex_api.CUTQ})
        self.assertEqual(self.st.sheets.get(cex_api.PARTIES[0], []), [])
        self.assertEqual([(c["заказ"], c["карта"], c["остаток"]) for c in cex_api.cut_queue()], [("7", "1", 20)])

        # закройщик берёт часть карты — карта остаётся «ждёт кроя»
        part = cex_api.create_party(ME, {"заказ": "7", "карта": "1", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "количество": 13},
            {"модель": "П1", "цвет": "Красный", "размер": "46", "количество": 4}]})
        self.assertEqual((part["штук"], part["вся_карта"]), (17, False))
        self.assertEqual(self.order()["статус"], cex_api.CUTQ)
        # карта — подсказка: по 42 осталось 0, но закройщик берёт ещё 1
        extra = cex_api.create_party(ME, {"заказ": "7", "карта": "1", "позиции": [
            {"модель": "П1", "цвет": "Красный", "размер": "42", "количество": 1}]})
        self.assertEqual((extra["штук"], extra["вся_карта"]), (1, False))
        with self.assertRaisesRegex(ValueError, "нет в карте"):  # новые размеры добавляет конструктор
            cex_api.create_party(ME, {"заказ": "7", "карта": "1", "позиции": [
                {"модель": "П1", "цвет": "Красный", "размер": "48", "количество": 1}]})
        rest = cex_api.create_party(ME, {"заказ": "7", "карта": "1"})  # без списка — весь остаток
        self.assertEqual((rest["штук"], rest["вся_карта"]), (3, True))
        # и в карте кроя можно раскроить больше плана партии
        party = next(p for p in cex_api.cut_state()["партии"] if p["номер"] == str(rest["партия"]))
        self.assertEqual(len(party["рулоны_карты"]), 2)
        with self.assertRaisesRegex(ValueError, "нет в номенклатуре"):
            cex_api.save_card(ME, {"партия": str(rest["партия"]), "длина": 5, "возврат": [
                {"материал": "Ситец", "количество": 1}], "разделы": [
                {"позиции": [{"цвет": "Красный", "размер": "44", "факт": 5}]}]})
        self.assertEqual(self.st.sheets.get(cex_api.CARDS[0], []), [])  # карта не записалась
        with self.assertRaisesRegex(ValueError, "целое число"):  # рулоны — штуками; остаток в кг — другим видом сырья
            cex_api.save_card(ME, {"партия": str(rest["партия"]), "длина": 5, "возврат": [
                {"материал": "габардин", "цвет": "Красный", "количество": 2.5}], "разделы": [
                {"позиции": [{"цвет": "Красный", "размер": "44", "факт": 5}]}]})
        self.assertEqual(self.st.sheets.get(cex_api.CARDS[0], []), [])  # и карта не записалась
        cut = cex_api.save_card(ME, {"партия": str(rest["партия"]), "длина": 5, "возврат": [
            {"материал": "габардин", "цвет": "Красный", "количество": 2}], "разделы": [
            {"позиции": [{"цвет": "Красный", "размер": "44", "факт": 5}]}]})
        self.assertEqual(cut["штук"], 5)
        self.assertEqual(cex_api.stock()[cex_api._mkey("Габардин", "Красный")], 11 - 2 + 2)  # 2 рулона ушли в крой, 2 целых вернули

        # приёмка после кроя: пока технолог не принял — в работу и распределение настил не идёт
        num = str(rest["партия"])
        party = lambda: next(p for p in cex_api.cut_state()["партии"] if p["номер"] == num)  # noqa: E731
        self.assertEqual(cex_api._nastils(party()), [])
        rev = cex_api.cut_review()
        self.assertEqual([(g["партия"], g["статус"], g["штук"]) for g in rev], [(num, "ждёт", 5)])
        with self.assertRaisesRegex(ValueError, "что исправить"):
            cex_api.review_cut(ME, {"партия": num, "карта": rev[0]["карта"], "решение": "вернуть"})
        cex_api.review_cut(ME, {"партия": num, "карта": rev[0]["карта"], "решение": "вернуть", "замечание": "пересчитать 44"})
        self.assertEqual([g["статус"] for g in cex_api.cut_state()["возвраты"]], ["возврат"])
        self.assertEqual(cex_api._nastils(party()), [])  # возвращённое тоже не в работе
        line = rev[0]["строки"][0]
        cex_api.resubmit_cut(ME, {"партия": num, "карта": rev[0]["карта"], "строки": [{**line, "факт": 6}]})
        cex_api.review_cut(ME, {"партия": num, "карта": rev[0]["карта"], "решение": "принять",
                                "строки": [{**line, "принято": 4}], "замечание": "2 шт брак кроя"})
        self.assertEqual([n["шт"] for n in cex_api._nastils(party())], [4])  # в распределение — принятое
        self.assertEqual(cex_api.cut_review(), [])
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

        cloth = {"материал": "Ткань", "цвет": "Красный", "ед": "м"}
        cex_api.save_material(ME, {"категория": "Ткани", "вид": "Ткань", "ед": "м"})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [
            {"материал": "Ткань", "цвет": "Красный", "количество": 100}, {"материал": "Ткань", "цвет": "Чёрный", "количество": 3}]})
        cex_api.save_supply(ME, {"номер": "7", "карта": 1, "готово": True, "строки": [cloth]})
        self.assertEqual([(c["заказ"], c["карта"], c["остаток"]) for c in cex_api.cut_queue()], [("7", "1", 13)])

        # карта 1 сразу у закройщика, он создаёт партию — карта 2 всё ещё у конструктора
        p1 = cex_api.create_party(ME, {"заказ": "7", "карта": "1"})
        self.assertEqual(self.order()["карты"], {"1": cex_api.IN_PARTY, "2": cex_api.DESIGN})

        # теперь карта 2: конструктор передаёт, снабженец, технолог, закройщик
        cex_api.save_design(ME, {"номер": "7", "готово": True, "позиции": card2})
        black = {"материал": "Ткань", "цвет": "Чёрный", "ед": "м"}
        cex_api.save_supply(ME, {"номер": "7", "карта": 2, "готово": True, "строки": [cloth, black]})
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
        cex_api.save_material(ME, {"категория": "Сырьё"})
        self.assertEqual([(m["категория"], m["вид"], m["код"]) for m in cex_api.materials()], [("Сырьё", "", "")])
        cex_api.save_material(ME, {"категория": "Сырьё", "вид": "Габардин", "ед": "кг", "параметры": "220 г/м²"})
        self.assertEqual([m["вид"] for m in cex_api.materials()], ["Габардин"])  # заглушка категории ушла
        with self.assertRaisesRegex(ValueError, "есть виды"):
            cex_api.save_material(ME, {"категория": "Сырьё", "удалить": True})

        cex_api.save_bom(ME, {"модель": "П1", "строки": [
            {"категория": "Сырьё", "материал": "Габардин", "ед": "кг", "норма": 0.3, "по_размерам": {"46": 0.4}}]})
        with self.assertRaisesRegex(ValueError, "есть в спецификации"):
            cex_api.save_material(ME, {"категория": "Сырьё", "вид": "Габардин", "удалить": True})
        need, missing = cex_api.supply_need([
            {"модель": "П1", "цвет": "Чёрный", "размер": "42", "итог": 10},
            {"модель": "П1", "цвет": "Чёрный", "размер": "46", "итог": 5}], cex_api.boms())
        self.assertEqual(missing, [])
        self.assertEqual(need, [{"материал": "Габардин", "цвет": "Чёрный", "ед": "кг", "нужно": 5.0}])  # 10×0.3 + 5×0.4
        with self.assertRaisesRegex(ValueError, "укажите норму"):
            cex_api.save_bom(ME, {"модель": "П1", "строки": [{"материал": "Габардин"}]})
        # изделие в 2 цвета: материал «цвет 2» берёт второй цвет, ед. — из номенклатуры
        cex_api.save_bom(ME, {"модель": "П2", "строки": [
            {"материал": "Габардин", "ед": "мусор", "норма": 100}, {"материал": "Габардин", "цвет": "цвет 2", "норма": 50}]})
        need, _ = cex_api.supply_need([{"модель": "П2", "цвет": "зелёный, бежевый", "размер": "42", "итог": 2}], cex_api.boms())
        self.assertEqual(need, [{"материал": "Габардин", "цвет": "зелёный", "ед": "кг", "нужно": 200.0},
                                {"материал": "Габардин", "цвет": "бежевый", "ед": "кг", "нужно": 100.0}])

    def test_nomenclature_moves_and_stock(self):
        cex_api.save_material(ME, {"категория": "Сырьё", "вид": "Габардин", "ед": "кг", "тип": "сырьё", "мин": 5})
        cex_api.save_material(ME, {"категория": "Нитки", "вид": "Нить 40/2", "ед": "шт"})
        self.assertEqual({m["вид"]: m["код"] for m in cex_api.materials()}, {"Габардин": "М-00001", "Нить 40/2": "М-00002"})
        cex_api.save_material(ME, {"категория": "Сырьё", "вид": "Габардин", "ед": "кг", "цена": 900})  # правка — код тот же
        self.assertEqual(next(m for m in cex_api.materials() if m["вид"] == "Габардин")["код"], "М-00001")
        with self.assertRaisesRegex(ValueError, "в другой группе"):
            cex_api.save_material(ME, {"категория": "Нитки", "вид": "габардин"})
        with self.assertRaisesRegex(ValueError, "нет в номенклатуре"):
            cex_api.add_move(ME, {"документ": "поступление", "строки": [{"материал": "Ситец", "количество": 1}]})

        cex_api.add_move(ME, {"документ": "поступление", "поставщик": "Ткани+", "строки": [
            {"материал": "габардин", "цвет": "Чёрный", "количество": 20, "цена": 900}]})
        with self.assertRaisesRegex(ValueError, "Не хватает"):
            cex_api.add_move(ME, {"документ": "расход в производство", "строки": [
                {"материал": "Габардин", "цвет": "Чёрный", "количество": 25}]})
        cex_api.add_move(ME, {"документ": "расход в производство", "заказ": "7", "карта": "1", "строки": [
            {"материал": "Габардин", "цвет": "чёрный", "количество": 5}]})
        cex_api.add_move(ME, {"документ": "инвентаризация", "строки": [
            {"материал": "Габардин", "цвет": "Чёрный", "количество": 14}]})  # было 15, факт 14 → −1
        self.assertEqual(cex_api.stock(), {("габардин", "чёрный"): 14})
        self.assertEqual([m["количество"] for m in cex_api.moves()], [20, -5, -1])
        with self.assertRaisesRegex(ValueError, "есть движения"):
            cex_api.save_material(ME, {"категория": "Сырьё", "вид": "Габардин", "удалить": True})

        cex_api.save_bom(ME, {"модель": "П1", "строки": [{"материал": "Габардин", "ед": "кг", "норма": 0.5}]})
        lines, _ = cex_api.supply_lines({"номер": "7"}, "1", cex_api.boms(),
                                        {"7": [{"карта": "1", "модель": "П1", "цвет": "Чёрный", "размер": "42", "итог": 10}]})
        self.assertEqual((lines[0]["на_складе"], lines[0]["списано"]), (14, 5))

    def test_rename_and_delete(self):
        cex_api.save_material(ME, {"категория": "Сырьё", "вид": "Габардин", "ед": "кг"})
        cex_api.save_material(ME, {"категория": "Ткань"})
        cex_api.save_bom(ME, {"модель": "П1", "строки": [{"категория": "Сырьё", "материал": "Габардин", "норма": 1}]})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [{"материал": "Габардин", "количество": 10}]})
        cex_api.add_move(ME, {"документ": "расход в производство", "строки": [{"материал": "Габардин", "количество": 4}]})
        cex_api.add_roll(ME, {"код": "R1", "материал": "Габардин", "вес": 20})

        cex_api.rename_material(ME, {"категория_было": "Сырьё", "вид_было": "Габардин", "категория": "ткань", "вид": "Габардин 220"})
        self.assertEqual([(m["категория"], m["вид"]) for m in cex_api.materials()], [("Сырьё", ""), ("Ткань", "Габардин 220")])
        self.assertEqual(cex_api.boms()["П1"][0]["материал"], "Габардин 220")
        self.assertEqual({m["материал"] for m in cex_api.moves()}, {"Габардин 220"})
        self.assertEqual(cex_api.roll_registry()["R1"]["материал"], "Габардин 220")
        cex_api.rename_material(ME, {"категория_было": "Ткань", "категория": "Ткани"})
        self.assertEqual(cex_api.boms()["П1"][0]["категория"], "Ткани")

        income, spend = cex_api.moves()
        with self.assertRaisesRegex(ValueError, "станет -4"):
            cex_api.delete_move(ME, {"id": income["id"]})
        cex_api.delete_move(ME, {"id": spend["id"]})
        cex_api.delete_move(ME, {"id": income["id"]})
        self.assertEqual(cex_api.moves(), [])
        cex_api.delete_roll(ME, {"код": "R1"})
        self.assertEqual(cex_api.roll_registry(), {})


class PackOrderStatusTests(unittest.TestCase):
    """Упаковка — этап швейного маршрута: прошла партия весь маршрут — она упакована и ждёт склад."""

    def setUp(self):
        self._old = (cex_api.store, cex_api._route_ready)
        cex_api.store = self.st = FakeStore()
        self.st.sheets[cex_api.ORDERS[0]] = [{"№ заказа": 9, "размер": "42", "статус": "принят"},
                                             {"№ заказа": 8, "размер": "42", "статус": "принят"}]
        self.st.sheets[cex_api.PARTIES[0]] = [
            {"№ партии": 1, "№ заказа": 9, "статус": "в производстве", "категория": "Брюки", "модель": "477"},
            {"№ партии": 2, "№ заказа": 9, "статус": "в производстве"},
            {"№ партии": 3, "№ заказа": 8, "статус": "в производстве"}]
        self.ready = {}
        cex_api._route_ready = lambda: dict(self.ready)

    def tearDown(self):
        cex_api.store, cex_api._route_ready = self._old

    def status(self, num):
        return next(r["статус"] for r in self.st.sheets[cex_api.ORDERS[0]] if str(r["№ заказа"]) == num)

    def route_done(self, party):  # как finish_work на последнем этапе маршрута
        rows = cex_api._rows(cex_api.PARTIES)
        cex_api.store.write_sheets([(cex_api.PARTIES[0], cex_api.PARTIES[1], rows)] + cex_api._mark_packed(party, rows))
        self.ready[(party, "К", "42")] = 5

    def test_pack_is_route_stage(self):
        self.assertEqual(cex_api._ops()[cex_api.PACK_STAGE]["название"], "Упаковка")
        self.st.sheets[cex_api.RATES[0]] = [{"модель": "477", "этап": cex_api.PACK_STAGE, "ставка": 3}]
        self.assertEqual(cex_api.stage_rate(cex_api.PACK_STAGE, "477"), 3.0)  # цена упаковки по модели

    def test_order_packed_after_last_party(self):
        self.route_done("1")
        self.assertEqual(self.status("9"), "принят")  # партия 2 ещё не прошла маршрут
        self.route_done("2")
        self.assertEqual(self.status("9"), "упакован")
        self.assertEqual(self.status("8"), "принят")  # чужой заказ не тронут

    def test_order_on_stock_after_all_parties_received(self):
        self.route_done("1")
        self.route_done("2")
        self.assertEqual(self.status("9"), "упакован")
        cex_api.pack_received("1", "К")
        self.assertEqual(self.status("9"), "упакован")  # партия 2 ещё не принята
        cex_api.pack_received("2", "К")
        self.assertEqual(self.status("9"), "на складе")
        self.assertEqual(self.status("8"), "принят")  # чужой заказ не тронут

    def test_route_done_waits_for_warehouse_then_received(self):
        # старая упаковка с экрана упаковщика тоже ждёт склад
        self.st.sheets[cex_api.PACK[0]] = [{"id": 1, "партия": 2, "цвет": "К", "размер": "42", "коробка": "1",
                                            "количество": 4, "статус": "упаковано"}]
        self.route_done("1")
        wait = cex_api.pack_awaiting()
        self.assertEqual([(w["партия"], w["модель"], w["цвет"], w["размеры"], w["штук"]) for w in wait],
                         [("2", "", "К", {"42": 4}, 4), ("1", "477", "К", {"42": 5}, 5)])
        self.assertEqual(cex_api.pack_received("1", "К"), 1)
        self.assertEqual([w["партия"] for w in cex_api.pack_awaiting()], ["2"])
        party = next(r for r in self.st.sheets[cex_api.PARTIES[0]] if str(r["№ партии"]) == "1")
        self.assertEqual(party["статус"], "на складе")
        self.assertEqual(cex_api.pack_received("1", "К"), 0)  # повторная приёмка ничего не меняет


if __name__ == "__main__":
    unittest.main()


class RollUnitsTests(unittest.TestCase):
    """Обычные рулоны на складе сырья — только штуками: кг и штуки не смешиваются в один остаток."""

    def setUp(self):
        self._old = cex_api.store
        cex_api.store = FakeStore()

    def tearDown(self):
        cex_api.store = self._old

    def test_rolls_counted_in_pieces(self):
        cex_api.save_material(ME, {"категория": "рулоны", "вид": "240", "ед": "кг"})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [{"материал": "240", "цвет": "чёрный", "количество": 3}]})
        self.assertEqual([m["ед"] for m in cex_api.moves()], ["шт"])  # ед. из номенклатуры (кг) для рулона не берём
        with self.assertRaisesRegex(ValueError, "целое число"):  # остаток рулона в кг — отдельным видом сырья
            cex_api.add_move(ME, {"документ": "возврат из кроя", "строки": [{"материал": "240", "цвет": "чёрный", "количество": 4.5}]})
        cex_api.add_move(ME, {"документ": "возврат из кроя", "строки": [{"материал": "240", "цвет": "чёрный", "количество": 1}]})
        self.assertEqual(cex_api.rolls_in_stock()[0]["шт"], 4)


class ModelRateTests(unittest.TestCase):
    """Одна роль — разная цена за штуку по моделям; без своей цены — общая ставка роли."""

    def setUp(self):
        self._old = (cex_api.store, cex_api._sync_process, cex_api.perms.log_event)
        cex_api.store = self.st = FakeStore()
        cex_api._sync_process = lambda *a, **k: None  # не трогаем data/processes
        cex_api.perms.log_event = lambda *a, **k: None

    def tearDown(self):
        cex_api.store, cex_api._sync_process, cex_api.perms.log_event = self._old

    def test_rate_per_model(self):
        cex_api.store.sheet_names = lambda: [cex_api.RATES_SHEET[0]]
        cex_api.save_stage(ME, {"код": "ОВЕР", "название": "Оверлок", "ставка": 10,
                                "по_моделям": {"П1": "12,5", "П2": ""}})
        self.assertEqual(cex_api.stage_rate("ОВЕР", "П1"), 12.5)
        self.assertEqual(cex_api.stage_rate("ОВЕР", "П2"), 10.0)
        self.assertEqual(cex_api.model_rates(), {"ОВЕР": {"П1": 12.5}})
        cex_api.save_stage(ME, {"код": "ОВЕР", "ставка": 10, "по_моделям": {}})  # убрали — снова общая
        self.assertEqual(cex_api.stage_rate("ОВЕР", "П1"), 10.0)
        with self.assertRaisesRegex(ValueError, "отрицательной"):
            cex_api.save_stage(ME, {"код": "ОВЕР", "по_моделям": {"П1": -1}})


class VdmRollTests(unittest.TestCase):
    """ВДМ — рулоны с кодом каждого; обычные — штуками. Не смешиваются."""

    def setUp(self):
        self._old = cex_api.store
        cex_api.store = self.st = FakeStore()
        cex_api.save_material(ME, {"категория": "рулоны", "вид": "Габардин", "ед": "шт"})
        cex_api.save_material(ME, {"категория": "рулоны", "вид": "ВДМ флис", "ед": "шт"})

    def tearDown(self):
        cex_api.store = self._old

    def test_vdm_with_code_plain_by_pieces(self):
        self.assertTrue(cex_api.is_vdm("ВДМ флис"))
        self.assertFalse(cex_api.is_vdm("Габардин"))
        cex_api.add_roll(ME, {"код": "V-1", "материал": "ВДМ флис", "цвет": "Чёрный", "вес": 22})
        cex_api.add_move(ME, {"документ": "поступление", "строки": [
            {"материал": "Габардин", "цвет": "Чёрный", "количество": 10, "ед": "шт"}]})
        got = {(x["вид"], x["цвет"]): (x["шт"], bool(x.get("вдм"))) for x in cex_api.rolls_in_stock()}
        self.assertEqual(got, {("Габардин", "чёрный"): (10.0, False), ("ВДМ флис", "чёрный"): (1, True)})
