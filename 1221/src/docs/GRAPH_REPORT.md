# Graph Report - Проект V2  (2026-11-08)

## Corpus Check
- 96 files · ~107,747 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 24 file(s) not represented in the graph (top: .xml 10, .css 5, .webmanifest 2)
- WARNING: 24 of 120 files seen (20%) have no supported extractor and are missing from this graph entirely. It may look complete while representing only part of the codebase.

## Summary
- 1643 nodes · 4298 edges · 81 communities (68 shown, 13 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 95 edges (avg confidence: 0.88)
- Token cost: 228,533 input · 0 output

## Community Hubs (Navigation)
- Цех UI Core (cex.js)
- Permissions & Roles
- Цех API Admin & Payroll
- Cutting Cards & Rolls
- FBS Picking Tests
- Route Editor UI
- Assignment & Labels API
- Design Flow UI
- Portal App Globals
- Цех Excel Store
- Android Scanner Intents
- Android Ceh Activities
- Warehouse Core
- Android Main UI
- HTTP Server Core
- iOS Portal App
- Order Flow Test Fakes
- Route Work Permissions
- Migration Export Tests
- Android Settings Callbacks
- WB Cabinets & Tokens
- Route Checks & Snapshots
- Portal Page Bindings
- Android WebView Client
- Access Admin UI
- Android Settings Probe
- Materials & BOM API
- iOS Project Config
- Portal Tabs Rendering
- SQL DB Layer
- Server Analytics & Batches
- Shop Cart UI
- Android AppConfig
- HTTP Request Handler
- Shop Catalog Sync
- Wildberries API Client
- Excel vs SQL Compare
- Warehouse Excel Export
- Portal Boot & Session
- Warehouse Orders Ops
- SQL Export & Shadow
- Warehouse Lookups
- Workbook Backups
- Sessions & Passwords
- Warehouse Address UI
- Assign UI
- Cut Card UI
- SQL Importer
- Ceh Launcher Icons
- FBS Sync Tests
- Warehouse Async Flush
- Icon Generator
- SQL Migration Design
- Demo Seed Data
- Item Labels Print
- Web App Icons
- Model Catalog Grid
- Orders Spec & Growth
- PWA & iOS Install
- iOS AppConfig
- Ceh LAN Discovery
- Android Build & README
- Sklad LAN Discovery
- Apps & TC15 Scanner
- Цех UX Helpers
- Roll Labels UI
- Migration Phases 4-6
- Offline Snapshot
- Pick Scan UI
- Sewing Timer UI
- Write Lock Test
- Ceh APK Build Script
- Sklad APK Build Script
- Unified Orders Spec
- Accounts Switcher
- Цех HTML Pages
- FBS Shipped Counts
- Server Permission Check
- Service Worker

## God Nodes (most connected - your core abstractions)
1. `_s()` - 107 edges
2. `_dispatch()` - 77 edges
3. `_rows()` - 68 edges
4. `_int()` - 41 edges
5. `esc()` - 38 edges
6. `_norm_size()` - 34 edges
7. `read_table()` - 34 edges
8. `api()` - 33 edges
9. `write_sheets()` - 32 edges
10. `nf()` - 32 edges

## Surprising Connections (you probably didn't know these)
- `iOS app «Цех V2» (SwiftUI + WKWebView)` --semantically_similar_to--> `Android app «Швейный цех» WebView wrapper`  [INFERRED] [semantically similar]
  ios/README.md → android/README.md
- `Android app wrapper (android-sklad README)` --semantically_similar_to--> `Android app «Швейный цех» WebView wrapper`  [INFERRED] [semantically similar]
  android-sklad/README.md → android/README.md
- `Discovery.java subnet scan for /api/companies` --semantically_similar_to--> `Find server in network (/api/companies scan)`  [INFERRED] [semantically similar]
  android/README.md → android-sklad/README.md
- `Sklad app (com.projectv2.sklad) launcher icon set` --semantically_similar_to--> `Ceh app (com.projectv2.ceh) launcher icon set`  [INFERRED] [semantically similar]
  android-sklad/res/mipmap-hdpi/ic_launcher.png → android/res/mipmap-hdpi/ic_launcher.png
- `_resolve_product()` --calls--> `_product_id()`  [INFERRED]
  wb_sync.py → sql/importer.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **SQL migration phases: shadow → compare → export → import → switch** — docs_migration_design_shadow_mode, docs_migration_design_compare_py, docs_migration_design_export_phase, docs_migration_design_import_phase, docs_migration_design_switch_and_rollback [EXTRACTED 1.00]
- **Thin client shells over the same Mac portal** — android_readme_android_webview_wrapper, android_sklad_readme_android_webview_wrapper, ios_readme_ios_wkwebview_app, docs_приложения_ios_pwa [INFERRED 0.85]
- **Unified orders model across FBS, FBO and Shop** — docs_тз_заказы_fbs_fbo_магазин_unified_orders_table, docs_тз_заказы_fbs_fbo_магазин_wb_fbs_sync, docs_тз_заказы_fbs_fbo_магазин_fbo_requests, docs_тз_заказы_fbs_fbo_магазин_shop_cart, docs_тз_заказы_fbs_fbo_магазин_status_machine [EXTRACTED 1.00]

## Communities (81 total, 13 thin omitted)

### Community 0 - "Цех UI Core (cex.js)"
Cohesion: 0.08
Nodes (86): addFromForm(), addFromGrid(), api(), AS_ROLES, asDef(), asOptions(), asRole(), asTabs() (+78 more)

### Community 1 - "Permissions & Roles"
Cohesion: 0.08
Nodes (31): access_state(), AccessError, _active(), all_roles(), allowed(), catalog(), _check_code(), check_role_change() (+23 more)

### Community 2 - "Цех API Admin & Payroll"
Cohesion: 0.08
Nodes (41): _all_users(), _clean_stage_input(), close_payroll(), delete_stage(), _deps(), _editor_stages(), ensure_sheets(), extra_roles_of() (+33 more)

### Community 3 - "Cutting Cards & Rolls"
Cohesion: 0.09
Nodes (27): accepted_map(), add_roll(), apply_decision(), card_history(), _card_no(), card_of(), _card_rows(), _check_supply_ready() (+19 more)

### Community 4 - "FBS Picking Tests"
Cohesion: 0.08
Nodes (20): PickTests, confirm_orders(), statistics_state(), confirm(), confirm_items(), counts(), _deduct(), _history() (+12 more)

### Community 5 - "Route Editor UI"
Cohesion: 0.13
Nodes (37): loadRoutes(), routeHtml(), RT, RT_VIEWS, rtActive(), rtAdd(), rtBary(), rtCan() (+29 more)

### Community 6 - "Assignment & Labels API"
Cohesion: 0.11
Nodes (31): assign_state(), assignments(), _brand(), cards_of(), cut_state(), datamatrix_svg(), decisions(), _fifo_key() (+23 more)

### Community 7 - "Design Flow UI"
Cohesion: 0.12
Nodes (37): bomHtml(), designCardHtml(), designHtml(), FL, FL_ROLL_FIELDS, flBoss(), flCards(), flCats() (+29 more)

### Community 8 - "Portal App Globals"
Cohesion: 0.07
Nodes (31): ACTIONS, ART_PATHS, BRAND, closeGsel(), COLOR_WORDS, COLORS, enhanceSelects(), FBSPAGE (+23 more)

### Community 9 - "Цех Excel Store"
Cohesion: 0.12
Nodes (25): _bytes(), _cells_to_values(), CexLocked, CexSourceError, _col_index(), _col_letter(), _ensure_header_style(), ensure_sheet() (+17 more)

### Community 10 - "Android Scanner Intents"
Cohesion: 0.08
Nodes (7): MainActivity, View.OnClickListener, Runnable, ConnectivityManager.NetworkCallback, Runnable, Runnable, android.content.BroadcastReceiver

### Community 12 - "Warehouse Core"
Cohesion: 0.11
Nodes (19): article_index(), _backup(), brand(), _cached_by_file(), ensure_settings_sheet(), _next_order_id(), _norm(), _read_brand() (+11 more)

### Community 13 - "Android Main UI"
Cohesion: 0.09
Nodes (10): MainActivity, View.OnClickListener, View.OnClickListener, Runnable, ConnectivityManager.NetworkCallback, Runnable, Runnable, android.content.BroadcastReceiver (+2 more)

### Community 14 - "HTTP Server Core"
Cohesion: 0.09
Nodes (21): append_row(), backup_data(), date_in(), ensure_tables(), lan_ip(), main(), month_key(), month_title() (+13 more)

### Community 15 - "iOS Portal App"
Cohesion: 0.08
Nodes (8): PortalApp, .body, SettingsView, .body, Coordinator, WebView, SwiftUI, WebKit

### Community 16 - "Order Flow Test Fakes"
Cohesion: 0.08
Nodes (6): FakeStore, MaterialsTests, OrderFlowTests, PackOrderStatusTests, SeveralCardsTests, StageRolesTests

### Community 17 - "Route Work Permissions"
Cohesion: 0.12
Nodes (22): bind_route(), _can(), _can_work(), cancel_work(), delete_route(), _deny(), dispatch(), _dispatch() (+14 more)

### Community 19 - "Migration Export Tests"
Cohesion: 0.08
Nodes (4): ExportTests, make_workbook(), MigrationTests, PreviewTests

### Community 20 - "Android Settings Callbacks"
Cohesion: 0.11
Nodes (9): Runnable, Runnable, View.OnClickListener, View.OnClickListener, View.OnClickListener, View.OnClickListener, Runnable, Runnable (+1 more)

### Community 21 - "WB Cabinets & Tokens"
Cohesion: 0.13
Nodes (11): cabinets(), clean_token(), mark_sync(), _read(), remove_cabinet(), save_cabinet(), token(), _tokens() (+3 more)

### Community 22 - "Route Checks & Snapshots"
Cohesion: 0.12
Nodes (18): check_route(), _finals(), model_routes(), _ops(), party_routes(), _party_snapshots(), _pick_template(), _route_rows() (+10 more)

### Community 23 - "Portal Page Bindings"
Cohesion: 0.14
Nodes (27): afterLogin(), bind(), bindFbs(), bindNeedNet(), bindPickPage(), bindSyncBar(), bindSyncChip(), cabSave() (+19 more)

### Community 24 - "Android WebView Client"
Cohesion: 0.18
Nodes (4): WebViewClient, DownloadListener, WebChromeClient, WebViewClient

### Community 25 - "Access Admin UI"
Cohesion: 0.19
Nodes (23): AC, AC_IMPORTANT, acCan(), acCardHtml(), accessHtml(), acGroups(), acLocked(), acLogHtml() (+15 more)

### Community 26 - "Android Settings Probe"
Cohesion: 0.13
Nodes (8): Runnable, Runnable, View.OnClickListener, View.OnClickListener, View.OnClickListener, View.OnClickListener, Runnable, Runnable

### Community 27 - "Materials & BOM API"
Cohesion: 0.14
Nodes (19): _add_party_ref(), boms(), _client_list(), _date_of(), materials(), _num(), _parse_sizes(), _parse_ts() (+11 more)

### Community 28 - "iOS Project Config"
Cohesion: 0.08
Nodes (23): CODE_SIGN_STYLE, ENABLE_BITCODE, INFOPLIST_FILE, PRODUCT_BUNDLE_IDENTIFIER, PRODUCT_NAME, SWIFT_VERSION, TARGETED_DEVICE_FAMILY, info (+15 more)

### Community 29 - "Portal Tabs Rendering"
Cohesion: 0.16
Nodes (24): archiveTab(), bitem(), boxesTab(), esc(), fbsListHtml(), kpi(), loadNegatives(), LOCS (+16 more)

### Community 30 - "SQL DB Layer"
Cohesion: 0.18
Nodes (15): archive_excel_data(), audit(), backend(), backup(), connect(), get_meta(), integrity(), load_config() (+7 more)

### Community 31 - "Server Analytics & Batches"
Cohesion: 0.24
Nodes (20): active_company(), analytics(), as_num(), batch_detail(), batch_map(), batch_sections(), batch_totals(), batch_view() (+12 more)

### Community 32 - "Shop Cart UI"
Cohesion: 0.20
Nodes (21): bindShop(), cartLines(), cartTotal(), colorOf(), iconFor(), isLight(), money(), num() (+13 more)

### Community 35 - "Shop Catalog Sync"
Cohesion: 0.24
Nodes (12): main(), as_num(), _category(), _clean(), _price_for(), set_source(), _signature(), source_path() (+4 more)

### Community 36 - "Wildberries API Client"
Cohesion: 0.15
Nodes (7): all_orders(), new_orders(), ping(), _request(), _ssl_context(), statistics_orders(), WbError

### Community 37 - "Excel vs SQL Compare"
Cohesion: 0.16
Nodes (8): _clean(), compare(), excel_metrics(), _num(), sql_metrics(), to_markdown(), preview(), _structure()

### Community 38 - "Warehouse Excel Export"
Cohesion: 0.13
Nodes (11): _append_shipment_row(), _compact_sheet(), _expand_tables(), export_to_excel(), _export_to_excel(), _fill_rates_sheet(), _fill_staff_sheet(), _last_filled_row() (+3 more)

### Community 40 - "Portal Boot & Session"
Cohesion: 0.16
Nodes (17): bindTabbar(), boot(), brandMark(), cacheSession(), forgetAccount(), homeRoute(), loadBrand(), logout() (+9 more)

### Community 41 - "Warehouse Orders Ops"
Cohesion: 0.25
Nodes (11): apply_ops(), cancel_order(), _clean(), create_order(), flush_async(), _num(), order_ship(), pick_order() (+3 more)

### Community 42 - "SQL Export & Shadow"
Cohesion: 0.22
Nodes (7): export_from_sql(), _formula_count(), _sha(), _write_rows(), _id(), mirror(), _product()

### Community 43 - "Warehouse Lookups"
Cohesion: 0.18
Nodes (12): _fbs_shipped(), find_many(), load_master(), meta(), negatives(), _op_key(), place(), receive() (+4 more)

### Community 44 - "Workbook Backups"
Cohesion: 0.18
Nodes (5): backup_path(), _sha(), snapshot(), backup(), main()

### Community 45 - "Sessions & Passwords"
Cohesion: 0.20
Nodes (7): find_user(), _new_session(), _pw_tag(), _save_sessions(), _session_user(), staff_users(), SessionPasswordTests

### Community 46 - "Warehouse Address UI"
Cohesion: 0.23
Nodes (14): api(), bindCabForm(), bindWh(), cabName(), fbsPick(), loadAddresses(), loadCabinets(), loadFbsPick() (+6 more)

### Community 47 - "Assign UI"
Cohesion: 0.29
Nodes (12): AS, asCutHtml(), asFixSave(), asGenerate(), asHero(), asLabelsHtml(), asParty(), asPeopleOptions() (+4 more)

### Community 48 - "Cut Card UI"
Cohesion: 0.27
Nodes (13): CC, ccColors(), ccFormHtml(), ccHistoryHtml(), ccLeft(), ccParty(), ccRefreshTotals(), ccReset() (+5 more)

### Community 49 - "SQL Importer"
Cohesion: 0.27
Nodes (7): _clean(), _file_sha(), _id(), import_workbook(), integrity_report(), _num(), _product_id()

### Community 50 - "Ceh Launcher Icons"
Cohesion: 0.17
Nodes (12): Ceh launcher icon (hdpi) - white V2 on dark rounded square, Ceh app (com.projectv2.ceh) launcher icon set, Ceh launcher icon (mdpi) - white V2 on dark rounded square, Ceh launcher icon (xhdpi) - white V2 on dark rounded square, Ceh launcher icon (xxhdpi) - white V2 on dark rounded square, Ceh launcher icon (xxxhdpi) - white V2 on dark rounded square, Sklad launcher icon (hdpi) - white V2 on dark rounded square, Sklad app (com.projectv2.sklad) launcher icon set (+4 more)

### Community 52 - "Warehouse Async Flush"
Cohesion: 0.18
Nodes (10): addresses(), close_order(), _flush_delay(), flush_pending(), flush_status(), _flush_worker(), _has_pending(), _ledger() (+2 more)

### Community 53 - "Icon Generator"
Cohesion: 0.22
Nodes (4): font(), make(), font(), make()

### Community 54 - "SQL Migration Design"
Cohesion: 0.24
Nodes (10): backup_db() VACUUM INTO backups, compare.py reconciliation report (phase 3), SQL schema v1 (products, purchases, placements, shipments, orders, order_items, employees, rates, sales, imports, audit_log), SQL migration design (phases 2–6), SQLite data/sql/portal.db (WAL), Working workbook цех_склад для apk.xlsm, Company name and logo (sheet «настройки»), Logins from Excel sheet «сотрудники» (+2 more)

### Community 55 - "Demo Seed Data"
Cohesion: 0.27
Nodes (7): d(), dt(), hours_ago(), seed(), u(), check_password(), hash_password()

### Community 56 - "Item Labels Print"
Cohesion: 0.36
Nodes (10): drawPick(), drawSheet(), esc(), fitNames(), labelHtml(), load(), nf(), params (+2 more)

### Community 57 - "Web App Icons"
Cohesion: 0.18
Nodes (11): V2 App Icon 1024x1024 (dark navy rounded square, white rounded bar overlapping 'V2' text, blue ellipse), V2 Portal App Icon Set (blue accent), V2 App Icon 180x180 (Apple touch icon size), V2 App Icon 192x192 (PWA icon size), V2 App Icon 512x512 (PWA icon size), Sklad (Warehouse) App Icon 1024x1024 (navy rounded square, white bar, 'СКЛАД' text overflowing edges, green ellipse), Sklad Warehouse App Icon Set (green accent), Sklad (Warehouse) App Icon 180x180 (Apple touch icon size) (+3 more)

### Community 58 - "Model Catalog Grid"
Cohesion: 0.20
Nodes (6): _catalog_names(), _catalog_rows(), _grid_for(), model_variants(), refs(), seed_refs()

### Community 59 - "Orders Spec & Growth"
Cohesion: 0.22
Nodes (8): Growth report 06.11.2026, New modules wb_api, wb_sync, fbs_stock, cex, order_status_history table, Orders API (/api/orders, /api/cabinets, /api/wb/sync), Order statuses new→processing→picking→picked→shipped→done / cancelled, wb_cabinets table (token_ref, not token), FBS sync via Wildberries API, Product matching (barcode, seller article, wb_sku_map)

### Community 60 - "PWA & iOS Install"
Cohesion: 0.29
Nodes (9): Offline warehouse (snapshot, op queue, sync), iOS PWA «На экран Домой», static/sw.js shell cache, manifest.webmanifest / manifest-sklad.webmanifest, iOS app «Цех V2» (SwiftUI + WKWebView), «Только склад» toggle (/sklad), Portal shell index.html (app.js + accounts.js), Service worker registration /sw.js (+1 more)

### Community 61 - "iOS AppConfig"
Cohesion: 0.24
Nodes (5): Foundation, AppConfig, .skladMode, .startURL, .url

### Community 63 - "Android Build & README"
Cohesion: 0.25
Nodes (6): Android app «Швейный цех» WebView wrapper, AppConfig.java DEFAULT_URL, build_apk.sh (aapt2 → javac → d8 → zipalign → apksigner, no Gradle), keystore.jks signing key, server.py --host 0.0.0.0 --port 8787, Android app wrapper (android-sklad README)

### Community 65 - "Apps & TC15 Scanner"
Cohesion: 0.36
Nodes (5): Apps overview: Android and iOS, Швейный цех V2 APK (com.projectv2.ceh), Склад V2 APK (com.projectv2.sklad), «Собрать заказ» assembly screen, Zebra TC15 DataWedge scanner setup

### Community 66 - "Цех UX Helpers"
Cohesion: 0.29
Nodes (4): UX, uxClean(), uxLeaveText, uxSetDirty()

### Community 67 - "Roll Labels UI"
Cohesion: 0.48
Nodes (5): esc(), labelHtml(), load(), nf(), params

### Community 68 - "Migration Phases 4-6"
Cohesion: 0.33
Nodes (5): config.json backend flag (excel / sql / readonly), Safe export from SQL to xlsm (phase 4), Import with dry-run and conflicts (phase 5), Master copy workbook (read-only, sha256 pinned), Backend switch and rollback (phase 6)

### Community 69 - "Offline Snapshot"
Cohesion: 0.33
Nodes (4): available_for_order(), orders(), snapshot(), _version()

### Community 70 - "Pick Scan UI"
Cohesion: 0.60
Nodes (5): applyScan(), bindPickRows(), pickCheckQty(), pickMark(), updatePickTotal()

### Community 71 - "Sewing Timer UI"
Cohesion: 0.80
Nodes (4): sewClock(), sewHtml(), sewStage(), sewTick()

### Community 73 - "Ceh APK Build Script"
Cohesion: 0.50
Nodes (3): JAVA_HOME, PATH, build_apk.sh script

### Community 74 - "Sklad APK Build Script"
Cohesion: 0.50
Nodes (3): JAVA_HOME, PATH, build_apk.sh script

### Community 75 - "Unified Orders Spec"
Cohesion: 0.50
Nodes (3): FBO client requests (not yet done), Spec: Orders FBS / FBO / Shop, Shop cart orders (registry JSON → orders type=shop)

### Community 77 - "Цех HTML Pages"
Cohesion: 0.67
Nodes (4): Cex scripts (cex.js, route.js, assign.js, sew.js, cutcard.js, access.js, flow.js, ux.js), Cex shell «Заказ на пошив» page, Item labels page (40×30 mm print), Labels page (58×40 roll toggle)

## Ambiguous Edges - Review These
- `Logo placeholder 1x1 (single pink pixel, not a real logo)` → `V2 Portal App Icon Set (blue accent)`  [AMBIGUOUS]
  static/logo.png · relation: conceptually_related_to

## Knowledge Gaps
- **40 isolated node(s):** `JAVA_HOME`, `PATH`, `JAVA_HOME`, `PATH`, `Foundation` (+35 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 384 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `read_table()` connect `Server Analytics & Batches` to `Permissions & Roles`, `Цех API Admin & Payroll`, `HTTP Request Handler`, `Shop Catalog Sync`, `Assignment & Labels API`, `Write Lock Test`, `Sessions & Passwords`, `HTTP Server Core`, `Route Work Permissions`, `Materials & BOM API`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `_dispatch()` (e.g. with `add_roll()` and `bind_route()`) actually correct?**
  _`_dispatch()` has 14 INFERRED edges - model-reasoned connections that need verification._
- **What connects `JAVA_HOME`, `PATH`, `JAVA_HOME` to the rest of the system?**
  _40 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Цех UI Core (cex.js)` be split into smaller, more focused modules?**
  _Cohesion score 0.0784019975031211 - nodes in this community are weakly interconnected._
- **Why does `SettingsActivity` connect `Android Ceh Activities` to `Android Settings Callbacks`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `_int()` (e.g. with `apply_decision()` and `_only_cards()`) actually correct?**
  _`_int()` has 3 INFERRED edges - model-reasoned connections that need verification._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `Logo placeholder 1x1 (single pink pixel, not a real logo)` and `V2 Portal App Icon Set (blue accent)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._