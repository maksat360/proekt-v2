# Дизайн миграции на SQL (фазы 2–6)

Дата: 21.10.2026 · Статус: **теневой режим**, SQL не является источником истины.

## 1. Принципы

1. Рабочая книга (`цех_склад для apk.xlsm`) остаётся **эталонным артефактом**. Код миграции её только читает.
2. Для любых операций используется **мастер-копия** `master/цех_склад_master_2026-10-21.xlsm` (chmod 444, sha256 зафиксирован).
3. SQL включается флагом, по умолчанию выключен: `config.json → "backend": "excel"`.
4. Экспорт всегда создаёт **новый файл**; импорт всегда требует подтверждения.
5. Любая операция, меняющая данные, начинается с резервной копии.

## 2. Выбор СУБД

**SQLite** (файл `data/sql/portal.db`, режим WAL, `busy_timeout=5000`).

Почему не PostgreSQL:
- одна машина, 2–3 пользователя, десятки операций в день;
- сервер и БД на одном хосте, сетевого доступа к БД нет;
- резервная копия — копирование одного файла;
- не требуется установка и администрирование.

Ограничение: SQLite сериализует записи. При росте до 10+ одновременных пользователей — переход на PostgreSQL. Запись через WAL + `BEGIN IMMEDIATE` для конфликтных операций.

## 3. Схема (v1)

```
meta(key PK, value)

products(id PK, name UNIQUE, category, model, color, size,
         source_sheet, source_row, created_at)

locations(id PK, code UNIQUE, kind, note)

purchases(id PK, ts, supplier, batch, product_id → products,
          qty, defect, status, source, external_uuid UNIQUE,
          source_sheet, source_row)

placements(id PK, ts, location_code, product_id, qty,
           external_uuid UNIQUE, source_sheet, source_row)

shipments(id PK, ts, target, product_id, qty, order_ref, user,
          external_uuid UNIQUE, source_sheet, source_row)

orders(id PK, ts, client, status, closed_at, cancelled_by, reason,
       external_uuid UNIQUE, source_sheet, source_row)

order_items(id PK, order_id → orders, product_id, qty, shipped)

employees(login PK, name, role, workshop, rate_hour, active, password_state)

rates(code PK, name, price, sort_order, required)

sales(id PK, ts, product_id, qty, price, total, buyer, user,
      status, external_uuid UNIQUE)

imports(id PK, ts, file_name, file_sha256, user, mode,
        summary_json, status)

import_changes(id PK, import_id → imports, entity, entity_id,
               change, before_json, after_json)

audit_log(id PK, ts, actor, action, entity, entity_id,
          payload_json, outcome)

schema_version(version PK, applied_at, note)
```

Правила:
- `external_uuid` — идемпотентность (повторная отправка не создаёт дубль).
- `source_sheet` + `source_row` — трассировка до строки книги.
- Все суммы — `REAL`; количество хранится как есть (штуки), без округления.
- Внешние ключи включены (`PRAGMA foreign_keys=ON`).

## 4. Маппинг книга → SQL

| Источник | Таблица | Ключ идемпотентности |
|---|---|---|
| главный (A–R) | products | `name` (уникальное) |
| Вспомогательный лист (G, I, J) | products.category, locations, поставщики → purchases.supplier | код адреса |
| приобритение (A–I) | purchases | `source_sheet:source_row` + sha строки |
| адрес (D–I) | placements | `source_sheet:source_row` |
| паставка ЖСК/ККМ/ААТ (A–E) | shipments | `source_sheet:source_row` |
| заказы | orders + order_items | `external_uuid` = `заказы:<№>:<позиция>` |
| сотрудники | employees | `login` |
| расценки | rates | `code` |
| data/users.xlsx | employees | `login` |
| data/sales.xlsx | sales | `external_uuid` |
| data/batches.xlsx и др. | **пока не импортируются** (фаза 2.1) | — |

Импорт идемпотентен: строки сопоставляются по `(source_sheet, source_row, hash)`; повторный запуск обновляет запись, а не создаёт новую. Строки, исчезнувшие из книги, **не удаляются**, а помечаются `status='missing_in_source'`.

## 5. Теневой режим

- `shadow.py`: после успешной операции склада (приход/адрес/отгрузка/заказ) пишет зеркальную запись в SQL в отдельной транзакции.
- Ошибка тени **никогда** не влияет на ответ пользователю: логируется в `audit_log` с `outcome='shadow_error'`.
- Приложение по-прежнему читает из Excel — поведение не меняется.
- Включение: `config.json → {"shadow": true}` или переменная окружения `V2_SHADOW=1`.

## 6. Сравнение (фаза 3)

`compare.py` строит отчёт:

| Проверка | Как считается |
|---|---|
| Товары | count(products) vs число наименований в «главный» |
| Остаток по товару | Excel: адрес − паставка* − магазин; SQL: placements − shipments − sales |
| Ожидает размещения | Excel: закуплено − размещено − неликвид; SQL: purchases − placements |
| Отгрузки по направлениям | суммы по `паставка*` vs `shipments` |
| Заказы | открытые/собранные/отменённые |
| Продажи | `sales.xlsx` vs `sales` |
| Расхождения | списком: missing / extra / qty_diff / duplicate / invalid_ref |

Отчёт не исправляет данные. Результат — JSON + читаемая таблица.

## 7. Экспорт (фаза 4)

1. Шаблон — **мастер-копия** (никогда не рабочая книга).
2. Копия в `exports/цех_склад_<дата>_<время>.xlsm`.
3. Обновляются только документированные области: `приобритение`, `адрес`, `паставка *`, `заказы`, `сотрудники`, `расценки`.
4. Формулы не перезаписываются: пишутся только колонки с данными.
5. VBA сохраняется (`keep_vba=True`), макросы не запускаются.
6. В `meta` книги (свойства документа) — пометка «сгенерировано из SQL, версия, время».
7. Проверка после экспорта: формат, наличие листов, формулы остались формулами, `vbaProject.bin` на месте, именованные диапазоны, суммы совпадают с SQL.
8. Пересчёт формул — только при открытии в Excel (`wb.calculation.fullCalcOnLoad = True`).

**Ограничение, которое нужно принять:** openpyxl теряет часть расширений (data validation, некоторые стили таблиц). Поэтому экспорт позиционируется как отчётная копия, а не как замена рабочей книги.

## 8. Импорт (фаза 5)

1. Пользователь выбирает файл (только чтение).
2. Проверки: формат, обязательные листы, шапки, колонки, уникальность ключей.
3. Определение происхождения: совпадает ли `file_sha256` с известным экспортом.
4. Dry-run: `insert / update / skip / conflict` по каждой строке.
5. Конфликт = значение в файле отличается от SQL **и** SQL менялся после последнего экспорта.
6. Применение — только после подтверждения, в одной транзакции.
7. `imports` + `import_changes` — аудит: кто, когда, что, прежние значения.
8. Отсутствующие в файле записи **не удаляются**.

## 9. Переключение и откат (фаза 6)

Переключение: `config.json → "backend": "sql"` (после того как сравнение зелёное и владелец подтвердил).

Порядок отката:
1. Остановить запись (флаг `backend` → `readonly`).
2. Экспорт свежей копии из SQL.
3. Проверить суммы экспорта против SQL.
4. Архивировать `portal.db` и журнал (`portal.db-wal`).
5. Вернуть `backend: "excel"`.
6. Записать в `meta` активный набор данных и время переключения.

Откат **не мгновенный**: шаги 2–4 занимают время и требуют проверки.

## 10. Резервное копирование

- SQL: `backup_db()` — `VACUUM INTO` в `data/sql/backups/portal_<ts>.db`, хранится 30 последних.
- Книга: существующий механизм `склад_бэкапы` (12 последних) + мастер-копия.
- `data/*.xlsx`: перед первым SQL-импортом делается полный архив `data/backups_<ts>.zip`.
- Восстановление: остановить сервер → заменить файл → запустить → проверить `PRAGMA integrity_check`.

## 11. Этапы

| Этап | Содержание | Статус |
|---|---|---|
| 1 | Инспекция и документирование | готово |
| 2 | Схема SQL, миграции, импортёр, теневой режим | в работе |
| 3 | Сравнение и валидация | после 2 |
| 4 | Безопасный экспорт из SQL | после 3 |
| 5 | Импорт с preview и конфликтами | после 4 |
| 6 | Переключение и откат | после подтверждения владельца |
