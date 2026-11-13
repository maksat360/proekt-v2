import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import perms  # noqa: E402
import warehouse  # noqa: E402


class ShopOrderTests(unittest.TestCase):
    def setUp(self):
        self.led = {"orders": [{"id": 1, "клиент": "Петров", "статус": "новый", "позиции": []}]}
        self._old = (warehouse._ledger, warehouse._save_ledger, warehouse.available_for_order, warehouse.flush_async)
        warehouse._ledger = lambda: self.led
        warehouse._save_ledger = lambda d: None
        warehouse.available_for_order = lambda: {"Брюки/477/чёрный/42": 10}
        warehouse.flush_async = lambda *a, **k: None

    def tearDown(self):
        warehouse._ledger, warehouse._save_ledger, warehouse.available_for_order, warehouse.flush_async = self._old

    def test_own_and_fbo_orders_are_mine(self):
        item = [{"наименование": "Брюки/477/чёрный/42", "количество": 2}]
        warehouse.create_order("Иванов", item, "Иванов")
        warehouse.create_order("FBO · ККМ", item, "Иванов", "FBO", "ККМ")
        mine = warehouse.orders(author="Иванов")
        self.assertEqual([(o["клиент"], o["тип"]) for o in mine], [("FBO · ККМ", "FBO"), ("Иванов", "свой")])
        self.assertEqual([o["id"] for o in warehouse.orders(author="Петров")], [1])  # старый заказ без «автор»

    def test_everyone_can_order_fbo_only_managers(self):
        for role in ("cutter", "packer", "designer", "supply", "accountant", "technologist", "client"):
            self.assertTrue(perms._default(role, "orders.create"), role)
        self.assertTrue(perms._default("admin", "orders.fbo"))
        self.assertFalse(perms._default("cutter", "orders.fbo"))


if __name__ == "__main__":
    unittest.main()
