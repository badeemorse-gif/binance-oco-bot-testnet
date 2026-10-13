# تقرير دليل الختم — G1.44: حارس هبوط BTC الدفاعي (BTC-follow)

- **task_id:** G1.44
- **severity:** major
- **protocol_version:** 1.5
- **phase:** G1_MANUAL_TESTING
- **status:** sealed
- **evidence_path:** `docs/G1_44_btc_follow_report.md`

## 1) الملخّص
حارس ثالث معزول داخل فرع «المراقبة الديناميكية» يرصد انحدار BTC المؤكّد (rate-of-change ضمن نافذة ثوانٍ مع debounce) ويحمي العملة المراقَبة دفاعيًا عبر **تضييق ستوب واقٍ** (لا بيع ماركت عارٍ، ولا شورت/هيدج). يعمل بجانب (شبكة أمان المركز) و(قوس الخروج بالسعر) دون التأثير عليهما، بتحكيم **«الأقرب يفوز»**، ومفتاح مستقلّ **Off/Observe/Live** الافتراضي فيه **OFF**.

## 2) الأجزاء الأربعة (كلّها DONE+VERIFIED)
- **chunk_1 — منطق خالص:** `ocobot/domain/btc_follow.py` (آلة الحالة `IDLE→ARMED→TIGHTEN/IDLE`، `drop_pct`/`window_seconds`/`confirm_seconds`، stdlib فقط بلا I/O).
- **chunk_2 — تحكيم وتغذية معزولة:** `ocobot/domain/btc_follow_supervisor.py` + دمج التحكيم في `GuardianSupervisor.tick`؛ fail-safe: فقد تغذية BTC = لا فعل ولا إسقاط للمراقبة.
- **chunk_3 — مسار التنفيذ:** تضييق الستوب الواقي بإعادة استخدام القيدين البنيويين لمنع البيع المزدوج (`has_resting_protective_sell` + `protective_qty = min(free_base_qty, monitored_qty)`) و cancel-replace أحادي الاتجاه عبر مسار `market_exit` المُختبَر.
- **chunk_4 — الواجهة والربط (المُستأنَف في هذا الدور):** مُبدِّل `Off/Observe/Live` مستقلّ + مؤشّر `BtcFollowIndicator` في `ocobot/ui/monitoring.py`؛ i18n ثنائي اللغة في `ocobot/ui/i18n.py`؛ طبقة التنبيهات؛ وربط `btc_exit_fn` الحقيقي عبر `execute_market_exit` في `ocobot/ui/guardian_arm.py`/`ocobot/ui/btc_follow_wiring.py`.

## 3) التحكيم والعزل والـ no-cancel invariant
- **الأولوية:** (1) شبكة أمان المركز (مركز عارٍ/`FAILED_NEEDS_ATTENTION` لا يُسبَق) ثم (2) حارس هبوط BTC ثم (3) قوس الخروج بالسعر.
- **الأقرب يفوز:** `MAX` على سعر ستوب `SELL` أحادي الاتجاه بلا تذبذب.
- **العزل:** BTC مُدخَل خارجي للقراءة فقط؛ الفعل والقيود على عملة المراقبة النشطة وحدها.
- **no-cancel invariant:** منفّذ الستوب الواقي لا يُلغي أبدًا؛ فعل `TIGHTEN` يمرّ عبر `btc_exit_fn` المحقونة (مسار `market_exit` المُختبَر).
- **fail-safe + الافتراضي OFF:** بغياب `btc_follow` لا أثر إطلاقًا؛ `dry_run` (Observe) ⇒ تنبيه اقتراح تضييق دون تنفيذ.

## 4) القاعدة ثنائية اللغة (§1.5)
- أُضيفت لكلّ نصّ عربي جديد مفاتيحه في `AR_TO_EN` بقيمة إنجليزية خالية من العربية: `حارس هبوط BTC`→`BTC Drop Guard`، `وضع حارس BTC`→`BTC Guard Mode`، حالات المؤشّر (`حارس BTC: مطفأ/نائم (يراقب)/رصد هبوط…/تدخّل ✓/—`)، بادئة التنبيه `حارس هبوط BTC على `، ونصوص التنبيهات الثلاثة (تنفيذ/Observe/تعذّر).
- `retranslate_widget_tree` تغطّي `QComboBox` (مُبدِّل الوضع) و`QListWidget` إضافةً إلى الودجت القائمة، وتستدعي الخطّاف `retranslate_i18n` لعنصر المؤشّر.
- يفرض ذلك اختبار `tests/test_g1_44_chunk4_i18n.py`: كلّ نصّ جديد له مدخل، ولا حرف عربي في ترجمته، وكلّ قيم `_BTC_STATE_TEXT` مغطّاة — فلا تسرّب عند التبديل EN↔AR.

## 5) الدليل (acceptance_checks)
- **الأمر:** `python -m unittest discover -s tests -t .`
- **النتيجة:** `Ran 605 tests in 143.453s` — **OK** (failures=0، errors=0).
- **العدد المتوقَّع:** ≥ 585 ⇐ **محقَّق (605)**. المخرَج الخام الكامل حُفظ في `_g1_44_verify_run.txt` ثم أُرشف إلى `_archive` (قابل للاسترجاع).
- **اختبارات G1.44:** `tests/test_g1_44_btc_follow.py`، `tests/test_g1_44_btc_follow_supervisor.py`، `tests/test_g1_44_guardian_btc_integration.py`، `tests/test_g1_44_chunk4_guard.py`، `tests/test_g1_44_chunk4_wiring.py`، `tests/test_g1_44_chunk4_i18n.py`.
- **عدم كسر سكيمة الاستئناف:** حالة الحارس طيّارة (لا تُسرَّب إلى الحالة الدائمة) — سويت الاستئناف يبقى أخضر ضمن الـ605.

## 6) حدود النطاق والأمان
- **داخل النطاق:** `btc_follow.py`, `market_feed.py`, `guardian_supervisor.py`, `guardian_exec.py`, `monitoring.py`, `i18n.py`, طبقة التنبيهات, `tests`.
- **خارج النطاق (لم يُمَس):** مسار `T0–T16`، ثوابت الأمان §1، بيع ماركت عارٍ، شورت/هيدج BTC، وأيّ Live على الحساب الحقيقي قبل G1.
- **§10.5:** لا تُرقية إلى `T16`؛ الافتراضي OFF ولا Live قبل اكتمال معيار الخروج (صفر critical/major غير مختوم + فحص صلاحيات مفتاح API + فحص IP whitelist + عبارة اعتماد صريحة من المستخدم).
