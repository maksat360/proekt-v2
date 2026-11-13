# -*- coding: utf-8 -*-
"""Справочник контрагентов: первое заполнение, добавить, изменить, удалить."""
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "sql"))
import db as sqldb  # noqa: E402
import counterparties as cp  # noqa: E402


class CounterpartyTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="v2-cp-")) / "db.sqlite"
        self._old = sqldb.connect
        sqldb.connect = lambda *a, **k: self._old(self.path)
        cp._READY.clear()

    def tearDown(self):
        sqldb.connect = self._old

    def test_seed_once_without_duplicates(self):
        seed = [("санжар ака", "Поставщики"), ("Санжар ака", "Поставщики"), ("ЖСК", "Собственные компании"), ("", "x")]
        rows = cp.list_all(seed)
        self.assertEqual(sorted(r["название"] for r in rows), ["ЖСК", "санжар ака"])
        cp.save("t", {"id": rows[0]["id"], "удалить": True})
        self.assertEqual(len(cp.list_all(seed)), 1, "удалённого не возвращаем повторным заполнением")

    def test_add_edit_delete(self):
        a = cp.save("t", {"название": "аскат", "категория": "Поставщики", "телефон": "+996"})
        with self.assertRaises(ValueError):
            cp.save("t", {"название": "АСКАТ", "категория": "Покупатели"})
        b = cp.save("t", {"id": a["id"], "название": "Аскат", "категория": "Собственные цеха"})
        self.assertEqual((b["название"], b["категория"], b["телефон"]), ("Аскат", "Собственные цеха", ""))
        self.assertEqual(cp.names("Собственные цеха"), ["Аскат"])
        self.assertEqual(cp.save("t", {"id": a["id"], "удалить": True}), {"удалён": "Аскат"})
        self.assertEqual(cp.list_all(), [])
        with self.assertRaises(ValueError):
            cp.save("t", {"название": "", "категория": "Поставщики"})


if __name__ == "__main__":
    unittest.main()
