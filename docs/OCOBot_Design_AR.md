# OCOBot — المستند التصميمي المعتمد (DESIGN-ONLY / تصميم فقط)

> **مصدر الحقيقة التصميمي.** هذا المستند ينفّذه أي فريق/نموذج لاحق دون الرجوع لأسئلة أساسية.
> مبني بالكامل على البرومبت الأصلي (المؤرشف الآن في `docs/archive/OCOBot_Design_Prompt_AR.md` — مرجع تاريخي لا يُنفَّذ منه) والموك-أب المعتمد في `docs/ui_mockups/`.
> **صفر كود تطبيقي.** لا `.py`، لا مكوّنات UI منفّذة، لا دوال جاهزة — فقط مخططات ومواصفات وجداول و state machines و pseudocode توضيحي قصير جدًا عند الضرورة.
> **لغة:** عربية + مصطلحات تقنية بالإنجليزية. **الحالة:** جاهز للتنفيذ (Ready-to-build).

---

## 0) افتراضات مقفولة + منهجية

**افتراضات اتخذها المصمّم ومضى (Assumptions):**
- **A1 — نوع الأمر:** الاستخدام الأساسي هو **OCO بيع (SELL)** لحماية مركز موجود (TP فوق السوق + Stop Loss تحته). التصميم symbol-agnostic ولا يمنع BUY OCO مستقبلًا، لكن الـ MVP يستهدف SELL لأنه سيناريو "إدارة صفقة قائمة".
- **A2 — النِّسب مرجعها السعر الحي:** `TP%` فوق `current_live_price` و`SL%` تحته، في الوضعين اليدوي والديناميكي (كما في القسم 5-D و6 من البرومبت).
- **A3 — الكمية مقفولة:** موروثة من الأمر المختار، Read-only؛ عند إعادة التموضع تُستخدم **الكمية المتبقية الفعلية** بعد أي Partial Fill (تُقرأ لحظة التنفيذ).
- **A4 — SL Limit داخلي:** يُحسب دائمًا = `SL Trigger − gap` (لا يدخله المستخدم). `gap` افتراضيًا 1–2 tick ويُوسَّع للعملات المتقلبة.
- **A5 — أمر واحد في كل مرة:** المعمارية معزولة/async تسمح بالتوسّع، لكن تعدّد الأوامر المتوازية **غير مُفعّل الآن**.
- **A6 — البيئة الافتراضية Testnet** حتى الاعتماد الصريح للتحويل إلى Live.

**سبب/Trade-off لكل قرار:** مذكور بإيجاز بجانب القرار داخل الأقسام (بصيغة _لماذا:_).

**سؤال يوقف سلامة التصميم (Open — غير محسوم):** لا يوجد سؤال يمنع البدء. البنود غير القاطعة موضوعة في **القسم 12 / Open Questions** ولا تُدرَج في التصميم الأساسي.

---

# Deliverable 1 — الرؤية والنطاق (Vision & Scope)

## 1.1 الرؤية المعتمدة (Canonical)
**OCOBot** نظام سطح مكتب احترافي لإدارة وإعادة تموضع أوامر **Binance Spot OCO** الحقيقية. يقدّم **دورة واحدة متصلة** (تجربة منتج واحد، لا أدوات منفصلة):

```
Read → Select → Understand → Prepare → Activate → Verify → Replace → Monitor → Reposition → Verify → Repeat
```

المستخدم: يرى أوامره الحقيقية، يختار OCO واحدًا بدقة (`orderListId`)، يعدّل مستويات الخروج بالنِّسب بأمان دون المساس بالأمر الأصلي أثناء الإعداد، ثم ينفّذ **Replacement** سريعًا ومتحقَّقًا (`≤ 3s`, "Fast, but not blind")، مع **مراقبة ديناميكية اختيارية** تعيد التموضع تلقائيًا وفق قواعد يحددها المستخدم.

## 1.2 المبادئ الأربعة المقدّسة (Invariants)
| # | المبدأ | الأثر التصميمي |
|---|--------|----------------|
| P1 | **اختيار دقيق** — OCO واحد بهويته `orderListId` | كل عملية تحمل `orderListId` + `symbol` وتُعاد المصادقة عليها قبل التنفيذ |
| P2 | **لا تغيير قبل القرار** — فتح شاشة التعديل لا يلغي شيئًا | مفهوم **Draft** منفصل تمامًا عن الأمر الحقيقي؛ لا نداء كتابي قبل **Activate** |
| P3 | **لا لمس للآخرين** — لا يُمَس أي OCO غير المحدد | كل الطلبات الكتابية مُقيَّدة بـ `orderListId` المحدد؛ لا عمليات bulk |
| P4 | **أتمتة بقواعد المستخدم** — لا استراتيجية مخترعة | Monitoring Engine ينفّذ نِسبًا يدخلها المستخدم فقط |

## 1.3 خارج النطاق (Out of Scope — لا يُبنى)
General Trading Platform · Market Order Bot · Generic Buy Bot · Autonomous Coin Discovery · إشارات تداول · AI يقرر البيع/الشراء · Portfolio Manager كامل · P&L Analytics متقدم · News/Sentiment · دعم Live "جاهز من البداية".

**قاعدة "لا تخترع":** أي فكرة إضافية → **Open Questions** فقط، لا تدخل التصميم الأساسي.

---

# Deliverable 2 — المعمارية (Architecture)

## 2.1 المكوّنات ومسؤولياتها (Modular، مفصولة المسؤوليات)
| المكوّن | المسؤولية الوحيدة | لا يفعل |
|---------|-------------------|---------|
| **OCO Reader** | جلب الأوامر المفتوحة الحقيقية + تفاصيل OCO المحدد من Binance | لا يعدّل شيئًا |
| **Order/Draft Manager** | إدارة الـ **Draft** (النِّسب، الحساب، القيم القديمة/الجديدة) دون أي نداء كتابي | لا يتصل بالبورصة كتابيًا |
| **Monitoring Engine** | تطبيق قواعد المراقبة الديناميكية (Trigger/Latch/Latest Price) وإطلاق الـ Reposition | لا يخترع استراتيجية؛ لا ينفّذ REST بنفسه (يفوّض Execution) |
| **Validation/Filters** | قراءة `exchangeInfo` وتطبيق `tickSize/stepSize/minQty/minNotional` وترتيب الأسعار الثلاثة | لا قرارات تجارية من عنده |
| **Execution** | تنفيذ **Safe Cancel → Create** الذرّي مع Idempotency والتحقق | لا منطق UI |
| **Persistence/State** | حفظ حالة المراقبة/الإعداد/`reference_price`/cursor + Audit Log (استئناف بعد تعطّل) | لا نداءات شبكة |
| **Notifier** | رسائل بشرية واضحة + حالات مرئية | لا منطق تنفيذ |
| **Connectivity Layer** | REST client موقّع (HMAC) + WS (market) + User Data Stream + إدارة المفاتيح/البيئة | لا منطق منتج |
| **UI Layer** | العرض RTL الداكن، Progressive disclosure، حالات مرئية | لا نداءات شبكة مباشرة (يمر عبر الخدمات) |

## 2.2 تدفق البيانات (Data Flow)
```
                       ┌──────────────────────────────────────────────┐
                       │                 UI Layer (RTL)               │
                       │  Dashboard · Orders · Selected/Edit · Monitor │
                       └───────▲───────────────▲──────────────▲────────┘
        (events/state)         │               │              │ (user actions)
                       ┌───────┴───────────────┴──────────────┴────────┐
                       │              Application Services              │
   ┌───────────────────┴──────┐  ┌───────────────────┐  ┌──────────────┴─────────┐
   │  OCO Reader / Draft Mgr   │  │ Monitoring Engine │  │       Execution        │
   └──────────┬───────────────┘  └─────────┬─────────┘  └──────────┬─────────────┘
              │                             │                       │
        ┌─────▼─────┐   ┌──────────────────▼──────┐          ┌──────▼───────┐
        │Validation │   │  Persistence / State     │◄────────►│  Notifier    │
        │ /Filters  │   │  (+ Audit Log, recovery) │          └──────────────┘
        └─────┬─────┘   └──────────────────────────┘
              │
   ┌──────────▼───────────────────────────────────────────────┐
   │                  Connectivity Layer (async)               │
   │  REST(signed) · Market WS · User Data Stream · Keys/Env    │
   └──────────┬───────────────────────────────────────────────┘
              │
        ┌─────▼──────────────────────┐
        │   Binance Spot (Testnet/Live)│
        └─────────────────────────────┘
```

**قواعد التدفق:**
- **كل IO async خارج UI thread** — الواجهة لا تتجمّد أبدًا. تحديثات UI **incremental** (لا re-render شامل). _لماذا: شرط "صفر lag" في البرومبت._
- **السعر الحي حقيقي دائمًا** من Market WS؛ **حالة الأوامر** من User Data Stream؛ **العمليات الكتابية** عبر REST الموقّع. _لماذا: فصل مصادر البيانات يمنع "Preview ثابت يوهم أنه Live"._
- **مصدر واحد لهوية الهدف:** `orderListId` يمرّ في كل طبقة؛ Execution يعيد التحقق منه قبل أي كتابة (P1).

## 2.3 خريطة الوحدات (Module Map — منطقية، غير مُلزِمة بأسماء ملفات إنتاجية)
```
core/        → connectivity (rest_signed, market_ws, user_data_stream, keys, env)
domain/      → oco_reader, draft_manager, filters_validation, execution, monitoring_engine
state/       → persistence, audit_log, recovery
ui/          → screens (dashboard, orders, selected_edit, monitoring, safe_exec), widgets, theme(RTL/dark)
app/         → wiring / dependency graph (single-order orchestrator)
```

---

# Deliverable 3 — مواصفة UI/UX شاشة-بشاشة (RTL · Dark · WCAG AA)

**قواعد بصرية ملزمة (من البرومبت + الموك-أب المعتمد):**
- **RTL كامل** (اللغة والاتجاه من اليمين لليسار)، خط `Tajawal`.
- **ثيم داكن موحّد** عبر كل الشاشات (ممنوع خلط فاتح/داكن). تباين WCAG AA.
- **الالتزام بالموك-أب** في `docs/ui_mockups/` بأقل تغيير ممكن؛ الحرية في الصقل/الأداء فقط، لا في الـ layout.
- **Palette معتمدة:**

| Token | Hex | استخدام |
|-------|-----|---------|
| BG | `#031021` | خلفية عامة |
| SIDEBAR | `#020d1c` | الشريط الجانبي |
| CARD | `#061529` | البطاقات |
| CARD_ALT | `#081d32` | بطاقات بديلة/hover |
| BORDER | `#0d2a43` | الحدود |
| TEXT | `#f0f7fb` | نص أساسي |
| TEXT_SOFT | `#dce9f2` | نص ثانوي |
| MUTED | `#6f8ba2` | لابلز خافتة |
| BLUE | `#0876e8` | أزرار رئيسية |
| TEAL | `#073b42` | ثانوي |
| GREEN | `#19c58b` | نجاح/محدَّد |
| RED | `#ff4b68` | خطر/فشل |
| AMBER | `#f08f1b` | تحذير/بيئة |

- **Layout عام:** Sidebar يمين (تنقّل) + Topbar (العنوان + Pills: Environment، Connection) + Content. (مطابق للموك-أب.)

## 3.1 A — Dashboard (`01_dashboard.html`)
مركز تحكم لا صفحة زينة. بطاقات نظرة واحدة:
`Selected OCO · Symbol · Current Price · Current TP · Current SL · Reference Price · Next Trigger · Monitoring State · Connection (Testnet/Live) · Last Reposition + result · Environment`.
- Current Price يتحدّث لحظيًا (Market WS). Monitoring State بلون الحالة (Idle/Active/Paused/…).
- **قبل اختيار OCO:** الحقول تعرض `—` وحالة "لم يُختَر أمر".

## 3.2 B — Open OCO Orders (`02_open_orders.html`)
جدول التحكم. أعمدة: `# · Order List ID · Symbol · Status · Qty · Sale/TP · Stop Trigger · Limit After Trigger` + زر **Select**.
- المصدر: `GET /api/v3/openOrderList` (حقيقي). زر **Refresh** يدوي + تحديث حالة عبر User Data Stream.
- اختيار صف → ينتقل إلى Selected OCO ويؤسّس Live context.

## 3.3 C — Selected OCO (تأكيد الفهم) (`03_selected_and_edit.html` — العمود الأول)
الهوية واضحة جدًا (الخطأ في اختيار الأمر أخطر من الخطأ في الرقم):
`Order List ID · Symbol · Quantity · TP · Stop Trigger · Stop Limit · Leg IDs · Status · Current Price`.
- الكمية معروضة مع شارة **🔒 مقفولة**.

## 3.4 D — Manual Edit بالنِّسب (`03_selected_and_edit.html` — العمودان 2 و3)
- **Checkbox تفعيل** (Progressive disclosure): حقول الإدخال **لا تظهر/تُفتح** إلا بعد تفعيله بإرادة المستخدم.
- إدخال المستخدم: `TP %` (فوق السعر الحالي) و`SL %` (تحته) فقط.
- **النظام يملأ تلقائيًا الأسعار الثلاثة:** TP price، Stop Trigger، Stop Limit (= Trigger − gap، أسفل التريجر). الكمية Read-only.
- تُعرض **القيم القديمة** بجانب الجديدة للمرجع. الأمر الأصلي **فعّال حتى Activate**.
- **Live panel (العمود 3):** السعر الحالي + **أعلى Stop متاح** وفق قواعد Binance + زر **Max Available Stop**.
- **قبل اختيار OCO لا يبدأ الـ Live context.**
- زر **Activate** (BLUE) يطلق Safe Execution (شاشة F).

## 3.5 E — Dynamic Monitoring (`04_dynamic_monitoring.html`)
- **Checkbox تفعيل** يفتح 3 حقول نِسب: `Reposition Trigger Rise %` · `TP Distance Above Current %` · `SL Distance Below Current %`.
- لوحة حيّة تُبقي ظاهرًا دائمًا (لا يختفي أثناء المراقبة): `Symbol · Order List ID · Current Price · Reference Price · Trigger Price · Current TP · Current SL · Next TP · Next SL · SL Limit · Tick Size · Monitoring State · Last Operation + Result · Connection · Environment`.
- أزرار: **Start** · **Pause/Resume** (لكل أمر) · **Kill Switch** (إيقاف كل المراقبة فورًا بلا إلغاء أوامر).
- تفاصيل المنطق في Deliverable 6.

## 3.6 F — Safe Execution flow (`05_safe_execution.html`)
شاشة/overlay تعرض خطوات التنفيذ الذرّي مرئيًا وبالترتيب. **ملاحظة تصميمية:** الترتيب هنا يُنقّح تسلسل البرومقت بحيث يُحسَب البديل ويُتحقَّق منه بالكامل **قبل** أي إلغاء (Pre-Cancel Validation Gate) — لتقليص "النافذة العارية" وتفادي إلغاء أمر ثم اكتشاف تعذّر وضع البديل:
```
① Re-verify selected OCO (ID/Symbol/Status/Identity)
② Get latest usable price + remaining quantity (بعد أي Partial Fill)
③ Recalculate levels (الأسعار الثلاثة) + تقريب tick/step + ترتيب صارم
④ 🛡️ Pre-Cancel Validation Gate  ← بوابة تحقّق مسبق قبل أي إلغاء
⑤ Cancel selected OCO only
⑥ Create replacement OCO
⑦ Confirm new orderListId
```
كل خطوة لها مؤشّر (pending/running/done/failed). عند الفشل تظهر الحالة الدقيقة (راجع Deliverable 7).

**🛡️ Pre-Cancel Validation Gate (الخطوة ④ — إلزامية):** قبل إرسال أي `DELETE`، يجب أن يجتاز البديل المحسوب **كل** الفحوص التالية؛ وأي إخفاق ⇒ **Abort مبكّر بلا أي إلغاء** (الأمر الأصلي يبقى سليمًا):
1. **الترتيب الصارم:** `Stop Limit < Stop Trigger < Last Price < TP` (SELL) — وإلا Abort.
2. **الفلاتر:** كل الأسعار مضاعفات `tickSize`؛ الكمية مضاعفات `stepSize` و`≥ minQty`.
3. **`minNotional`:** `remainingQty × price ≥ minNotional` لكل رِجل ذات سعر.
4. **الرصيد:** الأصل المتاح (بعد أي أوامر أخرى) يكفي الكمية المتبقية.
_لماذا: Binance لا يوفّر عملية `cancelReplace` ذرّية لقوائم OCO، فالتحقق المسبق هو خط الدفاع الأول ضد "النافذة العارية"._

> ⚠️ **Naked Window (نافذة بلا حماية) — قيد بورصة صريح:** لا يمكن استبدال OCO بشكل ذرّي على Binance Spot (`cancelReplace` متاح للأوامر المفردة فقط، لا لقوائم OCO). لذلك بين `Cancel` و`Create` توجد **لحظة يكون فيها المركز بلا حماية**. لا يمكن إلغاء هذا القيد؛ نُقلّصه فقط بـ: (أ) Pre-Cancel Validation Gate، (ب) هدف الزمن `≤ 3s`، (ج) عدم فصل السعر عن أحدث قيمة usable، (د) **No Blind Retry** ⇒ عند فشل `Create` بعد `Cancel` ناجح ننتقل فورًا إلى `FAILED_NEEDS_ATTENTION` مع تنبيه بشري صريح. **يجب إبراز هذه النافذة للمستخدم في UI أثناء الخطوتين ⑤–⑥.**

## 3.7 G — Demo Mode (داخل الواجهة)
ليس Unit tests فقط. المستخدم يرى الدورة كاملة بعينه: `Select → Set rules → Start → Price moves → Trigger → Reposition → New OCO → Monitoring continues` — قبل استخدام Binance الحقيقي. **فصل بصري واضح** (شارة DEMO) حتى لا يُخلَط مع Live.

## 3.8 عناصر عرضية عامة
- **I — Kill Switch:** زر واحد أحمر ثابت الوصول.
- **J — Audit Log:** شاشة/لوحة سجل دائم قابل للعرض والفلترة.
- **الحالات المرئية (Badges):** `Connected · Selected · Monitoring Active · Paused · Triggered · Repositioning · Success · Aborted · FAILED_NEEDS_ATTENTION` — كل حالة بلونها (GREEN/AMBER/RED/BLUE).

---

# Deliverable 4 — مواصفة تكامل Binance (Binance Integration Spec)

> **قاعدة حاكمة:** **البورصة هي المرجع.** لا قيود تجارية مخترعة. كل قيم العملة تُقرأ ديناميكيًا من `exchangeInfo`. تم التحقق من الـ endpoints أدناه مقابل واجهة Binance Spot الحالية.

## 4.1 Base URLs (التحويل إلى Live = تبديل إعداد فقط)
| البيئة | REST | Market WS | ملاحظات |
|--------|------|-----------|---------|
| **Testnet** | `https://testnet.binance.vision/api` | `wss://stream.testnet.binance.vision/ws` | البداية المعتمدة |
| **Live** | `https://api.binance.com` | `wss://stream.binance.com:9443/ws` | خلف بوابة تحقق |

**الفرق الوحيد بين البيئتين: `base URL` + المفتاح المستخدَم.** نفس مسار الكود بالكامل. _لماذا: يمنع تفرّع منطق Testnet/Live الذي سبّب ألمًا سابقًا._

## 4.2 الـ Endpoints المعتمدة
| الغرض | Method + Path | توقيع | Weight | ملاحظات |
|-------|---------------|:-----:|:------:|---------|
| قواعد العملة | `GET /api/v3/exchangeInfo?symbol=` | لا | متغيّر | يُخزَّن مؤقتًا (cache) ويُحدَّث دوريًا |
| السعر الحالي (fallback) | `GET /api/v3/ticker/price?symbol=` | لا | 1–2 | مصدر رئيسي للسعر = WS |
| الأوامر المفتوحة (OCO) | `GET /api/v3/openOrderList` | **نعم** | 3 | قائمة الـ order lists المفتوحة |
| تفاصيل OCO محدد | `GET /api/v3/orderList?orderListId=` | **نعم** | 2 | للتحقق قبل التنفيذ |
| **إنشاء OCO (المعتمد)** | `POST /api/v3/orderList/oco` | **نعم** | 1 | بنية `above`/`below` legs |
| **إلغاء OCO** | `DELETE /api/v3/orderList` | **نعم** | 1 | `symbol` + `orderListId` (يلغي الرِّجلين معًا) |
| فتح User Data Stream | `POST /api/v3/userDataStream` | مفتاح فقط | 1 | يعيد `listenKey` |
| إبقاء القناة حيّة | `PUT /api/v3/userDataStream` | مفتاح فقط | 1 | كل ~30 دقيقة |

> ❌ **القديم `POST /api/v3/order/oco` deprecated** — لا يُعتمد إطلاقًا.

## 4.3 الأسعار الثلاثة → خريطة الحقول (SELL OCO)
البنية الحقيقية = **رِجلان (2 legs)** لكن **3 أسعار (3 خانات)**. لا يجوز نمذجتها بسعرين.

| خانة المنتج | حقل Binance (`above`/`below`) | ملاحظة |
|-------------|------------------------------|--------|
| **TP / سعر الليمِت** (فوق السوق) | **above leg**: `aboveType=LIMIT_MAKER`, `abovePrice=TP` | LIMIT_MAKER بلا `timeInForce`/`stopPrice` |
| **Stop Trigger / سعر التفعيل** | **below leg**: `belowStopPrice = Stop Trigger` | التريجر |
| **Stop Limit / التنفيذ بعد التفعيل** | **below leg**: `belowType=STOP_LOSS_LIMIT`, `belowPrice = Stop Limit`, `belowTimeInForce=GTC` | **أسفل التريجر بالـ gap** |

**Common params:** `symbol`, `side=SELL`, `quantity`, `listClientOrderId`, `aboveClientOrderId`, `belowClientOrderId`, `recvWindow`, `timestamp`, `signature`.

**بديل مقبول لرِجل الـ TP:** `TAKE_PROFIT_LIMIT` (`aboveStopPrice`+`abovePrice`+`aboveTimeInForce=GTC`) — يبقى LIMIT_MAKER الافتراضي لأنه maker-only بلا رسوم taker.

## 4.4 ترتيب الأسعار الصارم (Binance ترفض غير ذلك — SELL)
```
Stop Limit Price  <  Stop Trigger Price  <  Last Price  <  TP Limit Price
```
- **قاعدة داخلية مصحّحة:** `Stop Limit = Stop Trigger − gap` (فرق صغير أسفل التريجر). ⚠️ **ممنوع نهائيًا** وضع Stop Limit فوق Stop Trigger. _لماذا: وضعه فوق التريجر قد يُرفض أو يترك الصفقة بلا حماية في سوق هابط._
- `gap` افتراضيًا 1–2 tick، ويُوسَّع للعملات المتقلبة لضمان التنفيذ.
- المستخدم يُدخل **النِّسب فقط**؛ النظام يحسب ويملأ الأسعار الثلاثة وفق هذا الترتيب (يدوي وديناميكي).

## 4.5 الكمية والفلاتر (تُطبَّق دائمًا)
| الفلتر | القاعدة | التطبيق |
|--------|---------|---------|
| **PRICE_FILTER** | `tickSize` | كل الأسعار = مضاعفات `tickSize` (تقريب) |
| **LOT_SIZE** | `stepSize`, `minQty` | الكمية = مضاعفات `stepSize` (**floor** للبيع كي لا تتجاوز الرصيد) و`≥ minQty` |
| **NOTIONAL / MIN_NOTIONAL** | `minNotional` | `quantity × price ≥ minNotional` لكل رِجل ذات سعر |

- **الكمية:** موروثة ومقفولة من الأمر المختار. عند إعادة التموضع: **الكمية المتبقية الفعلية** بعد أي Partial Fill (تُقرأ لحظة التنفيذ)، لا الأصلية.
- **⛔ حافة الكمية المتبقية (Partial-Fill edge):** إذا أصبحت `remainingQty × price < minNotional` **أو** `remainingQty < minQty` بعد Partial Fill ⇒ **يتعذّر إنشاء OCO بديل**. القرار المعتمد: **Abort مبكّر قبل أي `Cancel`** (ضمن Pre-Cancel Validation Gate) + تنبيه بشري صريح؛ يبقى الأمر الأصلي سليمًا ولا نقع في مركز عارٍ. _لماذا: الإلغاء ثم اكتشاف تعذّر البديل يترك المركز بلا حماية._
- **دقة السعر/الكمية:** من `exchangeInfo` (`tickSize`/`stepSize`) — **لا hardcode**. النظام symbol-agnostic.

## 4.6 التوقيع والأمان ضد `-1022`
- كل الطلبات الموقّعة: **HMAC SHA256** على query string (+body عند وجوده) بالمفتاح السري، مع `timestamp` (ms) و`recvWindow` (افتراضي 5000، أقصى 60000).
- **منع `-1022`:** ثبات ترتيب البارامترات وتضمين `timestamp`/`recvWindow` **قبل** التوقيع؛ توقيع بايتات query string نفسها المُرسَلة؛ التحقق من مزامنة الساعة.
- **معالجة `-1021` (Timestamp خارج recvWindow):** مزامنة ساعة العميل دوريًا مع `GET /api/v3/time` (serverTime) واحتساب **إزاحة (clock offset)** تُضاف إلى `timestamp` عند كل توقيع؛ عند ظهور `-1021` ⇒ **إعادة المزامنة + إعادة التوقيع مرة واحدة** (لا تكرار كتابة أعمى — راجع Idempotency). رفع `recvWindow` باعتدال خيار احتياطي لا بديل عن المزامنة. _لماذا: انزياح ساعة الجهاز سبب شائع لرفض الطلبات الموقّعة بجانب `-1022`._
- **تحقق عند الإقلاع (Preflight):** نداء موقّع خفيف (مثل قراءة الحساب/الوقت) للتأكد من صحة المفتاح والتوقيع للبيئة المختارة قبل أي عملية. _لماذا: يحسم "المفاتيح غير معرّفة" و`-1022` مبكرًا._

## 4.7 Rate Limits
- مراقبة رؤوس الاستجابة: `X-MBX-USED-WEIGHT-*` و`X-MBX-ORDER-COUNT-*`.
- التعامل مع `429` (Too Many Requests) و`418` (IP ban) بـ backoff محترم؛ عدم إعادة المحاولة العمياء لعمليات الكتابة (راجع Idempotency).

## 4.8 القنوات اللحظية (Streams)
- **Market WS:** `<symbol>@bookTicker` (أفضل bid/ask للسعر القابل للاستخدام) و/أو `@miniTicker`/`@trade` للسعر الحي. **مصدر السعر الرئيسي.**
- **User Data Stream:** عبر `listenKey` (`executionReport`, `listStatus`) لتتبّع حالة الأوامر/الـ OCO لحظيًا؛ keepalive كل ~30 دقيقة.
- **fallback:** REST `ticker/price` عند انقطاع WS، مع وسمه كـ "سعر REST" لا يوهم بأنه بث حي مستمر.

---

# Deliverable 5 — State Machine لدورة حياة الأمر (Order/List Lifecycle)

## 5.1 حالة القائمة (OCO List — `listOrderStatus`)
```
              create OK
   [PENDING]───────────► EXECUTING ──────────────┐
      │  create REJECT      │  (كلتا الرِّجلين NEW)   │ إحدى الرِّجلين تُنفَّذ/تُطلَق
      ▼                     │                       ▼
   REJECT               (partial fills على رِجل)   ALL_DONE
                                                   (الأخرى CANCELED/EXPIRED)
```
- `listStatusType`: `RESPONSE` → `EXEC_STARTED` → `ALL_DONE` (أو `REJECT`).

## 5.2 حالة الرِّجل الواحدة (Order — `status`)
```
NEW ──► PARTIALLY_FILLED ──► FILLED
  │            │
  └────────────┴──► CANCELED / EXPIRED / EXPIRED_IN_MATCH
```
- عند لمس أحد المستويات: رِجل → `FILLED`/`PARTIALLY_FILLED`، والأخرى تُلغى تلقائيًا (`CANCELED`/`EXPIRED`) والقائمة → `ALL_DONE`.

## 5.3 حالة هدف المراقبة داخل OCOBot (Monitoring Target)
```
DISCONNECTED ─connect+preflight→ CONNECTED ─select→ SELECTED
   SELECTED ─enable+Start→ MONITORING_ACTIVE
   MONITORING_ACTIVE ─price ≥ trigger (latched)→ TRIGGERED
   TRIGGERED ─begin safe exec→ REPOSITIONING
   REPOSITIONING ─create OK→ SUCCESS ─rollover(new orderListId)→ MONITORING_ACTIVE
   REPOSITIONING ─order gone before cancel→ ABORTED
   REPOSITIONING ─cancel OK & create FAIL→ FAILED_NEEDS_ATTENTION
   MONITORING_ACTIVE ─user Pause→ PAUSED ─Resume→ MONITORING_ACTIVE
   (any) ─Kill Switch→ MONITORING_STOPPED (بلا إلغاء أوامر)
   MONITORING_ACTIVE ─OCO filled/canceled externally→ CLOSED (stop + notify)
```
- **مبدأ مقفول:** `SUCCESS` ينقل المراقبة إلى `orderListId` الجديد (**OCO Identity Rollover**) — دائمًا هدف واحد.

---

# Deliverable 6 — مواصفة Dynamic Monitoring (النسخة النهائية)

## 6.1 مدخلات المستخدم (3 نِسب فقط)
1. `Reposition Trigger Rise %` (مثال 1%).
2. `TP Distance Above Current %` (مثال 4%).
3. `SL Distance Below Current %` (مثال 2%).

## 6.2 قواعد ثابتة (Invariants)
- **SL Limit داخلي** = `SL Trigger − gap` (أسفل التريجر؛ **ممنوع فوقه**؛ لا يدخله المستخدم).
- **Reference Price:** عند Start ⇒ `reference = current_live_price`، ثم انتظار ارتفاع بنسبة Trigger.
- **Trigger Latching:** بمجرد عبور مستوى الـ Trigger يُثبَّت الشرط ولا يُلغى لو رجع السعر قليلًا.
- **Latest Price Principle:** عند التنفيذ نحسب TP/SL من **أحدث سعر usable**، لا من سعر لحظة الـ Trigger.
- **القفز فوق أكثر من Trigger:** إعادة تموضع **واحدة فقط** من أحدث سعر، ثم يصبح المرجع الجديد.
- **One Replacement In-Flight:** لا دورة جديدة قبل انتهاء الجارية؛ نحتفظ بأحدث حالة سعر للدورة التالية.
- **OCO Identity Rollover:** بعد نجاح الإنشاء تنتقل المراقبة للـ `orderListId` الجديد.

## 6.3 هامش السماحية والحارس (Tolerance & Guard)
- **Tolerance band قابل للضبط:** لا يضيع التنفيذ إذا تراجع السعر قليلًا لحظة التنفيذ (مثلًا من 1% إلى 0.8–0.9%).
- **حارس أمان (Adverse-move guard):** لو تحرّك السعر عكسيًا أكثر من حدٍّ بين التحضير والتنفيذ ⇒ قرار واضح: **تنفيذ من أحدث سعر** أو **إيقاف + تنبيه** (لا مستويات خاطئة).

## 6.4 pseudocode توضيحي (قصير — للفكرة فقط)
```
on price_tick(p):
  if state==ACTIVE and not latched and p >= reference*(1+trigger%): latched=true
  if latched and no_reposition_in_flight:
      last = latest_usable_price()
      if adverse_move(last) > guard: decide(execute_latest | halt_notify); return
      levels = compute(last, tp%, sl%, gap, filters)   # 3 prices, remaining qty
      execution.safe_replace(orderListId, levels)       # atomic; sets in_flight
```

## 6.5 مثال رقمي (توضيحي — رموز/أرقام أمثلة فقط)
بداية `0.05000`، Trigger 1% ⇒ تفعيل عند `0.05050`. أحدث سعر `0.05060` ⇒ `TP=+4%=0.05262`، `SL Trigger=-2%=0.04959`، `SL Limit=0.04958` (أسفل التريجر، `tick=0.00001`). كل القيم تُقرّب لـ `tickSize` وتُتحقّق مقابل الفلاتر.

## 6.6 Pause/Resume
إيقاف الحركة الديناميكية لأمر مختار مع **إبقاء الـ OCO الحقيقي كما هو تمامًا** (لا يُلغى/يُعدّل)، ثم استئناف من نفس النقطة. حالة `PAUSED` ضمن state machine.

---

# Deliverable 7 — مصفوفة حالات الفشل والحواف + نصوص الرسائل

## 7.1 قرارات الفشل الجوهرية
| السيناريو | القرار | الحالة | Blind Retry؟ |
|-----------|--------|--------|:------------:|
| الأمر لم يعد موجودًا قبل التنفيذ | **لا Replacement** | `ABORTED` | لا |
| الكمية المتبقية بعد Partial Fill < `minNotional`/`minQty` | **Abort مبكّر قبل أي Cancel** (Pre-Cancel Gate) + تنبيه | `ABORTED` | لا |
| Cancel فشل | **لا Create** | `ABORTED` | لا |
| **Cancel نجح & Create فشل** | تدخّل يدوي | `FAILED_NEEDS_ATTENTION` | **لا — إطلاقًا** |
| OCO المُراقَب نُفِّذ/أُلغي خارجيًا | إيقاف فوري + تنبيه | `CLOSED` | لا |
| ضياع رد الشبكة بعد إرسال أمر | **تحقّق أولًا** عبر `clientOrderId` قبل أي إعادة | حسب النتيجة | لا (idempotent check) |
| `429/418` Rate limit | backoff محترم، تأجيل لا تكرار كتابة | يبقى `MONITORING_ACTIVE` | لا |
| `-1022` توقيع | إيقاف + إعادة preflight | خطأ اتصال | لا |
| `-1021` timestamp خارج recvWindow | مزامنة الوقت (serverTime offset) + إعادة توقيع مرة واحدة | خطأ اتصال | لا |
| انقطاع WS | fallback REST + إعادة اتصال | تنبيه "سعر REST مؤقت" | — |

## 7.2 Idempotency (منع التكرار على المال الحقيقي)
`newClientOrderId`/`listClientOrderId` **فريد لكل إنشاء/إلغاء**. عند ضياع الرد: **يُتحقَّق من وجود الأمر أولًا** بدل تكراره. _لماذا: يمنع أوامر مكرّرة._

## 7.3 نصوص الرسائل (بشرية — لا `Exception: ...`)
| الحدث | النص |
|-------|------|
| Cancel نجح/Create فشل | "تم إلغاء الأمر المحدد، لكن إنشاء البديل فشل — **لا توجد إعادة محاولة تلقائية**. تدخّل يدوي مطلوب." |
| الأمر اختفى قبل التنفيذ | "الأمر لم يعد موجودًا — تم إلغاء إعادة التموضع (Aborted)، ولم يُنشأ أي بديل." |
| OCO أُغلق أثناء المراقبة | "الصفقة أُغلقت / الأمر لم يعد نشطًا — توقفت المراقبة تلقائيًا." |
| فشل توقيع | "تعذّر الاتصال الآمن بـ Binance (توقيع غير صالح) — تحقّق من المفاتيح والبيئة." |
| Rate limit | "تم تجاوز حد الطلبات مؤقتًا — سنعيد المحاولة بعد قليل دون تكرار أي أمر." |
| Kill Switch | "تم إيقاف كل المراقبة النشطة فورًا. **لم يُلغَ أي أمر على Binance.**" |

**قاعدة شفافية:** لا يبدو النظام "شغّالًا" وهو متوقف فعليًا — الحالة المرئية تعكس الواقع دائمًا.

---

# Deliverable 8 — الأمان والإعداد (Config & Security)

## 8.1 تحميل المفاتيح تلقائيًا
- المسار الافتراضي (قابل للتهيئة): `D:\فولدرات\مفتاح بنانس\key.txt`.
- **تنسيق مقترح واضح يفصل البيئتين:**
```
TESTNET_KEY=...
TESTNET_SECRET=...
LIVE_KEY=...
LIVE_SECRET=...
```
- عند الإقلاع: التحقق من وجود الملف + صلاحية المفاتيح **للبيئة المختارة** + إظهار حالة الاتصال بوضوح.

## 8.2 تدرّج البيئات (Env tiers)
```
Demo/Paper → Testnet → Validated → Live
```
- **نبدأ ببوت Testnet**؛ بعد الاعتماد يتحوّل إلى Live. **Live خلف بوابة تحقق**، ليس زرًا مفتوحًا من البداية.

## 8.3 قواعد أمان
- **لا تُسجَّل المفاتيح في أي log إطلاقًا** (redaction إلزامي).
- صلاحيات المفتاح: **تداول فقط، بدون Withdrawals**.
- توصية **IP whitelisting**؛ حماية ملف المفاتيح على القرص؛ **عدم رفعه لأي repo** (gitignore).
- **التحويل إلى Live = تبديل إعداد فقط** (base URL + مفتاح) — نفس مسار الكود.

---

# Deliverable 9 — نموذج البيانات والتخزين (Persistence)

## 9.1 الكيانات (منطقية)
| الكيان | الحقول الأساسية |
|--------|-----------------|
| **SelectedOCO** | `orderListId, symbol, quantity, tp, stopTrigger, stopLimit, legIds[], status, currentPrice@t` |
| **Draft** | `mode(manual/dynamic), tp%, sl%, gap, computed{tp, trigger, limit}, remainingQty, oldValues{}` |
| **MonitoringState** | `enabled, state, reference_price, trigger%, tp%, sl%, latched, in_flight, target_orderListId, cursor, tolerance, guard` |
| **AuditRecord** | `ts, action(cancel/create/reposition), priceUsed, old{}, new{}, result(success/fail/abort), clientOrderIds, message` |
| **AppConfig** | `env(testnet/live), keysPath, baseUrls, gapDefault, tolerance, guard, recvWindow` |
| **ExchangeInfoCache** | `symbol → {tickSize, stepSize, minQty, minNotional, updatedAt}` |

## 9.2 قواعد التخزين
- **Persisted باستمرار:** `MonitoringState` (+ `reference_price` + cursor + الأمر المُراقَب) و`AuditRecord` و`AppConfig`.
- **Runtime Recovery:** عند إعادة التشغيل بعد إغلاق/تعطّل ⇒ استئناف المراقبة تلقائيًا من آخر وضع دون فقد. (لا يُعاد لمس الأمر إن كان قد أُغلق — يُتحقَّق أولًا.)
- **صيغة مقترحة:** ملف/قاعدة محلية خفيفة (JSON/SQLite) — قرار تفصيلي في مرحلة التنفيذ. Audit Log **append-only**.
- **الاتساق:** كتابة `AuditRecord` قبل/بعد كل خطوة تنفيذ حرجة (before-cancel، after-create) لضمان تتبّع كامل حتى عند التعطّل.

---

# Deliverable 11 — خطة المراحل (Roadmap · Testnet-first)

> تقدير المجهود نسبي (S ≈ صغير، M ≈ متوسط، L ≈ كبير) لا زمن مطلق. كل مهمة لها Definition of Done في `PROJECT_STATE.json`. الجدول التالي على مستوى المرحلة؛ و**تقدير المجهود لكل مهمة (T0–T7)** مسجّل في حقل `effort_estimate` داخل `task_ledger` في `PROJECT_STATE.json` (ومكرَّر في جدول المهام أدناه).

| المرحلة | المهام | تقدير |
|---------|--------|:-----:|
| **M0 — Foundation** | Connectivity (REST موقّع + preflight `-1022`) · تحميل المفاتيح · اختيار البيئة | M |
| **M1 — Read & Select (Testnet)** | exchangeInfo cache · `openOrderList` · جدول Orders · Selected OCO · Dashboard قراءة فقط | M |
| **M2 — Manual Edit + Safe Execution** | Draft بالنِّسب · حساب الأسعار الثلاثة + الفلاتر · Live panel/Max Stop · Activate → safe cancel/create + Idempotency | L |
| **M3 — Dynamic Monitoring** | Market WS + reference/trigger/latch · Latest Price · Tolerance/Guard · Rollover · Pause/Resume · Kill Switch | L |
| **M4 — Resilience & UX** | User Data Stream · Runtime Recovery · Audit Log · مصفوفة الفشل + الرسائل · Demo Mode | M |
| **M5 — Validated** | تشغيل شامل على Testnet + مراجعة أمان/حواف + معايير القبول | M |
| **M6 — Live (بوابة)** | تبديل إعداد فقط + بوابة تحقق + IP whitelist + مراقبة رؤوس Rate limit | S |

**تقدير المجهود لكل مهمة (مطابق لحقل `effort_estimate` في `task_ledger`):**

| المهمة | العنوان المختصر | تقدير |
|--------|-----------------|:-----:|
| T0 | المستند التصميمي + PROJECT_STATE | M (مكتمل) |
| T1 | M0 — Foundation (Connectivity + مفاتيح + preflight) | M |
| T2 | M1 — Read & Select | M |
| T3 | M2 — Manual Edit + Safe Execution (+ Pre-Cancel Gate) | L |
| T4 | M3 — Dynamic Monitoring | L |
| T5 | M4 — Resilience & UX | M |
| T6 | M5 — Validated | M |
| T7 | M6 — Live (بوابة) | S |

**الترتيب المقفول:** `Testnet-first → Validated → Live`. لا Live قبل اجتياز M5 **ولا قبل بوابة اعتماد بشري (G1): إعلان اكتمال البوت التجريبي + تجربة المستخدم اليدوية + عبارة اعتماد صريحة**. مهام Live (T7) تبقى `blocked` حتى تُجتاز G1.

---

# Deliverable 12 — الأخطاء الواجب منعها + المخاطر + Open Questions

## 12.1 أخطاء ماضية يمنعها التصميم صراحةً
- **تفرّع الهوية** (بقايا Buy/Market/Trade Setup) ⇒ **OCO management فقط، بلا legacy**.
- **شكل غير موحّد** (فاتح+داكن) ⇒ هوية بصرية واحدة (Palette + RTL).
- **Live Price غير حقيقي / Preview ثابت** ⇒ سعر حي حقيقي + فصل واضح Demo/Live.
- **`-1022` ومفاتيح غير محمّلة** ⇒ تحميل تلقائي + preflight.
- **وثائق بقواعد قديمة** ⇒ مصدر حقيقة واحد (`PROJECT_STATE.json`).
- **تجربة موزّعة كأدوات منفصلة** ⇒ دورة End-to-End واحدة.
- **Blind Retry بعد Cancel ناجح** ⇒ ممنوع؛ `FAILED_NEEDS_ATTENTION`.
- **نمذجة OCO بسعرين** ⇒ ممنوع؛ 3 أسعار دائمًا.

## 12.2 المخاطر (Risks)
| الخطر | التخفيف |
|-------|---------|
| رفض Binance لترتيب الأسعار | تطبيق الترتيب الصارم + الفلاتر قبل الإرسال (تحقّق مسبق) |
| Partial fill يغيّر الكمية | قراءة الكمية المتبقية لحظة التنفيذ |
| تقلّب حاد بين التحضير والتنفيذ | Tolerance band + Adverse-move guard |
| ازدواج أوامر عند ضياع الرد | Idempotency عبر clientOrderId + تحقّق-قبل-إعادة |
| **Naked Window** بين Cancel وCreate — **قيد بورصة** (لا يوجد `cancelReplace` ذرّي لقوائم OCO) | Pre-Cancel Validation Gate + `≤3s` + السعر من أحدث قيمة usable + **No Blind Retry** ⇒ `FAILED_NEEDS_ATTENTION` + **إبراز النافذة صراحةً في UI** أثناء الخطوتين ⑤–⑥ |
| الكمية المتبقية بعد Partial Fill تسقط تحت `minNotional`/`minQty` | Pre-Cancel Gate يكشفها ⇒ **Abort مبكّر قبل أي Cancel** (لا مركز عارٍ) |
| انزياح ساعة الجهاز (`-1021`) | مزامنة `serverTime` + clock offset عند التوقيع + إعادة توقيع واحدة |
| deprecation لقنوات listenKey مستقبلًا | عزل Connectivity Layer ليسمح بالانتقال لـ WS API user-data دون لمس المنطق |

## 12.3 Open Questions (لا تدخل التصميم الأساسي)
1. دعم **BUY OCO** لاحقًا (الآن SELL فقط) — يتطلب عكس الأدوار above/below.
2. صيغة التخزين النهائية (JSON مقابل SQLite) — تُحسم في M2/M4.
3. مصدر السعر "usable" الأمثل (`bookTicker` bid مقابل last trade) لدقّة الـ SELL.
4. سياسة توسيع `gap` تلقائيًا حسب تقلّب العملة (معادلة الضبط الدقيقة).

---

# Deliverable 13 — ميزات التحكم والمرونة (Control & Resilience)

| الميزة | السلوك المعتمد |
|--------|----------------|
| **Pause/Resume (لكل أمر)** | إيقاف الحركة الديناميكية مع إبقاء الـ OCO الحقيقي كما هو تمامًا؛ استئناف من نفس النقطة. حالة `PAUSED`. |
| **Kill Switch** | زر واحد يوقف **كل** المراقبة النشطة فورًا **دون إلغاء أي أوامر على Binance**. |
| **Audit Log** | سجل دائم append-only لكل reposition/execution (الوقت، السعر، القديم/الجديد، النتيجة) قابل للعرض والمراجعة. |
| **Runtime Recovery** | استئناف تلقائي بعد إغلاق/تعطّل من آخر وضع (state + reference + cursor + الأمر). |
| **Live = تبديل إعداد** | لا تغيير منطقي؛ فقط base URL + المفتاح، خلف بوابة تحقق. |

---

## معيار "أنك انتهيت" (Definition of Done للمستند)
- ✅ كل قرار تصميمي معه سبب/trade-off موجز.
- ✅ لا شيء مخترع خارج النطاق (الأفكار الإضافية في Open Questions فقط).
- ✅ المستند يكفي أي فريق/نموذج للتنفيذ دون أسئلة أساسية.
- ✅ **لم يُكتب أي كود تطبيقي** — تصميم فقط.
- ✅ الـ 13 deliverable مغطّاة + `PROJECT_STATE.json` (Deliverable 10) كملف منفصل في جذر المشروع.

**التالي للنموذج المنفّذ:** اقرأ `PROJECT_STATE.json` فقط، خذ المهمة `status=next`، نفّذها ذرّيًا، تحقّق، حدّث الـ ledger والـ cursor، اكتب handoff، ثم قف.

---

## ملحق تنفيذ G1.11 — طبقة الاتصال المرنة (مزامنة توثيق)

أُضيفت شاشة اتصال جديدة `07_connection` (الاتصال بالحساب) في `ocobot/ui/connection_screen.py`، مسجّلة في `ocobot/ui/screens.py` و`ocobot/ui/content.py`. تتيح إدخال `API Key` و`API Secret` (مقنّع `*****`) يدويًا أو اختيار ملف `txt` عبر «فتح ملف»، وزر «اتصال» يشغّل اختبار `/api/v3/account` (قراءة فقط، Testnet) عبر `ocobot/core/connection.py::make_gui_connect_handler` ثم `test_connection`، ويُظهر لمبة حالة: خضراء «متصل» / حمراء «خطأ اتصال» / كهرمانية «جارٍ الاتصال» / «غير متصل». أولوية مصدر المفاتيح: الحقول ثم الملف المختار ثم المسار الثابت القديم كـfallback. الإقلاع لا يتعطّل عند غياب المسار الثابت. لا مساس بـ`signed_request`/`monitoring_loop`/`create_oco_only`/`buy_and_oco` — تغيّر مصدر المفاتيح فقط. الدليل: `_g1_11_run.txt` (Ran 285 tests OK).

---

## ملحق تنفيذ G1.14 — فرع الصفقات المنتهية (مزامنة توثيق)

أُضيفت شاشة جديدة `08_completed_trades` (الصفقات المنتهية) في `ocobot/ui/completed_trades.py`، مسجّلة في `ocobot/ui/screens.py` (مُدخل جديد في `SCREENS`) و`ocobot/ui/content.py` (استيراد `CompletedTradesScreen` + فرع `elif key == "08_completed_trades"` في `ContentRouter`). الشاشة عربية بالكامل عدا الأرقام ورمز العملة (`$`) ورمز العملة التداولية (symbol)، RTL + ثيم داكن عبر `PALETTE` (D15)، وعدد الشاشات صار 8.

الشاشة **قراءة فقط** مقسومة نصفين (مطابقة لـ`docs/ui_mockups` بالاصطلاح):
- النصف العلوي: قائمة رأسية بالصفقات المنتهية (CLOSED) قابلة للاختيار مع تمرير بعجلة الماوس، وزرّان: «مسح الصفقة المحددة» و«تفاصيل الصفقة».
- النصف السفلي: جدول تفاصيل سلسلة التموضع للصفقة المحددة (التاريخ/الوقت الدقيق `ts`، السعر المرجعي/الدخول، سعر الإيقاف، سعر البيع، سلسلة إعادة التموضع، والربح `$`/`%`) مع تمرير بعجلة الماوس.

كل البناء/الحساب/الإخفاء يمرّ عبر طبقة الـ domain `ocobot/domain/completed_trades.py` (`load_completed_trades` + `build_completed_trades` + `compute_profit` + `DismissStore`)؛ ولا تُجري الشاشة أي شبكة أو IO مباشر (تحترم حارس الواجهة ضدّ النداءات الشبكية المباشرة). القرارات: DS1 المسح = إخفاء عبر `DismissStore` (ملف JSON منفصل) لا حذف من سجلّ التدقيق append-only؛ DS2 سعر البيع يُلتقط إضافيًّا append-only عبر `on_order_event` (`build_fill_recorder` → `trade_closed_fill`) والصفقات القديمة تُظهر «غير متاح»؛ DS3 الربح دالة نقية `pct=(exit-reference)/reference*100` و`usd=(exit-reference)*quantity` من `reference_price` عند `monitor_start`؛ DS4 لا توجد نقطة تجميع إنتاجية تُنشئ `UserDataStreamConsumer` بعد (لا ربط T16/Live)، فتعرض الواجهة «غير متاح» حيث لا تتوفّر بيانات حيّة. اختبار التنقّل في `tests/test_ui_navigation.py` يثبت تسجيل الشاشة وقابلية الوصول إليها وعدد الشاشات = 8. الدليل: `tests/_g1_14_run.txt`.
