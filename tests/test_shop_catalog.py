# -*- coding: utf-8 -*-
"""Каталог магазина строится из остатков склада, а не из листа «главный»; цена и фото сохраняются."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import shop_sync  # noqa: E402
import warehouse  # noqa: E402

STOCK = [
    {"наименование": "Брюки/477/чёрный/42", "категория": "Брюки", "модель": "477", "цвет": "чёрный", "размер": "42", "остаток": 5},
    {"наименование": "Футболка ХБ/264/фуме/56", "категория": "Футболка ХБ", "модель": "264", "цвет": "фуме", "размер": "56", "остаток": 10},
    {"наименование": "Худи/H-4/чёрный/XL", "категория": "Худи", "модель": "H-4", "цвет": "чёрный", "размер": "XL", "остаток": 0},
]


class ShopCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="v2-shop-"))
        self.p = [mock.patch.object(server, "DATA", tmp), mock.patch.object(shop_sync, "STATUS_FILE", tmp / "shop_status.json"),
                  mock.patch.object(warehouse, "stock_items", lambda: STOCK)]
        for x in self.p:
            x.start()
        server.write_table("products", [{"id": 1, "наименование": "Брюки/477/чёрный/42", "категория": "Брюки", "модель": "477",
                                         "цвет": "чёрный", "размер": "42", "цена": 2500, "фото": "p.jpg", "количество": 0}])

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_catalog_from_stock(self):
        shop_sync.sync_from_excel(force=True)
        items = {i["наименование"]: i for i in server.read_table("products")}
        self.assertEqual(set(items), {s["наименование"] for s in STOCK}, "все товары склада, в том числе с нулём")
        self.assertEqual(float(items["Брюки/477/чёрный/42"]["цена"]), 2500.0, "цена из прежнего каталога")
        self.assertEqual(items["Брюки/477/чёрный/42"]["фото"], "p.jpg")
        self.assertEqual(items["Футболка ХБ/264/фуме/56"]["категория"], "Футболка ХБ")


if __name__ == "__main__":
    unittest.main()
