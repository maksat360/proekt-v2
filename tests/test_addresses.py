# -*- coding: utf-8 -*-
"""Адресное хранение: ячейки, коробки, мешки, переезд коробки, вскрытие, мешок частями, замена этикетки."""
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402
import addresses as ad  # noqa: E402

BR = "Брюки/477/чёрный/44"


class AddressTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="v2-addr-")) / "db.sqlite"
        self._old = (sqldb.connect, ad._stock)
        sqldb.connect = lambda *a, **k: self._old[0](self.path)
        ad._stock = lambda: {BR: 30.0}
        ad._READY.clear()
        ad.create_rack("t", "P", 1, 5, 8)
        ad.create_rack("t", "N", 1, 7, 28)

    def tearDown(self):
        sqldb.connect, ad._stock = self._old

    def test_codes_and_route(self):
        self.assertEqual(len(ad.places("P")), 40)
        self.assertEqual(ad.places("N")[0]["код"], "N-1-01")
        self.assertEqual(ad.create_rack("t", "P", 1, 5, 8), [], "повторно не дублирует")
        self.assertEqual(ad.issue("t", "K", 3), ["K-0001", "K-0002", "K-0003"])
        self.assertEqual(ad.issue("t", "K", 2), ["K-0004", "K-0005"], "номера идут дальше")
        self.assertEqual(ad.norm("з1-3-05"), "P1-3-05", "русская раскладка сканера")
        self.assertLess(ad.route_key("P1-1-08"), ad.route_key("P1-2-01"))
        self.assertLess(ad.route_key("P6-5-04"), ad.route_key("N-1-01"))

    def test_box_moves_whole_and_opens_into_cell(self):
        k = ad.issue("t", "K", 1)[0]
        ad.put("t", k, BR, 20)
        with self.assertRaises(ValueError):
            ad.put("t", "P1-1-01", BR, 11)  # без адреса осталось 10
        ad.box_to("t", k, "N-2-05")
        ad.box_to("t", k, "N-3-01")
        self.assertEqual(ad.state(k)["где"], "N-3-01")
        self.assertEqual(ad.state("N-2-05")["коробки"], [], "старая ячейка освободилась сама")
        res = ad.box_to("t", k, "P1-1-01")
        self.assertEqual((res["действие"], res["штук"]), ("вскрыта", 20))
        self.assertEqual(ad.state("P1-1-01")["содержимое"], [{"наименование": BR, "количество": 20}])
        self.assertEqual((ad.state(k)["содержимое"], ad.state(k)["где"]), ([], ""), "пустая коробка свободна")
        with self.assertRaises(ValueError):
            ad.box_to("t", k, "N-1-01")  # пустую наружу не ставим

    def test_bag_partial_and_relabel(self):
        m = ad.issue("t", "M", 1)[0]
        ad.put("t", m, BR, 12)
        res = ad.move("t", m, "P1-2-03", [{"наименование": BR, "количество": 5}])
        self.assertEqual(res["осталось"], [{"наименование": BR, "количество": 7}])
        with self.assertRaises(ValueError):
            ad.move("t", m, "P1-2-03", [{"наименование": BR, "количество": 8}])
        w = ad.where(BR)
        self.assertEqual((w["без_адреса"], [a["код"] for a in w["адреса"]]), (18, ["P1-2-03", m]))
        k1, k2 = ad.issue("t", "K", 2)
        ad.put("t", k1, BR, 3)
        ad.box_to("t", k1, "N-1-02")
        ad.relabel("t", k1, k2)
        st = ad.state(k2)
        self.assertEqual((st["где"], st["содержимое"][0]["количество"]), ("N-1-02", 3))
        with self.assertRaisesRegex(ValueError, "списан"):
            ad.put("t", k1, BR, 1)


class AddressApiTests(unittest.TestCase):
    """Маршруты /api/wh/addr/* через настоящий сервер (временная база)."""
    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        import server
        self.server = server
        self.path = Path(tempfile.mkdtemp(prefix="v2-addr-api-")) / "db.sqlite"
        self._old = (sqldb.connect, ad._stock, server.Handler._session)
        sqldb.connect = lambda *a, **k: self._old[0](self.path)
        ad._stock = lambda: {BR: 5.0}
        ad._READY.clear()
        server.Handler._session = lambda h: {"логин": "boss", "фио": "Тест", "роль": "admin", "цех": "Ц-01", "активен": 1}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        sqldb.connect, ad._stock, self.server.Handler._session = self._old

    def call(self, sub, body=None):
        import json
        import urllib.error
        import urllib.request
        from urllib.parse import quote
        req = urllib.request.Request(self.base + "/api/wh/addr/" + quote(sub, safe="?=&"),
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            raw = urllib.request.urlopen(req, timeout=20).read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
        return raw if sub.startswith("codes.xlsx") else json.loads(raw)

    def test_flow(self):
        self.assertEqual(self.call("rack", {"зона": "P", "стеллаж": 1, "этажей": 2, "ячеек": 3})["создано"], 6)
        k = self.call("issue", {"тип": "K", "количество": 2})["коды"]
        self.assertEqual(k, ["K-0001", "K-0002"])
        self.assertTrue(self.call("put", {"код": k[0], "наименование": BR, "количество": 4})["ok"])
        self.assertFalse(self.call("put", {"код": "P1-1-01", "наименование": BR, "количество": 2})["ok"])
        self.assertEqual(self.call("box", {"коробка": k[0], "ячейка": "P1-2-03"})["действие"], "вскрыта")
        self.assertEqual(self.call("state?код=з1-2-03")["data"]["содержимое"][0]["количество"], 4)
        self.assertEqual(self.call("summary")["data"]["коробки"]["последний"], "K-0002")
        self.assertTrue(self.call("codes.xlsx?тип=K&от=K-0001").startswith(b"PK"))
        self.assertGreater(len(self.call("journal")["data"]), 3)


if __name__ == "__main__":
    unittest.main()
