# -*- coding: utf-8 -*-
"""Отчёты начальника: поставки по неделям и ИП, продажи категория → артикул → размер."""
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402
import boss_report  # noqa: E402


class BossReportTests(unittest.TestCase):
    def test_build(self):
        con = sqldb.connect(Path(tempfile.mkdtemp(prefix="v2-boss-")) / "db.sqlite")
        sqldb.migrate(con)
        for pid, cat, model, size in (("p1", "Брюки", "477", "42"), ("p2", "Брюки", "477", "44"),
                                      ("p3", "Постель", "шахмат", "1 сп"), ("p4", "Худи", "263", "XL")):
            con.execute("INSERT INTO products(id, name, category, model, size, created_at) VALUES (?,?,?,?,?,?)",
                        (pid, f"{cat}/{model}/{size}", cat, model, size, "2026-11-01"))
        for i, (target, ts, pid, qty) in enumerate((
                ("ЖСК", "2026-11-12 10:00:00", "p1", 3),   # четверг → неделя с понедельника 09.11
                ("ЖСК", "2026-11-10 09:00:00", "p3", 2),
                ("ААТ", "2026-11-03 09:00:00", "p2", 1),
                ("WB", "2026-11-13 09:00:00", "p1", 4),    # FBS без заказа — только в продажах
                ("САДЫК", "2026-11-14 09:00:00", "p1", 9))):  # заказ сотрудника — покупатель
            con.execute("INSERT INTO shipments(id, ts, target, product_id, qty) VALUES (?,?,?,?,?)",
                        (f"s{i}", ts, target, pid, qty))
        con.execute("INSERT INTO orders(id, ts, client, type, cabinet_id) VALUES ('o1', '2026-11-12', 'WB', 'fbs', 'zhsk')")
        con.execute("INSERT INTO shipments(id, ts, target, product_id, qty, order_ref) VALUES ('s9', ?, 'WB', 'p3', 1, 'o1')",
                    ("2026-11-13 10:00:00",))  # FBS кабинета ЖСК — в поставки ЖСК
        stock = {"Брюки/477/42": 5, "Брюки/477/44": 2, "Худи/263/XL": 4}  # худи не продавали, но остаток есть
        r = boss_report.build(con, stock)
        self.assertEqual(r["категории"], ["Брюки", "Постель"])
        self.assertEqual([(x["неделя"], x["ип"], x["покупатель"], x["итог"]) for x in r["поставки"]],
                         [("2026-11-09", "ЖСК", False, 6), ("2026-11-09", "Садык", True, 9),
                          ("2026-11-02", "Алтын", False, 1)])
        s = r["продажи"]
        self.assertEqual(s["всего"], 20)
        br = s["категории"][0]
        self.assertEqual((br["категория"], br["штук"], br["доля"]), ("Брюки", 17, 85.0))
        self.assertEqual(br["остаток"], 7)
        self.assertEqual(br["артикулы"][0]["размеры"], [{"размер": "42", "штук": 16, "остаток": 5},
                                                        {"размер": "44", "штук": 1, "остаток": 2}])
        self.assertEqual(s["остаток"], 11)
        hoodie = next(c for c in s["категории"] if c["категория"] == "Худи")
        self.assertEqual((hoodie["штук"], hoodie["остаток"]), (0, 4))


if __name__ == "__main__":
    unittest.main()
