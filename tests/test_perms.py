# -*- coding: utf-8 -*-
"""Права: роль + личные настройки, защита от самоназначения и от потери последнего админа."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import perms  # noqa: E402

ADMIN = {"логин": "boss", "роль": "admin", "активен": 1}
ADMIN2 = {"логин": "boss2", "роль": "admin", "активен": 1}
MANAGER = {"логин": "ivanov", "роль": "manager", "активен": 1}
TECH = {"логин": "petrov", "роль": "technologist", "активен": 1}
TECH2 = {"логин": "tech2", "роль": "technologist", "активен": 1}
SEW = {"логин": "kozlova", "роль": "user", "активен": 1}
USERS = [ADMIN, MANAGER, TECH, TECH2, SEW]


class PermsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (perms.FILE, perms.LOG)
        perms.FILE = Path(self.tmp.name) / "permissions.json"
        perms.LOG = Path(self.tmp.name) / "log.jsonl"
        perms._CACHE.update(sig=None, data=None)

    def tearDown(self):
        perms.FILE, perms.LOG = self._old
        perms._CACHE.update(sig=None, data=None)
        self.tmp.cleanup()

    def test_order_flow_roles(self):
        designer = {"логин": "d", "роль": "designer"}
        supply = {"логин": "s", "роль": "supply"}
        store = {"логин": "k", "роль": "storekeeper"}
        self.assertTrue(perms.allowed(designer, "cex.design"))
        self.assertFalse(perms.allowed(designer, "cex.supply"))
        self.assertTrue(perms.allowed(supply, "cex.supply"))
        self.assertFalse(perms.allowed(supply, "cex.tech"))
        self.assertTrue(perms.allowed(store, "cex.create"))
        self.assertFalse(perms.allowed(TECH, "cex.design"))

    def test_technologist_has_default_staff_rights(self):
        for code in ("staff.add", "staff.edit", "stages.create", "stages.edit", "stages.assign"):
            self.assertTrue(perms.allowed(TECH, code), code)
        self.assertFalse(perms.allowed(TECH, "perms.roles"))
        self.assertFalse(perms.allowed(SEW, "staff.view"))

    def test_admin_takes_right_from_role_and_gives_to_another(self):
        perms.set_role_perm(ADMIN, USERS, "technologist", "staff.add", False)
        perms.set_role_perm(ADMIN, USERS, "accountant", "staff.add", True)
        self.assertFalse(perms.allowed(TECH, "staff.add"))
        self.assertFalse(perms.allowed(TECH2, "staff.add"))  # для всей роли
        self.assertTrue(perms.allowed({"логин": "buh", "роль": "accountant"}, "staff.add"))
        self.assertTrue(perms.allowed(TECH, "staff.edit"))  # остальные права роли не тронуты
        perms._CACHE.update(sig=None, data=None)
        self.assertFalse(perms.allowed(TECH, "staff.add"), "сохранено в файл")

    def test_personal_right_touches_only_one_person(self):
        perms.set_user_perm(ADMIN, USERS, SEW, "staff.view", True)
        perms.set_user_perm(ADMIN, USERS, TECH, "stages.create", False)
        self.assertTrue(perms.allowed(SEW, "staff.view"))
        self.assertFalse(perms.allowed({"логин": "other", "роль": "user"}, "staff.view"))
        self.assertFalse(perms.allowed(TECH, "stages.create"))
        self.assertTrue(perms.allowed(TECH2, "stages.create"))
        perms.set_user_perm(ADMIN, USERS, TECH, "stages.create", None)  # «как у роли»
        self.assertTrue(perms.allowed(TECH, "stages.create"))

    def test_no_self_escalation(self):
        perms.set_user_perm(ADMIN, USERS, TECH, "perms.users", True)
        with self.assertRaises(perms.AccessError):  # себе
            perms.set_user_perm(TECH, USERS, TECH, "perms.roles", True)
        with self.assertRaises(perms.AccessError):  # чужому — право, которого нет у самого
            perms.set_user_perm(TECH, USERS, SEW, "perms.roles", True)
        with self.assertRaises(perms.AccessError):  # своей роли
            perms.set_role_perm(ADMIN2 | {"роль": "admin"}, USERS, "admin", "staff.add", False)
        with self.assertRaises(perms.AccessError):  # без права управлять ролями
            perms.set_role_perm(MANAGER, USERS, "user", "staff.view", True)

    def test_last_admin_is_protected(self):
        with self.assertRaises(perms.AccessError):  # отключить единственного админа
            perms.check_role_change(ADMIN2, USERS, ADMIN, None, False)
        with self.assertRaises(perms.AccessError):  # понизить единственного админа
            perms.check_role_change(ADMIN2, USERS, ADMIN, "manager", None)
        with self.assertRaises(perms.AccessError):  # забрать права у единственного админа
            perms.set_user_perm(ADMIN2, USERS, ADMIN, "perms.roles", False)
        perms.check_role_change(ADMIN, USERS + [ADMIN2], ADMIN2, "manager", None)  # второй есть — можно

    def test_only_admin_appoints_admin(self):
        perms.set_role_perm(ADMIN, USERS, "manager", "staff.edit", True)
        with self.assertRaises(perms.AccessError):
            perms.check_role_change(MANAGER, USERS, TECH, "admin", None)
        with self.assertRaises(perms.AccessError):  # роль с правами, которых нет у назначающего
            perms.check_role_change(TECH, USERS, SEW, "manager", None)

    def test_changes_are_logged(self):
        perms.set_role_perm(ADMIN, USERS, "technologist", "staff.add", False)
        perms.set_user_perm(ADMIN, USERS, SEW, "staff.view", True)
        log = perms.journal()
        self.assertEqual([e["право"] for e in log], ["staff.view", "staff.add"])
        self.assertEqual(log[0]["кто"], "boss")


if __name__ == "__main__":
    unittest.main()
