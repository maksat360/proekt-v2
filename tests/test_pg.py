# -*- coding: utf-8 -*-
"""Переходник SQLite → PostgreSQL (sql/db.py)."""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sql"))
import db as sqldb  # noqa: E402

PG_BIN = sqldb._pg_bin("createdb")


class PgSqlTranslateTests(unittest.TestCase):
    def test_translate(self):
        self.assertEqual(sqldb._pg_sql("SELECT * FROM t WHERE a=? AND b LIKE 'x%'"),
                         "SELECT * FROM t WHERE a=%s AND b LIKE 'x%%'")
        self.assertEqual(sqldb._pg_sql("BEGIN IMMEDIATE"), "BEGIN")
        self.assertIn('"user"', sqldb._pg_sql("INSERT INTO s(id, user) VALUES (?,?)"))
        self.assertNotIn('""user""', sqldb._pg_sql('SELECT "user" FROM s'))
        self.assertIn("SERIAL PRIMARY KEY", sqldb._pg_sql("id INTEGER PRIMARY KEY AUTOINCREMENT"))
        self.assertIn("DOUBLE PRECISION", sqldb._pg_sql("qty REAL NOT NULL"))


class PgLiveTests(unittest.TestCase):
    DB = "portal_unittest"

    @classmethod
    def setUpClass(cls):
        try:
            import psycopg  # noqa: F401
            subprocess.run([sqldb._pg_bin("dropdb"), "--if-exists", cls.DB], check=True, capture_output=True)
            subprocess.run([PG_BIN, cls.DB], check=True, capture_output=True)
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"PostgreSQL недоступен: {exc}")
        cls.con = sqldb.PgConnection(f"dbname={cls.DB}")
        sqldb.migrate(cls.con)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        subprocess.run([sqldb._pg_bin("dropdb"), cls.DB], capture_output=True)

    def test_schema_and_loose_types(self):
        c = self.con
        c.execute("INSERT INTO products(id, name, created_at) VALUES ('p1', 'А', ?)", (sqldb.now(),))
        c.execute("INSERT INTO shipments(id, ts, target, product_id, qty, user) VALUES ('s1', ?, 'WB', 'p1', 1.5, 'u')",
                  (sqldb.now(),))
        c.execute("INSERT INTO orders(id, ts, client, type, external_id) VALUES ('o1', ?, 'WB', 'fbs', ?)",
                  (sqldb.now(), 101))
        row = c.execute("SELECT id FROM orders WHERE external_id = ?", (101,)).fetchone()
        self.assertEqual((row["id"], row[0]), ("o1", "o1"))
        self.assertEqual(c.execute("SELECT qty FROM shipments").fetchone()["qty"], 1.5)
        sqldb.set_meta(c, "k", {"a": 1})
        self.assertEqual(sqldb.get_meta(c, "k"), {"a": 1})
        self.assertEqual(sqldb.integrity(c), "ok")


if __name__ == "__main__":
    unittest.main()
