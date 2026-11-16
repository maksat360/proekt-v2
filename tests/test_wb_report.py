# -*- coding: utf-8 -*-
"""Аналитика WB: история заказов/выкупов в базе без дублей, отчёт о реализации, перевод артикулов, сезонность."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wb_report  # noqa: E402


class WbReportTests(unittest.TestCase):
    def setUp(self):
        self._old = wb_report.CACHE, wb_report._CAT["data"], wb_report._CAT["ts"]
        wb_report.CACHE = Path(tempfile.mkdtemp(prefix="v2-wbt-"))
        # справочник: баркод → наименование, (артикул, размер) → наименование, наименование → поля
        wb_report._CAT.update(ts=9e18, data=(
            {"111": "Брюки/477/чёрный/52"},
            {("брюки/483/чёрный/", "42"): "Брюки/483/чёрный/42"},
            {"Брюки/477/чёрный/52": ("Брюки", "477", "чёрный", "52"),
             "Брюки/483/чёрный/42": ("Брюки", "483", "чёрный", "42")},
            lambda v: str(v or "").strip().lower(), lambda v: str(v or "").strip()))

    def tearDown(self):
        wb_report.CACHE, wb_report._CAT["data"], wb_report._CAT["ts"] = self._old

    def test_history_report_and_translation(self):
        o = {"supplierArticle": "477-ч-сред", "techSize": "52", "barcode": "111"}
        orders = [{**o, "srid": "a", "date": "2026-11-15T10:00:00", "isCancel": False},
                  {**o, "srid": "b", "date": "2026-11-01T10:00:00", "isCancel": False},
                  {**o, "srid": "c", "date": "2026-11-14T10:00:00", "isCancel": True},
                  {**o, "srid": "d", "date": "2026-09-01T10:00:00", "isCancel": False}]  # старше 30 дн
        wb_report.store_orders("zhsk", orders)
        wb_report.store_orders("zhsk", orders)  # повторная выгрузка не дублирует
        wb_report.store_sales("zhsk", [{**o, "srid": "a", "saleID": "S1", "date": "2026-11-10", "forPay": 900},
                                       {**o, "srid": "e", "saleID": "R1", "date": "2026-11-11", "forPay": -900}])
        wb_report.store_realization("zhsk", [  # та же продажа «a» из отчёта о реализации — не дубль
            {"srid": "a", "sellerOperName": "Продажа", "saleDt": "2026-11-10T00:00:00Z", "vendorCode": "477-ч-сред",
             "techSize": "52", "sku": "111", "quantity": 1, "forPay": "905.5", "currency": "RUB"},
            {"srid": "old", "sellerOperName": "Продажа", "saleDt": "2025-12-03T00:00:00Z", "vendorCode": "477-ч-сред",
             "techSize": "52", "sku": "111", "quantity": 2, "forPay": "1800", "currency": "RUB"},
            {"srid": "old", "sellerOperName": "Логистика", "saleDt": "2025-12-03T00:00:00Z", "quantity": 1}])
        remains = [{"vendorCode": "Брюки/483/чёрный/", "techSize": "42", "warehouses": [
            {"warehouseName": "Всего находится на складах", "quantity": 168},
            {"warehouseName": "Склад WB РФ", "quantity": 168}]}]  # уже входит во «Всего» — не удваиваем
        rows, currency = wb_report.build(["zhsk"], remains, today=date(2026, 11, 16))
        by = {(r["модель"], r["размер"]): r for r in rows}
        a = by[("477", "52")]
        self.assertEqual((a["категория"], a["цвет"], a["артикулы_wb"]), ("Брюки", "чёрный", ["477-ч-сред"]))
        self.assertEqual((a["заказы_7"], a["заказы_30"], a["отмены_30"]), (1, 2, 1))
        self.assertEqual((a["выкупы_30"], a["возвраты_30"], a["к_перечислению"]), (1, 1, 5.5))
        self.assertEqual(a["месяцы"], {"2025-12": 2, "2026-11": 1})
        self.assertEqual(by[("483", "42")]["на_wb"], 168, "по артикулу и размеру, если баркода нет")
        self.assertEqual(currency, "RUB")
        self.assertEqual(wb_report.resolve("", "28Б-ч", "S", "Футболки"), ("Футболки", "28", "чёрный", "S"))
        self.assertEqual(wb_report.resolve("", "483-пт", "44", "Брюки"), ("Брюки", "483", "синий", "44"))
        self.assertEqual(wb_report.resolve("", "483-ф", "44", "Брюки"), ("Брюки", "483", "—", "44"), "неизвестный код")


if __name__ == "__main__":
    unittest.main()
