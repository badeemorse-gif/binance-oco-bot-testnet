# تقرير G1.49 — سياسة تنفيذ خروج موحّدة مضادّة للتعليق ومحدِّدة للانزلاق + إصلاح لمس القوس الكاذب

**الحالة:** sealed · **الخطورة:** major · **البروتوكول:** 1.5 · **الطور:** G1_MANUAL_TESTING
**النطاق:** Testnet فقط — لا Live/T16 قبل اجتياز بوّابة G1 بعبارة الاعتماد الصريحة (§10.5).

## المشكلة (من التجربة اليدوية)
1. قوس الخروج كتب «تم ملامسة الحد العلوي» والسعر الحيّ لا يزال ~0.8% تحت الحد (لمس قوس كاذب على wick لحظي).
2. أمر البيع الناتج كان ~1% فوق السعر الحيّ ⇒ خطر تعليق (الأمر يرقد فوق السوق بدل التنفيذ).

## السبب الجذري (قراءة القرص)
- `BracketMonitor.check` كان يطلق على tick/wick لحظي عند الحد ثم يُسعِّر الخروج على ذلك السعر القديم.
- التسعير العلوي كان LIMIT بإزاحة 0.1% فقط تحت المرجع ⇒ يبقى أعلى من السوق المستقرّ بعد الارتداد فيعلّق.

## الحل — سياسة تنفيذ خروج موحّدة (Unified Exit-Execution Policy)
الهدف المعتمد من المستخدم: **عدم التعليق** + **الخروج بأقرب نقطة سعرية** في الطوارئ لا بنقطة بعيدة.
الآلية: ترسية على أفضل BID حيّ لحظة الإطلاق + band عبور محكوم + `LIMIT IOC` + chase نازل لحد أرضية صارمة + ملاذ أخير (ب) `MARKET` محمي بالأرضية + wick-debounce يمنع اللمس الكاذب.

## التنفيذ بالأجزاء
- **chunk_1 — التشخيص:** `docs/G1_49_diagnosis.md` + اختبار انحدار `tests/test_g1_49_bracket_wick.py` (يحاكي wick الكاذب).
- **chunk_2 — المنطق الخالص:** `ocobot/domain/market_exit.py`: `marketable_sell_price` / `flash_crash_floor` / `plan_chase_ladder` / `compute_slippage_pct` / `ExitExecutionPolicy` + `tests/test_g1_49_exit_policy.py`.
- **chunk_3 — القوس:** `ocobot/domain/bracket.py`: wick-debounce (تِكّتان متتاليتان أو نافذة `debounce_ms` عبر clock محقون) + حالة ARMED + ترسية الخروج على `bid_getter` حيّ لحظة الإطلاق.
- **chunk_4 — الربط + الإزاحة + لا-تعارض:**
  - `ocobot/core/market_exit_broker.py`: `place_limit_sell_ioc` (timeInForce=IOC).
  - `ocobot/domain/market_exit.py`: `execute_exit_chase` (أمان: kill_switch→cancel_oco→RECONCILE→eff_qty=min(target,free)؛ chase نازل IOC بإعادة قراءة BID حيّ؛ أرضية مثبّتة؛ ملاذ MARKET محمي) + إضافة `stop_limit_offset_pct` للخروج السفلي في `plan_market_exit`/`execute_market_exit`.
  - `ocobot/ui/manual_exit.py`: ربط `execute_exit_chase` كمسار موحّد opt-in عبر `bid_getter` (fallback `execute_market_exit` عند غيابه ⇒ لا انحدار).
  - `ocobot/domain/guardian_exec.py`: `plan_protective_stop`/`place_protective_stop` + `stop_limit_offset_pct` و`price_floor_pct` (None ⇒ سلوك قديم مطابق) لجعل STOP_LOSS_LIMIT للحارس marketable مع أرضية.
  - `ocobot/domain/guardian_supervisor.py`: تمرير الإزاحة/الأرضية إلى `_intervene` (الحارس + المسار المشترك).
  - `tests/test_g1_49_no_conflict.py` (11) — بيع واحد وأولوية صحيحة بلا بيع مزدوج.
- **chunk_5 — بارامترات الواجهة + §1.5:** `ocobot/ui/monitoring.py`: قسم «سياسة تنفيذ الخروج الموحّدة» (5 حقول) + `exit_policy_values()`/`exit_execution_policy()` (عرض/ضبط فقط). `ocobot/ui/i18n.py`: 6 مفاتيح ثنائية اللغة. `tests/test_g1_49_ui_params.py` (6).

## ضمانات لا-التعارض (بنيوية)
مسار خروج واحد مسلسل + منع بيع مزدوج (RECONCILE + has_resting_protective_sell + eff_qty=min(target,free)) + latch/idempotent + تحكيم أولوية (يدوي فوق الكل) + kill_switch يوقف المراقبة قبل الوضع. كل الجديد اختياري (default None/opt-in) ⇒ لا تغيير سلوكي للمسارات القائمة.

## الحدود (scope)
داخل: `market_exit.py`, `guardian_exec.py`, `bracket.py`, `bracket_wiring.py`, `manual_exit.py`, `guardian_supervisor.py`, `monitoring.py` (UI params), `i18n.py`, `market_exit_broker.py` (core — وُسّع النطاق بإذن المستخدم). خارج: hot_path (`on_price_tick`/`MonitoringEngine.start`/`SafeExecutor.execute`/`reposition`/`create_oco`) وأي مختوم؛ لا Live.

## الدليل (acceptance)
تحقّق split-per-file (يتجاوز انهيار إغلاق Qt البيئي): **99 ملف اختبار · 717 اختبار · 0 فشل · 0 خطأ · 0 مفقود** (≥ baseline 672).
فحوص القبول مستوفاة: wick-debounce يمنع اللمس الكاذب · الخروج العلوي يُرسى على bid حيّ ضمن band ولا يرقد فوق السوق · chase→floor→ملاذ MARKET محمي · لا-تعارض (الوسائل + اليدوي ⇒ بيع واحد وأولوية صحيحة) · §1.5 ثنائية اللغة بلا تسرّب عربي في EN بعد retranslate · بلا لمس hot_path · لا Live.
