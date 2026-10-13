# تقرير G1.46 — بطاقة نتيجة الصفقة أسفل الوسيلة المنفِّذة

## الخلاصة
إضافة **عرض فقط**: بطاقة «نتيجة الصفقة» تظهر أسفل بطاقة الوسيلة التي نفّذت الخروج،
مُسنِدةً كل صفقة مُغلقة لإحدى الوسائل الأربع عبر `exit_source` مشتقّ في نموذج القراءة
`completed_trades` (فوق سجلّ التدقيق، دون المساس به). لا تغيير لأي منطق تداول/مستويات/تنفيذ،
ولا أي Live. ثنائية اللغة §1.5 دون تسرّب.

## عقد الإسناد (exit_source)
- enum: `MONITORING | PRICE_BRACKET | BTC_FOLLOW | POSITION_SAFETY_NET`.
- العلامة حدث تدقيق إضافي بحت: `event = "exit_source"`, `details = {"source": "<ENUM>"}`،
  تُكتب **داخل** مقطع الصفقة (`monitor_start → monitor_closed`) قبل الإغلاق مباشرةً.
- الاشتقاق في `completed_trades.build_completed_trades`: آخر علامة `exit_source` داخل المقطع
  تفوز؛ غياب العلامة أو قيمة غير معروفة ⇒ `MONITORING` (توافق خلفي مع السجلّات القديمة).
  الصفقة المفتوحة (LIVE) ⇒ `exit_source = ""`.

## مواضع إصدار العلامة في الإنتاج (إضافية ومحروسة)
- `MonitoringEngine.note_exit_source(source)` (طريقة إضافية؛ تستعمل `self._record` القائم؛
  لا تغيير لأي إصدار قائم).
- `GuardianSupervisor._intervene`: `note_exit_source("POSITION_SAFETY_NET")` قبل `kill_switch()`.
- `GuardianSupervisor._btc_tick`: `note_exit_source("BTC_FOLLOW")` قبل منفّذ خروج حارس BTC.
- `BracketExitWiring._exit`: `exit_source_noter("PRICE_BRACKET")` قبل `execute_market_exit`
  (مُطلِق اختياري مُحقَن من `ocobot/ui/app.py` ⇐ `engine.note_exit_source`).
- `MONITORING` هو الافتراضي (مسار TP/SL الأصلي بلا علامة).

## الواجهة (عرض فقط)
- عنصر جديد `ocobot/ui/deal_result_card.py` (`DealResultCard`): يعرض الدخول = `reference_price`
  (سعر بدء المراقبة) · الخروج = `exit_price` · الجانب = `side` · الربح/الخسارة = `profit_pct`٪
  و`profit_usd`. مخفيّ حتى تتوفّر نتيجة.
- تُركّب بطاقة أسفل كل بطاقة وسيلة في `ocobot/ui/monitoring.py` (المراقبة/شبكة أمان المركز/
  حارس هبوط BTC/قوس الخروج)، وتُغذّى عبر `DynamicMonitoringScreen.set_deal_results(trades)`
  التي تختار أحدث صفقة مُغلقة لكل وسيلة.

## §1.5 ثنائية اللغة
أُضيفت في `ocobot/ui/i18n.py::AR_TO_EN`: «نتيجة الصفقة»=Deal Result · «الدخول»=Entry ·
«الخروج»=Exit · «الجانب»=Side · «الربح/الخسارة»=Profit/Loss. التبديل EN↔AR تحقّق باختبار
`test_bilingual_en_no_arabic_leak` (صفر تسرّب) و`test_bilingual_toggle_back_to_arabic`.

## الملفّات المتأثرة
- `ocobot/domain/completed_trades.py` (حقل `exit_source` + `_derive_exit_source` + `_EXIT_SOURCE_ALLOWED`)
- `ocobot/domain/monitoring.py` (`note_exit_source` إضافية)
- `ocobot/domain/guardian_supervisor.py` (وسم الحارسَين)
- `ocobot/ui/bracket_wiring.py` + `ocobot/ui/app.py` (وسم قوس الخروج)
- `ocobot/ui/deal_result_card.py` (جديد)، `ocobot/ui/monitoring.py` (تركيب + `set_deal_results`)
- `ocobot/ui/i18n.py` (§1.5)
- `tests/test_g1_46_exit_source_attribution.py` (جديد)، `tests/test_g1_46_deal_result_card_ui.py` (جديد)

## الدليل (acceptance_checks)
الأمر: `python -m unittest discover -s tests -t .`

```
Ran 646 tests in 633.140s

OK
```

- كامل السويت أخضر: **646 اختبارًا، OK** (خط الأساس عند G1.45 كان 632 ⇐ +14 جديدة).
- إسناد الوسائل الأربع بمحاكاة سجلّ تدقيق JSONL: `tests/test_g1_46_exit_source_attribution.py`
  (9 اختبارات: الافتراضي MONITORING، PRICE_BRACKET، BTC_FOLLOW، POSITION_SAFETY_NET،
  آخر علامة تفوز، قيمة غير معروفة ⇒ MONITORING، توافق خلفي، صفقة LIVE، عزل المقاطع) — ok.
- واجهة §1.5: `tests/test_g1_46_deal_result_card_ui.py` (5 اختبارات: إظهار/إخفاء، التعبئة،
  ربح غير متاح، EN بلا تسرّب عربي، العودة إلى AR) — ok.
- لا كسر لنموذج القراءة القائم ولا تغيير لمنطق التنفيذ (كل التغييرات إضافية ومحروسة).
