# -*- coding: utf-8 -*-
"""Приход «сразу на склад»: без адресного хранения товар сразу попадает в остаток."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import warehouse  # noqa: E402


class ReceiveDirectTests(unittest.TestCase):
    def setUp(self):
        self.led, self.mirrored = {}, []
        self._old = (warehouse._ledger, warehouse._save_ledger, warehouse.flush_async,
                     warehouse.resolve_product, warehouse._shadow)
        warehouse._ledger = lambda: self.led
        warehouse._save_ledger = lambda d: None
        warehouse.flush_async = lambda *a, **k: None
        warehouse.resolve_product = lambda n: {"наименование": n}
        warehouse._shadow = lambda kind, payload, actor="": self.mirrored.append((kind, payload))

    def tearDown(self):
        (warehouse._ledger, warehouse._save_ledger, warehouse.flush_async,
         warehouse.resolve_product, warehouse._shadow) = self._old

    def test_direct_places_without_address(self):
        rows = [{"наименование": "Брюки/477/чёрный/42", "количество": 5},
                {"наименование": "Брюки/477/чёрный/44", "количество": 0}]
        res = warehouse.receive_multi("цех", "", 0, rows, direct=True)
        self.assertEqual((res["строк"], res["штук"], res["сразу_на_склад"]), (1, 5, True))
        self.assertEqual([(r["коробка"], r["количество"]) for r in self.led["адрес"]], [("без адреса", 5)])
        self.assertEqual([k for k, _ in self.mirrored], ["приход", "адрес"])

    def test_default_waits_for_placement(self):
        warehouse.receive_multi("цех", "", 0, [{"наименование": "Брюки/477/чёрный/42", "количество": 5}])
        self.assertNotIn("адрес", self.led)
        self.assertEqual([k for k, _ in self.mirrored], ["приход"])


class ReceiptsTests(unittest.TestCase):
    ROWS = [{"ts": "2026-11-12 09:00:00", "supplier": "цех", "batch": "28", "qty": 4.0, "name": "Брюки/40"},
            {"ts": "2026-11-13 10:00:00", "supplier": "цех", "batch": "28", "qty": 5.0, "name": "Брюки/42"},
            {"ts": "2026-11-13 11:00:00", "supplier": "цех", "batch": "29", "qty": 3.0, "name": "Брюки/44"},
            {"ts": "2026-11-13 12:00:00", "supplier": "Алтын", "batch": "", "qty": 2.0, "name": "Брюки/46"}]

    def setUp(self):
        self._old = warehouse._receipt_rows
        warehouse._receipt_rows = lambda day="": [r for r in self.ROWS if r["ts"].startswith(day)]

    def tearDown(self):
        warehouse._receipt_rows = self._old

    def test_grouped_by_day_and_supplier(self):
        got = {(g["поставщик"], g["партия"]): (g["штук"], g["даты"]) for g in warehouse.receipts()}
        self.assertEqual(got, {("цех", "28"): (9.0, ["2026-11-12", "2026-11-13"]),  # партия за два дня — одна
                               ("цех", "29"): (3.0, ["2026-11-13"]), ("Алтын", ""): (2.0, ["2026-11-13"])})
        self.assertEqual(len(warehouse.receipt_lines("", "цех", "28")), 2)

    def test_excel_by_supplier(self):
        import io
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(warehouse.receipt_xlsx("2026-11-13", "цех"))).active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual([r[3] for r in rows[2:-1]], ["Брюки/42", "Брюки/44"])
        self.assertEqual(rows[-1][4], 8)
        self.assertEqual(len(warehouse.receipt_lines("2026-11-13")), 3)  # «*» — все поставщики
        self.assertEqual([x["товар"] for x in warehouse.receipt_lines("2026-11-13", "цех", "29")], ["Брюки/44"])
        with self.assertRaises(ValueError):
            warehouse.receipt_xlsx("2026-01-01")


class FullExportTests(unittest.TestCase):
    def test_full_book_has_all_sheets(self):
        import io, os, tempfile
        from openpyxl import load_workbook
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sql"))
        import db as sqldb
        tmp = tempfile.mkdtemp()
        con = sqldb.connect(os.path.join(tmp, "t.db"))
        sqldb.migrate(con)
        con.close()
        old = (warehouse.stock_items, sqldb.connect)
        warehouse.stock_items = lambda: [{"наименование": "Брюки/1/чёрный/42", "категория": "Брюки", "модель": "1",
                                          "цвет": "чёрный", "размер": "42", "остаток": 3, "ожидает": 0, "приход": 5,
                                          "отгружено": 2, "фbs": 1, "адрес": "А1"}]
        sqldb.connect = lambda *a, **k: old[1](os.path.join(tmp, "t.db"))
        try:
            wb = load_workbook(io.BytesIO(warehouse.full_xlsx()))
        finally:
            warehouse.stock_items, sqldb.connect = old
        self.assertEqual(wb.sheetnames, ["Остатки", "Приход", "Размещение", "Отгрузки"])
        self.assertEqual(wb["Остатки"]["F2"].value, 3)


if __name__ == "__main__":
    unittest.main()
