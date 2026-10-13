# CONVERT-ON-START PLAN (G1.13) — §9.4 READ-ONLY FINDINGS + IMPLEMENTATION PLAN

> هذا توثيق فقط (قراءة‑فقط). **لم يُعدَّل أي ملف كود/إعداد.** كل المقاطع أدناه منقولة
> حرفيًا من القرص (`D:\oco`) وقت التحقيق. التصميم الجديد المؤكَّد: التحويل يحدث عند
> ضغط **بدء** في شاشة المراقبة الديناميكية 04 (لا زر على 02)، باستخدام السعر الحيّ
> (D14) والنِّسب الثلاث، بنفس منطق إعادة تموضع OCO، ثم تُراقَب على `orderListId` الجديد.

---

## A) `ocobot/ui/monitoring.py` — DynamicMonitoringScreen

### A.1 حقول النِّسب الثلاثة (الإنشاء)
تُبنى من ثابت الوحدة في أعلى الملف:

```python
PCT_FIELDS = [
    ("trigger_pct", "نسبة ارتفاع مُشغِّل إعادة التموضع %"),
    ("tp_pct", "نسبة بُعد جني الأرباح فوق الحالي %"),
    ("sl_pct", "نسبة بُعد وقف الخسارة تحت الحالي %"),
]
```

تُنشأ داخل `_build_rules_section`:

```python
self._pct_widgets = []
for key, label in PCT_FIELDS:
    ...
    edit = QLineEdit(card)
    edit.setObjectName("MonitoringPctEdit_%s" % key)
    ...
    edit.textChanged.connect(self._refresh_live_panel)
    self._pct_edits[key] = edit
    self._pct_widgets.append(caption)
    self._pct_widgets.append(edit)
```

- **المفاتيح/أسماء الكائنات:** `trigger_pct` → objectName `MonitoringPctEdit_trigger_pct` (= **trigger%**، نسبة التفعيل)؛ `tp_pct` → `MonitoringPctEdit_tp_pct` (= **TP%**)؛ `sl_pct` → `MonitoringPctEdit_sl_pct` (= **SL%**).
- يُخزَّن كل حقل في القاموس `self._pct_edits[key]`.
- **القراءة:** عبر `self._pct_edits["<key>"].text().strip()` (انظر `_on_start_clicked`، `_computed_levels`، `_trigger_price`).
- **التحقّق:** لا تحقّق صريح في `_on_start_clicked` قبل التمرير للمحرّك — القيم تُمرَّر كنصوص ويُحوّلها المحرّك/`compute_levels` إلى `Decimal`، وأي استثناء يُلتقط في `try/except` ويُعرَض. (`compute_levels` تُستدعى فقط للمعاينة الحيّة في `_computed_levels` وتعيد `None` عند الفشل.) الحقول مخفيّة حتى تفعيل `_enable_toggle` (كشف تدريجي).

### A.2 `_on_start_clicked` (الجسم الكامل) — وفيه guard الرفض الحالي

```python
def _on_start_clicked(self, *args):
    """يبدأ المراقبة على المحرّك المحقون بالسعر الحيّ الحقيقي (D14)."""
    engine = self._engine
    selected = self._selected
    if engine is None or selected is None:
        return
    # G1.13: لا تُبدأ المراقبة على مرشّح تحويل (أمر مستقل غير OCO) — يلزم
    # تحويله إلى OCO أولًا. لا نمسّ أيّ أمر على Binance (P2/P3).
    if getattr(selected, "is_convert_candidate", False):
        self._set_last_operation(
            "بدء", "تعذّر البدء — يلزم تحويل الأمر إلى OCO أولًا"
        )
        self._refresh_live_panel()
        return
    reference = self._current_price
    if reference is None:  # D14: لا بدء بلا سعر حيّ حقيقي
        reference = getattr(selected, "current_price", None)
    if reference is None:
        self._set_last_operation("بدء", "تعذّر البدء — لا سعر حيّ بعد")
        self._refresh_live_panel()
        return
    trigger = self._pct_edits["trigger_pct"].text().strip()
    tp = self._pct_edits["tp_pct"].text().strip()
    sl = self._pct_edits["sl_pct"].text().strip()
    try:
        engine.start(selected, trigger, tp, sl, reference)
        self._set_last_operation("بدء", "بدأت المراقبة")
        self.start_live_updates()
    except Exception as exc:  # noqa: BLE001 — يُعرَض دون كسر الواجهة
        self._set_last_operation("بدء", str(exc))
    self._sync_pause_resume_label()
    self._refresh_live_panel()
```

**guard الرفض الحرفي** هو كتلة `if getattr(selected, "is_convert_candidate", False): ...` أعلاه.
لا يوجد helper خارجي للبدء — `_on_start_clicked` ينادي `engine.start(...)` مباشرة ثم `self.start_live_updates()`.

يُعضَد الرفض بتعطيل زر البدء داخل `_refresh_live_panel`:

```python
if hasattr(self, "start_button"):
    is_candidate = bool(getattr(selected, "is_convert_candidate", False)) if selected else False
    self.start_button.setEnabled(not is_candidate)
    if hasattr(self, "_convert_hint"):
        self._convert_hint.setText(
            "سيُحوَّل إلى OCO — يلزم التحويل أولًا قبل بدء المراقبة"
            if is_candidate else ""
        )
        self._convert_hint.setVisible(is_candidate)
```

### A.3 `set_selected` (الجسم الكامل)

```python
def set_selected(self, selected):
    """يضبط الـ OCO المختار (SelectedOCO أو None) ويحدّث اللوحة الحيّة."""
    self._selected = selected
    if selected is None:
        self._current_price = None
    else:
        # قد يحمل الهدف سعرًا مرجعيًا حقيقيًا مبدئيًا (يُستبدَل بأول tick حيّ).
        self._current_price = getattr(selected, "current_price", None)
    self._refresh_live_panel()
```

- يخزّن الاختيار في `self._selected`، ويضبط `self._current_price` من `selected.current_price` (قد يكون `None`).
- **لا يملك مزوّد سعر خاصًّا به هنا** — المزوّد محقون في `__init__` كـ `self._price_provider` (callable يُرجع السعر الحيّ)، ولا تُستدعى `set_symbol` من داخل الشاشة إطلاقًا (الشاشة لا تلمس الشبكة؛ حارس `test_ui_no_direct_network`). السعر الحيّ يصل عبر `set_current_price` أو حلقة `start_live_updates`/`_schedule_tick`.

### A.4 معالج إعادة التموضع داخل النبضة (`_on_live_tick`) — تحديث `order_list_id`

```python
if tick is not None and getattr(tick, "event", "") == "REPOSITIONED":
    res = getattr(tick, "execution_result", None)
    if res is not None and self._selected is not None:
        new_id = getattr(res, "new_order_list_id", None)
        if new_id is not None:
            self._selected.order_list_id = new_id
        draft = getattr(res, "draft", None)
        if draft is not None:
            if getattr(draft, "tp_price", None) is not None:
                self._selected.tp = draft.tp_price
            if getattr(draft, "stop_trigger", None) is not None:
                self._selected.stop_trigger = draft.stop_trigger
            if getattr(draft, "stop_limit", None) is not None:
                self._selected.stop_limit = draft.stop_limit
```

### A.5 المُنشئ `__init__` — ما يستقبله ويخزّنه

```python
def __init__(self, parent=None, engine=None, price_provider=None, runner=None,
             selected_oco=None, environment=None):
    ...
    self._engine = engine                 # MonitoringEngine المحقون (يفوّض للـ SafeExecutor)
    self._price_provider = price_provider  # callable يُرجع السعر الحيّ الحقيقي (D14)
    self.runner = runner                   # AsyncRunner (اختياري) — لا IO في الواجهة
    self._selected = selected_oco          # الـ OCO المختار (SelectedOCO أو None)
    self._environment = environment        # اسم البيئة (Testnet/Live) للعرض
    self._current_price = None             # آخر سعر حيّ حقيقي محقون (لا Preview)
    self._pct_edits = {}
    self._live = {}
    self._ticking = False
    self._tick_interval = 1.0
```

**الباراميترات:** `parent, engine, price_provider, runner, selected_oco, environment`.
**لا يستقبل اليوم:** `selector` ولا `convert_cb` ولا `executor`. ⇒ هذه الفجوة الأساس للتحويل‑عند‑البدء.

---

## B) محرّك المراقبة/إعادة التموضع — `ocobot/domain/monitoring.py`

### B.1 `MonitoringEngine.__init__` + `start(...)`

```python
class MonitoringEngine:
    def __init__(self, executor, *, guard_policy: GuardPolicy = GuardPolicy.HALT_NOTIFY,
                 dry_run: bool = False, audit: Optional["AuditLog"] = None,
                 checkpoint_sink=None):
        self._executor = executor
        ...

    def start(self, selected_oco, trigger_pct, tp_pct, sl_pct, reference_price,
              tolerance_pct=Decimal("0.1"), guard_pct=Decimal("1.0")) -> MonitoringState:
        """يبدأ المراقبة على السعر المرجعي الحيّ الحقيقي المُمرَّر (D14)."""
        self._selected_oco = selected_oco
        st = self.state
        st.symbol = getattr(selected_oco, "symbol", "")
        st.target_order_list_id = getattr(selected_oco, "order_list_id", None)
        st.trigger_pct = _dec(trigger_pct)
        st.tp_pct = _dec(tp_pct)
        st.sl_pct = _dec(sl_pct)
        st.reference_price = _dec(reference_price)
        ...
        st.enabled = True
        st.state = MonitoringStateEnum.MONITORING_ACTIVE
        ...
        return st
```

**ملخّص السلوك:** `start()` فقط يسجّل الحالة (symbol/target/pcts/reference) ويُفعّل المراقبة — **لا يُنفّذ أي cancel/create**. ملاحظة مهمّة: `start` يقرأ `selected_oco.order_list_id` كهدف؛ لو كان الاختيار مرشّح تحويل (`order_list_id is None`) فالهدف سيكون `None` — لذا يجب التحويل أوّلاً وتحديث الاختيار قبل `start`.

### B.2 أين يُنفَّذ cancel+create فعليًا (مرآة التحويل)
داخل `on_price_tick`، بعد تجاوز مستوى التفعيل و latching، يُستدعى **المنفّذ المحقون** (SafeExecutor):

```python
st.in_flight = True
st.state = MonitoringStateEnum.REPOSITIONING
result = self._executor.execute(
    order_list_id=st.target_order_list_id,
    tp_pct=st.tp_pct,
    sl_pct=st.sl_pct,
    reference_price=last,
    dry_run=self.dry_run,
)
return self._interpret(result, last)
```

- **المحرّك نفسه لا يلغي/ينشئ.** يفوّض لـ `SafeExecutor.execute(...)` في `ocobot/domain/reposition.py`:

```python
def execute(self, order_list_id: int, tp_pct, sl_pct, reference_price,
            dry_run=False) -> ExecutionResult:
    # ① verify ② price+qty ③ recalc ④ Pre-Cancel Gate ⑤ cancel ⑥ create ⑦ confirm
```

`SafeExecutor.execute` هو **المنفّذ الذي يعيد تموضع OCO** (cancel OCO قديم → create OCO جديد) ويعيد `ExecutionResult` ذا `new_order_list_id`.

### B.3 التفسير + Rollover (`_interpret`, حالة SUCCESS)

```python
if state == ExecutionState.SUCCESS:
    if result.new_order_list_id is not None:
        st.target_order_list_id = result.new_order_list_id
    st.reference_price = last
    st.latched = False
    st.in_flight = False
    st.cursor += 1
    st.state = MonitoringStateEnum.MONITORING_ACTIVE
    ...
    return MonitorTick("REPOSITIONED", st.state, last, execution_result=result,
                       message=f"أُعيد التموضع إلى OCO {result.new_order_list_id}.")
```

**⇒ المرآة للتحويل:** `ConvertExecutor.convert(...)` (قسم C) يؤدي نفس cancel→create لكن للمصدر أيًّا كان نوعه، ويعيد نفس نوع `ExecutionResult` بـ `new_order_list_id` — لذا نستعمله لمرّة التحويل الأولى، ثم تكمل `SafeExecutor.execute` إعادات التموضع التالية على الـ OCO الجديد.

---

## C) توفّر CONVERT من المراقبة اليوم

- **لا `convert_cb` ولا `ConvertExecutor` يصل اليوم إلى شاشة المراقبة 04 ولا إلى `MonitoringEngine`.** المحرّك يحمل `SafeExecutor` فقط، والشاشة 04 لا تملك باراميتر `convert_cb`/`selector`/`executor`.
- بناء `convert_cb` موجود في `ocobot/app_wiring.py`:

```python
def build_convert_executor(client, audit=None):
    return ConvertExecutor(client, ExchangeInfoService(client), audit=audit)

def make_convert_cb(convert_executor, price_provider):
    def convert_cb(source, tp_pct, sl_pct, reference_price=None, dry_run=False):
        if reference_price is None or (isinstance(reference_price, str) and not reference_price.strip()):
            if hasattr(price_provider, "set_symbol"):
                price_provider.set_symbol(source.symbol)
            price = price_provider.get_price()
            if price is None:
                raise ValueError("LIVE_PRICE_UNAVAILABLE: تعذّر جلب السعر الحيّ (D14)")
            reference_price = price
        return convert_executor.convert(source, tp_pct, sl_pct, reference_price, dry_run=dry_run)
    return convert_cb
```

- اليوم `convert_cb` يُمرَّر فقط نحو شاشة 02 (عبر `MainWindow(convert_cb=...)` → `ContentRouter(convert_cb=...)` → `OpenOrdersScreen.set_convert_cb`) ويُطلقه زر «تحويل إلى OCO». **لا شيء يمرّره نحو المراقبة 04.** كذلك `ocobot/ui/app.py::main()` لا يبني `convert_cb` ولا يمرّره أصلاً (الفجوة الأصلية).

- **`ConvertExecutor.convert`** يقبل مرشّح standalone بالفعل ويعيد `new_order_list_id`:

```python
def convert(self, source: OpenSellOrder, tp_pct, sl_pct, reference_price,
            dry_run: bool = False) -> ExecutionResult:
    step("verify", ...); draft = self.build_draft(...)
    gate = validate_pre_cancel(draft, draft.reference_price, draft.filters, available_qty=draft.quantity)
    if not gate.ok: return ExecutionResult(state=ExecutionState.ABORTED, ...)
    if dry_run:    return ExecutionResult(state=ExecutionState.GATE_PASSED, ...)
    # cancel source: standalone => cancel_order(DELETE /api/v3/order)؛ OCO => DELETE /api/v3/orderList
    ...
    resp = self._client.signed_request("POST", PATH_CREATE_OCO, create_params)
    result.new_order_list_id = resp.get("orderListId")
    ...
    result.state = ExecutionState.SUCCESS
    return result
```

واختبارات `tests/test_convert_g1_13.py` تؤكّد: `test_standalone_success` ⇒ `state==SUCCESS` و `new_order_list_id==999` مع `cancel_order` + `POST /orderList/oco`. **المصدر `source` من نوع `OpenSellOrder` (ليس `SelectedOCO`).** ⇒ انظر الملاحظة الحرجة في القسم «D».

**⚠️ ملاحظة حرجة (نوع المصدر):** `convert_cb`/`ConvertExecutor.convert` يتوقّعان `OpenSellOrder` (يقرآن `source.origQty/executedQty/orderId/oco_group_id/is_oco/badge`). لكن شاشة المراقبة تحمل `SelectedOCO` (مرشّح تحويل) الذي يحمل فقط `source_order_id/source_order_type/trailing_delta/symbol/quantity`. ⇒ يلزم إمّا:
1. تمرير `OpenSellOrder` الأصلي معه حتى المراقبة (أفضل)، أو
2. إضافة طريق في `ConvertExecutor`/غراء جديد يقبل `SelectedOCO` ويعيد بناء مصدر، أو
3. أن تحتفظ شاشة 02 بـ `OpenSellOrder` الأصلي وتمرّره مع الاختيار.
الخيار (1) هو الأقل خطرًا ويبقى داخل ملفات UI (انظر الخطة).

---

## D) `ocobot/ui/app.py::main()` — التغذية والانتشار والتنقّل التلقائي

### D.1 تغذية شاشة 02 اليوم (مسار OCO فقط — يجب تغييره)

```python
if _client is not None:
    oo = window.content.screen_for("02_open_orders")
    if oo is not None and hasattr(oo, "set_source"):
        oo.set_source(
            build_fn=lambda: OcoReader(
                build_gui_client(AppConfig.from_env_vars())
            ).list_open_ocos(),
            runner=window.runner,
        )
        oo.refresh()
```

### D.2 بناء backend في `main()`

```python
_selector = Selector(OcoReader(_client), ExchangeInfoService(_client)) if _client is not None else None
_executor = _build_executor(_client, audit=None) if _client is not None else None
_engine = MonitoringEngine(_executor, dry_run=False) if (...) else None
_price = SelectionPriceProvider(_cfg, _client) if _client is not None else None
...
app, window = build_app(select_fn=_select, executor=_executor, engine=_engine, price_provider=_price)
```

ملاحظة: `build_app(...)` و `MainWindow(...)` اليوم **لا يمرّران `convert_cb`** رغم أن `MainWindow.__init__` يقبله. `main()` لا يبني `convert_cb` إطلاقًا.

### D.3 الانتشار + التنقّل التلقائي (في `main_window.py`)

- وصل الاختيار على 02 (مسار OCO): `oo.set_on_select(self.handle_oco_selection)`.
- وصل مسار «كل أوامر البيع» (موجود): `oo.set_on_sell_select(self._show_selected)` و `oo.set_convert_cb(self._on_convert_requested)` (الأخير فقط إن `convert_cb` ليس None).
- `handle_oco_selection(order_list_id)` → عبر الرَنَر `self._select_fn(order_list_id)` → `_show_selected(selected)`.
- `_show_selected(selected)` يغذّي 03 و04 و01 **ثم يُنقّل تلقائيًا إلى 03** (التنقّل التلقائي ما قبل G1.13 مُحافَظ عليه):

```python
def _show_selected(self, selected):
    sel = self.content.screen_for("03_selected_and_edit")
    if sel is not None:
        sel.set_selected(selected)
    mon = self.content.screen_for("04_dynamic_monitoring")
    if mon is not None and hasattr(mon, "set_selected"):
        mon.set_selected(selected)
    dash = self.content.screen_for("01_dashboard")
    if dash is not None and hasattr(dash, "update_snapshot"):
        dash.update_snapshot(build_dashboard(selected, ...))
    self.navigate_to("03_selected_and_edit")
```

- شاشة 04 تتلقّى الاختيار عبر `mon.set_selected(selected)` (لا `set_selector`؛ لا يوجد).
- **مفاتيح الرَاوتر** (من `ocobot/ui/screens.py` + `content.py`): `02_open_orders`، `03_selected_and_edit`، `04_dynamic_monitoring` (وأيضًا `01_dashboard`، `05_safe_execution`).

---

## E) `ocobot/ui/open_orders.py` — عزلية إزالة زر «تحويل إلى OCO»

كل مراجع الزرّ ومساره (كلها داخل هذا الملف فقط عدا الحقن في content/main_window):

```python
self.convert_button = QPushButton("تحويل إلى OCO", self)
self.convert_button.setObjectName("ConvertToOco")
self.convert_button.setEnabled(False)
self.convert_button.clicked.connect(self._handle_convert_clicked)
header.addWidget(self.convert_button)
...
def convert_button_enabled(self):
    return self.convert_button.isEnabled()
...
# داخل _handle_sell_selection_changed:
self.convert_button.setEnabled(is_candidate)
...
def _handle_convert_clicked(self):
    sel = self._current_selection
    if sel is None or not getattr(sel, "is_convert_candidate", False):
        return
    if self._convert_cb is not None:
        self._convert_cb(sel)
...
# داخل clear():
self.convert_button.setEnabled(False)
```

- `set_convert_cb(cb)` يُحقن من `content.py` و`main_window.py` فقط.
- **لا اختبار يرجع إلى `convert_button` ولا `ConvertToOco` ولا `convert_button_enabled`** (بحث شامل `tests/*.py` ⇒ صفر نتائج). ⇒ إزالة الزرّ ومعالجه آمنة.
- `set_open_sell_orders(orders)` يعرض **كل أنواع البيع** (standalone + OCO مدموج) مع شارة لكل صفّ عبر `classify_badge` (TRAILING عند `trailingDelta>0`)، والعرض/الاختيار يعملان بلا الزرّ: `_handle_sell_selection_changed` ينتج `SelectedOCO` عبر `self._selector.select_from_row(order)` ويستدعي `self._on_sell_select(selected)`. ⇒ view+select يعملان مستقلّين تمامًا عن الزرّ.
- **تبعية يجب الحفاظ عليها عند الإزالة:** `_handle_sell_selection_changed` و`clear()` و`_handle_convert_clicked` تلمس `self.convert_button`؛ لذا أزِل كلّ هذه الأسطر معًا (وأبقِ `_on_sell_select`/`_selector`/`set_open_sell_orders`).

---

## F) `ocobot/ui/selected_oco.py` (شاشة 03) — عرض/تعديل فقط لمرشّح التحويل

- 03 شاشة عرض+تعديل (قسم القراءة + قسم Manual Edit بالنِّسب + زر Activate لإعادة تموضع OCO قائم).
- زر **Activate** لا ينفّذ تحويلًا؛ يرفض مرشّح التحويل صراحةً:

```python
def _on_activate_clicked(self, *args):
    execute = self._execute_cb or (self._executor.execute if self._executor is not None else None)
    selected = getattr(self, "_selected", None)
    if execute is None or selected is None:
        return
    # G1.13: لا تفعيل إعادة تموضع على مرشّح تحويل (أمر مستقل بلا OCO بعد).
    if getattr(selected, "is_convert_candidate", False):
        self._activate_status.setText("سيُحوَّل إلى OCO — يلزم التحويل أولًا")
        return
    ...
```

- `set_selected` يعرض «سيُحوَّل إلى OCO (<type>)» بدل `orderListId` للمرشّح. ⇒ 03 لا تملك إجراء تنفيذ/تحويل خاص؛ display+edit فقط. لا تغييرات مطلوبة فيها لهذه الميزة.

---

# CONVERT-ON-START PLAN

## 1) التغيير الدقيق على `_on_start_clicked` (monitoring.py)

استبدال guard الرفض الحالي بفرع تحويل. المنطق المقترح:

```
def _on_start_clicked:
    engine, selected = self._engine, self._selected
    if engine is None or selected is None: return
    trigger = self._pct_edits["trigger_pct"].text().strip()
    tp       = self._pct_edits["tp_pct"].text().strip()
    sl       = self._pct_edits["sl_pct"].text().strip()
    reference = self._current_price or getattr(selected, "current_price", None)
    if reference is None:
        self._set_last_operation("بدء", "تعذّر البدء — لا سعر حيّ بعد"); self._refresh_live_panel(); return

    # G1.13 CONVERT-ON-START
    if getattr(selected, "is_convert_candidate", False):
        if self._convert_cb is None:   # لم يُحقن طريق التحويل
            self._set_last_operation("بدء", "تعذّر التحويل — لا يوجد منفّذ تحويل محقون"); self._refresh_live_panel(); return
        source = getattr(self, "_source_order", None)   # OpenSellOrder الأصلي (انظر §2)
        if source is None:
            self._set_last_operation("بدء", "تعذّر التحويل — مصدر الأمر غير متاح"); self._refresh_live_panel(); return
        try:
            result = self._convert_cb(source, tp, sl, reference)   # يعيد ExecutionResult
        except Exception as exc:
            self._set_last_operation("بدء", str(exc)); self._refresh_live_panel(); return
        state = getattr(getattr(result, "state", None), "value", None) or getattr(getattr(result,"state",None),"name",None)
        new_id = getattr(result, "new_order_list_id", None)
        if state != "SUCCESS" or new_id is None:
            self._set_last_operation("بدء", getattr(result, "reason", None) or "فشل التحويل"); self._refresh_live_panel(); return
        # رقِّ الاختيار إلى OCO حقيقي حتى تمرّ guard القديمة ويُعرَف الهدف للمحرّك
        selected.order_list_id = new_id
        selected.is_convert_candidate = False
        draft = getattr(result, "draft", None)
        if draft is not None:
            selected.tp = draft.tp_price; selected.stop_trigger = draft.stop_trigger; selected.stop_limit = draft.stop_limit
        self._set_last_operation("تحويل", f"حُوِّل إلى OCO {new_id}")

    # من هنا المسار الطبيعي (الاختيار الآن OCO حقيقي)
    try:
        engine.start(selected, trigger, tp, sl, reference)
        self._set_last_operation("بدء", "بدأت المراقبة")
        self.start_live_updates()
    except Exception as exc:
        self._set_last_operation("بدء", str(exc))
    self._sync_pause_resume_label(); self._refresh_live_panel()
```

ملاحظات مطابِقة للتصميم:
- السعر المرجعي = السعر الحيّ `self._current_price` (D14)؛ TP/SL% من حقول النِّسب (D6)؛ الكمية read‑only داخل `ConvertExecutor.build_draft` (D7).
- بعد النجاح، `order_list_id = new_id` و`is_convert_candidate=False` يجعلان `_refresh_live_panel` يُفعّل زر البدء ويزيل تلميح التحويل، و`engine.start` يلتقط `target_order_list_id = new_id` (AC3).
- يجب أيضًا **إزالة/تعطيل** الـ guard القديمة الحرفية `if is_convert_candidate: refuse` (تُستبدل بفرع التحويل أعلاه)، وتعديل كتلة `start_button.setEnabled(not is_candidate)` في `_refresh_live_panel` بحيث لا يبقى الزر معطّلًا للمرشّح (نريد السماح بالبدء→تحويل). خيار آمن: اجعل الزر مفعّلًا دائمًا طالما يوجد اختيار، وغيّر نص `_convert_hint` إلى «سيُحوَّل عند البدء».

## 2) كيف تحصل المراقبة على CONVERT + المصدر `OpenSellOrder`

مطلوب حقن شيئين في شاشة 04: `convert_cb` و`OpenSellOrder` الأصلي.

- **convert_cb:** أضف باراميتر `convert_cb=None` إلى `DynamicMonitoringScreen.__init__` وخزّنه `self._convert_cb`. مرّره عبر `ContentRouter.__init__(convert_cb=...)` إلى `DynamicMonitoringScreen(...)` (الراوتر يملكه أصلًا كـ `self._convert_cb`)، و`MainWindow` يملكه ويمرّره للراوتر. ثم في `main()` ابنِه عبر `build_convert_executor`+`make_convert_cb` ومرّره لـ `build_app/MainWindow`.
- **المصدر `OpenSellOrder`:** الاختيار الواصل إلى 04 هو `SelectedOCO`، بينما `convert_cb` يحتاج `OpenSellOrder`. الحل الأقل خطرًا داخل UI:
  - في `OpenOrdersScreen._handle_sell_selection_changed` احتفظ بـ `OpenSellOrder` الأصلي للصفّ (`self._sell_rows[row]`) وأرفقه إلى الـ`SelectedOCO` (مثلاً `selected._source_order = order`) قبل استدعاء `self._on_sell_select(selected)` — تعديل داخل `open_orders.py` فقط.
  - في `monitoring.set_selected` خزّن `self._source_order = getattr(selected, "_source_order", None)` ليستعمله `_on_start_clicked`.
  - بديل بلا تلويث `SelectedOCO`: مرّر `source` عبر callback منفصل من 02→main_window→04. الأبسط هو حمله على الاختيار.
- حلقة `start_live_updates`/`_schedule_tick` موجودة وتعمل بالمزوّد `self._price_provider` المحقون (نفس `_price` من `main()`), ويجب أن يكون `price_provider.set_symbol(symbol)` قد نودي (يُنادى اليوم داخل `_select` في `app.py`؛ لمسار البيع يجب ضمان ندائه كذلك — انظر §3).

## 3) ما يُزال على 02 + تغييرات التغذية/الاختيار/التنقّل في app.py/main_window.py

- **open_orders.py:** احذف `convert_button` (الإنشاء + `addWidget` + `clicked.connect`) و`_handle_convert_clicked` و`convert_button_enabled`، وأزِل سطري `self.convert_button.setEnabled(...)` من `_handle_sell_selection_changed` و`clear()`. أبقِ `set_selector`/`set_on_sell_select`/`set_open_sell_orders`/`select_from_row`/الشارات. (اختياريًا أبقِ `set_convert_cb` كـ no‑op للتوافق، أو احذفه مع حقنه في content/main_window.)
- **app.py::main():** غيّر تغذية 02 من `list_open_ocos()` إلى `read_all_open_sell_orders(client)` معروضة عبر `set_open_sell_orders` (بدل `set_source(...list_open_ocos...)` + `oo.refresh()`), واحقن `oo.set_selector(_selector)`. ابنِ `convert_executor = build_convert_executor(_client)` و`convert_cb = make_convert_cb(convert_executor, _price)` ومرّره: `build_app(..., convert_cb=convert_cb)` → `MainWindow(convert_cb=...)`. تأكّد أن مسار اختيار البيع يستدعي `_price.set_symbol(symbol)` (أضِفه في `_show_selected` أو في مسار البيع) حتى تعمل حلقة السعر الحيّ على رمز المرشّح.
- **main_window.py:** مرّر `convert_cb` إلى `ContentRouter` (موجود)، وزِد تمريره إلى شاشة 04. التنقّل التلقائي إلى 03 عند الاختيار (`_show_selected → navigate_to("03_selected_and_edit")`) يبقى كما هو قبل G1.13. أزِل (أو أبقِ غير فعّال) ربط `_on_convert_requested`/`set_convert_cb` على 02 لأن التحويل لم يعد يُطلَق من 02.
- **build_app في app.py:** أضف باراميتر `convert_cb=None` ومرّره إلى `MainWindow`.

## 4) الملفات التي ستُكتب (ضمن النطاق المسموح)

1. `ocobot/ui/app.py` — بناء `convert_cb`، تمريره، تغذية 02 بـ `read_all_open_sell_orders` + `set_selector`، ضمان `set_symbol`.
2. `ocobot/ui/open_orders.py` — إزالة زر التحويل ومعالجه؛ إرفاق `OpenSellOrder` الأصلي بالاختيار.
3. `ocobot/ui/main_window.py` — تمرير `convert_cb` إلى 04؛ تنظيف ربط التحويل على 02.
4. `ocobot/ui/content.py` — تمرير `convert_cb` إلى `DynamicMonitoringScreen(...)`.
5. `ocobot/ui/monitoring.py` — باراميتر `convert_cb`؛ حفظ `_source_order` في `set_selected`؛ فرع التحويل في `_on_start_clicked`؛ تعديل تعطيل زر البدء/تلميح التحويل في `_refresh_live_panel`.
6. ملف اختبار جديد: `tests/test_ui_convert_on_start_g1_13.py` — يغطّي: البدء على مرشّح تحويل يستدعي `convert_cb(source, tp, sl, live_price)`، ويرقّي الاختيار إلى `new_order_list_id`، ثم `engine.start` يستهدف الـ OCO الجديد؛ وفشل التحويل لا يبدأ المراقبة؛ وبلا سعر حيّ لا تحويل.

### أعلام (ملفات خارج النطاق قد تلزم)
- **لا يلزم** تعديل `ocobot/domain/convert.py` ولا `app_wiring.py` إذا مرّرنا `OpenSellOrder` الأصلي (الخيار 1) — `convert_cb`/`ConvertExecutor` يقبلانه كما هو. **لكن** إن اختير بدل ذلك جعل المراقبة تقبل `SelectedOCO` وتعيد بناء مصدر، فسيلزم تعديل `app_wiring.py` أو `domain/convert.py` (خارج النطاق) — يُفضَّل تجنّبه بإرفاق المصدر على الاختيار داخل `open_orders.py`.
- `build_convert_executor` و`ExchangeInfoService` و`SelectionPriceProvider` كلها جاهزة؛ `app.py` يستوردها من `app_wiring` بلا تعديل للغير.
- حارس `tests/test_ui_no_direct_network` يمنع أي شبكة مباشرة في `ocobot/ui/*` — كل التغييرات أعلاه تبقى callbacks/حقن بلا `signed_request`/`urllib`.
