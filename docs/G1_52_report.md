# تقرير G1.52 — التقاط أي أمر بيع منفَّذ (OCO أو مستقل) ونسبته للصفقة في نموذج الصفقات المنتهية

- **المعرّف:** G1.52 · **الخطورة:** major · **الطور:** G1_MANUAL_TESTING (§10)
- **بوّابة بشرية:** `human_gate=false` — لا Live/T16 قبل بوّابة G1 (§10.5)
- **الدليل:** split-per-file: `TOTAL ran=739 failures=0 errors=0 files=104 status=OK` (خط الأساس 727 + 12 اختبارًا جديدًا)

## 1) المشكلة (root-cause)
- `build_fill_recorder` كان يكتب `trade_closed_fill` لأي `executionReport/FILLED` دون تمييز الجانب، ويأخذ `order_list_id` من `g` فقط. الأوامر المستقلّة (LIMIT/MARKET/STOP SELL خارج OCO) تحمل `g=-1`.
- لم يكن هناك `order_id`/`client_order_id` في السجلّ لمطابقة أدقّ.
- `exit_source` للوسائل الثلاث (قوس السعر/شبكة الأمان/حارس BTC) كان يُسجَّل عبر `MonitoringEngine.note_exit_source` فقط، وقائمته **لا تضمّ `MANUAL_EXIT`** — فالخروج اليدوي بلا نسبة.

## 2) تصحيح افتراض العقد (الحقيقة على القرص §9.4)
خلافًا لصياغة العقد:
- **`UserDataStreamConsumer` غير مُنشأ في الإنتاج** (grep: الإنشاء في الاختبارات فقط). فـ«نقطة التجميع» حيث *ينبغي* الربط ⇒ وُفِّر مُساعِد تكامل opt-in (chunk_4) جاهز للحقن مع الحفاظ على أيّ معالِج سابق.
- **`note_exit_source` يكتب أصلًا إلى سجلّ التدقيق** عبر `self._record` (مع `audit=_audit` في الإنتاج) منذ G1.46 — فالوسائل الثلاث تُسجَّل بالفعل؛ سبب «0 في السجلّ» هو عدم حدوث خروج بعد (تاريخ Testnet فارغ)، لا فجوة ربط. الفجوة الفعلية في `exit_source` هي **`MANUAL_EXIT` فقط** (مرفوض في قائمة `note_exit_source` خارج النطاق) ⇒ عولج بتسجيل مباشر للتدقيق.

(سُجِّل القرار `g1_52_consumer_not_wired` في `state/decisions_log.json`.)

## 3) ما نُفِّذ (داخل scope_boundary فقط، بلا لمس hot_path/تسعير/Live)

**chunk_2 — `ocobot/domain/completed_trades.py`:**
- `build_fill_recorder`: يسجّل `trade_closed_fill` فقط عند `e==executionReport ∧ X==FILLED ∧ S==SELL` (تعبئات الدخول BUY ليست إغلاقًا)، **بلا تصفية بـ `g`** فالأوامر المستقلّة (`g=-1`) تُلتقط. أُضيف للحقول `order_id` (i) و`client_order_id` (c).
- `build_completed_trades`: اشتقاق الخروج يفضّل آخر تعبئة جانبها `SELL` (مع تراجع خلفي لآخر `trade_closed_fill`) — فتُقبل التعبئة المستقلّة داخل المقطع. النسب بعضوية المقطع لا بـ `order_list_id` (توافق OCO محفوظ).
- `_EXIT_SOURCE_ALLOWED`: أُضيف `MANUAL_EXIT`.
- `make_exit_source_recorder(audit_log)`: مُسجِّل `exit_source` موحّد محروس (للمصادر المسموح بها فقط؛ بلا أثر عند `audit=None`).

**chunk_3 — إصدار `exit_source` (opt-in، default None ⇒ لا انحدار):**
- `ocobot/ui/manual_exit.py`: `exit_source_noter` في `run_manual_market_exit` و`build_manual_exit_fn`؛ يُصدر `MANUAL_EXIT` لحظة الإطلاق الفعلي (`dry_run=False`) وقبل المنفّذ، ولا يُصدر في المعاينة.
- `ocobot/domain/guardian_supervisor.py`: `exit_source_sink` (opt-in) يُصدر `POSITION_SAFETY_NET`/`BTC_FOLLOW` بجوار `note_exit_source` القائم — جسر موحّد للتدقيق متاح.
- `ocobot/ui/bracket_wiring.py`: يملك `exit_source_noter("PRICE_BRACKET")` منذ G1.46 (دون تغيير).
- **الربط الحيّ** `ocobot/ui/app.py`: مرّر `exit_source_noter=make_exit_source_recorder(_audit)` لمحوّل الخروج اليدوي ⇒ يُسجَّل `MANUAL_EXIT` في نفس سجلّ التدقيق فيلتقطه `_derive_exit_source`.

**chunk_4 — `ocobot/app_wiring.py`:**
- `make_fill_recorder_order_event(audit, prior_on_order_event=None)`: يبني `on_order_event` جاهزًا لحقنه في `UserDataStreamConsumer` (يلتقط تعبئة البيع ويحفظ المعالِج السابق). تكامل opt-in بحت.

## 4) الاختبارات (chunk_1 + chunk_3 + chunk_4) — 12 اختبارًا جديدًا
- `tests/test_g1_52_capture_independent_sell.py` (3): تعبئة SELL مستقلّة (g=-1) تُسجَّل مع `order_id`/`client_order_id`؛ تعبئة BUY لا تُسجَّل؛ النسب end-to-end تعطي `exit_price` وربحًا متاحًا.
- `tests/test_g1_52_exit_source.py` (6): `make_exit_source_recorder` (صالح/غير معروف/None)؛ `MANUAL_EXIT` يُصدر حيًّا ولا يُصدر في dry_run؛ `POSITION_SAFETY_NET` عبر sink الحارس.
- `tests/test_g1_52_fill_recorder_wiring.py` (3): مُساعِد الربط يسجّل تعبئة البيع ويحفظ المعالِج السابق؛ `prior=None` سليم.
- تحديث `tests/test_completed_trades_capture.py` ليعكس الحقلين الجديدين `order_id`/`client_order_id` (الاختبار القائم كان يؤكّد تطابق القاموس حرفيًّا).

## 5) التحقّق (acceptance_checks)
- أي بيع منفَّذ (OCO أو مستقل) يُنتج `trade_closed_fill` ويُنسب ✓ (chunk_2 + chunk_1).
- `exit_price`/profit متاح للخروج غير-OCO ✓ (chunk_1 end-to-end).
- `exit_source` صحيح لكل وسيلة ✓ (3 وسائل عبر `note_exit_source` القائم + `MANUAL_EXIT` حيّ عبر `make_exit_source_recorder`؛ مُختبَر).
- توافق OCO القديم محفوظ (لا انحدار) ✓ (السويت 739 أخضر؛ لا تغيير سلوك عند القيم الافتراضية).
- لا لمس hot_path ✓ (كل الإضافات opt-in محروسة خارج مسار التنفيذ/التسعير؛ `monitoring.py` لم يُمَس).
- §1.5 ثنائية اللغة ✓ (لا نصّ واجهة جديد — القيم enum/سجلّ؛ `test_g1_41_i18n_no_leak` ضمن الأخضر).
- كامل السويت أخضر ≥ baseline(727) ✓ (739).

## 6) ملاحظة تسليم (§9.1–9.4)
فُوِّض تنفيذ chunk_1..chunk_4 لعملية فرعية أعادت ردًّا فارغًا؛ أثبت القرص أنها نفّذت chunk_2 فقط (وكسرت اختبارًا قائمًا). طُبّق §9.2(ج)/§9.4: عُدّت العملية «جزئية»، وأُكمل الباقي مباشرةً بلا تفويض، مع التحقّق من القرص وإصلاح الانحدار.

## 7) التنظيف والختم (§1.3/§11.3/§11.6)
نُقلت ملفات الخرج المؤقّتة إلى `_archive` مع قيود في `_archive/manifest.json`؛ الختم عبر `tools/rotate_state.py apply` (نسخة احتياطية + تدوير بارد + بصمات + verify). `tools/_run_suite_per_file.py` أداة محلية قابلة لإعادة الاستخدام تبقى في `tools/`.

## 8) الخلاصة
`G1.52 = sealed`. البندان `G1.53` (مُجمِّع ربحية + telemetry) و`G1.54` (لوحة ربحية في شاشة 08) يبقيان `contracted` ويعتمدان على G1.52. لا بنود `critical/major` غير مختومة ناتجة عن هذه المهمة.
