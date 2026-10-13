# حفظ الحالة — تحقيق قراءة‑فقط لمسار G1.13 «تحويل أمر بيع غير‑OCO إلى OCO»

> ملف حالة (checkpoint) أُنشئ لاستئناف العمل عند العودة. **لم تُجرَ أي تعديلات على الكود أو الإعدادات** — هذا تحقيق قراءة فقط فقط لتوثيق النتائج.
> نطاق التحقيق: جذر المشروع `D:\oco` (المستند الملزِم `docs/OCOBot_Design_AR.md` + الموك‑أب `docs/ui_mockups/` + `PROJECT_STATE.json` + `WORKING_MEMORY.json` + كود `ocobot/`).

---

## 0) أين توقفنا (resume point)
- `WORKING_MEMORY.json`: `task = G1.13`، `resume_point = convert_cb_wired`.
- **المُنجَز (DONE):** غراء `convert_cb` = `app_wiring.build_convert_executor` + `make_convert_cb` → `ConvertExecutor.convert` بسعر حيّ (D14، يرفع `ValueError` إن تعذّر السعر) + `tests/test_convert_cb_g1_13.py` (5 اختبارات). كامل المجموعة أخضر: Ran 316 OK.
- **المتبقّي (NEXT) حسب الذاكرة:** ربط الواجهة في `ui/open_orders` (عرض كل أنواع البيع بشارات + انتشار الاختيار عبر `select_from_row` + زر «تحويل إلى OCO» → `convert_cb` → شاشة `05_safe_execution`، مع الحفاظ على التخطيط 1360x768 @125%)، ثم تغذية `orderListId` الجديد للمراقبة الديناميكية (T4/T13).
- ملاحظة مهمة: الكود يُظهر أن أجزاء من «المتبقّي» قد نُفّذت فعلًا (زر التحويل + مساره موجود في `open_orders.py`/`main_window.py`)، لكن **التوصيل النهائي في نقطة الدخول `ocobot/ui/app.py::main()` ناقص** (لا يُحقَن `convert_cb` ولا `set_open_sell_orders`/`set_selector`). التفاصيل في القسم 4.

---

## 1) الجواب الحاسم للسؤال الدقيق

**السؤال:** عند تحويل أمر بيع غير‑OCO إلى OCO: (أ) أي شاشة/زر يُطلق التنفيذ الفعلي؟ و(ب) من أي حقول تُؤخذ TP%/SL%؟ (السعر المرجعي = السعر الحي D14).

**الإجابة المدعومة بالأدلة:**

### (أ) الزر/الشاشة التي تُطلق التحويل
- **المصدر الملزِم (التصميم) صامت صراحةً عن «تحويل غير‑OCO → OCO».** `docs/OCOBot_Design_AR.md` يصف فقط إدارة/إعادة تموضع OCO قائم؛ قسم `02_open_orders` فيه زر **Select** فقط (لا زر «تحويل»)، وقسم `03` فيه زر **Activate** الذي يُطلق Safe Execution لإعادة تموضع OCO قائم. **لا يوجد ذكر لزر «تحويل إلى OCO» في المستند ولا في أي موك‑أب HTML.**
- **ميزة التحويل مُعرَّفة في `PROJECT_STATE.json` (عيب/مهمة G1.13) لا في مستند التصميم.** القرار المعماري هناك (الخطوة 2 و4):
  - زر التحويل على **شاشة الأوامر المفتوحة `02_open_orders`** (ليس على شاشة التعديل 03).
  - المسار: بوّابة تحقّق قبل الإلغاء (D16) ← إلغاء الأمر المختار (`DELETE /api/v3/order` للمستقل، `DELETE /api/v3/orderList` لـ OCO) ← إنشاء OCO جديد (`POST /api/v3/orderList/oco`) ← شاشة `05_safe_execution`.
- **تأكيد من الكود (الحقيقة الفعلية على القرص):**
  - الزر: `ocobot/ui/open_orders.py` → `self.convert_button = QPushButton("تحويل إلى OCO")` بـ `objectName = "ConvertToOco"`، مُعطَّل افتراضيًا، يُفعَّل فقط عند اختيار صفّ بيع مستقل (`is_convert_candidate`). `clicked → _handle_convert_clicked → self._convert_cb(sel)`.
  - التوجيه: `main_window.py::_on_convert_requested(selected)` → `result = self._convert_cb(selected)` → `_handle_execution_result(result, selected)` → يعرض شاشة **`05_safe_execution`**.
  - الغراء غير‑ui: `app_wiring.make_convert_cb` → `ConvertExecutor.convert` (في `ocobot/domain/convert.py`).
  - **زر Activate في شاشة 03 لا يُنفّذ التحويل:** `selected_oco.py` عند `is_convert_candidate` يعرض «سيُحوَّل إلى OCO — يلزم التحويل أولًا» ويمنع إعادة التموضع؛ وشاشة المراقبة `04` كذلك تُعطّل البدء وتعرض نفس التلميح.

**⇒ الخلاصة (أ):** التنفيذ الفعلي يُطلقه زر **«تحويل إلى OCO»** على شاشة **`02_open_orders`** (بعد اختيار صفّ بيع مفرد)، ثم يُعرَض التقدّم على شاشة **`05_safe_execution`**. هذا **قرار G1.13 في `PROJECT_STATE.json`**، وليس في مستند التصميم الملزِم (الذي يبقى صامتًا عن ميزة التحويل).

### (ب) من أين تُؤخذ TP%/SL%
- **القرار الموثّق `D-G1.13-refprice` في `PROJECT_STATE.json`:** عند تحويل أمر بيع مفرد (غير‑OCO) إلى OCO، السعر المرجعي لحساب %TP و%SL هو **السعر الحي الحالي** (`market_feed` مع REST fallback، **D14**)؛ الكمية موروثة للقراءة فقط (D7)؛ **المستخدم يُدخل %TP/%SL فقط** (D6).
- **التوقيع في الكود:** `ConvertExecutor.convert(source, tp_pct, sl_pct, reference_price, dry_run)` و `convert_cb(source, tp_pct, sl_pct, reference_price=None, dry_run=False)` — وإذا كان `reference_price` فارغًا يجلب السعر الحي عبر `price_provider` (D14) ويرفع `ValueError("LIVE_PRICE_UNAVAILABLE")` إن تعذّر.
- **فجوة واجهة (مهمة عند الاستئناف):** في المسار الحالي بالكود، نقر زر التحويل في `open_orders.py` ينادي `self._convert_cb(sel)` **بدون تمرير `tp_pct`/`sl_pct`** (يمرّر الـ selection فقط). أي **لا توجد بعدُ حقول إدخال TP%/SL% مربوطة بزر التحويل** على شاشة 02. حقول TP%/SL% الموجودة فعليًا (`SelectedTpPctEdit` / `SelectedSlPctEdit`) هي على شاشة **03 (التعديل اليدوي)** وتخدم مسار إعادة التموضع لا مسار التحويل. ⇒ **تناقض يجب حسمه عند العودة:** إمّا (1) جمع TP%/SL% على شاشة 02 بجوار زر التحويل، أو (2) جعل الاختيار يمرّ لشاشة 03 لإدخال النِّسب ثم يُطلق التحويل من هناك. التصميم الملزِم لا يحسم هذا (صامت)، وقرار G1.13 يضع الزر على 02.

---

## 2) المقاطع الحرفية من مستند التصميم `docs/OCOBot_Design_AR.md`

### A2 — مرجع النِّسب (السعر الحي)
> **A2 — النِّسب مرجعها السعر الحي:** `TP%` فوق `current_live_price` و`SL%` تحته، في الوضعين اليدوي والديناميكي (كما في القسم 5-D و6 من البرومبت).

### 3.2 B — شاشة الأوامر المفتوحة (`02_open_orders.html`)
> ## 3.2 B — Open OCO Orders (`02_open_orders.html`)
> جدول التحكم. أعمدة: `# · Order List ID · Symbol · Status · Qty · Sale/TP · Stop Trigger · Limit After Trigger` + زر **Select**.
> - المصدر: `GET /api/v3/openOrderList` (حقيقي). زر **Refresh** يدوي + تحديث حالة عبر User Data Stream.
> - اختيار صف → ينتقل إلى Selected OCO ويؤسّس Live context.

ملاحظة: **لا ذكر لزر «تحويل» هنا؛ فقط Select.** المصدر `openOrderList` (OCO فقط) — وهو جوهر عيب G1.13.

### 3.3 C + 3.4 D — الأمر المختار + التعديل اليدوي (`03_selected_and_edit.html`)
> ## 3.3 C — Selected OCO (تأكيد الفهم) (`03_selected_and_edit.html` — العمود الأول)
> `Order List ID · Symbol · Quantity · TP · Stop Trigger · Stop Limit · Leg IDs · Status · Current Price`. - الكمية معروضة مع شارة **🔒 مقفولة**.
>
> ## 3.4 D — Manual Edit بالنِّسب (`03_selected_and_edit.html` — العمودان 2 و3)
> - **Checkbox تفعيل** (Progressive disclosure): حقول الإدخال **لا تظهر/تُفتح** إلا بعد تفعيله بإرادة المستخدم.
> - إدخال المستخدم: `TP %` (فوق السعر الحالي) و`SL %` (تحته) فقط.
> - **النظام يملأ تلقائيًا الأسعار الثلاثة:** TP price، Stop Trigger، Stop Limit (= Trigger − gap، أسفل التريجر). الكمية Read-only.
> - تُعرض **القيم القديمة** بجانب الجديدة للمرجع. الأمر الأصلي **فعّال حتى Activate**.
> - **Live panel (العمود 3):** السعر الحالي + **أعلى Stop متاح** وفق قواعد Binance + زر **Max Available Stop**.
> - **قبل اختيار OCO لا يبدأ الـ Live context.**
> - زر **Activate** (BLUE) يطلق Safe Execution (شاشة F).

### 3.6 F — Safe Execution (`05_safe_execution.html`)
> ① Re-verify selected OCO (ID/Symbol/Status/Identity)
> ② Get latest usable price + remaining quantity (بعد أي Partial Fill)
> ③ Recalculate levels (الأسعار الثلاثة) + تقريب tick/step + ترتيب صارم
> ④ 🛡️ Pre-Cancel Validation Gate ← بوابة تحقّق مسبق قبل أي إلغاء
> ⑤ Cancel selected OCO only
> ⑥ Create replacement OCO
> ⑦ Confirm new orderListId
>
> **🛡️ Pre-Cancel Validation Gate (④ إلزامية):** الترتيب الصارم `Stop Limit < Stop Trigger < Last Price < TP` (SELL)؛ الفلاتر tickSize/stepSize/minQty؛ `minNotional`؛ الرصيد. أي إخفاق ⇒ Abort مبكّر بلا أي إلغاء.
> ⚠️ **Naked Window:** لا `cancelReplace` ذرّي لقوائم OCO؛ بين Cancel و Create لحظة بلا حماية؛ No Blind Retry ⇒ عند فشل Create بعد Cancel ناجح → `FAILED_NEEDS_ATTENTION`.

**ملاحظة قاطعة:** مستند التصميم **لا يحتوي أي مقطع عن «تحويل أمر غير‑OCO (LIMIT/STOP/TRAILING) إلى OCO»** (بحث عن: تحويل، convert، non‑OCO، trailingDelta — بلا نتائج في المستند؛ كلمة «تحويل» تظهر فقط بمعنى «التحويل إلى Live»). ⇒ **المستند الملزِم صامت عن هذه الميزة**، ومصدر المواصفة الوحيد لها هو عيب/مهمة `G1.13` في `PROJECT_STATE.json`.

---

## 3) ملخص الموك‑أب `docs/ui_mockups/`
الملفات: `index.html`, `01_dashboard.html`, `02_open_orders.html`, `03_selected_and_edit.html`, `04_dynamic_monitoring.html`, `05_safe_execution.html` (كلها HTML نصّي، RTL داكن).

- **`02_open_orders.html`:** جدول بأعمدة `# · Order List ID · Symbol · Status · Qty · سعر البيع / TP · Stop Trigger · Limit بعد التفعيل` + زر «↻ تحديث الأوامر» فقط. **لا يوجد زر «تحويل إلى OCO».** صفوف أمثلة OCO (TUTUSDT) أحدها محدَّد «✓ محدد».
- **`03_selected_and_edit.html`:** ٣ أعمدة — (1) الأمر المختار (Order List ID/Symbol/الكمية 🔒/TP/Stop Trigger/Stop Limit)، (2) تعديل يدوي بحقول `TP — سعر الليمِت`, `Stop Trigger`, `Stop Limit` (readonly) + ملاحظة «الأمر الأصلي يبقى فعّالًا حتى تضغط تفعيل» + زر «تفعيل / Activate»، (3) لوحة Live بالسعر الحالي + «أعلى Stop متاح» + زر «Max Available Stop» + Tick Size. **ملاحظة:** الموك‑أب هنا يعرض حقول **بالأسعار** لا بالنِّسب صراحةً، بينما نصّ التصميم 3.4 D يقول «TP %/SL %». **لا زر «تحويل إلى OCO».**
- **`05_safe_execution.html`:** stepper خطوات: التحقق ✓ → إلغاء الأمر المحدد ✓ → جلب أحدث سعر (جارٍ) → إنشاء البديل → تأكيد الأمر الجديد؛ + مفتاح حالات (Connected/Selected/Monitoring/Triggered/Repositioning/Success/Aborted/FAILED_NEEDS_ATTENTION)؛ + مثال فشل `FAILED_NEEDS_ATTENTION — Cancel ✓ · Create ✗`.
- **`index.html`:** بطاقات تنقّل للشاشات الخمس. **لا ذكر لأي زر تحويل.**

**⇒ خلاصة الموك‑أب:** لا يوجد في أي موك‑أب زر «تحويل إلى OCO»؛ شاشة 02 فيها Select/Refresh فقط، وشاشة 05 تعرض نتيجة التنفيذ (verify/cancel/price/create/confirm + naked window + FAILED_NEEDS_ATTENTION).

---

## 4) ما الموجود فعلًا في الكود (الحقيقة على القرص) + الفجوات

**موجود ومربوط:**
- `ocobot/ui/open_orders.py`: زر `ConvertToOco` «تحويل إلى OCO» (مُعطَّل افتراضيًا، يُفعَّل بـ `is_convert_candidate`) + `set_convert_cb` + `set_selector` + `set_on_sell_select` + `set_open_sell_orders` (مسار «كل أوامر البيع» مع شارات نوع عبر `classify_badge`؛ TRAILING عند `trailingDelta>0`) + `_handle_convert_clicked → self._convert_cb(sel)`.
- `ocobot/ui/main_window.py`: يستقبل `convert_cb`، يمرّره لـ `ContentRouter`، ويضبط `oo.set_convert_cb(self._on_convert_requested)` و `oo.set_on_sell_select(self._show_selected)`؛ `_on_convert_requested` → `_convert_cb(selected)` → `_handle_execution_result` → شاشة `05_safe_execution`.
- `ocobot/ui/content.py`: يمرّر `convert_cb` للشاشة 02 إن توفّر.
- `ocobot/app_wiring.py`: `build_convert_executor(client)` + `make_convert_cb(convert_executor, price_provider)` (يجلب السعر الحي D14 عند غياب `reference_price`).
- `ocobot/domain/convert.py`: `ConvertExecutor.convert/build_draft` — يعيد استخدام بوّابة reposition (D16/D17/D9/D19)، إلغاء مستقل `cancel_order` أو OCO `DELETE /api/v3/orderList`، إنشاء `POST /api/v3/orderList/oco`.
- `ocobot/domain/models.py` + `selection.py`: `OpenSellOrder` + `classify_badge` + `select_from_row` ينتج `SelectedOCO` بـ `is_convert_candidate=True` لغير OCO (بلا TP/SL محسوب، الكمية read‑only).
- `ocobot/ui/selected_oco.py` و `ocobot/ui/monitoring.py`: يُعطّلان Activate/Start على مرشّح التحويل ويعرضان «سيُحوَّل إلى OCO — يلزم التحويل أولًا».
- اختبارات: `tests/test_convert_g1_13.py` (7) + `tests/test_convert_cb_g1_13.py` (5) + `tests/test_selection_g1_13.py`.

**الفجوات/المعلّقات التي يجب حسمها عند العودة:**
1. **التوصيل في `ocobot/ui/app.py::main()` ناقص:** لا يُبنى `convert_cb` (لا استدعاء لـ `build_convert_executor`/`make_convert_cb`)، ولا يُمرَّر إلى `build_app`/`MainWindow` (التوقيع يقبل `convert_cb` لكن `app.py` لا يمرّره)، ولا تُستدعى `set_open_sell_orders`/`set_selector` على شاشة 02 (شاشة 02 ما زالت تُغذّى بـ `OcoReader.list_open_ocos()` = OCO فقط، لا بـ `read_all_open_sell_orders`). ⇒ **زر التحويل لن يظهر/يعمل في التشغيل الحقيقي حتى يُستكمل هذا التوصيل.**
2. **مصدر TP%/SL% لمسار التحويل غير مربوط بالواجهة:** `_handle_convert_clicked` ينادي `self._convert_cb(sel)` بوسيط واحد فقط، بينما `convert_cb` يتوقّع `(source, tp_pct, sl_pct, reference_price=None, ...)`. ⇒ **يلزم قرار UX:** أين يُدخل المستخدم %TP/%SL للتحويل (على 02 بجوار الزر، أو تمرير الاختيار إلى 03 ثم التحويل من هناك). السعر المرجعي محسوم = السعر الحي D14 (`price_provider`).
3. **تناقض بسيط بين الموك‑أب والتصميم على شاشة 03:** الموك‑أب يعرض حقول بالأسعار؛ النصّ 3.4 D يقول «TP %/SL %». (الكود يتبع النِّسب: `SelectedTpPctEdit`/`SelectedSlPctEdit`.)
4. تغذية `orderListId` الجديد للمراقبة الديناميكية (T4/T13) بعد نجاح التحويل.

---

## 5) خطوات الاستئناف المقترحة (عند العودة — قراءة فقط حتى الآن)
1. حسم UX مصدر %TP/%SL لمسار التحويل (02 أم 03) — بما يحترم D6/D7/D14.
2. استكمال `ocobot/ui/app.py::main()`: بناء `convert_cb` (`build_convert_executor` + `make_convert_cb`) وتمريره لـ `build_app/MainWindow`؛ تغذية شاشة 02 بـ `read_all_open_sell_orders` + `set_selector` + `set_open_sell_orders` بدل `list_open_ocos` فقط.
3. تمرير `tp_pct/sl_pct` فعليًا من حقول الإدخال إلى `convert_cb`.
4. ربط `orderListId` الجديد بالمراقبة الديناميكية.
5. تشغيل كامل المجموعة (كان 316 OK) + إضافة اختبارات انحدار للواجهة، مع الحفاظ على التخطيط 1360x768 @125% وقفل Testnet.

> ملفات مرجعية رئيسية: `docs/OCOBot_Design_AR.md` (ملزِم، صامت عن التحويل) · `PROJECT_STATE.json` (عيب/قرارات G1.13 + D6/D7/D14/D-G1.13-refprice) · `WORKING_MEMORY.json` (resume_point=convert_cb_wired) · `ocobot/ui/open_orders.py` · `ocobot/ui/main_window.py` · `ocobot/app_wiring.py` · `ocobot/domain/convert.py` · `ocobot/ui/app.py`.
