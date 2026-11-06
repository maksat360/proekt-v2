# -*- coding: utf-8 -*-
"""Швейные этапы как роли: этап даёт право работать, отключённый этап не назначается заново."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tests"))

import cex_api  # noqa: E402
import perms  # noqa: E402
from test_order_flow import FakeStore  # noqa: E402

ADMIN = {"логин": "boss", "фио": "Тест", "роль": "admin"}
KEEPER = {"логин": "keeper", "роль": "storekeeper"}


class StageRolesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (cex_api.store, cex_api._sync_process, perms.FILE, perms.LOG)
        perms.FILE = Path(self.tmp.name) / "p.json"
        perms.LOG = Path(self.tmp.name) / "log.jsonl"
        perms._CACHE.update(sig=None, data=None)
        cex_api._sync_process = lambda code, fields: None  # data/processes.xlsx не трогаем
        cex_api.store = self.st = FakeStore()
        self.st.sheet_names = lambda: list(self.st.sheets)
        self.st.sheets["расценки"] = [
            {"код": "ОВЕРЛ", "операция": "Оверлок", "расценка за шт": 5, "порядок": 10},
            {"код": "КАРМАН", "операция": "Карман", "расценка за шт": 3, "порядок": 20}]

    def tearDown(self):
        cex_api.store, cex_api._sync_process, perms.FILE, perms.LOG = self._old
        perms._CACHE.update(sig=None, data=None)
        self.tmp.cleanup()

    def test_stage_gives_right_to_work(self):
        self.assertFalse(cex_api._can_work(KEEPER))  # у складчика нет права работать на этапах
        # старая колонка «этап» читается как «роли» (до переноса данных)
        self.st.sheets[cex_api.STAFF[0]] = [{"логин": "keeper", "этап": "ОВЕРЛ;КАРМАН"}]
        self.assertTrue(cex_api._can_work(KEEPER))
        self.assertEqual(cex_api.roles_of(KEEPER), ["ОВЕРЛ", "КАРМАН"])
        perms._save({"роли": {}, "сотрудники": {"keeper": {"cex.work": False}}})
        self.assertFalse(cex_api._can_work(KEEPER))  # личный запрет начальника сильнее

    def test_disabled_stage_kept_but_not_added(self):
        route = [{"код": "ОВЕРЛ", "после": "РАСКР"}, {"код": "КАРМАН", "после": "РАСКР"}]
        cex_api.save_route(ADMIN, {"шаблон": "Основной", "этапы": route})
        cex_api.toggle_stage(ADMIN, {"код": "КАРМАН", "отключён": True})
        self.assertTrue(cex_api._ops()["КАРМАН"]["отключён"])
        # там, где этап уже был, маршрут сохраняется
        cex_api.save_route(ADMIN, {"шаблон": "Основной", "этапы": route})
        # в новый маршрут отключённый этап не добавить
        with self.assertRaises(ValueError):
            cex_api.save_route(ADMIN, {"шаблон": "Новый", "этапы": route})
        cex_api.toggle_stage(ADMIN, {"код": "КАРМАН", "отключён": False})
        cex_api.save_route(ADMIN, {"шаблон": "Новый", "этапы": route})


if __name__ == "__main__":
    unittest.main()
