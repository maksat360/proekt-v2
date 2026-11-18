# -*- coding: utf-8 -*-
"""Ревизия: скан находит товар, поправка ±N, проведение прибавляет/списывает её, повтор невозможен."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))
sys.path.insert(0, str(BASE))

import db as sqldb  # noqa: E402
import revision  # noqa: E402

STOCK = "SELECT COALESCE((SELECT SUM(qty) FROM placements WHERE product_id=?),0) - " \
        "COALESCE((SELECT SUM(qty) FROM shipments WHERE product_id=?),0)"


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-rev-"))
        path = self.tmp / "db.sqlite"
        self._old = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old(path)
        con = sqldb.connect()
        sqldb.migrate(con)
        for pid, name, qty in (("a", "Постель/сакура/голубой, белый/1 сп", 10),
                               ("b", "Постель/сирень/белый, сиреневый/1 сп", 4),
                               ("c", "Брюки/477/чёрный/42", 7)):
            con.execute("INSERT INTO products(id, name, created_at) VALUES (?,?,?)", (pid, name, sqldb.now()))
            con.execute("INSERT INTO placements(id, ts, location_code, product_id, qty) VALUES (?,?,?,?,?)",
                        ("pl" + pid, sqldb.now(), "x", pid, qty))
        con.close()

    def tearDown(self):
        sqldb.connect = self._old

    def stock(self, pid):
        con = sqldb.connect()
        try:
            return con.execute(STOCK, (pid, pid)).fetchone()[0]
        finally:
            con.close()

    def test_count_and_apply(self):
        rid = revision.start("Постель", "склад")["id"]
        with self.assertRaises(ValueError):
            revision.start("", "склад")  # вторая открытая — нельзя
        cur = revision.current()
        self.assertEqual([i["наименование"] for i in cur["товары"]],
                         ["Постель/сакура/голубой, белый/1 сп", "Постель/сирень/белый, сиреневый/1 сп"])
        # скан только находит товар — ничего не меняет (раньше один скан = «всего 1 шт» и списание остального)
        self.assertEqual(revision.count(rid, "Постель/сакура/голубой, белый/1 сп", "склад")["поправка"], None)
        revision.count(rid, "Постель/сакура/голубой, белый/1 сп", "склад", delta=-2)
        revision.count(rid, "Постель/сирень/белый, сиреневый/1 сп", "склад", delta=1)
        revision.count(rid, "Постель/сирень/белый, сиреневый/1 сп", "склад", delta=2)    # исправил: +2
        revision.count(rid, "Брюки/477/чёрный/42", "склад", delta=3)
        revision.count(rid, "Брюки/477/чёрный/42", "склад", delta=0)                     # 0 — убрать
        with self.assertRaisesRegex(ValueError, "всего 10"):
            revision.count(rid, "Постель/сакура/голубой, белый/1 сп", "склад", delta=-11)
        cur = {i["наименование"]: i for i in revision.current()["товары"]}
        self.assertEqual(cur["Постель/сакура/голубой, белый/1 сп"]["станет"], 8)
        res = revision.apply(rid, "склад")
        self.assertEqual(res, {"позиций": 2, "излишек": 2.0, "недостача": 2.0})
        self.assertEqual((self.stock("a"), self.stock("b"), self.stock("c")), (8, 6, 7))
        with self.assertRaises(ValueError):
            revision.apply(rid, "склад")
        self.assertIsNone(revision.current())
        h = revision.history()[0]
        self.assertEqual((h["статус"], h["позиций"], len(h["расхождения"])), ("проведена", 2, 2))
        self.assertEqual({(d["система"], d["факт"]) for d in h["расхождения"]}, {(10, 8), (4, 6)})

    def test_cancel_changes_nothing(self):
        rid = revision.start("", "склад")["id"]
        revision.count(rid, "Брюки/477/чёрный/42", "склад", delta=-1)
        revision.count(rid, "Постель/сакура/голубой, белый/1 сп", "склад", delta=3)
        revision.count(rid, "Постель/сакура/голубой, белый/1 сп", "склад", delta=None)  # стёр поле
        revision.cancel(rid, "склад")
        self.assertEqual(self.stock("c"), 7)
        self.assertEqual(revision.history()[0]["позиций"], 1)

    def test_undo_restores_stock(self):
        rid = revision.start("", "склад")["id"]
        revision.count(rid, "Брюки/477/чёрный/42", "склад", delta=-2)
        revision.count(rid, "Постель/сирень/белый, сиреневый/1 сп", "склад", delta=3)
        revision.apply(rid, "склад")
        self.assertEqual((self.stock("c"), self.stock("b")), (5, 7))
        self.assertEqual(revision.undo(rid, "начальник")["позиций"], 2)
        self.assertEqual((self.stock("c"), self.stock("b")), (7, 4), "остаток — как до ревизии")
        self.assertEqual(revision.history()[0]["статус"], "откатена")
        with self.assertRaises(ValueError):
            revision.undo(rid, "начальник")  # второй раз — нельзя

    def test_undo_refuses_when_surplus_already_shipped(self):
        rid = revision.start("", "склад")["id"]
        revision.count(rid, "Постель/сирень/белый, сиреневый/1 сп", "склад", delta=3)
        revision.apply(rid, "склад")
        con = sqldb.connect()
        con.execute("INSERT INTO shipments(id, ts, target, product_id, qty) VALUES ('s1', ?, 'WB', 'b', 6)", (sqldb.now(),))
        con.close()
        with self.assertRaisesRegex(ValueError, "излишек ревизии уже ушёл"):
            revision.undo(rid, "начальник")
        self.assertEqual(self.stock("b"), 1, "ничего не тронуто")


if __name__ == "__main__":
    unittest.main()
