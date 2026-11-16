# -*- coding: utf-8 -*-
"""Джарвис-помощник: подтверждение «да» для действий, фильтр склада по фразе, сводки анализа."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import assistant  # noqa: E402

def setUpModule():  # старый путь (шаблоны слов): агент ходит в облако, его проверяет test_assistant_agent
    assistant.AGENT = False


def tearDownModule():
    assistant.AGENT = True


ITEMS = [{"категория": "Брюки", "модель": "477", "цвет": "серый", "размер": "46"},
         {"категория": "Брюки", "модель": "477", "цвет": "светло серый", "размер": "48"},
         {"категория": "Постель", "модель": "серый гул", "цвет": "белый, серый", "размер": "1 сп"}]


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.done = []
        self.tools = {"revision_start": ("начать ревизию", {"запрос": {}},
                                         lambda запрос="": self.done.append(запрос) or "ревизия начата",
                                         lambda запрос="": "Начать ревизию?")}

    def test_action_needs_yes(self):
        res = assistant.ask("Тест", "Начальник", "начни ревизию по постели", [], tools=self.tools)
        self.assertIn("Скажите «да»", res["ответ"])
        self.assertEqual(res["подтвердить"]["действие"], "revision_start")
        self.assertEqual(self.done, [])  # без «да» ничего не сделано
        res = assistant.ask("Тест", "Начальник", "да", [], tools=self.tools, confirm=res["подтвердить"])
        self.assertIn("ревизия начата", res["ответ"])
        self.assertEqual(len(self.done), 1)

    def test_no_cancels_and_unknown_action_ignored(self):
        res = assistant.ask("Тест", "Начальник", "нет", [], tools=self.tools,
                            confirm={"действие": "revision_start", "args": {}})
        self.assertIn("не делаю", res["ответ"])
        self.assertEqual(self.done, [])
        # действия нет в правах сотрудника — «да» его не выполнит
        self.assertFalse(assistant._confirmable({}, "revision_start"))

    def test_stock_filter(self):
        self.assertEqual(assistant.stock_filter(ITEMS, "покажи 477 серый сорок шестой"),
                         {"cat": [], "model": ["477"], "color": ["серый"], "size": ["46"]})
        self.assertEqual(assistant.stock_filter(ITEMS, "постель серый гул")["model"], ["серый гул"])
        self.assertEqual(assistant.stock_filter(ITEMS, "постель серый гул")["color"], [])

    def test_stock_question_with_chatty_words(self):
        items = [dict(i, остаток=5) for i in ITEMS]
        self.assertIn("в наличии 15 шт", assistant.stock_summary(items, "сколько товаров у меня на складе"))
        self.assertIn("в наличии 10 шт", assistant.stock_summary(items, "сколько у нас брюк 477"))
        self.assertIn("ничего не найдено", assistant.stock_summary(items, "сколько 999"))

    def test_summaries(self):
        orders = [{"номер": "3", "статус": "у снабженца", "штук": 40, "карты": {"1": "у снабженца"},
                   "позиции": [{"модель": "479"}]},
                  {"номер": "2", "статус": "на складе", "штук": 10, "карты": {}, "позиции": []}]
        queue = [{"номер": "3", "карта_номер": "1", "без_спецификации": ["479"], "сырьё": []}]
        text = assistant.cex_orders_summary(orders, queue)
        self.assertIn("заказ №3", text)
        self.assertIn("нет спецификации у модели 479", text)
        self.assertNotIn("заказ №2", text)
        moves = assistant.wh_moves_summary([{"name": "A", "qty": 5}], [{"name": "A", "target": "WB", "qty": 2}], 7)
        self.assertIn("пришло 5 шт, ушло 2 шт (WB 2)", moves)


if __name__ == "__main__":
    unittest.main()
