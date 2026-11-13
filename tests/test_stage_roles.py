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

    def test_packer_works_on_pack_stage(self):
        packer = {"логин": "pack", "роль": "packer"}
        self.assertIn(cex_api.PACK_STAGE, cex_api.roles_of(packer))
        self.assertTrue(cex_api._can_work(packer))

    def test_pack_stage_is_packer_role(self):
        roles = {r["код"]: r for r in cex_api.access_state(ADMIN)["роли"]}
        self.assertNotIn(cex_api.PACK_STAGE, roles)  # «Упаковка» отдельной ролью не показывается
        self.assertEqual(roles["packer"]["этап"], cex_api.PACK_STAGE)
        self.assertIn("ставка", roles["packer"])

    def test_delete_account(self):
        import types
        users = [dict(ADMIN), {"логин": "anna", "фио": "Анна", "роль": "ОВЕРЛ"}]
        table = {"users": [dict(u) for u in users]}
        fake = types.SimpleNamespace(read_table=lambda n: [dict(r) for r in table[n]],
                                     write_table=lambda n, rows: table.__setitem__(n, rows))
        old_users, old_srv = cex_api._all_users, sys.modules.get("server")
        cex_api._all_users = lambda: users
        sys.modules["server"] = fake
        try:
            self.st.sheets[cex_api.STAFF[0]] = [{"логин": "anna", "роли": "КАРМАН"}, {"логин": "boss"}]
            perms._save({"роли": {}, "сотрудники": {"anna": {"cex.work": False}}})
            self.assertEqual(cex_api.delete_account(ADMIN, {"логин": "anna"})["удалён"], True)
            self.assertEqual([r["логин"] for r in table["users"]], ["boss"])
            self.assertEqual([r["логин"] for r in self.st.sheets[cex_api.STAFF[0]]], ["boss"])
            self.assertNotIn("anna", perms.load()["сотрудники"])
            with self.assertRaises(perms.AccessError):  # себя удалить нельзя
                cex_api.delete_account(ADMIN, {"логин": "boss"})
        finally:
            cex_api._all_users = old_users
            if old_srv is None:
                sys.modules.pop("server", None)
            else:
                sys.modules["server"] = old_srv

    def test_logins_excel(self):
        import io
        from openpyxl import load_workbook
        users = [dict(ADMIN, пароль="secret"), {"логин": "anna", "фио": "Анна", "роль": "ОВЕРЛ", "пароль": "1111"},
                 {"логин": "old", "фио": "Старый", "роль": "ОВЕРЛ", "пароль": "a" * 64}]
        old_users = cex_api._all_users
        cex_api._all_users = lambda: users
        try:
            rows = list(load_workbook(io.BytesIO(cex_api.logins_xlsx(ADMIN))).active.iter_rows(values_only=True))
            got = {r[1]: r[2] for r in rows[1:]}
            self.assertEqual((got["anna"], got["boss"]), ("1111", "secret"))
            self.assertIn("зашифрован", got["old"])
            with self.assertRaises(PermissionError):  # швея логины не выгружает
                cex_api.logins_xlsx({"логин": "anna", "роль": "ОВЕРЛ"})
        finally:
            cex_api._all_users = old_users

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


class FinishedRouteTests(unittest.TestCase):
    """Маршрут ГП (приёмка → поставка): на выбор только роли складского процесса."""
    setUp = StageRolesTests.setUp
    tearDown = StageRolesTests.tearDown

    def test_fin_palette_is_warehouse_roles(self):
        fin, sew = set(cex_api._wh_ops()), set(cex_api._ops())  # палитры маршрута ГП и швейного
        self.assertTrue({"storekeeper", "wh_receiver", "wh_picker", "wh_kitter"} <= fin)
        self.assertFalse(fin & {"ОВЕРЛ", "КАРМАН", "packer"}, "швейных операций и упаковщика в маршруте ГП нет")
        self.assertFalse(sew & {"storekeeper", "wh_picker"}, "складских ролей в швейном маршруте нет")

    def test_fin_route_saves_with_warehouse_roles(self):
        cex_api.save_route(ADMIN, {"вид": "гп", "шаблон": cex_api.MAIN_ROUTE, "этапы": [
            {"код": "wh_receiver", "после": []}, {"код": "wh_picker", "после": ["wh_receiver"]}]})
        rows = cex_api.route_templates("гп")[cex_api.MAIN_ROUTE]
        st = cex_api._editor_stages(rows, cex_api._route_ops())
        self.assertEqual([(x["код"], x["название"], x["после"]) for x in st],
                         [("wh_receiver", "Приёмщик", []), ("wh_picker", "Сборщик", ["wh_receiver"])])


if __name__ == "__main__":
    unittest.main()
