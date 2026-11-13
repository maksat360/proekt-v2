import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import shop_sync  # noqa: E402


class WbPhotoTests(unittest.TestCase):
    def test_first_photo_to_all_sizes_keeps_portal_photo(self):
        products = [{"наименование": "Брюки/477/чёрный/42", "фото": ""},
                    {"наименование": "Брюки/477/чёрный/44", "фото": ""},
                    {"наименование": "Брюки/477/хаки/42", "фото": "свое.jpg"},
                    {"наименование": "Худи/9/синий/S", "фото": ""}]
        saved = {}
        old = (server.read_table, server.write_table)
        server.read_table = lambda name: products
        server.write_table = lambda name, rows: saved.setdefault(name, rows)
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Товары"
            for _ in range(4):
                ws.append([])
            ws.append(["1", "Брюки/477/черный/", "", "", "", "", "", "https://x/1.webp;https://x/2.webp"])
            ws.append(["1", "Брюки/477/хаки/", "", "", "", "", "", "https://x/3.webp"])
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "wb.xlsx"
                wb.save(p)
                res = shop_sync.import_wb_photos(p)
        finally:
            server.read_table, server.write_table = old
        self.assertEqual(res["товаров_с_фото"], 2)
        self.assertEqual([x["фото"] for x in products], ["https://x/1.webp", "https://x/1.webp", "свое.jpg", ""])


if __name__ == "__main__":
    unittest.main()
