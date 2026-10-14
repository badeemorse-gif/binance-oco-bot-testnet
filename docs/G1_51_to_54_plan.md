# خطة البنود G1.51 → G1.54 — قياس الربحية والتقاط الخروج (write-first)

> **البروتوكول:** protocol_version 1.5 · phase `G1_MANUAL_TESTING` · Testnet فقط.
> لا Live/T16 قبل بوّابة G1 (§10.5). خط الأساس الحالي للسويت الكاملة = **724** اختبار (آخر مختوم `last_sealed = G1.50`).
> كل بند يجب أن يُبقي السويت لاحقًا **>= baseline** بـ 0 fail / 0 err، ويُشغَّل **split-per-file** (عملية لكل ملف) لتفادي انهيار Qt teardown المعروف.
> كل سلوك جديد **DI/opt-in** (الافتراضي `None`) بـ **صفر تغيير سلوكي** على المسارات القائمة (نفس انضباط G1.49/G1.50).
> **لا لمس `hot_path` في أي مكان:** `hot_path = on_price_tick / MonitoringEngine.start / SafeExecutor.execute / reposition / create_oco`.

هذه الوثيقة تُنتَج في خطوة **الكتابة أولًا (§10.2)** فقط: سُجِّلت أربعة عقود دفاعية في `state/defects/` وفُتِحت في `PROJECT_STATE.json.defect_log` بالحالة `contracted`. لم يُكتب أي كود ميزة، ولم تُشغَّل السويت، ولم يُختم أي بند.

---

## نظرة عامة والترتيب

| id | العنوان | severity | depends_on |
|------|---------|----------|------------|
| `G1.51` | إصلاح سرقة التحديد في شاشة الصفقات المنتهية بسبب التحديث الدوري | major | — |
| `G1.52` | التقاط أي أمر بيع منفَّذ (OCO أو مستقل) ونسبته للصفقة النشطة [الأساس] | major | — |
| `G1.53` | مُجمِّع ربحية خالص لكل وضع + telemetry تنفيذ الخروج | major | `G1.52` |
| `G1.54` | لوحة ربحية احترافية (عرض فقط) داخل شاشة `08_completed_trades` مع drill-down | major | `G1.51`, `G1.53` |

**ترتيب التنفيذ (مع احترام depends_on):** `G1.51 → G1.52 → G1.53 → G1.54`.

---

## G1.51 — إصلاح ثبات التحديد في «الصفقات المنتهية»

**العنوان:** إصلاح سرقة التحديد في شاشة الصفقات المنتهية بسبب التحديث الدوري.

**السبب الجذري (مؤكَّد من `ocobot/ui/completed_trades.py`):** يوجد `QTimer` بفاصل `1000ms` في `__init__` موصّل بـ `self.refresh` يعمل أثناء ظهور الشاشة (`showEvent` يبدؤه، `hideEvent` يوقفه). كل نبضة تستدعي `refresh() -> set_trades()` الذي ينفّذ `self.list_table.setRowCount(0)` (يمسح كل الصفوف والتحديد) ثم يعيد الإدراج، وفي نهايته: `if self._trades: self.list_table.setCurrentCell(0, 0)` أي يفرض الرجوع للصف الأول دائمًا، ويفرّغ `detail_table`. لذلك عند اختيار الصف الثاني/الثالث يرجع التحديد للصف الأول خلال ثانية واحدة كحدّ أقصى.

**النطاق:**
- **in:** `ocobot/ui/completed_trades.py` + اختبار انحدار جديد في `tests/`
- **out:** `ocobot/domain/completed_trades.py` (منطق النموذج), `hot_path`, أي Live/T16

**الخطوات المرتّبة:**
- `chunk_1` (risk: long · ينتج اختبار انحدار): اختبار يحاكي اختيار الصف 2 ثم استدعاء `refresh/set_trades` بنفس البيانات ويؤكّد بقاء `currentRow == 2` (أحمر بالتصميم قبل الإصلاح).
- `chunk_2` (risk: long · ينتج كود الإصلاح): جعل `set_trades` محافظًا على التحديد وغير هدّام: (أ) حساب توقيع من قائمة `trade_key` وعدم إعادة بناء الجدول إن لم يتغيّر؛ (ب) قبل أي إعادة بناء، حفظ `trade_key` للصف المحدّد ثم إعادة اختيار نفس المفتاح بعد البناء؛ (ج) الرجوع للصف الأول `setCurrentCell(0,0)` فقط عند أول تحميل أو عند اختفاء الصفقة المحدّدة؛ (د) لفّ إعادة البناء بـ `blockSignals` لتفادي إعادة تحميل التفاصيل بالغلط.
- `chunk_3` (risk: short · ينتج توثيق+ختم): `docs/G1_51_report.md` + سويت خضراء split-per-file + ختم + أرشفة.

**فحوص القبول:** التحديد يثبت عبر التحديث الدوري (اختبار) · الصفقات الجديدة تظهر دون سرقة التحديد · لا إعادة بناء للجدول عند عدم تغيّر البيانات · لا لمس `hot_path` · §1.5 ثنائية اللغة سليمة · كامل السويت أخضر >= baseline.

---

## G1.52 — التقاط أي أمر بيع منفَّذ (ليس OCO فقط) [الأساس]

**العنوان:** التقاط أي أمر بيع منفَّذ (OCO أو مستقل) ونسبته للصفقة النشطة في نموذج الصفقات المنتهية.

**هدف معتمد من المستخدم:** الصفقات المنتهية ولوحة الربحية يجب أن تقرأ أي أمر بيع تنفّذ، وليس أوامر OCO فقط.

**السبب الجذري (مؤكَّد):** `completed_trades.build_fill_recorder` يكتب `trade_closed_fill` من `executionReport` بحالة `FILLED` ويأخذ `order_list_id` من الحقل `g` (= `orderListId`). الأوامر المستقلة (`LIMIT`/`MARKET`/`STOP` SELL خارج OCO) تحمل `g = -1`، فلا تُنسب للصفقة ⇒ خروجات الوسائل (`manual_exit` عبر `execute_market_exit`، `bracket`، guardian `STOP_LOSS_LIMIT`، `market_exit` chase) لا تُلتقط كـ `exit_price` ⇒ `profit_available=False` دائمًا للخروج غير-OCO. أيضًا لا يوجد أي سجلّ `exit_source` مُصدَر حاليًا (`0` في `ocobot_audit.jsonl`) فكل صفقة تُنسب `MONITORING` افتراضيًا. وجسر التنبيهات `AlertsAuditBridge._ALERT_EVENTS = {monitor_start, repositioned}` فقط.

**النطاق:**
- **in:** `ocobot/domain/completed_trades.py` (توسيع `build_fill_recorder` ومطابقة التعبئة بالصفقة النشطة عبر `symbol` + `orderId`/`clientOrderId` لا `orderListId` فقط, مع إبقاء توافق OCO), نقطة تجميع `UserDataStreamConsumer` (ربط `build_fill_recorder` — غالبًا `ocobot/app_wiring.py` أو `ocobot/ui/app.py`), إصدار `exit_source` من `ocobot/ui/manual_exit.py` و `ocobot/ui/bracket_wiring.py` و `ocobot/domain/guardian_supervisor.py` و `ocobot/ui/btc_follow_wiring.py` لحظة الإطلاق, توسيع `_EXIT_SOURCE_ALLOWED` بـ `MANUAL_EXIT` في `ocobot/domain/completed_trades.py`, `ocobot/ui/i18n.py` لأي نص جديد.
- **out:** منطق `hot_path`/التنفيذ, تغيير قرارات التسعير/الخروج, أي Live/T16.

**الخطوات المرتّبة:**
- `chunk_1` (long · اختبار تشخيصي): اختبار يثبت أن تعبئة SELL مستقلّة (`g=-1`) يجب أن تُنسب للصفقة النشطة ضمن مقطع `monitor_start` المفتوح (بالرمز/الوقت) وتعطي `exit_price`.
- `chunk_2` (long · كود): توسيع `build_fill_recorder` ليلتقط أي `executionReport` `FILLED` حيث `S==SELL` (ليس فقط `g>0`) ويكتب `trade_closed_fill` مع `order_id`/`client_order_id` والرمز وسعر/كمية التعبئة؛ وتعديل منطق النسب في `build_completed_trades` ليقبل التعبئة المستقلّة داخل المقطع. إبقاء مسار OCO كما هو (لا انحدار).
- `chunk_3` (long · كود): إصدار سجلّ `exit_source` عبر `AuditLog.record` لحظة إطلاق كل وسيلة بالقيمة الصحيحة من `{PRICE_BRACKET, BTC_FOLLOW, POSITION_SAFETY_NET, MANUAL_EXIT, MONITORING}`؛ إضافة `MANUAL_EXIT` إلى `_EXIT_SOURCE_ALLOWED`. كل الحقن opt-in (sink/callable default `None` ⇒ لا انحدار).
- `chunk_4` (long · ربط+اختبارات): ربط `build_fill_recorder` عند نقطة تجميع `UserDataStreamConsumer` عبر `on_order_event` (يحافظ على أي معالِج قائم)؛ اختبارات لا-انحدار تؤكّد التقاط الخروج اليدوي/السوقي/القوس/الحارس ونسبته + صحة `exit_source` لكل وسيلة.
- `chunk_5` (short · توثيق+ختم): `docs/G1_52_report.md` + سويت خضراء + ختم + أرشفة.

**فحوص القبول:** أي بيع منفَّذ (OCO أو مستقل) يُنتج `trade_closed_fill` ويُنسب للصفقة · `exit_price`/profit متاح للخروج غير-OCO · `exit_source` صحيح لكل وسيلة (`PRICE_BRACKET`/`BTC_FOLLOW`/`POSITION_SAFETY_NET`/`MANUAL_EXIT`/`MONITORING`) · توافق OCO القديم محفوظ (لا انحدار) · لا لمس `hot_path` · كامل السويت أخضر >= baseline.

---

## G1.53 — قياس الربحية لكل وضع (telemetry + تجميع) · depends_on: `G1.52`

**العنوان:** مُجمِّع ربحية خالص لكل وضع + telemetry تنفيذ الخروج.

**الوصف:** دالة خالصة فوق `build_completed_trades` تُجمّع `CLOSED` trades حسب `exit_source` وتُنتج لكل وضع المقاييس. إضافة telemetry `exit_execution` تُحفظ من منفّذ الخروج (القيم محسوبة أصلًا في `execute_exit_chase` لكنها تُهمَل).

**النطاق:**
- **in:** `ocobot/domain/` (مُجمِّع جديد `profitability_by_mode` خالص + اختباراته), `ocobot/domain/market_exit.py` (كتابة `exit_execution` عبر `audit_sink` DI opt-in داخل `execute_exit_chase`/`execute_market_exit` — بلا تغيير سلوك), `ocobot/domain/completed_trades.py` (قراءة فقط لإعادة الاستخدام).
- **out:** `hot_path`, تغيير أي قرار تنفيذ, أي Live/T16.

**الخطوات المرتّبة:**
- `chunk_1` (long): دالة خالصة `profitability_by_mode(trades)` تُعيد لكل وضع: `n`, `win_rate = |profit_pct>0|/n*100`, `avg_return_pct = mean(profit_pct)`, `net_usd = sum(profit_usd)`, `expectancy = net_usd/n`, (وعند توفّر `exit_execution`) `avg_slippage_pct` و `floor_rate`. كل الحساب `Decimal`. + اختبارات على مقطع تخليقي.
- `chunk_2` (long): كتابة سجلّ `exit_execution` append-only (`source, exit_side, order_type∈{LIMIT_IOC,MARKET,STOP_LOSS_LIMIT}, tif, requested_price, filled_price, live_bid, slippage_pct, band_pct, attempts_used, reached_floor, floor_price, qty, trade_uid, dry_run`) عبر `audit_sink` محقون default `None` في `market_exit` (opt-in ⇒ لا انحدار). + اختبارات.
- `chunk_3` (short · اختياري): التقاط العمولة (`executionReport` حقول `n`/`N`) لحساب صافي PnL لو متاح.
- `chunk_4` (short): `docs/G1_53_report.md` + سويت خضراء + ختم + أرشفة.

**فحوص القبول:** المقاييس لكل وضع صحيحة على مقطع تخليقي (اختبار) · `exit_execution` تُكتب append-only `Decimal` · `audit_sink` default `None` ⇒ لا انحدار · لا لمس `hot_path` · كامل السويت أخضر >= baseline.

---

## G1.54 — لوحة الربحية الاحترافية في شاشة 08 · depends_on: `G1.51`, `G1.53`

**العنوان:** لوحة ربحية احترافية (عرض فقط) داخل شاشة `08_completed_trades` مع drill-down.

**الوصف:** إعادة تنظيم شاشة `08_completed_trades` إلى: أعلى = ملخّص ربحية احترافي لكل وضع، أوسط = قائمة الصفقات (قابلة للفلترة بالوضع + التحديد المُصلَّح من `G1.51`)، أسفل = تفاصيل التموضع القائمة. تُغذّى قراءةً فقط من `profitability_by_mode` (`G1.53`) و `load_completed_trades` القائمة.

**النطاق:**
- **in:** `ocobot/ui/` (مكوّن لوحة ربحية جديد عرض-فقط + دمجه في `ocobot/ui/completed_trades.py`), `ocobot/ui/i18n.py` (§1.5).
- **out:** أي شبكة في خيط الواجهة, `hot_path`, أي منطق تنفيذ, أي Live/T16.

**الخطوات المرتّبة:**
- `chunk_1` (long): مكوّن عرض خالص: بطاقة لكل وضع (win-rate كحلقة تقدّم، متوسط العائد٪، الصافي$، التوقّع/صفقة، متوسط الانزلاق) + ترتيب الأوضاع بالتوقّع (leaderboard) + منحنى P&L تراكمي بسيط (`QPainter`) + شريط توزيع رابح/خاسر. عرض فقط، RTL، ألوان `PercentTracker` (أخضر صعود/أحمر هبوط)، صيغة أرقام متّسقة. + اختبارات Qt-safe.
- `chunk_2` (long): الدمج في `08`: الملخّص أعلى، فلترة القائمة بالوضع، drill-down (نقر وضع ⇒ تصفية القائمة ⇒ نقر صفقة ⇒ تفاصيل)، مع إعادة استخدام منطق التحديث المحافظ على التحديد من `G1.51`.
- `chunk_3` (short): مفاتيح i18n §1.5 ثنائية اللغة + تغطية `retranslate` + اختبارات.
- `chunk_4` (short): `docs/G1_54_report.md` + سويت خضراء + ختم + أرشفة.

**فحوص القبول:** اللوحة عرض-فقط تعرض مقاييس كل وضع · drill-down (وضع→صفقات→تفاصيل) يعمل · التحديد ثابت أثناء التحديث الدوري · §1.5 ثنائية اللغة بلا تسرّب عربي في EN بعد `retranslate` · لا شبكة في خيط الواجهة ولا `hot_path` · كامل السويت أخضر >= baseline.

---

## التبعيات وترتيب التنفيذ

```
G1.51  (مستقل)
G1.52  (مستقل، الأساس للبيانات)
G1.53  depends_on → G1.52
G1.54  depends_on → G1.51, G1.53
```

**ترتيب التنفيذ:** `G1.51 → G1.52 → G1.53 → G1.54`.
- `G1.52` هو الأساس الذي يُنتج التقاط الخروج و`exit_source` اللذين يبني عليهما `G1.53` التجميع.
- `G1.54` لوحة العرض تحتاج التحديد المُصلَّح من `G1.51` ومقاييس `profitability_by_mode` من `G1.53`.

---

## طريقة التنفيذ العامة (لكل بند)

**write-first (مُنجَزة في هذه الخطوة)** ⇒ **TDD لكل chunk** (اختبار أحمر ⇒ تنفيذ ⇒ أخضر) ⇒ **السويت الكاملة split-per-file** (`>= 724`، 0 fail / 0 err) ⇒ **تقرير docs** ⇒ **ختم في `state/defects/*.json`** ⇒ **أرشفة الملفات المؤقتة إلى `_archive`**.

**ثوابت حاكمة طوال التنفيذ:**
- لا لمس `hot_path` إطلاقًا (`on_price_tick / MonitoringEngine.start / SafeExecutor.execute / reposition / create_oco`).
- كل سلوك جديد DI/opt-in، الافتراضي `None`، بصفر تغيير سلوكي على المسارات القائمة.
- السويت تبقى `>= baseline (724)` بـ 0 fail / 0 err، split-per-file لتفادي انهيار Qt teardown.
- §1.5 ثنائية اللغة لأي نص واجهة جديد (EN↔AR بلا تسرّب) + تغطية `retranslate`.
- لا Live/T16 قبل بوّابة G1 (§10.5).
