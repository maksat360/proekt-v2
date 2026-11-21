import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


class LoginGuardTest(unittest.TestCase):
    def setUp(self):
        server._LOGIN_FAILS.clear()

    def test_five_wrong_passwords_lock_login_for_window(self):
        keys = [("u:Ц-01:ali", server.LOGIN_MAX_USER)]
        for i in range(4):
            server.login_failed(["u:Ц-01:ali"], now=1000 + i)
        self.assertEqual(server.login_wait(keys, now=1010), 0)
        server.login_failed(["u:Ц-01:ali"], now=1010)
        self.assertGreater(server.login_wait(keys, now=1011), 800)
        self.assertEqual(server.login_wait(keys, now=1000 + server.LOGIN_WINDOW + 1), 0)  # окно прошло

    def test_check_password_plain_and_old_hash(self):
        self.assertTrue(server.check_password("qwe", "qwe"))
        self.assertFalse(server.check_password("qwe", "qwE"))
        self.assertTrue(server.check_password("123456", server.hash_password("123456")))
        self.assertFalse(server.check_password("", server.hash_password("123456")))

    def test_secure_cookie_only_over_https(self):
        h = server.Handler.__new__(server.Handler)
        h.connection = object()
        h.headers = {"Host": "sharq.tail1234.ts.net"}
        self.assertTrue(h._is_https())
        h.headers = {"Host": "192.168.0.116:8787"}
        self.assertFalse(h._is_https())


if __name__ == "__main__":
    unittest.main()
