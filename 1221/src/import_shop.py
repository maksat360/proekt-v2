#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручной импорт каталога магазина из Excel-файла цеха.

Обычно запускать не нужно: портал сам подхватывает изменения файла
(проверка mtime при каждом открытии магазина и раз в 10 секунд).

Запуск:
    python3 import_shop.py                  # источник по умолчанию или сохранённый
    python3 import_shop.py --file "путь.xlsm"
    python3 import_shop.py --file "путь.xlsm" --save-source
"""
import argparse

from shop_sync import sync_from_excel, set_source, source_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="путь к файлу цеха (.xlsm)")
    ap.add_argument("--save-source", action="store_true", help="запомнить путь как основной")
    args = ap.parse_args()

    if args.file and args.save_source:
        set_source(args.file)

    src = args.file or source_path()
    st = sync_from_excel(src, force=True)

    if st.get("error"):
        print("ошибка:", st["error"])
        return

    print(f"источник: {st['source']}")
    print(f"синхронизировано: {st['synced_at']}")
    print(f"позиций: {st['позиций']} · в наличии: {st['в_наличии']} · штук: {st['шт']:g}")
    print(f"FK сумма: {st['fk_сумма']:g} · каробки: {st['каробки_сумма']:g} · расхождений: {st['расхождений']}")


if __name__ == "__main__":
    main()
