# -*- coding: utf-8 -*-
"""Листы в базе вместо Excel: перенос файла, чтение по строкам/колонкам, запись цеха, выгрузка."""
import io
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import sheets  # noqa: E402
import cex_store  # noqa: E402


class SheetsTests(unittest.TestCase):
    def setUp(self):
        from openpyxl import Workbook
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-sh-"))
        self._old = sheets.DATA
        sheets.DATA = self.tmp
        wb = Workbook()
        ws = wb.active
        ws.title = "главный"
        ws["B5"], ws["C5"], ws["L5"] = "Брюки/477/чёрный/", 42, "Брюки/477/чёрный/42"
        ws2 = wb.create_sheet("Партии")
        ws2.append(["№", "модель", "штук"])
        ws2.append([1, "477", 10.0])
        wb.save(self.tmp / "book.xlsm")
        self.assertEqual(sheets.import_file("цех", self.tmp / "book.xlsm"), 2)

    def tearDown(self):
        sheets.DATA = self._old

    def test_grid_keeps_row_and_column_positions(self):
        g = sheets.grid("цех", "главный")
        self.assertEqual(len(g), 5, "пустые строки сверху сохраняются")
        self.assertEqual((g[4][1], g[4][2], g[4][11]), ("Брюки/477/чёрный/", 42, "Брюки/477/чёрный/42"))
        view = sheets.View("цех")
        self.assertEqual(view.sheetnames, ["главный", "Партии"])
        self.assertEqual(list(view["главный"].iter_rows(min_row=5))[0][11], "Брюки/477/чёрный/42")

    def test_cex_read_write_append_ensure(self):
        self.assertEqual(cex_store.read_sheet("Партии"), [{"№": 1, "модель": "477", "штук": 10}])
        cex_store.append_rows("Партии", ["№", "модель", "штук"], [{"№": 2, "модель": "483", "штук": 5}])
        self.assertEqual([r["модель"] for r in cex_store.read_sheet("Партии")], ["477", "483"])
        self.assertEqual(cex_store.ensure_sheets([("партии", ["x"], [10]), ("Рулоны", ["код"], [10])]),
                         ["Рулоны"], "регистр не дублирует лист")
        self.assertEqual(cex_store.first_row("Рулоны"), ["код"])
        with self.assertRaises(KeyError):
            cex_store.write_sheet("Нет такого", ["a"], [])

    def test_workbook_roundtrip_writes_only_changes(self):
        before = sheets.version("цех")
        sheets.save("цех", sheets.workbook("цех"))
        self.assertEqual(sheets.version("цех"), before, "без правок ничего не пишется")
        wb = sheets.workbook("цех")
        wb["главный"].cell(row=5, column=20, value="111")
        sheets.save("цех", wb)
        self.assertNotEqual(sheets.version("цех"), before)
        self.assertEqual(sheets.grid("цех", "главный")[4][19], "111")
        from openpyxl import load_workbook
        out = load_workbook(io.BytesIO(sheets.to_xlsx("цех")))
        self.assertEqual(out["главный"]["T5"].value, "111")


if __name__ == "__main__":
    unittest.main()
