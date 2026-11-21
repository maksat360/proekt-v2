import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sew_plan  # noqa: E402

NAMES = [f"Брюки/477/{c}/{s}" for c in ("чёрный", "темно-синий", "синий", "бежевый") for s in ("50", "52")]
DEMAND = {("чёрный", "50"): 60, ("чёрный", "52"): 20, ("темно-синий", "50"): 10, ("синий", "52"): 10,
          ("бежевый", "50"): 5}
SUBS = {"Брюки/477/синий": "Брюки/477/темно-синий"}


class SewPlanTest(unittest.TestCase):
    def test_allocate_sums_and_rounds(self):
        got = sew_plan.allocate({"a": 3, "b": 1, "c": 0}, 100)
        self.assertEqual(sum(got.values()), 100)
        self.assertTrue(all(v % 10 == 0 for v in got.values()))
        self.assertEqual(got["c"], 0)
        self.assertGreater(got["a"], got["b"])

    def test_off_colors_fold_into_substitute_and_order_is_gap(self):
        stock = {"Брюки/477/чёрный/50": 100, "Брюки/477/синий/52": 7}
        res = sew_plan.compute(NAMES, DEMAND, stock, 1000, ["бежевый", "синий"], SUBS)
        row = {(r["цвет"], r["размер"]): r for r in res["строки"]}
        self.assertEqual(res["итого"]["норма"], 1000)
        self.assertEqual(row[("бежевый", "50")]["норма"], 0)  # бежевый не считаем
        self.assertEqual(row[("синий", "52")]["норма"], 0)  # синий не шьём…
        self.assertEqual(row[("темно-синий", "52")]["норма"], 100)  # …его спрос ушёл в тёмно-синий
        self.assertEqual(row[("чёрный", "50")]["норма"], 600)
        self.assertEqual(row[("чёрный", "50")]["шить"], 500)
        self.assertEqual(row[("синий", "52")]["лишнее"], 7)
        self.assertEqual(res["после"], res["итого"]["есть"] + res["итого"]["шить"])

    def test_xlsx_opens(self):
        from openpyxl import load_workbook
        res = sew_plan.compute(NAMES, DEMAND, {}, 1000, ["бежевый"], SUBS)
        res.update(модель="477", норма=1000, не_шьём=["бежевый"], дней=30, с="2026-10-21", категория="Брюки")
        wb = load_workbook(io.BytesIO(sew_plan.xlsx(res)))
        self.assertEqual(wb.sheetnames, ["Что шить", "Подробно", "Как считали"])


if __name__ == "__main__":
    unittest.main()
