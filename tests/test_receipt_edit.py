# -*- coding: utf-8 -*-
"""Правка принятой партии: дописывается разница (+/−) в ту же партию, история не стирается,
уменьшить ниже уже отгруженного нельзя."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))
sys.path.insert(0, str(BASE))

import db as sqldb  # noqa: E402
import fbs_stock  # noqa: E402
import warehouse  # noqa: E402

A, B = "Брюки/477/чёрный/42", "Брюки/477/чёрный/44"
STOCK = ("SELECT COALESCE((SELECT SUM(qty) FROM placements WHERE product_id=?),0) - "
         "COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id=?),0)")


class ReceiptEditTests(unittest.TestCase):
    def setUp(self):
        path = Path(tempfile.mkdtemp(prefix="v2-rcpt-")) / "db.sqlite"
        self._old = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old(path)
        con = sqldb.connect()
        sqldb.migrate(con)
        for pid, name in (("a", A), ("b", B)):
            con.execute("INSERT INTO products(id, name, created_at) VALUES (?,?,?)", (pid, name, sqldb.now()))
        con.execute("""INSERT INTO purchases(id, ts, supplier, batch, product_id, qty, defect, source, external_uuid)
                       VALUES ('p1', ?, 'гулжамал', '28', 'a', 10, 0, 'shadow', 'x1')""", (sqldb.now(),))
        con.execute("INSERT INTO placements(id, ts, location_code, product_id, qty) VALUES ('pl1', ?, 'без адреса', 'a', 10)",
                    (sqldb.now(),))
        con.execute("INSERT INTO shipments(id, ts, target, product_id, qty) VALUES ('s1', ?, 'WB', 'a', 7)", (sqldb.now(),))
        con.close()
        self.patches = [mock.patch.object(warehouse, "resolve_product", lambda n: {"наименование": n} if n in (A, B) else None),
                        mock.patch.object(fbs_stock, "fact_by_name", self.fact)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        sqldb.connect = self._old

    def stock(self, pid):
        con = sqldb.connect()
        try:
            return con.execute(STOCK, (pid, pid)).fetchone()[0]
        finally:
            con.close()

    def fact(self):
        return {A: self.stock("a"), B: self.stock("b")}

    def test_add_reduce_and_new_size(self):
        res = warehouse.receipt_edit("гулжамал", "28", [{"наименование": A, "количество": 12},
                                                        {"наименование": B, "количество": 5}], "склад")
        self.assertEqual(res, {"изменено": 2, "плюс": 7, "минус": 0})
        self.assertEqual((self.stock("a"), self.stock("b")), (5, 5))  # 10 + 2 − 7 отгружено; новый размер +5
        self.assertEqual(warehouse.receipt_edit("гулжамал", "28", [{"наименование": A, "количество": 9}], "склад")["минус"], 3)
        self.assertEqual(self.stock("a"), 2)
        with self.assertRaisesRegex(ValueError, "часть уже отгружена"):
            warehouse.receipt_edit("гулжамал", "28", [{"наименование": A, "количество": 0}], "склад")  # 9 → 0, а на складе 2
        self.assertEqual(warehouse.receipt_edit("гулжамал", "28", [{"наименование": A, "количество": 9}], "склад")["изменено"], 0)


if __name__ == "__main__":
    unittest.main()
