# -*- coding: utf-8 -*-
"""Справка портала: файл читается, Джарвис находит нужный ответ, на болтовню справку не тянет."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import assistant  # noqa: E402


class HelpTests(unittest.TestCase):
    def test_file_shape(self):
        d = json.loads((BASE / "справка.json").read_text(encoding="utf-8"))
        ids = {c["id"] for c in d["кластеры"]}
        for q in d["вопросы"]:
            self.assertTrue(q["вопрос"] and q["ответ"] and q["слова"], q)
            self.assertIn(q["кластер"], ids, q["вопрос"])
        self.assertTrue(all(s["шаг"] and s["где"] for s in d["путь_заказа"]))

    def test_karta_page(self):
        import server
        page = server.render_karta().decode("utf-8")
        self.assertIn("Карта портала SHARQ", page)
        self.assertIn("← В портал", page)
        self.assertNotIn("__DATA__", page)
        self.assertIn("Почему снабженец не может подтвердить", page)  # справка встроена

    def test_hits(self):
        top = lambda t: (assistant.help_hits(t) or [{}])[0].get("вопрос", "")
        self.assertIn("снабженец", top("почему снабженец не может подтвердить заказ"))
        self.assertIn("нет в списке", top("модели нет в списке нового заказа"))
        self.assertIn("Карман", top("почему карман делится на белый и чёрный"))
        self.assertEqual(assistant.help_hits("привет как дела"), [])


if __name__ == "__main__":
    unittest.main()
