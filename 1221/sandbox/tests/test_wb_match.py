# -*- coding: utf-8 -*-
"""Сопоставление выгрузки WB (артикул = модель, цвет отдельно — как у ЖСК) со строками «главного»."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import warehouse as w  # noqa: E402


class WbMatchTests(unittest.TestCase):
    def test_model_color_size_all_must_match(self):
        self.assertEqual(w.wb_key("477", "мята пыльная", "42", "Брюки спортивные"),
                         w.name_key("Брюки/477/мята-пыльная/42"))  # дефис и пробел — одно и то же
        self.assertNotEqual(w.wb_key("477", "черный", "42", "Брюки"), w.name_key("Брюки/477/чёрный/44"))
        self.assertNotEqual(w.wb_key("S-1", "черный;глубокий черный", "46", "Лонгсливы"),
                            w.name_key("Лонгслив/S-1/графит/46"))

    def test_bedding_without_size(self):
        self.assertEqual(w.wb_key("сакура", "голубой;белый", "0", "Постельное белье"),
                         w.name_key("Постель/сакура/белый, голубой/1 сп"))  # цвета в любом порядке
        # в «главном» полуторка записана с приставкой в модели и часто без цвета
        self.assertEqual(w.wb_key("1,5 СП ЖАШЫЛ КЛЕТКА", "черный;белый", "0", "Постельное белье"),
                         w.name_key("Постель/1,5 СП ЖАШЫЛ КЛЕТКА//1.5 сп"))
        self.assertNotEqual(w.wb_key("жашыл клетка", "зеленый;бежевый", "0", "Постельное белье"),
                            w.name_key("Постель/1,5 СП ЖАШЫЛ КЛЕТКА//1.5 сп"))  # односпальный ≠ полуторка
        self.assertNotEqual(w.wb_key("сакура", "голубой;белый", "0", "Постельное белье"),
                            w.name_key("Навычка/сакура/голубой, белый/1 сп"))  # наволочку не путаем с комплектом


if __name__ == "__main__":
    unittest.main()
