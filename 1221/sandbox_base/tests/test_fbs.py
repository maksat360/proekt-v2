# -*- coding: utf-8 -*-
"""FBS: импорт новых заказов из WB, идемпотентность, подтверждение в сборку."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "sql"))
sys.path.insert(0, str(BASE))

import cabinets_store  # noqa: E402
import db as sqldb  # noqa: E402
import wb_api  # noqa: E402
import wb_sync  # noqa: E402

SAMPLE = [
    # один заказ (rid=500) с двумя позициями — как у клиента
    {"id": 101, "rid": 500, "article": "Брюки/477/чёрный/42", "skus": ["2049570812130"],
     "price": 250000, "convertedPrice": 250000, "createdAt": "2026-11-04T10:00:00Z",
     "sizeCode": "42", "colorCode": "чёрный"},
    {"id": 103, "rid": 500, "article": "Брюки/477/чёрный/42", "skus": ["2049570812130"],
     "price": 250000, "convertedPrice": 250000, "createdAt": "2026-11-04T10:00:00Z",
     "sizeCode": "42", "colorCode": "чёрный"},
    # второй заказ без сопоставления
    {"id": 102, "rid": 501, "article": "Неизвестный/товар/чёрный/50", "skus": ["2000000000001"],
     "price": 199900, "convertedPrice": 199900, "createdAt": "2026-11-04T10:05:00Z"},
]


_REAL_STATUSES = wb_api.order_statuses
STATUSES: dict = {}  # статусы WB для тестов: id → {supplierStatus, wbStatus}


def setUpModule():  # в тестах в настоящий WB не ходим
    wb_api.order_statuses = lambda token, ids: {i: STATUSES[i] for i in map(str, ids) if i in STATUSES}


def tearDownModule():
    wb_api.order_statuses = _REAL_STATUSES


class FbsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-fbs-"))
        self.con = sqldb.connect(self.tmp / "db.sqlite")
        sqldb.migrate(self.con)
        self.con.execute("INSERT INTO products(id, name, created_at) VALUES ('p1','Брюки/477/чёрный/42',?)",
                         (sqldb.now(),))
        self.con.execute("""INSERT INTO placements(id, ts, location_code, product_id, qty, external_uuid)
                            VALUES ('pl0', ?, 's/t1/e1/i1', 'p1', 5, 'pl0')""", (sqldb.now(),))
        self.con.commit()

        # подменяем пути кабинетов и токенов на временные
        self._old = (cabinets_store.CABINETS, cabinets_store.TOKENS)
        cabinets_store.CABINETS = self.tmp / "cabinets.json"
        cabinets_store.TOKENS = self.tmp / "tokens.json"
        cabinets_store.cabinets()                     # создаст 3 по умолчанию
        cabinets_store.save_cabinet("zhsk", "ЖСК", token="token-zhsk")
        cabinets_store.save_cabinet("kkm", "ККМ", token="token-kkm")

        # подменяем соединение и сеть
        self._old_connect = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old_connect(self.tmp / "db.sqlite")
        self._old_new = wb_api.new_orders
        self._old_confirm = wb_api.confirm_orders
        self._old_all = wb_api.all_orders
        wb_api.all_orders = lambda token, **k: {}
        self.confirmed = []

        def fake_new(token):
            if token == "token-zhsk":
                return list(SAMPLE)
            return []

        def fake_confirm(token, ids):
            self.confirmed.append((token, list(ids)))
            return {}

        wb_api.new_orders = fake_new
        wb_api.confirm_orders = fake_confirm
        import warehouse  # справочник баркодов — свой, не из рабочей книги
        self._old_bc = warehouse.resolve_by_barcode
        warehouse.resolve_by_barcode = lambda bc: {"2049570812130": "Брюки/477/чёрный/42"}.get(bc)

    def tearDown(self):
        import warehouse
        warehouse.resolve_by_barcode = self._old_bc
        cabinets_store.CABINETS, cabinets_store.TOKENS = self._old
        sqldb.connect = self._old_connect
        wb_api.new_orders = self._old_new
        wb_api.confirm_orders = self._old_confirm
        wb_api.all_orders = self._old_all
        wb_api.all_orders = self._old_all
        self.con.close()

    def orders(self):
        return self.con.execute("SELECT * FROM orders WHERE type='fbs' ORDER BY external_id").fetchall()

    def test_sync_creates_orders_with_cabinet(self):
        res = wb_sync.sync()
        self.assertEqual(res["создано"], 3, "три задания = три заказа, даже если rid общий")
        rows = self.orders()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["external_id"] for r in rows}, {"101", "102", "103"})
        self.assertEqual({r["cabinet_id"] for r in rows}, {"zhsk"})
        self.assertEqual({r["status"] for r in rows}, {"new"})

    def test_sync_is_idempotent(self):
        wb_sync.sync()
        wb_sync.sync()
        self.assertEqual(len(self.orders()), 3, "повторная синхронизация не должна дублировать")

    def test_article_matching(self):
        wb_sync.sync()
        items = self.con.execute(
            """SELECT i.external_id, i.product_id FROM orders o
               JOIN order_items i ON i.order_id = o.id WHERE o.type='fbs'""").fetchall()
        by_ext = {r["external_id"]: r["product_id"] for r in items}
        self.assertEqual(by_ext["101"], "p1")
        self.assertEqual(by_ext["103"], "p1", "вторая позиция того же заказа")
        self.assertIsNone(by_ext["102"], "неизвестный артикул остаётся без товара")

    def test_history_written(self):
        wb_sync.sync()
        rows = self.con.execute("SELECT * FROM order_status_history").fetchall()
        self.assertEqual(len(rows), 3, "по одной записи на заказ")
        self.assertEqual(rows[0]["to_status"], "new")
        self.assertEqual(rows[0]["actor"], "wb-api")

    def test_confirm_moves_to_processing(self):
        wb_sync.sync()
        oid = [o for o in self.orders() if o["external_id"] == "101"][0]["id"]
        wb_sync.pick(oid, actor="sklad")
        res = wb_sync.confirm([oid], actor="sklad")
        self.assertEqual(res["подтверждено"], 1)
        self.assertTrue(self.confirmed, "в WB должен уйти запрос confirm")
        self.assertEqual(self.confirmed[0][1], [101], "подтверждается задание №101")
        row = self.con.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
        self.assertEqual(row["status"], "processing")
        hist = self.con.execute(
            "SELECT * FROM order_status_history WHERE order_id=? ORDER BY id DESC LIMIT 1",
            (oid,)).fetchone()
        self.assertEqual((hist["from_status"], hist["to_status"]), ("picking", "processing"))

    def test_confirm_twice_is_refused(self):
        wb_sync.sync()
        oid = [o for o in self.orders() if o["external_id"] == "101"][0]["id"]
        wb_sync.pick(oid)
        wb_sync.confirm([oid])
        res = wb_sync.confirm([oid])
        self.assertEqual(res["подтверждено"], 0)
        self.assertEqual(len(res["ошибки"]), 1)

    def test_cabinet_without_token_is_skipped(self):
        res = wb_sync.sync()
        skipped = [c for c in res["кабинеты"] if c.get("пропущен")]
        self.assertTrue(any(c["id"] == "altyn" for c in skipped))


class PickTests(unittest.TestCase):
    """Сборка сканером: что есть — уходит, чего нет — остаётся."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-pick-"))
        self.con = sqldb.connect(self.tmp / "db.sqlite")
        sqldb.migrate(self.con)
        self.con.execute("INSERT INTO products(id, name, created_at) VALUES ('p1','Брюки/477/чёрный/42',?)",
                         (sqldb.now(),))
        self.con.execute("INSERT INTO products(id, name, created_at) VALUES ('p2','Худи/265/серый/XL',?)",
                         (sqldb.now(),))
        self.con.commit()

        # остатки: p1 — 5 шт (через размещение), p2 — 0
        self.con.execute("""INSERT INTO placements(id, ts, location_code, product_id, qty, external_uuid)
                            VALUES ('pl1', ?, 's/t1/e1/i1', 'p1', 5, 'pl1')""", (sqldb.now(),))
        # два FBS-заказа: один с остатком, второй без
        for ext, pid, title in (("201", "p1", "Брюки/477/чёрный/42"), ("202", "p2", "Худи/265/серый/XL")):
            oid = "o" + ext
            self.con.execute("""INSERT INTO orders(id, ts, client, status, type, cabinet_id, external_id)
                                VALUES (?,?,'ЖСК','new','fbs','zhsk',?)""", (oid, sqldb.now(), ext))
            self.con.execute("""INSERT INTO order_items(id, order_id, product_id, qty, shipped, title)
                                VALUES (?,?,?,1,0,?)""", ("i" + ext, oid, pid, title))
        self.con.commit()

        self._old = (cabinets_store.CABINETS, cabinets_store.TOKENS)
        cabinets_store.CABINETS = self.tmp / "c.json"
        cabinets_store.TOKENS = self.tmp / "t.json"
        cabinets_store.cabinets()
        cabinets_store.save_cabinet("zhsk", "ЖСК", token="token-zhsk")

        self._old_connect = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old_connect(self.tmp / "db.sqlite")
        self._old_confirm = wb_api.confirm_orders
        self._old_all = wb_api.all_orders
        wb_api.all_orders = lambda token, **k: {}
        self.sent = []
        wb_api.confirm_orders = lambda token, ids: self.sent.append(list(ids)) or {}

    def tearDown(self):
        cabinets_store.CABINETS, cabinets_store.TOKENS = self._old
        sqldb.connect = self._old_connect
        wb_api.confirm_orders = self._old_confirm
        self.con.close()

    def test_pickable_shows_stock(self):
        rows = {r["external_id"]: r for r in wb_sync.pickable()}
        self.assertTrue(rows["201"]["can_pick"])
        self.assertFalse(rows["202"]["can_pick"])
        self.assertEqual(rows["201"]["stock"], 5)

    def test_pick_moves_to_picking(self):
        res = wb_sync.pick("o201", actor="sklad")
        self.assertEqual(res["статус"], "собран")
        row = self.con.execute("SELECT status FROM orders WHERE id='o201'").fetchone()
        self.assertEqual(row["status"], "picking")

    def test_pick_without_stock_is_allowed_with_warning(self):
        res = wb_sync.pick("o202", actor="sklad")
        self.assertEqual(res["статус"], "собран")
        self.assertIn("нет в наличии", res["предупреждение"])
        row = self.con.execute("SELECT status FROM orders WHERE id='o202'").fetchone()
        self.assertEqual(row["status"], "picking")

    def test_confirm_without_stock_sends_without_shipment(self):
        wb_sync.pick("o202", actor="sklad")
        res = wb_sync.confirm(["o202"], actor="sklad")
        self.assertEqual(res["подтверждено"], 1)
        self.assertEqual(self.sent, [[202]])
        self.assertIsNone(self.con.execute(
            "SELECT * FROM shipments WHERE order_ref='202'").fetchone())

    def test_confirm_from_new_is_allowed(self):
        # сборка идёт через общий экран заказа: подтверждение — явное действие
        res = wb_sync.confirm(["o201"], actor="sklad")
        self.assertEqual(res["подтверждено"], 1)
        self.assertEqual(self.sent, [[201]])
        hist = [dict(h) for h in self.con.execute(
            "SELECT * FROM order_status_history WHERE order_id='o201' ORDER BY id")]
        self.assertEqual(hist[-1]["to_status"], "processing")

    def test_pick_deducts_stock(self):
        self.assertEqual(wb_sync.pickable()[0]["stock"], 5)
        wb_sync.pick("o201", actor="sklad")
        ship = self.con.execute("SELECT * FROM shipments WHERE source_sheet='FBS'").fetchone()
        self.assertIsNotNone(ship, "при сборке товар должен списаться со склада")
        self.assertEqual(ship["qty"], 1)

    def test_confirm_picked_sends_and_writes_shipment(self):
        wb_sync.pick("o201", actor="sklad")
        res = wb_sync.confirm(["o201"], actor="sklad")
        self.assertEqual(res["подтверждено"], 1)
        self.assertEqual(self.sent, [[201]])
        row = self.con.execute("SELECT status FROM orders WHERE id='o201'").fetchone()
        self.assertEqual(row["status"], "processing")
        ship = self.con.execute("SELECT * FROM shipments WHERE source_sheet='FBS'").fetchone()
        self.assertIsNotNone(ship)
        self.assertEqual(ship["target"], "WB")
        hist = [dict(h) for h in self.con.execute(
            "SELECT * FROM order_status_history WHERE order_id='o201' ORDER BY id")]
        self.assertEqual([h["to_status"] for h in hist], ["picking", "processing"])


class AggregateTests(unittest.TestCase):
    """Все FBS-позиции — как один заказ, массовая сборка."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-agg-"))
        self.con = sqldb.connect(self.tmp / "db.sqlite")
        sqldb.migrate(self.con)
        self.con.execute("INSERT INTO products(id, name, created_at) VALUES ('p1','Товар А',?)", (sqldb.now(),))
        self.con.execute("INSERT INTO products(id, name, created_at) VALUES ('p2','Товар Б',?)", (sqldb.now(),))
        self.con.execute("""INSERT INTO orders(id, ts, client, status, type, cabinet_id, external_id)
                            VALUES ('o700', ?, 'ЖСК','new','fbs','zhsk','700')""", (sqldb.now(),))
        for item, pid, title in (("701", "p1", "Товар А"), ("702", "p2", "Товар Б")):
            self.con.execute("""INSERT INTO order_items(id, order_id, product_id, qty, shipped, title, external_id)
                                VALUES (?,?,?,1,0,?,?)""", (f"i{item}", "o700", pid, title, item))
        self.con.commit()

        self._old = (cabinets_store.CABINETS, cabinets_store.TOKENS)
        cabinets_store.CABINETS = self.tmp / "c.json"
        cabinets_store.TOKENS = self.tmp / "t.json"
        cabinets_store.cabinets()
        cabinets_store.save_cabinet("zhsk", "ЖСК", token="token-zhsk")
        self._old_connect = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old_connect(self.tmp / "db.sqlite")
        self._old_confirm = wb_api.confirm_orders
        self._old_all = wb_api.all_orders
        wb_api.all_orders = lambda token, **k: {}
        self.sent = []
        wb_api.confirm_orders = lambda token, ids: self.sent.append(list(ids)) or {}

    def tearDown(self):
        cabinets_store.CABINETS, cabinets_store.TOKENS = self._old
        sqldb.connect = self._old_connect
        wb_api.confirm_orders = self._old_confirm
        self.con.close()

    def test_aggregate_is_one_order(self):
        agg = wb_sync.aggregate_order()
        self.assertIsNotNone(agg)
        self.assertTrue(agg["агрегат"])
        self.assertEqual(len(agg["позиции"]), 2, "обе позиции внутри одного заказа")

    def test_confirm_items_sends_only_checked(self):
        agg = wb_sync.aggregate_order()
        first = agg["позиции"][0]["item_id"]
        res = wb_sync.confirm_items([first], actor="sklad")
        self.assertEqual(res["подтверждено"], 1)
        self.assertEqual(self.sent, [[701]])
        # вторая позиция осталась новой
        row = self.con.execute("SELECT status FROM orders WHERE id='o700'").fetchone()
        self.assertEqual(row["status"], "processing")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class BarcodeMatchTests(unittest.TestCase):
    """Баркоды WB пишутся в колонку T «главного» (по артикулу B и размеру C); FBS ищет только по ним."""

    def setUp(self):
        import warehouse
        from openpyxl import Workbook
        self.wh = warehouse
        self.tmp = Path(tempfile.mkdtemp(prefix="v2-bc-"))
        self.book = self.tmp / "book.xlsm"
        wb = Workbook()
        ws = wb.active
        ws.title = "главный"
        for _ in range(4):
            ws.append([])
        for art, size, name in (("Брюки/477/чёрный/", "42", "Брюки/477/чёрный/42"),
                                ("Брюки/477/чёрный/", "44", "Брюки/477/чёрный/44"),
                                ("Постель/шанель/", None, "Постель/шанель/1 сп")):
            ws.append(["", art, size] + [""] * 8 + [name])
        wb.save(self.book)
        wb = Workbook()
        ws = wb.active
        ws.title = "Товары"
        for _ in range(4):
            ws.append([])
        for art, bc, size in (("Брюки/477/чёрный/", "111", "44"), ("Брюки/477/чёрный/", "112", "42."),
                              ("Постель/шанель/", "113", "0"), ("28Б-ч", "114", "44")):
            ws.append([1, art] + [""] * 9 + [bc, size])
        self.export = self.tmp / "wb.xlsx"
        wb.save(self.export)
        self._old = (warehouse.source_path, warehouse.cex_guard, warehouse._backup)
        warehouse.source_path = lambda: self.book
        warehouse.cex_guard = lambda p: None
        warehouse._backup = lambda p: None
        warehouse._ART_CACHE["key"] = None

    def tearDown(self):
        self.wh.source_path, self.wh.cex_guard, self.wh._backup = self._old
        self.wh._ART_CACHE["key"] = None

    def test_import_into_main_sheet_and_resolve(self):
        res = self.wh.import_barcodes(self.export)
        self.assertEqual((res["баркодов"], res["строк_заполнено"]), (4, 3))
        self.assertEqual(res["нет_в_главном"], [("28б-ч", "44", "114")])
        r = self.wh.resolve_by_barcode
        self.assertEqual(r("111"), "Брюки/477/чёрный/44", "артикул и размер вместе, а не первый 42-й")
        self.assertEqual(r("112"), "Брюки/477/чёрный/42", "«42.» = «42»")
        self.assertEqual(r("113"), "Постель/шанель/1 сп", "размер «0» = без размера")
        self.assertIsNone(r("114"))
        self.wh.import_barcodes(self.export)  # повторная загрузка не дублирует
        from openpyxl import load_workbook
        self.assertEqual(load_workbook(self.book)["главный"]["T6"].value, "111")


class WbStagesTests(unittest.TestCase):
    """Этапы как во вкладках WB: На сборке → В доставке → Завершённые; подтягиваем то, что уже в работе."""

    def test_wb_target(self):
        t = wb_sync.wb_target
        self.assertEqual(t({"supplierStatus": "confirm", "wbStatus": "waiting"}), wb_sync.STATUS_PROCESSING)
        self.assertEqual(t({"supplierStatus": "complete", "wbStatus": "waiting"}), wb_sync.STATUS_SHIPPED)
        self.assertEqual(t({"supplierStatus": "complete", "wbStatus": "sorted"}), wb_sync.STATUS_DONE)  # принят складом WB
        self.assertEqual(t({"supplierStatus": "complete", "wbStatus": "sold"}), wb_sync.STATUS_DONE)
        self.assertEqual(t({"supplierStatus": "complete", "wbStatus": "canceled_by_client"}), wb_sync.STATUS_CANCELLED)
        self.assertIsNone(t({}))

    def test_reconcile_moves_and_imports(self):
        tmp = Path(tempfile.mkdtemp(prefix="v2-stages-"))
        con = sqldb.connect(tmp / "db.sqlite")
        sqldb.migrate(con)
        cab = {"id": "zhsk", "name": "ЖСК"}
        for oid in ("1", "2", "3"):
            wb_sync._upsert_order(con, cab, {"id": int(oid), "rid": oid, "article": "477", "skus": [],
                                             "createdAt": "2026-11-10T07:00:00Z"})
        con.execute("UPDATE orders SET status='picking' WHERE external_id='3'")
        STATUSES.clear()
        STATUSES.update({"1": {"supplierStatus": "complete", "wbStatus": "waiting"},
                         "2": {"supplierStatus": "complete", "wbStatus": "sold"},
                         "3": {"supplierStatus": "confirm", "wbStatus": "waiting"},
                         "9": {"supplierStatus": "confirm", "wbStatus": "waiting"},   # не застали в «Новых»
                         "8": {"supplierStatus": "complete", "wbStatus": "sold"}})   # давно завершён — не тянем
        old_all = wb_api.all_orders
        wb_api.all_orders = lambda token, **k: {i: {"id": int(i), "rid": i, "article": "477", "skus": [],
                                                    "createdAt": "2026-11-09T07:00:00Z"} for i in ("1", "2", "3", "8", "9")}
        try:
            res = wb_sync.reconcile(con, "zhsk", set(), "t", cabinet=cab)
        finally:
            wb_api.all_orders = old_all
        st = {r[0]: r[1] for r in con.execute("SELECT external_id, status FROM orders")}
        self.assertEqual(st, {"1": "shipped", "2": "done", "3": "picking", "9": "processing"})
        self.assertEqual((res["подтянуто"], res["отправлено"], res["завершено"]), (1, 1, 1))
