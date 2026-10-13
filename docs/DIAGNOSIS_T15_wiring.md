# OCOBot GUI ↔ Testnet Wiring Diagnosis (READ-ONLY)

Repo: `D:\oco` · Branch `main` (…origin/main) · Language: Python · UI: PySide6/PyQt6 via `ocobot/ui/_qt.py` shim.
No files were modified, created (except this report), deleted, staged, committed, checked out, or stashed. All `git` commands were read-only (`status`, `diff`, `log`). No stashes exist.

---

## 1) GIT STATE (uncommitted local edits are intact)

`git status --porcelain=v1 -b`:
```
## main...origin/main
 M ocobot/ui/app.py
 M ocobot/ui/open_orders.py
 M ocobot/ui/topbar.py
?? _apply_seal_agent.py
?? _apply_t15_s1.py
?? _apply_t15_seal.py
?? "صور من التجربة/"
```

`git diff --stat`:
```
 ocobot/ui/app.py         | 14 ++++++++++++++
 ocobot/ui/open_orders.py |  7 +++++++
 ocobot/ui/topbar.py      |  6 +++---
 3 files changed, 24 insertions(+), 3 deletions(-)
```

### Per-file summary of the uncommitted change

**A. `ocobot/ui/app.py` (+14):** This is THE key wiring change. It converts `main()` from a bare shell launcher into a real composition root. New imports + new body in `main()`:
```python
from ocobot.config import AppConfig
from ocobot.core.preflight import run_preflight
from ocobot.cli import _client_with_keys
from ocobot.domain.oco_reader import OcoReader
...
def main():  # pragma: no cover - interactive entry point
    app, window = build_app()
    window.show()
    window.refresh_connection(lambda: run_preflight(AppConfig.from_env_vars()))
    oo = window.content.screen_for("02_open_orders")
    if oo is not None and hasattr(oo, "set_source"):
        oo.set_source(
            build_fn=lambda: OcoReader(
                _client_with_keys(AppConfig.from_env_vars())
            ).list_open_ocos(),
            runner=window.runner,
        )
        oo.refresh()
    return app.exec()
```
Why it matters: `build_app()`/`MainWindow()` alone construct **zero** real services, so before this edit the launched GUI showed empty screens and a hard-coded connection pill. This edit (1) drives a **real preflight** onto the connection pill off the UI thread, and (2) injects a **real OcoReader→signed client** into the Open Orders screen and refreshes it. Confirmed **syntactically valid** (`ast.parse` OK) — the raw diff preview looked truncated/unbalanced but the file on disk is complete and parses.

**B. `ocobot/ui/open_orders.py` (+7):** Adds a `set_source(build_fn=None, runner=None)` injector to `OpenOrdersScreen` (previously it only had `set_on_select`). This is exactly the hook `app.py` above calls to hand the screen its real data source + runner post-construction:
```python
def set_source(self, build_fn=None, runner=None):
    if build_fn is not None:
        self._build_fn = build_fn
    if runner is not None:
        self._runner = runner
```

**C. `ocobot/ui/topbar.py` (6, ±3):** Changes the **initial** Connection Pill from a hard-coded "connected" to "disconnected" (honest default before preflight runs):
```python
-        self.conn_pill = Pill("متصل", PALETTE["GREEN"], self)
+        self.conn_pill = Pill("غير متصل", PALETTE["MUTED"], self)
```
Why it matters: removes a misleading static "متصل/GREEN" that lied about connectivity; the pill is now driven live by `refresh_connection`→`set_connection_state`. ⚠️ This makes the committed test `tests/test_ui_navigation.py::test_topbar_has_two_static_pills` (asserts `conn_pill.text() == "متصل"`) stale — it would fail against the dirty tree. See GAPS.

---

## 2) GUI ENTRY POINT & COMPOSITION

- **Production entry point:** `ocobot/ui/app.py::main()` (guarded by `if __name__ == "__main__": raise SystemExit(main())`). `build_app(argv)` returns `(app, window)` and is CI-safe under `QT_QPA_PLATFORM=offscreen`.
- There is **no** UI console-script in packaging. `ocobot/__main__.py` runs `ocobot.cli.main` (the **CLI**, not the GUI). So the GUI is launched by running `ocobot/ui/app.py` directly / calling `ui.app.main()` — there is currently no `python -m` shortcut for the GUI.
- **Composition in `build_app()`:** constructs only `QApplication`, applies theme, and builds `MainWindow()` with **all-default args** — i.e. it injects **no** real services. All real service wiring lives in `main()` (the uncommitted edit), and even there it only wires **two** things: the connection pill (preflight) and Open Orders (OcoReader). `MainWindow` itself defaults everything else to `None`:
```python
# main_window.py
def __init__(self, parent=None, runner=None, select_fn=None, executor=None, execute_cb=None,
             engine=None, price_provider=None):
    ...
    self.runner = runner or AsyncRunner()
    self.content = ContentRouter(parent=..., runner=self.runner, executor=executor,
        execute_cb=execute_cb, engine=engine, price_provider=price_provider)
    oo = self.content.screen_for("02_open_orders")
    if oo is not None and hasattr(oo, "set_on_select"):
        oo.set_on_select(self.handle_oco_selection)  # select_fn is None ⇒ no-op at runtime
```
Because `app.py::main()` calls `MainWindow()` with no args: `select_fn=None`, `executor=None`, `execute_cb=None`, `engine=None`, `price_provider=None` in the real path.

---

## 3) PER-SCREEN WIRING MAP

Screens are registered in `ocobot/ui/screens.py` and instantiated in `ocobot/ui/content.py::ContentRouter.__init__`. Note there are **6** nav entries; `05_safe_execution` is a bare `PlaceholderScreen` (no dedicated class).

| Screen | key | Constructed in ContentRouter with | Real path receives |
|---|---|---|---|
| Dashboard | `01_dashboard` | `DashboardScreen(self)` | no runner, **no build_fn** |
| Open OCO Orders | `02_open_orders` | `OpenOrdersScreen(self)` then `set_on_select` from MainWindow; `set_source` from app.py | **real** OcoReader build_fn + runner (via uncommitted app.py) |
| Selected/Manual Edit | `03_selected_and_edit` | `SelectedOcoScreen(self, runner, executor, execute_cb)` | runner=real; **executor=None, execute_cb=None** |
| Dynamic Monitoring | `04_dynamic_monitoring` | `DynamicMonitoringScreen(self, engine, price_provider, runner)` | runner=real; **engine=None, price_provider=None** |
| Safe Execution | `05_safe_execution` | `PlaceholderScreen(...)` | empty placeholder (out of built scope) |
| Demo Mode | `06_demo` | `DemoModeScreen(self)` | internal `DemoSimulator` only (by design) |

**Dashboard — `DashboardScreen(parent=None, runner=None, build_fn=None)`**
- Real path: `DashboardScreen(self)` → `runner=None`, `build_fn=None`. It exposes `update_snapshot()`/`refresh(build_fn)` and consumes `build_dashboard(...)` output, but **nothing ever calls `refresh`/`update_snapshot` in the real path** and no `build_dashboard`/Selector is wired. 
- Chain: **BROKEN at the source** — no `build_fn` injected, no call site. Screen stays all `—` / "لم يُختَر أمر". No hard-coded values (D14-safe placeholders only).

**Open OCO Orders — `OpenOrdersScreen(parent=None, runner=None, build_fn=None, on_select=None)`**
- Real path: constructed bare, then `set_on_select(MainWindow.handle_oco_selection)` and (uncommitted) `set_source(build_fn=OcoReader(...).list_open_ocos, runner=window.runner)` + `oo.refresh()`.
- Chain `GUI → build_fn → OcoReader.list_open_ocos → SignedRestClient.signed_request(GET /api/v3/openOrderList) → Testnet`: **COMPLETE** (with the uncommitted app.py). Runs off-thread via `AsyncRunner.submit`. No hard-coded symbol/price. UI layer itself makes no network (guarded by `tests/test_ui_no_direct_network.py`); IO is inside the injected `build_fn`.

**Selected OCO / Manual Edit — `SelectedOcoScreen(parent=None, runner=None, build_fn=None, executor=None, execute_cb=None, confirm_cb=None)`**
- Real path: gets `runner` but `executor=None` and `execute_cb=None` (ContentRouter forwards what MainWindow got, and app.py passes neither). `set_selected(selected)` is fed by `MainWindow._show_selected` (read display works). 
- Activate button resolves `execute = self._execute_cb or (self._executor.execute if self._executor else None)`; with both `None` → `_on_activate_clicked` early-returns (no execution). 
- Chain `GUI Activate → SafeExecutor.execute → cancel+create on Testnet`: **BROKEN** — no SafeExecutor injected in the real path (the documented T12b decision: "app.py left executor=None; building a real executor from the testnet client was out of scope for T12b"). No hard-coded values; `current_price` for reference comes from `set_current_price`/selected (stays `None` in real path — see §5/GAPS).

**Dynamic Monitoring — `DynamicMonitoringScreen(parent=None, engine=None, price_provider=None, runner=None, selected_oco=None, environment=None)`**
- Real path: `engine=None`, `price_provider=None`, runner=real. `set_selected` populates the live panel; Start/Pause/Resume/Kill Switch handlers all early-return when `engine is None`. `refresh_price(provider)` early-returns when `price_provider is None`.
- Chain `GUI → MonitoringEngine → SafeExecutor / PriceFeedController(WS+REST) → Testnet`: **BROKEN** — neither engine nor price_provider injected. Live Current Price stays `—` (D14-honest). `_connection_display()` reads `provider.mode` (WS/REST) but provider is None ⇒ `—`. No hard-coded symbol/price in the real path.
- Also note: even when an engine is injected, the UI never calls `engine.on_price_tick(price)` — `refresh_price` only updates the *display* via `set_current_price`; there is **no periodic price loop / QTimer** wired in the UI to (a) poll the provider or (b) feed ticks into the engine for reposition. See GAPS.

**Demo Mode — `DemoModeScreen(parent=None, simulator=None, symbol="BTCUSDT", tick_size=Decimal("0.01"))`**
- Real path: constructed bare → internal `DemoSimulator()` (pure in-memory random-walk / injected sequence). `symbol="BTCUSDT"` and `tick_size=Decimal("0.01")` are **display-only demo defaults** (legitimate for a simulator, and environment label is forced to `"DEMO"`). No engine/executor/client/network — by design.

---

## 4) REAL SERVICES INVENTORY (file paths + inject-ready public API)

- **Signed REST client:** `ocobot/core/rest_client.py::SignedRestClient(config, credentials, transport=None, clock=None, now_ms=None)`. Methods: `sync_time()`, `get_account()`, `signed_request(method, path, params=None)`, `public_request(method, path, params=None)`. Built by `ocobot/cli.py::_client_with_keys(cfg: AppConfig) -> SignedRestClient` (loads keys via `core/keys.load_credentials(cfg.keys_path, cfg.env)`).
- **exchangeInfo cache:** `ocobot/domain/exchange_info.py::ExchangeInfoService(client, ttl_seconds=3600, monotonic=None)`; `get_filters(symbol, force_refresh=False) -> SymbolFilters`.
- **OCO reader (openOrderList):** `ocobot/domain/oco_reader.py::OcoReader(client)`; `list_open_ocos() -> List[OcoOrder]`, `get_oco(order_list_id) -> OcoOrder`.
- **SafeExecutor:** `ocobot/domain/reposition.py::SafeExecutor(client, reader, exchange_info, id_factory=None, gap_ticks=DEFAULT_GAP_TICKS, audit=None)`; `execute(order_list_id, tp_pct, sl_pct, reference_price, dry_run=False) -> ExecutionResult` (**positional** args), `build_draft(...)`. CLI builder: `cli._build_executor(client, audit=None)`.
- **MonitoringEngine:** `ocobot/domain/monitoring.py::MonitoringEngine(executor, *, guard_policy=GuardPolicy.HALT_NOTIFY, dry_run=False, audit=None, checkpoint_sink=None)`; `start(selected_oco, trigger_pct, tp_pct, sl_pct, reference_price, ...)`, `on_price_tick(price)`, `pause()`, `resume()`, `kill_switch()`, `resume_from_state(...)`. It calls `executor.execute(order_list_id=..., tp_pct=..., sl_pct=..., reference_price=..., dry_run=...)` with **keyword** args.
- **PriceFeed (WS+REST):** `ocobot/core/market_feed.py`.
  - `RestPriceSource(client)`; `get_price(symbol) -> Decimal` (public `GET /api/v3/ticker/price`).
  - `MarketWebSocketSource(ws_base, symbol, connect_fn=None)`; `connect()`, `get_price(symbol="")`, `close()` (`<symbol>@bookTicker`).
  - `PriceFeedController(ws_source, rest_source, symbol)`; **`get_price() -> Decimal`** (no-arg; WS-preferred, REST fallback, `.mode`/`.alert`, `try_reconnect_ws()`). CLI builder: `cli._build_feed(cfg, client, symbol)`.
- **Selector + selected-OCO context:** `ocobot/domain/selection.py::Selector(reader: OcoReader, exchange_info: ExchangeInfoService)`; `select(order_list_id) -> SelectedOCO`, `selected`, `clear()`. Context object `ocobot/domain/models.py::SelectedOCO` (`from_oco(oco, filters=None)`; note `current_price` defaults `None`). Dashboard snapshot builder `selection.build_dashboard(selected, environment, connection)`.
- **State store:** `ocobot/core/state_store.py::StateStore(checkpoint_path, *, ensure_dir=True, audit_log_path=None)`; `save(PersistedState)`, `load(strict=False)`, `clear()`. Schemas: `MonitoringCheckpoint`, `SelectedOcoContext`, `LogLocations`, `PersistedState`.
- **Preflight / connection:** `ocobot/core/preflight.py::run_preflight(config: AppConfig, transport=None, now_ms=None, credentials=None) -> ConnectionState`. Config: `ocobot/config.py::AppConfig.from_env_vars(**overrides)` (env `OCOBOT_ENV` default `testnet`, `OCOBOT_KEYS_PATH`, `OCOBOT_RECV_WINDOW`).

The CLI (`ocobot/cli.py`) already composes ALL of these end-to-end (`_cmd_orders`, `_cmd_select`, `_cmd_dashboard`, `_cmd_draft`, `_cmd_activate`, `_cmd_monitor`) — it is the reference wiring the GUI should mirror.

---

## 5) SELECTION FLOW (orderListId + selected-OCO context propagation)

Wired path today:
1. `OpenOrdersScreen` row select → `itemSelectionChanged` → `_handle_selection_changed` → `_on_select(orderListId)`.
2. `MainWindow.set_on_select(self.handle_oco_selection)` (wired in `MainWindow.__init__`).
3. `MainWindow.handle_oco_selection(order_list_id)` → if `self._select_fn` is not None: `runner.submit(select_fn, order_list_id, on_result=self._show_selected)`.
4. `_show_selected(selected)` → `content.screen_for("03_selected_and_edit").set_selected(selected)` → `navigate_to("03_selected_and_edit")`.

Where it drops:
- **`select_fn` is `None` in the real path.** `app.py::main()` calls `MainWindow()` with no `select_fn`, so `handle_oco_selection` **early-returns** → selecting a row does nothing. (In `tests/test_ui_selected.py` it works only because the test passes `MainWindow(runner=_SyncRunner(), select_fn=selector.select)`.)
- Propagation **stops at Selected OCO**. `_show_selected` only feeds `03_selected_and_edit`. It does **NOT** call `set_selected` on `04_dynamic_monitoring`, and there is no propagation into Manual Edit beyond the Selected screen (Manual Edit lives inside `SelectedOcoScreen` so it shares the same `selected`, but Dynamic Monitoring never receives it). So `orderListId`/context never reaches Dynamic Monitoring in any path.
- Also `SelectedOCO.current_price` is `None` from `Selector.select` (from_oco doesn't set it), and no live price is injected into the Selected/Monitoring screens in the real path.

---

## 6) DEMO MODE ISOLATION

- Demo is fully isolated: `DemoModeScreen` uses only an in-memory `DemoSimulator` (seeded random-walk or explicit injected `prices`), no client/engine/executor/network/persistence. Environment label is hard-forced to `DEMO_ENVIRONMENT = "DEMO"` and a prominent DEMO badge is shown. Enforced by `tests/test_ui_demo_mode.py` (forbids `urllib`, `import socket`, `SignedRestClient`, `.signed_request(`, `.public_request(`) plus the global `tests/test_ui_no_direct_network.py`.
- Leak risk **demo→testnet:** none — Demo constructs no real services and shares no state with other screens (separate stack page; nothing calls into it).
- Leak risk **testnet→network-in-demo:** none — the whole UI layer is network-free by guard; all IO is in injected service callables, and Demo injects none.
- The only "defaults" in Demo (`symbol="BTCUSDT"`, `tick_size=0.01`, `start="60000.00"`) are simulator display seeds, clearly labeled DEMO, and cannot reach the Testnet path.

---

## 7) TEST LAYOUT & RUN COMMAND

- Framework: **unittest** (also runnable via pytest). No `pyproject.toml`/`pytest.ini`/`tox.ini`/`setup.cfg` with pytest config exists — searches returned none.
- Run command (from README + evidence `_t15_run.txt`): **`python -m unittest discover -s tests -t .`** (with `QT_QPA_PLATFORM=offscreen` for UI tests). Latest full-suite evidence `_t15_run.txt`: `Ran 244 tests ... OK`.
- `tests/` layout (39 files) — domain/core suites plus UI suites: `test_ui_app.py`, `test_ui_async.py`, `test_ui_connection_indicator.py`, `test_ui_dashboard.py`, `test_ui_demo_mode.py`, `test_ui_manual_edit.py`, `test_ui_monitoring.py`, `test_ui_navigation.py`, `test_ui_no_direct_network.py`, `test_ui_open_orders.py`, `test_ui_selected.py`; shared fakes `tests/_fakes.py` (`FakeClient`, `SYMBOL_OBJ`, `list_obj`, `leg`) and `tests/_fakes_monitoring.py` (`FakeSafeExecutor`, `FakePriceSource`, `FakeSelectedOCO`).
- **How UI tests inject services (the pattern the real app must copy):**
  - Open Orders: `screen.set_orders(OcoReader(FakeClient()).list_open_ocos())` or `screen.refresh(build_fn=lambda: ocos)`.
  - Selection flow: `MainWindow(runner=_SyncRunner(), select_fn=Selector(OcoReader(FakeClient()), ExchangeInfoService(FakeClient())).select)` then `oo.select_row(0)`.
  - Selected/Manual Edit: `SelectedOcoScreen(runner=_SyncRunner(), execute_cb=_exec_cb(fake))` where `_exec_cb` adapts SafeExecutor's **positional** `execute(order_list_id, tp_pct, sl_pct, reference_price)` to `FakeSafeExecutor.execute(*, order_list_id=..., ...)` (keyword-only). This positional↔keyword mismatch is bridged only in tests.
  - Dynamic Monitoring: `DynamicMonitoringScreen(engine=MonitoringEngine(FakeSafeExecutor()), price_provider=lambda: Decimal("60000.00"), runner=None)` and `MainWindow(engine=..., price_provider=...)`.
  - Dashboard: `screen.update_snapshot(build_dashboard(None, environment="testnet", connection="OK"))` / `screen.refresh(build_fn=lambda: snap)`.

---

## GAPS (concrete wiring gaps to make the real Testnet GUI end-to-end)

- **`app.py` does not inject a `select_fn`.** `MainWindow()` is built with no args ⇒ `handle_oco_selection` early-returns ⇒ selecting an Open Orders row does nothing. Must pass `select_fn=Selector(OcoReader(client), ExchangeInfoService(client)).select` (client from `_client_with_keys(AppConfig.from_env_vars())`).
- **Selected/Manual Edit has no SafeExecutor.** `executor=None`/`execute_cb=None` in the real path ⇒ Activate cannot cancel+create on Testnet. Inject `executor = SafeExecutor(client, OcoReader(client), ExchangeInfoService(client), audit=...)` (or `cli._build_executor(client)`), passed through `MainWindow(executor=...)`→`ContentRouter`.
- **Dynamic Monitoring has no MonitoringEngine and no price_provider.** `engine=None`, `price_provider=None` ⇒ Start/Pause/Resume/Kill Switch and live price are inert. Inject `engine = MonitoringEngine(executor, ...)` and `price_provider = cli._build_feed(cfg, client, symbol).get_price` via `MainWindow(engine=..., price_provider=...)`.
- **Dashboard is never fed.** No `build_fn`/`build_dashboard` wired and `refresh()`/`update_snapshot()` never called in the real path ⇒ always `—`. Inject a `build_fn` (e.g. `lambda: build_dashboard(selector.selected, environment=cfg.env.value, connection=...)`) and call it on show/selection.
- **Selection context does not propagate to Dynamic Monitoring (or a shared context).** `MainWindow._show_selected` only calls `set_selected` on `03_selected_and_edit`; it must also call `screen_for("04_dynamic_monitoring").set_selected(selected)` so `orderListId`/symbol/filters reach monitoring.
- **No live price loop / engine tick feed in the UI.** Even with a `price_provider`+`engine`, the UI only refreshes the displayed price (`refresh_price`→`set_current_price`); nothing polls periodically (no QTimer) and nothing calls `engine.on_price_tick(price)`. A UI-side ticking mechanism (off-thread via `AsyncRunner`) that (a) updates the panels and (b) feeds `engine.on_price_tick` is required for real reposition monitoring.
- **`SelectedOCO.current_price` stays `None` in the real select path.** `Selector.select`→`SelectedOCO.from_oco` never sets `current_price`; without injecting a live reference price, Manual Edit preview / Monitoring Start (which needs a real reference price, D14) cannot proceed. Wire the live price into `SelectedOcoScreen.set_current_price` / monitoring `set_current_price`.
- **SafeExecutor.execute signature mismatch is only bridged in tests.** Real code path in `SelectedOcoScreen._on_activate_clicked` calls `execute(order_list_id, tp_pct, sl_pct, reference_price)` **positionally**, which matches `SafeExecutor.execute` (positional) — OK for a real executor. But note the engine path uses **keyword** args; when wiring a real executor into both the Selected screen and the engine, keep the positional-vs-keyword contract consistent (tests use a `_exec_cb` adapter that must not be relied on in production).
- **No GUI entry point in packaging.** Only `ocobot/__main__.py` → CLI exists. Add a console entry / `python -m` path for `ocobot.ui.app:main` so the wired GUI is actually launchable in production.
- **Stale test vs uncommitted topbar edit.** `tests/test_ui_navigation.py::test_topbar_has_two_static_pills` asserts `conn_pill.text() == "متصل"`, but the uncommitted `topbar.py` now initializes it to `"غير متصل"`. Running the suite against the dirty tree will fail that assertion; the test must be updated to the honest disconnected default (or the initial-state expectation revised) as part of landing the wiring.
- **`05_safe_execution` is a bare placeholder.** It is a nav entry with no dedicated screen/class; if the Safe Execution screen is in scope it still needs to be built and wired to `SafeExecutor`.

_Context: `PROJECT_STATE.json` cursor = `{last_completed: T15, current: G1, next: G1}`; T14 (Demo) and T15 (Validated on Testnet) are `done`, next is the human-approval gate **G1** before any Live (T16). This diagnosis is read-only and changed no project state._

> RESOLVED (G1.1 - 2026-09-26): حُدِّث الاختبار test_topbar_has_two_static_pills ليتوقّع 'غير متصل' (السلوك الحيّ الصحيح وفق قاعدة الشفافية)؛ السويت الكاملة Ran 244 OK؛ الاتصال الحقيقي بـ Testnet CONNECTED (AC2). خُتم البند G1.1.

> RESOLVED (G1.2 - 2026-09-26): جلب الأوامر المفتوحة موصول بالعرض (ui/app.py set_source → OcoReader.list_open_ocos → GET /api/v3/openOrderList؛ set_source في ui/open_orders.py). AC1 سويت 244 OK؛ AC2 جلب حقيقي على Testnet أظهر أمر OCO مفتوحًا فعليًا (LSKUSDT، EXECUTING، orderListId 136428). خُتم G1.2.

---

## G1.3 — انتشار حالة الأمر المختار إلى الأقسام المستهلِكة + إعادة التظليل

**تغييرات التوصيل (wiring):**
- `ocobot/ui/app.py`: حقن `select_fn=Selector(...).select` عبر `build_app→MainWindow`، فيصبح اختيار صف في قسم الأوامر المفتوحة يؤسّس Live context فعليًا في الواجهة الحقيقية (بدل الرجوع المبكر من `handle_oco_selection`).
- `ocobot/ui/main_window.py`: توسيع `_show_selected` ليغذّي **04_dynamic_monitoring** عبر `set_selected` و**01_dashboard** عبر `update_snapshot(build_dashboard(selected))` (باستيراد `build_dashboard`) — إضافةً إلى **03_selected_and_edit** — فينتشر نفس `orderListId`/الرمز إلى الأقسام الثلاثة.
- `ocobot/ui/open_orders.py`: تذكّر آخر `_selected_order_id` وإعادة تظليل صفه في `set_orders` باستخدام `blockSignals` (إعادة التظليل عند العودة دون إعادة إطلاق الاختيار).

**أدلة القبول:**
- **AC1:** السويت الكاملة خضراء — `_g1_3_run.txt` ⇒ `Ran 247 tests ... OK` (247 = 244 خط أساس + 3 اختبارات موجَّهة جديدة).
- **AC2:** ثلاثة اختبارات وحدة موجَّهة خضراء — `test_ui_app`، `test_ui_selected`، `test_ui_open_orders`: اختيار صف يغذّي 03/04/01 بنفس `orderListId`، و`set_orders` يعيد تظليل الصف المتذكَّر.
- **AC3:** تأكيد يدوي من المستخدم على Testnet (2026-09-26): اختيار أمر ينتشر إلى 03/04/01 بنفس `orderListId`، ويُعاد تظليل الصف عند العودة، و`06_demo` يبقى معزولًا.

**العزل والنطاق:** `06_demo` معزول بالتصميم (لا يعكس التحديد الحقيقي — سلوك مقصود)، ولم يُمس أي `orderListId` آخر (P3)، ولا حقن executor/engine/price. خُتم G1.3.

---

## G1.4 — إصلاح تداخل/عدم وضوح خانات القسمين 03 و04 عند تكبير النافذة

**السبب الجذري:** في `selected_oco.py::_build_old_new_row` كانت `old_value`/`new_value` عبارة `QLabel` بلا `minimumWidth` ولا `sizePolicy` مع `addStretch(1)` أخير يبتلع العرض فتنكمش الخانتان؛ وفي `monitoring.py::_build_live_panel` عمود القيمة بلا حدّ أدنى للعرض وخط 16px فيفيض قليلًا.

**الإصلاح (داخل النطاق فقط):**
- `_build_old_new_row`: إضافة `QSizePolicy`، وضبط `old_value`/`new_value` بـ `setMinimumWidth(120)` و`setSizePolicy(Expanding,Preferred)`، و`addWidget(...,1)` للخانتين، وإزالة `addStretch(1)` الأخير.
- `_build_live_panel`: `grid.setColumnMinimumWidth(1,140)`، `value.setMinimumWidth(120)`، وتصغير خط القيمة 16px→15px.

**الأدلة:**
- **AC1:** `Ran 251 tests OK` (247 + 4) بلا FAIL/ERROR — `_g1_4_run.txt`.
- **AC2:** `tests/test_g1_4_layout_geometry.py` = 4 اختبارات (عدم تداخل العنوان/القيمة في 03/04 + حدّ أدنى لعرض خانات التعديل والقيم الحيّة).
- **AC3:** تأكيد المستخدم اليدوي على Testnet بأن أرقام القسمين 03 و04 واضحة وغير متداخلة عند التصغير والتكبير (نجح بعد إعادة الإصلاح؛ الجولة الأولى فشلت).

**الحالة:** sealed — ts `2026-09-26T21:18:00Z`، `evidence_path=_g1_4_run.txt`.


## G1.5 — ارتداد خانات القسم 03 عند التكبير (1360×768 @125%) — sealed 2026-09-27T01:21:24Z
الحل: تحجيم نسبي موحّد لكل ودجات القيمة في القسم 03 داخل ocobot/ui/selected_oco.py: _build_old_new_row (old_value/new_value، كانت سليمة)، _build_live_panel (_live_current_price/_live_max_stop: setMinimumWidth(90)+Expanding+stretch)، وحقلا SL%/TP% (_sl_pct_edit/_tp_pct_edit: setSizePolicy(Expanding,Preferred)+setMinimumWidth(90)). القسم 04 (monitoring.py) خارج النطاق. الدليل: _g1_5_run.txt (Ran 255 OK) + اختبار test_section03_all_value_widgets_min_width_readonly_and_checked + تأكيد AC3 يدوي.


## G1.8 — تم الحل والختم (2026-09-29T00:55:00Z)
- حُقِن backend حقيقي في app.py::main() (executor/engine/price_provider) مع قفل Testnet.
- EnvironmentPill موصول بالبيئة الفعلية؛ الداشبورد/التفاصيل/جدول الأوامر/التفعيل+النسب/أزرار المراقبة تعمل وتحدّث الأرقام الحيّة.
- شاشة 05_safe_execution صارت SafeExecutionScreen حقيقية؛ مسح step_9: صفر عناصر غير موصولة.
- الدليل: _g1_8_run.txt = Ran 260 tests OK (failures=0 errors=0). Testnet فقط — صفر Live/Withdrawals.
