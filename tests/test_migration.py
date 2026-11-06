# -*- coding: utf-8 -*-
"""Тесты миграции: импорт, идемпотентность, откат, сравнение, тень, бэкап."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))

import compare  # noqa: E402
import db as sqldb  # noqa: E402
import importer  # noqa: E402
import shadow  # noqa: E402


def make_workbook(path: Path, shift: int = 0) -> Path:
    """Синтетическая книга той же структуры, что рабочая."""
    wb = Workbook()
    ws = wb.active
    ws.title = "главный"
    for _ in range(4):
        ws.append([None] * 19)
    for name in ("Брюки/100/чёрный/42", "Брюки/100/чёрный/44"):
        row = [None] * 19
        row[11] = name
        row[17] = 10
        ws.append(row)

    ws = wb.create_sheet("приобритение")
    for _ in range(6):
        ws.append([None] * 12)
    ws.append(["дата", "номер", "Наименования товаров", "модел", "свет", "размер",
               "не ликвид", "кл", "партия", "", "", ""])
    ws.append(["01.10.2026", "склад", "Брюки/100/чёрный/42", "100", "чёрный", "42",
               0, 20 + shift, "", "", "", ""])

    ws = wb.create_sheet("адрес")
    ws.append(["", "", "", "дата", "ID: каробки", "баркод", "количества", "проверка", "", ""])
    ws.append(["", "", "", "02.10.2026", "s/t1/e1/i1", "Брюки/100/чёрный/42", 5, "Nice", "", ""])
    ws.append(["", "", "", "02.10.2026", "s/t1/e1/i2", "Брюки/100/чёрный/42", -1, "Nice", "", ""])

    ws = wb.create_sheet("паставка ЖСК")
    ws.append(["", "", "", "", "ID: каробки", "баркод", "количества", "проверка", "", ""])
    ws.append(["", "", "", "", "03.10.2026", "Брюки/100/чёрный/42", 2, "Nice", "", ""])

    ws = wb.create_sheet("заказы")
    ws.append(["№", "дата", "клиент", "статус", "товар", "заказано", "собрано", "кто", "причина", "закрыт"])
    ws.append([1, "04.10.2026", "ЖСК", "новый", "Брюки/100/чёрный/42", 3, 0, "", "", ""])

    ws = wb.create_sheet("сотрудники")
    ws.append(["логин", "пароль", "ФИО", "роль", "должность", "цех", "ставка за час", "активен"])
    ws.append(["boss", "123456", "Асанов Эрлан", "admin", "Начальник", "Ц-01", 0, "да"])

    ws = wb.create_sheet("расценки")
    ws.append(["код", "операция", "расценка за шт", "порядок", "обязательная"])
    ws.append(["РАСКР", "Раскрой", 15, 10, "да"])

    wb.save(path)
    return path


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-test-"))
        self.db_path = self.tmp / "test.db"
        self.con = sqldb.connect(self.db_path)
        sqldb.migrate(self.con)
        self.book = make_workbook(self.tmp / "book.xlsx")
        # изолируем импортёр от рабочих data/*.xlsx
        self._old_data = importer.DATA
        importer.DATA = self.tmp / "data"
        importer.DATA.mkdir(exist_ok=True)

    def tearDown(self):
        importer.DATA = self._old_data
        self.con.close()

    def count(self, table: str) -> int:
        return self.con.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    def test_import_creates_records(self):
        stats = importer.import_workbook(self.book, self.con)
        self.assertEqual(stats["products"], 2)
        self.assertEqual(self.count("products"), 2)
        self.assertEqual(self.count("purchases"), 1)
        self.assertEqual(self.count("placements"), 2)   # включая отрицательную корректировку
        self.assertEqual(self.count("shipments"), 1)
        self.assertEqual(self.count("orders"), 1)
        self.assertEqual(self.count("employees"), 1)
        self.assertEqual(self.count("rates"), 1)

    def test_repeated_import_is_idempotent(self):
        importer.import_workbook(self.book, self.con)
        first = {t: self.count(t) for t in
                 ("products", "purchases", "placements", "shipments", "orders")}
        importer.import_workbook(self.book, self.con)
        second = {t: self.count(t) for t in first}
        self.assertEqual(first, second, "повторный импорт не должен создавать дубли")

    def test_records_trace_back_to_sheet_and_row(self):
        importer.import_workbook(self.book, self.con)
        row = self.con.execute("SELECT source_sheet, source_row FROM placements LIMIT 1").fetchone()
        self.assertEqual(row["source_sheet"], "адрес")
        self.assertGreater(row["source_row"], 1)

    def test_transaction_rolls_back_on_error(self):
        importer.import_workbook(self.book, self.con)
        before = self.count("placements")
        with self.assertRaises(Exception):
            self.con.execute("BEGIN IMMEDIATE")
            try:
                self.con.execute("DELETE FROM placements")
                raise RuntimeError("сбой посреди операции")
            except Exception:
                self.con.execute("ROLLBACK")
                raise
        self.assertEqual(self.count("placements"), before)

    def test_compare_detects_no_diff_and_a_real_diff(self):
        importer.import_workbook(self.book, self.con)
        excel = compare.excel_metrics(self.book)
        sql = compare.sql_metrics(self.con)
        report = compare.compare(excel, sql)
        self.assertTrue(report["ok"], report["расхождения"])
        self.assertEqual(report["товаров_excel"], report["товаров_sql"])

        self.con.execute("UPDATE placements SET qty = qty + 5 WHERE qty > 0")
        sql2 = compare.sql_metrics(self.con)
        report2 = compare.compare(excel, sql2)
        self.assertFalse(report2["ok"])
        self.assertGreater(report2["всего_расхождений"], 0)

    def test_unexpected_workbook_structure_is_rejected(self):
        bad = self.tmp / "bad.xlsx"
        wb = Workbook()
        wb.active.title = "что-то"
        wb.save(bad)
        with self.assertRaises(KeyError):
            importer.import_workbook(bad, self.con)

    def test_backup_creates_file(self):
        importer.import_workbook(self.book, self.con)
        old_dir = sqldb.BACKUP_DIR
        sqldb.BACKUP_DIR = self.tmp / "backups"
        try:
            path = sqldb.backup(self.con)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 0)
        finally:
            sqldb.BACKUP_DIR = old_dir

    def test_shadow_can_be_disabled_and_enabled(self):
        old = sqldb.shadow_enabled
        sqldb.shadow_enabled = lambda: False
        try:
            self.assertIsNone(shadow.mirror("адрес", {"наименование": "x", "количество": 1}))
        finally:
            sqldb.shadow_enabled = old

    def test_shadow_writes_and_never_raises(self):
        old_connect, old_enabled = sqldb.connect, sqldb.shadow_enabled
        sqldb.connect = lambda *a, **k: old_connect(self.db_path)
        sqldb.shadow_enabled = lambda: True
        try:
            res = shadow.mirror("адрес", {"uuid": "u1", "коробка": "s/t1/e1/i1",
                                          "наименование": "Брюки/100/чёрный/42",
                                          "количество": 2})
            self.assertTrue(res["mirrored"])
            self.assertEqual(self.count("placements"), 1)
            # повтор с тем же uuid не создаёт дубль
            shadow.mirror("адрес", {"uuid": "u1", "коробка": "s/t1/e1/i1",
                                    "наименование": "Брюки/100/чёрный/42", "количество": 2})
            self.assertEqual(self.count("placements"), 1)
            # ошибка внутри не пробрасывается наружу
            res2 = shadow.mirror("неизвестно", {})
            self.assertFalse(res2["mirrored"])
        finally:
            sqldb.connect, sqldb.shadow_enabled = old_connect, old_enabled

    def test_audit_is_written(self):
        importer.import_workbook(self.book, self.con)
        rows = self.con.execute("SELECT action, outcome FROM audit_log").fetchall()
        self.assertTrue(any(r["action"] == "import" and r["outcome"] == "ok" for r in rows))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-export-"))
        self.con = sqldb.connect(self.tmp / "db.sqlite")
        sqldb.migrate(self.con)
        self.book = make_workbook(self.tmp / "template.xlsx")
        self.old_data = importer.DATA
        importer.DATA = self.tmp
        importer.import_workbook(self.book, self.con)

    def tearDown(self):
        importer.DATA = self.old_data
        self.con.close()

    def test_export_creates_new_file_and_keeps_template(self):
        import exporter
        before = self.book.read_bytes()
        rep = exporter.export_from_sql(self.con, template=self.book, out_dir=self.tmp / "out")
        self.assertTrue(rep["ok"], rep["проверки"])
        self.assertTrue(Path(rep["файл"]).exists())
        self.assertEqual(self.book.read_bytes(), before, "шаблон не должен меняться")
        self.assertNotEqual(Path(rep["файл"]).resolve(), self.book.resolve())

    def test_export_preserves_formulas_outside_app_sheets(self):
        import exporter
        from openpyxl import Workbook, load_workbook
        wb = load_workbook(self.book)
        ws = wb["главный"]
        ws["S5"] = "=SUM(R5:R6)"      # формула в листе, который экспорт не трогает
        wb.save(self.book)
        rep = exporter.export_from_sql(self.con, template=self.book, out_dir=self.tmp / "out2")
        self.assertTrue(rep["проверки"]["формулы_сохранены"], rep["проверки"])

    def test_export_does_not_write_into_app_sheet_formulas(self):
        import exporter
        rep = exporter.export_from_sql(self.con, template=self.book, out_dir=self.tmp / "out3")
        wb = load_workbook(Path(rep["файл"]), data_only=False)
        try:
            for name in exporter.APP_SHEETS:
                if name in wb.sheetnames:
                    for row in wb[name].iter_rows(values_only=True):
                        for v in row:
                            self.assertFalse(isinstance(v, str) and v.startswith("="))
        finally:
            wb.close()


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-preview-"))
        self.con = sqldb.connect(self.tmp / "db.sqlite")
        sqldb.migrate(self.con)
        self.book = make_workbook(self.tmp / "book.xlsx")
        self.old_data = importer.DATA
        importer.DATA = self.tmp
        importer.import_workbook(self.book, self.con)

    def tearDown(self):
        importer.DATA = self.old_data
        self.con.close()

    def test_preview_of_current_state_is_empty(self):
        import import_preview
        out = import_preview.preview(self.book, self.con)
        self.assertTrue(out["совпадает"])
        self.assertEqual(out["всего_изменений"], 0)

    def test_preview_detects_changed_quantity(self):
        import import_preview
        self.con.execute("UPDATE placements SET qty = qty + 7 WHERE qty > 0")
        out = import_preview.preview(self.book, self.con)
        self.assertFalse(out["совпадает"])
        self.assertGreater(out["всего_изменений"], 0)
        self.assertEqual(out["изменения"][0]["тип"], "update")

    def test_preview_reports_missing_sheets(self):
        import import_preview
        from openpyxl import Workbook, load_workbook
        bad = self.tmp / "bad.xlsx"
        wb = Workbook()
        wb.active.title = "чужой"
        wb.save(bad)
        out = import_preview.preview(bad, self.con)
        self.assertFalse(out["проверки_структуры"]["обязательные_листы"]["главный"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
