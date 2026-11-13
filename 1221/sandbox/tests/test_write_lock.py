# -*- coding: utf-8 -*-
"""Параллельные POST не теряют записи: «прочитать лист → поменять → записать» идёт по одному."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import server  # noqa: E402

BOSS = {"логин": "boss", "фио": "Тест", "роль": "admin", "цех": "Ц-01", "активен": 1}


class WriteLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (server.DATA, server.SESSIONS_FILE, server.Handler._session)
        server.DATA = Path(self.tmp.name)  # реальная data/ не трогается
        server.SESSIONS_FILE = server.DATA / "sessions.json"
        server.Handler._session = lambda self: BOSS
        server._TABLE_CACHE.clear()
        server.write_table("materials", [{"артикул": "ТКАНЬ", "название": "ткань", "количество": 100,
                                          "ед": "м", "цена": 1, "поставщик": ""}])
        server.write_table("moves", [])
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/materials/move"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.DATA, server.SESSIONS_FILE, server.Handler._session = self._old
        server._TABLE_CACHE.clear()
        self.tmp.cleanup()

    def _receive_one(self):
        body = json.dumps({"артикул": "ТКАНЬ", "тип": "приход", "количество": 1}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()

    def test_parallel_receipts_are_all_saved(self):
        n = 20
        threads = [threading.Thread(target=self._receive_one) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        qty = server.read_table("materials")[0]["количество"]
        self.assertEqual(qty, 100 + n)
        self.assertEqual(len(server.read_table("moves")), n)


if __name__ == "__main__":
    unittest.main()
