# -*- coding: utf-8 -*-
"""Скан штрихкода: если кода нет в «листе для штрих кодов», ищем в баркодах WB листа «главный» (ЖСК и др.)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import warehouse  # noqa: E402

ITEM = {"наименование": "Брюки/477/хаки/60", "модель": "477", "цвет": "хаки", "размер": "60", "остаток": 3}


class BarcodeFallbackTests(unittest.TestCase):
    def test_wb_barcode_from_main_sheet(self):
        with mock.patch.object(warehouse, "stock_items", lambda: [ITEM]), \
                mock.patch.object(warehouse, "load_master", lambda: {"barcodes": {}, "codes": {}}), \
                mock.patch.object(warehouse, "article_index", lambda: {"barcodes": {"4706528928753": ITEM["наименование"]}, "pairs": {}}), \
                mock.patch.dict(warehouse._STOCK, {"index": {ITEM["наименование"].lower(): ITEM}}):
            self.assertEqual(warehouse.resolve_product("4706528928753")["наименование"], "Брюки/477/хаки/60")
            self.assertIsNone(warehouse.resolve_product("9999999999999"))

    def test_wrong_sheet_model_falls_back_to_orders(self):
        s1 = {"наименование": "Лонгслив/S-1/чёрный/54", "модель": "S-1", "цвет": "чёрный", "размер": "54", "остаток": 2}
        with mock.patch.object(warehouse, "stock_items", lambda: [s1]), \
                mock.patch.object(warehouse, "load_master", lambda: {"barcodes": {"2049899393518": {"модель": "S", "цвет": "чёрный", "размер": "54"}}, "codes": {}}), \
                mock.patch.object(warehouse, "article_index", lambda: {"barcodes": {}, "pairs": {}}), \
                mock.patch.object(warehouse, "order_barcodes", lambda: {"2049899393518": s1["наименование"]}), \
                mock.patch.dict(warehouse._STOCK, {"index": {s1["наименование"].lower(): s1}}):
            self.assertEqual(warehouse.resolve_product("2049899393518")["наименование"], "Лонгслив/S-1/чёрный/54")


if __name__ == "__main__":
    unittest.main()
