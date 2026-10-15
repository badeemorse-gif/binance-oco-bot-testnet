# تقرير G1.62 — تغطية تنبيهات Telegram الكاملة لدورة المراقبة

## المشكلة (كما أبلغ المستخدم أثناء التجربة اليدوية)
عند تشغيل المراقبة تصل رسالة البدء الصحيحة، لكن **لا تصل** رسائل عند: تدخّل أيٍّ من
الأنظمة الأربعة، أو الخروج/البيع (ربح/خسارة)، أو الإيقاف اليدوي. والمطلوب أيضًا أن
تتضمّن الرسائل النِّسب العاملة حاليًا (تموضع/ربح/لمت).

## السبب الجذري (بالفحص)
1. **قوس الخروج بالسعر (PRICE_BRACKET) صامت:** يُنشأ في `ocobot/ui/app.py` عبر
   `BracketExitWiring` **دون** تمرير `notifier=` ⇒ `execute_market_exit(notifier=None)`
   ⇒ لا تنبيه عند تدخّله. والدالة `make_market_exit_notifier` معرّفة في
   `ocobot/alerts/bridge.py` لكنها كانت مستعملة في الاختبارات فقط.
2. **لا رسالة عند الإغلاق/الخروج:** جسر التدقيق `AlertsAuditBridge` يقتصر على
   `_ALERT_EVENTS = {monitor_start, repositioned}`؛ وحدث الإغلاق `monitor_closed`
   (المكتوب في `ocobot/domain/monitoring.py` مع `end_reason`/`exit_source`) مُهمَل ⇒
   لا رسالة عند إتمام الخروج/البيع أو عند الإيقاف اليدوي/Kill/الانقطاع.

## الحل
- **`ocobot/ui/app.py`:** تمرير `notifier=make_market_exit_notifier(...)` عبر
  `_LazyNotifierShim`/`_LazyStoreShim` إلى `BracketExitWiring` (مرآة لربط الخروج
  اليدوي في G1.57) ⇒ القوس يرسل رسالته الثريّة 🧷 عند PLACED.
- **`ocobot/alerts/bridge.py`:** إضافة `"monitor_closed"` إلى `_ALERT_EVENTS` +
  توسيع `_enrich` لإثراء سجلّ `monitor_closed` بسياق آخر `monitor_start`
  (الرمز/المرجع/trigger/TP/SL).
- **`ocobot/alerts/formatting.py`:** دالة `build_monitor_closed_message` (🏁) تعرض
  الرمز وسبب الإغلاق (Take Profit / Stop Loss / Stopped manually / disconnect) ونتيجة
  الصفقة% (‪+tp‬ عند TP، ‪-sl‬ عند SL) والنِّسب العاملة (Activation/TP/SL) وسعر المرجع
  + توجيهها في `format_event` + تصديرها في `__all__`.

## الدلالة بعد الإصلاح
- **كل تدخّل** من الأنظمة الأربعة يرسل رسالته الثريّة: الحارس 🛡️ وحارس هبوط BTC ⬇️
  والخروج اليدوي ✋ (كانت موصولة في G1.57) + **قوس الخروج 🧷 (أُصلح الآن)**.
- **كل إغلاق** للصفقة يرسل 🏁 بالسبب والنتيجة: بيع TP/SL (ربح/خسارة%) أو إيقاف يدوي
  (بالسبب) أو انقطاع — أيًّا كانت الوسيلة.
- **النِّسب:** رسائل البدء/التموضع/الإغلاق تحمل trigger/TP/SL كنسب؛ ورسائل التدخّل
  تحمل Entry/Exit/PnL% الفعلية.
- رسالتا `monitor_start`/`repositioned` بلا تغيير (لا انحدار)، ولا مساس بالمسار الحار.

## الملفات المتأثّرة
- `ocobot/alerts/bridge.py`
- `ocobot/alerts/formatting.py`
- `ocobot/ui/app.py`
- `tests/test_g1_62_alert_coverage.py` (جديد — 9 اختبارات)

## معايير القبول
- `monitor_closed` ضمن `_ALERT_EVENTS` ويُثرى من `monitor_start` ويُرسَل عبر `poll_once`. ✓
- `build_monitor_closed_message`: TP/SL (نتيجة%) + إيقاف يدوي (بالسبب، بلا نتيجة). ✓
- `app.py` يمرّر `notifier` إلى قوس الخروج (حارس انحدار على مستوى المصدر). ✓
- رسالتا البدء/التموضع بلا انحدار؛ المُطلِقات الثلاثة الأخرى سليمة. ✓

## الدليل
`python tools/_run_suite_per_file.py` ⇒ `TOTAL ran=989 failures=0 errors=0 files=125 status=OK`
(منها `test_g1_62_alert_coverage = 9`). §1.5: رسائل تليجرام إنجليزية — لا نصّ Qt عربي جديد.
