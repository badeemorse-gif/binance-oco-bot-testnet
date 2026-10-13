# تقرير الإنجاز — G1.45: لوحات التتبّع اللحظي للنِّسب داخل المراقبة الديناميكية

**الحالة:** sealed · **الطور:** G1_MANUAL_TESTING · **الخطورة:** major
**مسار الدليل:** هذا الملف · **عدد الاختبارات:** 632 (أخضر، صفر فشل/خطأ)

## 1) الهدف
عنصر عرض واحد قابل لإعادة الاستخدام `PercentTracker` (عرض فقط) يعرض: سعر حيّ · سعر
سابق · نسبة التغيّر · نسبة التتبّع — بقواعد لون موحّدة (أخضر صعود / أحمر هبوط /
محايد) وصيغة `0.00000%`. نسختان داخل المراقبة الديناميكية:
- **(ب) BTC** داخل بطاقة «حارس هبوط BTC»: تُغذّى من لقطة `BtcFollowSupervisor`
  (سعر حيّ / سابق + نافذة تتبّع ~5s).
- **(ج) العملة المراقَبة**: النسبتان محسوبتان من **سعر بدء المراقبة المثبّت**
  `reference_price` (ثابت عبر إعادة التموضع) — لا تغيّر لحظي عن السابقة.

## 2) قرار نموذج التغذية (RECOVER)
عند الاستئناف كان `resume_point = chunk_2_awaiting_btc_feed_decision`. اعتمد
المستخدم «قرّر أنت وامضِ» + الخيار **(أ)**:
- **(أ)** وصل مصدر سعر `BTCUSDT` حيّ **مستقلّ عن وضع الحارس** (Off/Observe/Live)،
  يُسحب على نبض المراقبة القائم **خارج خيط الواجهة**، fail-safe، قراءة فقط على
  Testnet (لا Live). النتيجة: أرقام BTC تظهر دائمًا أثناء المراقبة حتى والحارس OFF.
- **توسيع نطاق (§6.3، رجعي منخفض الخطر):** أُضيف إلى `scope_boundary.in` كلٌّ من
  `ocobot/app_wiring.py` و`ocobot/ui/app.py` (حقن الموفّر)، و accessor للقراءة فقط
  `price_snapshot` في `ocobot/domain/btc_follow_supervisor.py`. مسجَّل في
  `decisions_session`.

## 3) ما نُفِّذ (الأجزاء)
- **chunk_1 (سابق):** `ocobot/ui/percent_tracker.py` — دوال خالصة + ودجت
  `PercentTracker` + 4 مفاتيح i18n + اختبار (13/13).
- **chunk_2:** مصدر سعر `BTCUSDT` حيّ:
  - `ocobot/app_wiring.py`: `BtcPriceProvider` (رمز ثابت `BTCUSDT`، بناء تغذية كسول،
    fail-safe، يعيد `None` عند أي خطأ).
  - `ocobot/ui/app.py`: حقن `BtcPriceProvider` في شاشة المراقبة في مساري الربط
    (الإقلاع + ما بعد الاتصال الكسول)، محروس، الشبكة داخل الموفّر فقط.
  - `ocobot/domain/btc_follow_supervisor.py`: `price_snapshot(now, window_seconds)`
    (قراءة فقط؛ تُعيد `(last, prev, window_start)`؛ لا ترمي).
  - `ocobot/ui/monitoring.py`: مُشرِف عرض `BtcFollowSupervisor` داخلي (نافذة 5s)،
    `set_btc_price_provider`، سحب سعر BTC وتغذيته داخل نبض `_work` (خارج خيط الواجهة)
    وأخذ لقطة، وعرضها عبر `_refresh_btc_tracker`. ودجت `PercentTracker` داخل بطاقة
    حارس هبوط BTC. مستقلّ تمامًا عن وضع الحارس.
- **chunk_3:** `ocobot/ui/monitoring.py`: بطاقة «تتبّع العملة المراقَبة» + ودجت
  `PercentTracker`؛ `_refresh_monitored_tracker` يجمّد `reference_price` من
  `engine.state.reference_price` **مرّة واحدة** ويحسب النسبتين منه (ثابت عبر إعادة
  التموضع)؛ إعادة التجميد عند `set_selected`/الإيقاف الطارئ.
- **chunk_4:** مفتاح i18n `«تتبّع العملة المراقَبة» → "Monitored Coin Tracking"`؛
  تغطية `retranslate` قائمة (QLabel + `PercentTracker.retranslate_i18n`)؛ سويت
  أخضر؛ ختم وأرشفة.

## 4) التحقّق (الدليل)
- **البيئة:** Python 3.12.10، `QT_QPA_PLATFORM=offscreen`.
- **ملاحظة تشغيلية:** تشغيل `python -m unittest discover` في عملية واحدة يبطؤ
  تربيعيًّا بسبب تراكم ودجت Qt عبر اختبارات الواجهة (وهو سبب بقاء تشغيل خلفي سابق
  نشطًا ~ساعتين). لذا شُغِّلت **نفس المجموعة كاملةً** عبر مُشغّل لكل وحدة في عملية
  مستقلّة (`QApplication` طازج لكل وحدة) — `tools/_g1_45_run_by_module.py` — فتُنفَّذ
  الاختبارات ذاتها بسرعة وبعزل أنظف. الحقيقة على القرص (§9.4) والكفاءة (§11.2).
- **النتيجة:** `MODULES=89  TOTAL_TESTS=632  FAILED=0  ERROR=0  RESULT=GREEN`
  (الدليل الخام: `_g1_45_bymodule_run.txt`). منها الجديد:
  `tests/test_g1_45_percent_tracker` (13) و`tests/test_g1_45_trackers` (14).
- العدّ ≥ 605 المطلوب (605 أساس G1.44 + 13 + 14 = 632).

## 5) تحقّق acceptance_checks
- [x] `PercentTracker` قابل لإعادة الاستخدام (سعر حيّ/سابق/Δ%/تتبّع%؛ لون موحّد؛
      صيغة `0.00000%`).
- [x] نسخة BTC من لقطة `BtcFollowSupervisor` (نافذة ~5s).
- [x] نسخة العملة المراقَبة من `reference_price` المثبّت، ثابت عبر إعادة التموضع
      (اختبار `test_monitored_anchor_frozen_across_reposition`).
- [x] عرض فقط بلا شبكة في طبقة الواجهة (`tests/test_ui_no_direct_network` أخضر).
- [x] §1.5 ثنائية اللغة: مفتاح إنجليزي خالٍ من العربية + تغطية retranslate.
- [x] كامل السويت أخضر (632) دون كسر أي نقطة نجاح قائمة.

## 6) التنظيف/الأرشفة (§11.3)
نُقلت الملفات المؤقتة لهذه المهمة ومخلّفات المهام المختومة السابقة إلى `_archive`
مع تحديث `_archive/manifest.json` عبر `tools/rotate_state.py`.
