# -*- coding: utf-8 -*-
"""Сменили пароль — старые сессии (и «переключиться без пароля») больше не пускают."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import server  # noqa: E402


class SessionPasswordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (server.SESSIONS_FILE, server.find_user, dict(server.SESSIONS))
        server.SESSIONS_FILE = Path(self.tmp.name) / "sessions.json"  # реальная data/ не трогается
        self.user = {"логин": "kozlova", "цех": "Ц-01", "пароль": server.hash_password("old"), "активен": 1}
        server.find_user = lambda login, company=None: self.user if login == "kozlova" else None

    def tearDown(self):
        server.SESSIONS_FILE, server.find_user, old = self._old
        server.SESSIONS.clear()
        server.SESSIONS.update(old)
        self.tmp.cleanup()

    def test_password_change_ends_session(self):
        tok = server._new_session("kozlova", "Ц-01")
        self.assertIs(server._session_user(tok, server.SESSIONS[tok]), self.user)
        self.user["пароль"] = server.hash_password("new")
        self.assertIsNone(server._session_user(tok, server.SESSIONS[tok]))
        self.assertNotIn(tok, server.SESSIONS)

    def test_old_session_without_tag_is_kept_until_change(self):
        server.SESSIONS["t"] = {"логин": "kozlova", "цех": "Ц-01", "ts": 0}
        self.assertIs(server._session_user("t", server.SESSIONS["t"]), self.user)
        self.user["пароль"] = server.hash_password("new")
        self.assertIsNone(server._session_user("t", server.SESSIONS["t"]))


if __name__ == "__main__":
    unittest.main()


class ReadablePasswordTests(unittest.TestCase):
    def test_admin_sees_plain_and_default_only(self):
        import cex_api
        self.assertEqual(cex_api._readable_pw("qwe12"), "qwe12")
        self.assertEqual(cex_api._readable_pw(server.hash_password("123456")), "123456")
        self.assertEqual(cex_api._readable_pw(server.hash_password("secret")), "")
        self.assertEqual(cex_api._readable_pw("изменён"), "")
