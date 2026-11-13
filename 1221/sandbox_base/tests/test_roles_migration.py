# -*- coding: utf-8 -*-
"""Перенос на единую систему ролей: «Швея» и этапы → роли, история и маршруты не теряются."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tests"))

import cex_api  # noqa: E402
import perms  # noqa: E402
import server  # noqa: E402
from test_order_flow import FakeStore  # noqa: E402

ACC = ["логин", "пароль", "ФИО", "роль", "должность", "цех", "активен"]


class Book(FakeStore):
    def sheet_names(self):
        return list(self.sheets)

    def first_row(self, name):
        return ACC if name == "сотрудники" else []


class RolesMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (cex_api.store, cex_api._sync_process, perms.FILE, perms.LOG, server.read_table,
                     cex_api._all_users)
        perms.FILE = Path(self.tmp.name) / "p.json"
        perms.LOG = Path(self.tmp.name) / "log.jsonl"
        perms._CACHE.update(sig=None, data=None)
        cex_api._sync_process = lambda code, fields: None   # data/processes.xlsx не трогаем
        server.read_table = lambda name: []                  # и data/users.xlsx тоже
        cex_api.store = self.st = Book()
        sh = self.st.sheets
        sh["сотрудники"] = [
            {"логин": "kozlova", "ФИО": "Козлова", "роль": "user", "должность": "Швея", "цех": "Ц-01", "активен": "да"},
            {"логин": "seam2", "ФИО": "Новая", "роль": "Швея", "должность": "Швея", "цех": "Ц-01", "активен": "да"},
            {"логин": "maksat", "ФИО": "Максат", "роль": "admin", "должность": "Все роли", "цех": "Ц-01", "активен": "да"},
            {"логин": "ombai", "ФИО": "Омбай", "роль": "cutter", "должность": "Закройщик", "цех": "Ц-01", "активен": "да"}]
        sh["расценки"] = [{"код": "РАСКР", "операция": "Раскрой"}, {"код": "ОВЕРЛ", "операция": "Оверлок"},
                          {"код": "КАРМАН", "операция": "Карманы"}, {"код": "КРАСКА", "операция": "краска"}]
        sh[cex_api.STAFF[0]] = [{"логин": "kozlova", "этап": "ОВЕРЛ;КАРМАН"},
                                {"логин": "maksat", "этап": "ОВЕРЛ"}, {"логин": "ombai", "этап": "КРАСКА"}]
        sh[cex_api.OUT[0]] = [{"id": 1, "этап": "ОВЕРЛ", "логин": "kozlova", "количество": 5, "статус": "готово"},
                              {"id": 2, "этап": "СТАРЫЙ", "логин": "kozlova", "количество": 2, "статус": "готово"}]
        perms.FILE.write_text(json.dumps({"роли": {"user": {"wh.view": True}}, "сотрудники": {},
                                          "доп_роли": {"ombai": ["user", "storekeeper"]}}), encoding="utf-8")
        cex_api._all_users = self._users

    def _users(self):
        out = []
        known = perms.all_roles()
        for r in self.st.read_sheet("сотрудники"):
            role = r["роль"] if r["роль"] in known else ""
            out.append({"логин": r["логин"], "фио": r["ФИО"], "роль": role, "цех": r["цех"], "активен": 1})
        return out

    def tearDown(self):
        (cex_api.store, cex_api._sync_process, perms.FILE, perms.LOG, server.read_table,
         cex_api._all_users) = self._old
        perms._CACHE.update(sig=None, data=None)
        self.tmp.cleanup()

    def test_migration(self):
        # «Швея» без операций — перенос не начинается, ничего не меняется
        rep = cex_api.migrate_roles()
        self.assertEqual(rep["без_ролей"], ["seam2"])
        self.assertFalse(rep["готово"])
        self.assertEqual(self.st.sheets["сотрудники"][0]["роль"], "user")

        rep = cex_api.migrate_roles({"seam2": ["КАРМАН"]})
        self.assertTrue(rep["готово"])
        self.assertEqual(rep["новые_роли"], ["СТАРЫЙ"])  # код из истории стал ролью
        acc = {r["логин"]: r for r in self.st.sheets["сотрудники"]}
        self.assertEqual(acc["kozlova"]["роль"], "ОВЕРЛ")
        self.assertEqual(acc["seam2"]["роль"], "КАРМАН")
        self.assertEqual(acc["maksat"]["роль"], "admin")  # Максат не тронут
        staff = {r["логин"]: r for r in self.st.sheets[cex_api.STAFF[0]]}
        self.assertIn("роли", staff["kozlova"])
        self.assertEqual(staff["kozlova"]["роли"], "КАРМАН")       # основная ОВЕРЛ — не дублируется
        self.assertEqual(staff["ombai"]["роли"], "КРАСКА;storekeeper")  # доп. роль из json переехала
        data = json.loads(perms.FILE.read_text(encoding="utf-8"))
        self.assertNotIn("доп_роли", data)
        self.assertNotIn("user", data["роли"])
        self.assertTrue(data["роли"]["ОВЕРЛ"]["wh.view"])  # права «Швеи» перешли к операциям
        self.assertEqual(len(self.st.sheets[cex_api.OUT[0]]), 2)  # история цела

        kozlova = self._users()[0]
        self.assertEqual(perms.roles_of(kozlova), ["ОВЕРЛ", "КАРМАН"])
        self.assertTrue(cex_api._can_work(kozlova))
        self.assertTrue(perms.allowed({"логин": "maksat", "роль": "admin"}, "perms.roles"))

        # повторный запуск ничего не меняет
        before = json.dumps(self.st.sheets, ensure_ascii=False, sort_keys=True)
        rep = cex_api.migrate_roles()
        self.assertTrue(rep["готово"])
        self.assertEqual(json.dumps(self.st.sheets, ensure_ascii=False, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
