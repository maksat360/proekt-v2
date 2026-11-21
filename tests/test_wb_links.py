import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sql"))

import substitutes  # noqa: E402
import wb_links  # noqa: E402

NAMES = ["Худи/263/шоколад/XL", "Худи/263/шоколад/2XL", "Брюки/477/синий/58", "Брюки/477/темно-синий/58"]
CARD = {"артикул": "263-бежевый", "размеры": [
    {"chrtId": 1, "size": "XL", "barcodes": ["b1", "b1x"], "name": None},
    {"chrtId": 2, "size": "2XL", "barcodes": ["b2"], "name": None},
    {"chrtId": 3, "size": "5XL", "barcodes": ["b5"], "name": None}]}


class LinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(wb_links.warehouse, "product_names", return_value=NAMES),
                        mock.patch.object(wb_links, "_audit"),
                        mock.patch.object(wb_links, "IGNORED", self.tmp / "ign.json"),
                        mock.patch.object(substitutes, "PATH", self.tmp / "subs.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_link_matches_sizes_and_writes_barcodes(self):
        with mock.patch.object(wb_links, "_cards", return_value=[CARD]), \
             mock.patch.object(wb_links.warehouse, "link_barcodes", side_effect=lambda l: list(l)) as put:
            res = wb_links.link("zhsk", "263-бежевый", "Худи/263/шоколад/", "Максат")
        put.assert_called_once_with({"Худи/263/шоколад/XL": ["b1", "b1x"], "Худи/263/шоколад/2XL": ["b2"]})
        self.assertEqual(res, {"связано": 2, "нет_размера": ["5XL"]})

    def test_link_unknown_product_refused(self):
        with mock.patch.object(wb_links, "_cards", return_value=[CARD]):
            with self.assertRaises(ValueError):
                wb_links.link("zhsk", "263-бежевый", "Худи/263/бежевый", "Максат")

    def test_substitutes_add_and_remove(self):
        wb_links.set_sub("Брюки/477/синий", "Брюки/477/темно-синий", "Максат")
        self.assertEqual(substitutes.load(), {"Брюки/477/синий": "Брюки/477/темно-синий"})
        self.assertEqual(substitutes.for_name("Брюки/477/синий/58"), "Брюки/477/темно-синий/58")
        with self.assertRaises(ValueError):
            wb_links.set_sub("Брюки/477/синий", "Брюки/477/синий", "Максат")
        with self.assertRaises(ValueError):
            wb_links.set_sub("Брюки/477/синий", "Брюки/000/нет", "Максат")
        wb_links.set_sub("Брюки/477/синий", "", "Максат")
        self.assertEqual(substitutes.load(), {})

    def test_ignore_toggle(self):
        wb_links.ignore("kkm", "28Б-ч", True, "Максат")
        self.assertEqual(wb_links._read(wb_links.IGNORED, {}), {"kkm": ["28Б-ч"]})
        wb_links.ignore("kkm", "28Б-ч", False, "Максат")
        self.assertEqual(wb_links._read(wb_links.IGNORED, {}), {"kkm": []})


if __name__ == "__main__":
    unittest.main()
