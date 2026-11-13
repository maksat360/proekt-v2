# -*- coding: utf-8 -*-
"""Карточка магазина: название, описание, фото и цены размеров; загрузка своего фото."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import server  # noqa: E402

BOSS = {"логин": "boss", "фио": "Тест", "роль": "admin", "цех": "Ц-01", "активен": 1}


class ShopCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (server.DATA, server.STATIC, server.SESSIONS_FILE, server.Handler._session)
        server.DATA = Path(self.tmp.name)  # реальные data/ и static/ не трогаются
        server.STATIC = Path(self.tmp.name) / "static"
        server.SESSIONS_FILE = server.DATA / "sessions.json"
        server.Handler._session = lambda self: BOSS
        server._TABLE_CACHE.clear()
        server.write_table("products", [
            {"id": 1, "модель": "477", "размер": "42", "цена": 1800, "наименование": "Брюки/477/чёрный/42"},
            {"id": 2, "модель": "477", "размер": "44", "цена": 1800, "наименование": "Брюки/477/чёрный/44"},
            {"id": 3, "модель": "500", "размер": "42", "цена": 900, "наименование": "Брюки/500/белый/42"}])
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.DATA, server.STATIC, server.SESSIONS_FILE, server.Handler._session = self._old
        server._TABLE_CACHE.clear()
        self.tmp.cleanup()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read())

    def test_card_saves_fields_for_all_sizes(self):
        res = self.post("/api/shop/card", {"ids": [1, 2], "название": "Брюки клёш", "описание": "хлопок",
                                           "фото": ["https://x/1.webp", "/static/uploads/shop/a.jpg"],
                                           "цены": {"1": 2000, "2": ""}})
        self.assertTrue(res["ok"], res)
        rows = {r["id"]: r for r in server.read_table("products")}
        self.assertEqual((rows[1]["название"], rows[1]["описание"], rows[1]["цена"]), ("Брюки клёш", "хлопок", 2000))
        self.assertEqual(rows[2]["фото"], "https://x/1.webp;/static/uploads/shop/a.jpg")
        self.assertEqual(rows[2]["цена"], 1800)  # пустая цена — не меняется
        self.assertFalse(rows[3].get("название"))  # другая карточка не тронута
        bad = self.post("/api/shop/card", {"ids": [1], "фото": ["javascript:alert(1)"]})
        self.assertFalse(bad["ok"])

    def test_photo_upload(self):
        data = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake").decode()
        res = self.post("/api/shop/photo", {"данные": data, "ext": "png"})
        self.assertTrue(res["url"].startswith("/static/uploads/shop/"))
        self.assertTrue((server.STATIC / res["url"][len("/static/"):]).exists())
        self.assertFalse(self.post("/api/shop/photo", {"данные": data, "ext": "exe"})["ok"])


if __name__ == "__main__":
    unittest.main()
