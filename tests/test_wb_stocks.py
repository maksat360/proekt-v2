import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sql"))

import wb_stocks  # noqa: E402


SIZES = [
    {"chrtId": 1, "barcodes": ["111"], "article": "477-ч", "size": "64"},
    {"chrtId": 2, "barcodes": ["222"], "article": "477-ч", "size": "62"},
    {"chrtId": 3, "barcodes": ["333"], "article": "чужой", "size": "S"},
    {"chrtId": 4, "barcodes": [], "article": "477-ч", "size": "60"},
    {"chrtId": 1, "barcodes": ["111"], "article": "477-ч", "size": "64"},  # дубль — один раз
]
BARCODES = {"111": "Брюки/477/чёрный/64", "222": "Брюки/477/чёрный/62"}
FACT = {"Брюки/477/чёрный/64": 101.0, "Брюки/477/чёрный/62": 30.0, "Брюки/477/чёрный/60": -2.0}
resolve = lambda art, size: {("477-ч", "60"): "Брюки/477/чёрный/60"}.get((art, size))  # noqa: E731


class PlanTest(unittest.TestCase):
    def test_only_differences_are_written(self):
        write, changes, unmapped = wb_stocks.plan(SIZES, {1: 101, 2: 5, 4: 3}, FACT, BARCODES, resolve)
        self.assertEqual(write, {2: 30, 4: 0})  # 64 совпал — не трогаем; минус → 0
        self.assertEqual(unmapped, 1)  # чужой товар не обнуляем
        self.assertEqual([c["товар"] for c in changes], ["Брюки/477/чёрный/62", "Брюки/477/чёрный/60"])

    def test_nothing_changed_nothing_written(self):
        write, _, _ = wb_stocks.plan(SIZES[:2], {1: 101, 2: 30}, FACT, BARCODES, resolve)
        self.assertEqual(write, {})


class AvailableTest(unittest.TestCase):
    def test_shop_free_minus_fbs_reserve(self):
        import warehouse
        with mock.patch.object(warehouse, "available_for_order", return_value={"А": 10.0, "Б": 1.0, "В": 5.0}), \
             mock.patch.object(wb_stocks, "fbs_reserved", return_value={"А": 2.0, "Б": 3.0}):
            self.assertEqual(wb_stocks.available(), {"А": 8.0, "Б": 0.0, "В": 5.0})


class SubstituteStockTest(unittest.TestCase):
    def test_out_of_stock_shows_substitute(self):
        import warehouse, substitutes
        free = {"Брюки/477/синий/58": 0.0, "Брюки/477/темно-синий/58": 40.0,
                "Брюки/477/синий/50": 3.0, "Брюки/477/темно-синий/50": 10.0}
        with mock.patch.object(warehouse, "available_for_order", return_value=free), \
             mock.patch.object(wb_stocks, "fbs_reserved", return_value={}), \
             mock.patch.object(substitutes, "load", return_value={"Брюки/477/синий": "Брюки/477/темно-синий"}):
            got = wb_stocks.available()
        self.assertEqual(got["Брюки/477/синий/58"], 40.0)  # своего нет — остаток тёмно-синего
        self.assertEqual(got["Брюки/477/синий/50"], 3.0)   # свой есть — свой
        self.assertEqual(got["Брюки/477/темно-синий/58"], 40.0)


class SyncCabinetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(wb_stocks, "STATE", Path(self.tmp.name) / "s.json")
        self.p.start()
        wb_stocks._CARDS.clear()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def _run(self, on, have):
        cab = {"id": "kkm", "name": "ККМ"}
        with mock.patch.object(wb_stocks.cabinets_store, "token", return_value="t"), \
             mock.patch.object(wb_stocks.cabinets_store, "analytics_token", return_value=""), \
             mock.patch.object(wb_stocks.wb_api, "warehouses", return_value=[{"id": 7, "name": "Цех"}]), \
             mock.patch.object(wb_stocks.wb_api, "card_sizes", return_value=SIZES[:2]), \
             mock.patch.object(wb_stocks.wb_api, "stocks", return_value=have), \
             mock.patch.object(wb_stocks.wb_api, "set_stocks") as put:
            res = wb_stocks.sync_cabinet(cab, FACT, BARCODES, resolve, on)
        return res, put

    def test_off_only_reports(self):
        res, put = self._run(False, {1: 100, 2: 30})
        put.assert_not_called()
        self.assertEqual((res["расходится"], res["записано"]), (1, 0))

    def test_on_writes_only_diff(self):
        res, put = self._run(True, {1: 100, 2: 30})
        put.assert_called_once_with("t", 7, {1: 101})
        self.assertEqual(res["записано"], 1)

    def test_on_no_diff_no_call(self):
        res, put = self._run(True, {1: 101, 2: 30})
        put.assert_not_called()
        self.assertEqual(res["ошибка"], "")

    def test_picks_warehouse_with_stock(self):
        cab = {"id": "zhsk", "name": "ЖСК"}
        whs = [{"id": 1, "name": "Upsell"}, {"id": 2, "name": "Мой склад"}]
        with mock.patch.object(wb_stocks.cabinets_store, "token", return_value="t"), \
             mock.patch.object(wb_stocks.cabinets_store, "analytics_token", return_value=""), \
             mock.patch.object(wb_stocks.wb_api, "warehouses", return_value=whs), \
             mock.patch.object(wb_stocks.wb_api, "card_sizes", return_value=SIZES[:2]), \
             mock.patch.object(wb_stocks.wb_api, "stocks", side_effect=lambda t, w, ids: {} if w == 1 else {1: 5}), \
             mock.patch.object(wb_stocks.wb_api, "set_stocks") as put:
            res = wb_stocks.sync_cabinet(cab, FACT, BARCODES, resolve, True)
            put.assert_called_once_with("t", 2, {1: 101, 2: 30})
            self.assertEqual(res["склад"], "Мой склад")
            put.reset_mock()
            with mock.patch.object(wb_stocks.wb_api, "stocks", return_value={}):
                res = wb_stocks.sync_cabinet(cab, FACT, BARCODES, resolve, True)
            put.assert_not_called()
            self.assertIn("все пустые", res["ошибка"])

    def test_run_skips_cabinet_when_orders_failed(self):
        import fbs_stock, wb_report
        wb_stocks.set_on(True)
        cabs = [{"id": "kkm", "name": "ККМ", "active": 1, "token_set": True},
                {"id": "zhsk", "name": "ЖСК", "active": 1, "token_set": True}]
        calls = {}
        def fake(cab, fact, bc, res, on):
            calls[cab["id"]] = on
            return {"имя": cab["name"], "записано": 0, "ошибка": ""}
        with mock.patch.object(wb_stocks, "pull_orders", return_value={"zhsk": "WB 429"}), \
             mock.patch.object(wb_stocks, "available", return_value=FACT), \
             mock.patch.object(fbs_stock, "fact_by_name", return_value=FACT), \
             mock.patch.object(wb_report, "_catalog", return_value=(BARCODES, {}, {}, str, str)), \
             mock.patch.object(wb_stocks.cabinets_store, "cabinets", return_value=cabs), \
             mock.patch.object(wb_stocks, "sync_cabinet", side_effect=fake):
            st = wb_stocks.run()
        self.assertEqual(calls, {"kkm": True, "zhsk": False})
        self.assertIn("заказы не обновились", st["кабинеты"]["zhsk"]["ошибка"])

    def test_switch_persists(self):
        self.assertFalse(wb_stocks.load()["вкл"])
        wb_stocks.set_on(True)
        self.assertTrue(wb_stocks.load()["вкл"])


if __name__ == "__main__":
    unittest.main()
