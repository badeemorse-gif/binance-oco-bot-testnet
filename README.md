# OCOBot

نظام سطح مكتب لإدارة وإعادة تموضع أوامر Binance Spot **OCO** (Testnet-first).
مصدر الحقيقة: [`docs/OCOBot_Design_AR.md`](docs/OCOBot_Design_AR.md) + [`PROJECT_STATE.json`](PROJECT_STATE.json).

> الحالة الحالية: المراحل **T1–T13** مكتملة (الأساس، القراءة والاختيار، التعديل اليدوي
> والتنفيذ الآمن، المراقبة الديناميكية، طبقة الاستمرارية / state store، توصيل Audit Log،
> وتوصيل Failure Matrix، واسترداد التشغيل (Runtime Recovery)، و**T9 (M4e — User Data Stream)**، و**T10 (M-UI/0 — هيكل الواجهة)**، و**T11 (M-UI/1 — شاشات القراءة)**، و**T12 (M-UI/2 — التعديل اليدوي والتنفيذ الآمن)**، و**T13 (M-UI/3 — شاشة المراقبة الديناميكية والتحكّم)**).
> المرحلة التالية هي **T14**. البقية تُبنى تباعًا حسب `task_ledger`
> (مصدر الحقيقة `PROJECT_STATE.json`).

## حالة المشروع / المراحل (Task Ledger)
مصدر الحقيقة: [`PROJECT_STATE.json`](PROJECT_STATE.json). ملخّص الحالة الحالية:

### مكتملة (Done)
- **T1 — M0 Foundation**: الأساس (REST موقّع، مفاتيح، بيئة، ساعة، preflight، حالة اتصال).
- **T2 — M1 Read & Select**: قراءة أوامر OCO واختيارها.
- **T3 — M2 Manual Edit + Safe Execution**: التعديل اليدوي والتنفيذ الآمن (cancel+create).
- **T4 — M3 Dynamic Monitoring**: المراقبة الديناميكية وإعادة التموضع التلقائي.
- **T5 — M4a Persistence / state store** (`ocobot/core/state_store.py`): كتابة ذرّية
  (temp→rename)، قراءة آمنة، مخطّط checkpoint بإصدار `SCHEMA_VERSION=1` يشمل
  `MonitoringState` + `SelectedOcoContext` + `LogLocations`، تخزين `Decimal` كنص (str)،
  redaction للأسرار، بالاعتماد على المكتبة القياسية فقط (stdlib-only).
- **T6 — M4b Audit Log** (`ocobot/core/audit_log.py`): توصيل سجلّ التدقيق بمسارات التنفيذ/المراقبة/الـ CLI.
- **T7 — M4c Failure Matrix** (`ocobot/core/failure_matrix.py`): توصيل مصفوفة تصنيف الأخطاء (كل الأخطاء عبر humanize؛ لا نصّ خام/Traceback).
- **T8 — M4d Runtime Recovery** (`ocobot/domain/recovery.py`): حفظ حالة المراقبة عبر state store عند كل انتقال + كشف آخر checkpoint ومطابقته بحالة الأمر الفعلية عبر REST قبل الاستئناف + HALT عند إغلاق OCO خارجيًا (لا استئناف أعمى)؛ موصول في CLI `monitor` عبر `recover()` + `--state-file` + `checkpoint_sink`.
- **T9 — M4e User Data Stream**: دورة listenKey (create/keepalive~30m/close) + استهلاك executionReport/listStatus لتحديث حالة الأمر لحظيًا وتغذية كشف الإغلاق الخارجي + إعادة اتصال آمنة بلا فقد حالة (إعادة الاتصال بنفس listenKey مع استمرارية keepalive دون فقد `MonitoringState`).
- **T10 — M-UI/0 هيكل الواجهة** (PySide6/PyQt6): نافذة رئيسية + RTL كامل + ثيم Palette D15 + قوقعة تنقّل (Sidebar/Topbar/Content) + IO غير متزامن خارج خيط الواجهة + مؤشر اتصال حيّ يعكس `ConnectionState` — **مكتمل** (T10a/T10b/T10c مكتملة).
- **T11 — M-UI/1 شاشات القراءة**: Dashboard وجدول Open OCO Orders وSelected OCO موصولة بالخدمات (build_dashboard / oco_reader / selection) — **مكتملة** (T11a/T11b/T11c مكتملة).
- **T12 — M-UI/2 التعديل اليدوي والتنفيذ الآمن**: إدخال TP%/SL% → 3 أسعار → Activate خلف تأكيد صريح (SafeExecutor) + Max Stop + إبراز Naked Window أثناء التنفيذ — **مكتملة** (T12a+T12b).
- **T13 — M-UI/3 شاشة المراقبة الديناميكية + التحكّم**: سعر حيّ (WS مع سقوط REST، لا Preview ثابت) + مستويات reference/trigger/latch + Start/Pause/Resume + Kill Switch (يوقف المراقبة دون إلغاء أي أمر على Binance) + tolerance/guard؛ لوحة حيّة بكل الحقول التي لا تختفي أثناء المراقبة (`ocobot/ui/monitoring.py` موصولة بـ MonitoringEngine عبر content.py/main_window.py) — **مكتملة** ومختومة.
- **الاختبارات**: الحزمة مؤكَّدة خضراء محليًا: **235 اختبارًا خضراء (عبر pytest)** (شاملة `tests/test_recovery.py` لاسترداد التشغيل). أضاف T7 الملف `tests/test_failure_matrix_wiring.py`، وأضاف T8 الملف `tests/test_recovery.py`، وأُكِّد التشغيل المحلّي عبر `python -m unittest discover -s tests -t .`.

### التالي (Next)
- **T14 — M-UI/4 Demo Mode**: المرحلة التالية. (لم تبدأ بعد.)

### قيد الانتظار / محجوبة لاحقًا (Pending / Blocked)
- **T12–T15**: بقية واجهة المستخدم (M-UI: T12–T14)، وطبقة M5 Validated (T15) — تبقى لاحقة.
- **G1**: بوابة الاعتماد البشري (اكتمال البوت التجريبي على Testnet) — **محجوبة**.
- **Live (T16)**: **محجوب** خلف بوابة الاعتماد البشري **G1**.

## M0 — ما الذي يوفّره؟
- عميل REST موقّع (HMAC SHA256) مع `timestamp` + `recvWindow` + إزاحة ساعة (clock offset).
- تحميل مفاتيح API من ملف قابل للتهيئة، مع **redaction** كامل (لا تُسجَّل المفاتيح إطلاقًا).
- اختيار البيئة (Testnet/Live): التبديل يغيّر **base URL + المفتاح فقط** (D12).
- **Preflight** عند الإقلاع: نداء موقّع خفيف (`GET /api/v3/account`) يمنع `-1022`.
- معالجة `-1021` (طابع زمني): إعادة مزامنة `serverTime` + إعادة توقيع **مرة واحدة** (D18).
- **حالة اتصال مرئية** (`ConnectionState`) تعرضها الواجهة/الـ CLI.

النطاق خارج M0 (لاحقًا): WebSocket، User Data Stream، قراءة/إنشاء/إلغاء الأوامر.

## المتطلبات
- Python 3.10+ (اختُبر على 3.12). **بدون اعتمادات خارجية** (المكتبة القياسية فقط).

## فتح الواجهة الرسومية (اختصار بلا console)
لفتح واجهة OCOBot الرسومية مباشرةً **بنقرة مزدوجة** ودون أي نافذة cmd/console:
- انقر نقرًا مزدوجًا على `OCOBot.lnk` في جذر المشروع (يشغّل `pythonw -m ocobot.ui.app` على Testnet بلا console).
- لإعادة توليد الاختصار على أي جهاز: شغّل `tools\create_OCOBot_shortcut.ps1` (يحلّ مسار `pythonw` ويضبط «Start in» على جذر المشروع).
- بديل محمول نصّي: `OCOBot.vbs` (يشغّل `pythonw` مخفيًّا من مجلد المشروع).

> طرق التشغيل القائمة تبقى كما هي: `python -m ocobot.ui.app` (الواجهة) و`python -m ocobot` (الـ CLI/preflight). التشغيل عبر `pythonw` فقط يُلغي ظهور نافذة console؛ وشكل/سلوك الواجهة لم يتغيّر.

## إعداد مفاتيح Binance (Keys Setup)

### المسار
- **المسار الافتراضي الثابت** لملف المفاتيح: `D:\فولدرات\مفتاح بنانس\key.txt`
  (معرّف في `config.py` كـ `DEFAULT_KEYS_PATH`).
- قابل للتهيئة عبر متغيّر البيئة `OCOBOT_KEYS_PATH` أو راية الـ CLI `--keys`.

### اختيار البيئة
- يتم عبر `OCOBOT_ENV` (الافتراضي `testnet`).
- `testnet` ⇒ يستخدم مفاتيح `TESTNET_`، و`live` ⇒ يستخدم مفاتيح `LIVE_`
  (D12: التبديل إعداد فقط — يغيّر base URL + المفتاح لا أكثر).

### صيغة الملف
ملف واحد يضم البيئتين معًا، أسطر بصيغة `KEY=VALUE`، وتُتجاهل الأسطر الفارغة
والأسطر التي تبدأ بـ `#` (تعليقات):

```
TESTNET_KEY=...
TESTNET_SECRET=...
LIVE_KEY=...
LIVE_SECRET=...
```

انسخ [`key.example.txt`](key.example.txt) إلى المسار أعلاه واملأ القيم الحقيقية.
> لا يوجد ملف `key.txt` حقيقي داخل المستودع — يوجد فقط القالب `key.example.txt`.

### سلوك الأخطاء
الرسائل واضحة وبشرية (وليست stack trace):
- إذا لم يوجد الملف ⇒ خطأ `KeysError` برسالة: «ملف المفاتيح غير موجود على المسار المحدد...».
- إذا نقص مفتاح للبيئة المختارة ⇒ خطأ `KeysError` برسالة: «المفاتيح ناقصة للبيئة ...».

### الأمان (D8)
- صلاحيات **تداول فقط، بدون Withdrawals**.
- يُنصح بـ **IP whitelist**.
- لا يُرفع ملف المفاتيح الحقيقي لأي repo (مُدرج ضمن `.gitignore`).
- **redaction** يمنع تسرّب المفاتيح في السجلّات وملفات الحالة.

## التشغيل (فحص الاتصال / Preflight)
```bash
# Testnet (الافتراضي)
python -m ocobot

# تحديد مسار مفاتيح مختلف
python -m ocobot --keys "C:\path\to\key.txt"

# اختيار البيئة صراحةً
python -m ocobot --env testnet
```
يطبع الأمر حالة الاتصال ويُرجع رمز خروج `0` عند النجاح و`1` عند الفشل.
بدائل الإعداد عبر متغيّرات البيئة: `OCOBOT_ENV`, `OCOBOT_KEYS_PATH`, `OCOBOT_RECV_WINDOW`.

## الاختبارات
```bash
python -m unittest discover -s tests -t .
```
اختبارات الوحدة لا تحتاج شبكة (Transport وهمي مُحقَن). اختبار القبول
"نداء موقّع خفيف ينجح على Testnet" يتطلب مفاتيح Testnet حقيقية عبر `python -m ocobot`.

## المراقبة الديناميكية (M3 / T4)
مراقبة سعر حيّ (WebSocket bookTicker مع سقوط REST) تُعيد تموضع OCO تلقائيًا عند
تجاوز مستوى التفعيل، مع تفويض كل cancel+create إلى المنفّذ الآمن (M2).
```bash
# افتراضيًا dry-run (لا كتابة) — يعرض ماذا كان سيحدث
python -m ocobot monitor <orderListId> --trigger 1 --tp 4 --sl 2

# تنفيذ حقيقي (بوابة اعتماد بشري) — يتطلب --yes
python -m ocobot monitor <orderListId> --trigger 1 --tp 4 --sl 2 --yes
```
- **Default dry-run**: بلا `--yes` لا تُكتب أي أوامر (متوافق مع `activate`).
- **Kill Switch**: يوقف كل المراقبة فورًا **دون** إلغاء أي أمر على Binance
  (الرسالة: «تم إيقاف كل المراقبة النشطة فورًا. لم يُلغَ أي أمر على Binance.»).
- **Pause/Resume**: الإيقاف المؤقت يُبقي أمر OCO كما هو تمامًا.
- خيارات: `--tolerance` (سحب صغير مسموح)، `--guard` (حدّ الحركة المعاكسة)،
  `--guard-policy`، `--max-ticks` (حدّ يمنع التعليق)، `--price` (بذرة تُستخدم فقط
  إن تعذّر السعر الحيّ — D14).

## التخطيط الحزمي
```
ocobot/
  config.py                # AppConfig (env, keysPath, recvWindow, baseUrls)
  cli.py, __main__.py      # نقطة تشغيل الـ preflight والأوامر
  core/
    environment.py         # Environment + base URLs + join_url
    keys.py                # تحميل المفاتيح + redaction
    signer.py              # HMAC SHA256
    clock.py               # مزامنة serverTime + offset
    rest_client.py         # عميل REST موقّع (-1021/-1022)
    connection_state.py    # الحالة المرئية
    preflight.py           # فحص الإقلاع
    market_feed.py         # تغذية السعر الحيّ (WebSocket + سقوط REST)
    state_store.py         # الاستمرارية: checkpoint ذرّي (SCHEMA_VERSION=1)
    audit_log.py           # سجلّ التدقيق (يُربَط في T6)
    failure_matrix.py      # مصفوفة تصنيف الأخطاء
    redaction.py, errors.py
  domain/
    models.py              # نماذج المجال
    oco_reader.py          # قراءة أوامر OCO
    selection.py           # اختيار الأمر
    exchange_info.py       # معلومات الرمز/القيود
    pricing.py             # حسابات الأسعار
    reposition.py          # منطق إعادة التموضع
    monitoring.py          # حالة/حلقة المراقبة
tests/                     # اختبارات وحدة (بدون شبكة) — 129/129 خضراء (T7 يلزم تأكيد محلّي)
```


<!-- T11b-sealed -->
T11b (جدول Open OCO Orders — ocobot/ui/open_orders.py) منجَزة وموصولة بـ oco_reader ومختومة — الحزمة خضراء 206 اختبارًا (_t11b_run.txt). التالي: T11c.
<!-- T11c-sealed -->
T11c (Selected OCO — ocobot/ui/selected_oco.py) منجَزة وموصولة بـ selection والسياق الحيّ ومختومة؛ مظلّة T11 (شاشات القراءة: Dashboard + Open OCO Orders + Selected OCO) مكتملة — الحزمة خضراء 214 اختبارًا (_t11c_run.txt). التالي: T12.
<!-- T12b-sealed -->
T12 (M-UI/2 — التعديل اليدوي والتنفيذ الآمن) مكتملة (T12a+T12b) ومختومة في PROJECT_STATE.json (completion_seal، 226 أخضر، _t12b_run.txt). التالي: T13.
<!-- T13-sealed -->
T13 (M-UI/3 — شاشة المراقبة الديناميكية والتحكّم: `ocobot/ui/monitoring.py`) منجَزة وموصولة بـ MonitoringEngine عبر content.py/main_window.py ومختومة في PROJECT_STATE.json (completion_seal، 235 أخضر، _t13_run.txt). التالي: T14.
