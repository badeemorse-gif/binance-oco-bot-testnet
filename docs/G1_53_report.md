# تقرير G1.53 — مُجمِّع ربحية خالص لكل وضع + telemetry تنفيذ الخروج

**المعرّف:** G1.53 · **الخطورة:** major · **البوّابة:** G1 (Testnet) · **human_gate:** false
**يعتمد على:** G1.52 (مختوم) · **الحالة:** implemented → verified (هذا التقرير) → sealed

---

## 1) الهدف
إضافة طبقتين **خالصتين قراءةً** فوق البنية القائمة، دون أي لمس للمسار الحار (hot_path)
ودون تغيير أي قرار تنفيذ:
1. **مُجمِّع ربحية خالص** `profitability_by_mode` يُجمّع الصفقات المنتهية (CLOSED)
   حسب «وسيلة الخروج» (`exit_source`) ويُنتج لكل وضع مقاييس احترافية بـ`Decimal`.
2. **telemetry تنفيذ الخروج** (`exit_execution`): سجلّ append-only يُكتب عبر
   `audit_sink` **محقون default None** (opt-in ⇒ لا انحدار) من داخل
   `execute_exit_chase` / `execute_market_exit` — القيم كانت تُحسب أصلًا وتُهمَل.

---

## 2) النطاق (scope_boundary)
- **داخل النطاق:**
  - `ocobot/domain/profitability.py` (جديد): المُجمِّع الخالص + قارئ telemetry +
    `net_pnl`.
  - `ocobot/domain/market_exit.py`: كتابة `exit_execution` عبر `audit_sink` DI
    (opt-in) + التقاط العمولة (best-effort) — **بلا تغيير سلوك**.
  - `ocobot/domain/completed_trades.py`: **قراءة فقط** (إعادة استخدام
    `CompletedTrade`/`build_completed_trades` دون أي تعديل).
- **خارج النطاق (لم يُمَسّ):** hot_path، أي قرار تنفيذ، أي Live/T16.

---

## 3) التغييرات بالتفصيل

### 3.1 `ocobot/domain/profitability.py` (جديد، خالص، مكتبة قياسية فقط)
- `profitability_by_mode(trades, exit_executions=None) -> Dict[str, ModeProfitability]`
- `extract_exit_executions(records) -> List[dict]` (قارئ telemetry: يحوّل الحقول
  الرقمية إلى `Decimal` و`reached_floor`/`dry_run` إلى منطقي، متسامح مع التلف).
- `net_pnl(gross_usd, commission_usd) -> Optional[Decimal]` (chunk_3).
- `ModeProfitability` (dataclass): `mode, n, win_rate, avg_return_pct, net_usd,
  expectancy, n_exec, avg_slippage_pct, floor_rate`.

**تعريف المقاييس لكل وضع (موثّق صراحةً):**
- `n` = عدد الصفقات المنتهية المنسوبة للوضع.
- `win_rate` = |profit_pct > 0| / n × 100.
- `avg_return_pct` = متوسّط `profit_pct` على الصفقات التي تتوفّر لها نسبة ربح فقط
  (`None` إن لا توجد).
- `net_usd` = مجموع `profit_usd` المتاح (صفر إن لا يوجد).
- `expectancy` = net_usd / n (`None` إن n=0).
- عند توفّر telemetry حقيقي (`dry_run == False`) للوضع:
  `avg_slippage_pct` = متوسّط `slippage_pct`، و`floor_rate` = |reached_floor|/n_exec×100،
  و`n_exec` = عدد سجلّات التنفيذ الحقيقية. **سجلّات dry_run تُستبعَد كليًّا.**

كل الحساب على `Decimal` حصراً — لا `float` للمال إطلاقًا. الصفقة المفتوحة
(`status == "live"`) والعناصر بلا `exit_source` تُقصى.

### 3.2 `ocobot/domain/market_exit.py` (إضافة بحتة opt-in)
- دالة خالصة `build_exit_execution_record(...)` تبني تفاصيل سجلّ `exit_execution`.
- مُرسِل آمن `_emit_exit_execution(audit_sink, details)` — `None` ⇒ لا شيء؛ أي
  استثناء من السِّنك **يُبتَلع** فلا يُفشِل الخروج أبدًا.
- حُقنت في `execute_market_exit` و`execute_exit_chase` معاملات **اختيارية**:
  `audit_sink=None, source="", trade_uid=""` (keyword-only، لا تغيّر أي توقيع قائم).
- نقاط الإرسال: مسار dry_run (dry_run=True) ومسار النتيجة الفعلية (dry_run=False)
  في كلتا الدالتين — **فقط حين `audit_sink is not None`** ⇒ صفر أثر وصفر انحدار
  عند الغياب.
- `sum_commission(resp)` (chunk_3): يجمع العمولة best-effort من شكلَي Binance
  (`executionReport` بحقلَي `n`/`N`، أو `fills[].commission/commissionAsset`).
  حقلا `commission`/`commission_asset` يُضافان للسجلّ **فقط عند توفّر عمولة** ⇒
  السجلّ مطابق لسكيمة chunk_2 عند غيابها.

**سكيمة سجلّ `exit_execution`:** `source, exit_side, order_type∈{LIMIT_IOC,
MARKET, STOP_LOSS_LIMIT, LIMIT}, tif, requested_price, filled_price, live_bid,
slippage_pct, band_pct, attempts_used, reached_floor, floor_price, qty, trade_uid,
dry_run` (+ `commission, commission_asset` اختياريان). القيم `Decimal` تُسلسَل
كنصوص عبر `AuditLog.record(default=str)` وتُعاد إلى `Decimal` عند القراءة.

---

## 4) قرارات التصميم (مُسجّلة)
- **opt-in صارم:** `audit_sink` default None، والإرسال محصور بـ`if audit_sink is not
  None` ⇒ ضمان رياضي بعدم تغيير سلوك المسارات القائمة.
- **لا تلويث للمقاييس من المعاينات:** تجميع الـtelemetry (slippage/floor) يستبعد
  `dry_run=True`.
- **صدق البيانات:** `filled_price` غير مُتتبَّع فرديًّا في الـchase ⇒ يُترك `None`
  بدل تلفيقه؛ `slippage_pct` هي القيمة المحسوبة أصلًا (مرجع البداية مقابل آخر سعر مطلوب).
- **العمولة بلا تحويل عملات:** `net_pnl` يطرح العمولة فقط إن كانت بعملة الاقتباس
  نفسها؛ لا تحويل FX في هذه الطبقة (مسؤولية المُستدعي) — لذا `net_usd` يبقى إجماليًّا.

---

## 5) الاختبارات (جديدة، بلا شبكة/Qt)
- `tests/test_g1_53_profitability.py` — 7 اختبارات (مقاييس دقيقة على مقطع تخليقي،
  إقصاء live، معالجة الربح الغائب، telemetry حقيقي فقط، أنواع Decimal).
- `tests/test_g1_53_exit_telemetry.py` — 7 اختبارات (opt-in بلا انحدار، dry_run
  بلا أثر جانبي، التقاط القيم المحسوبة، سِنك يرمي لا يكسر الخروج، PLACED، تكامل
  مع القارئ).
- `tests/test_g1_53_commission.py` — 9 اختبارات (`sum_commission` بالشكلين،
  التقاط العمولة، بقاء سكيمة chunk_2 عند الغياب، القارئ، `net_pnl`).
- **مجموع G1.53:** 23 اختبارًا — خضراء (OK).

---

## 6) الفحوص مقابل acceptance_checks
- ✅ المقاييس لكل وضع صحيحة على مقطع تخليقي (اختبار قيم Decimal دقيقة).
- ✅ `exit_execution` تُكتب append-only (عبر `AuditLog.record`) وبقيم `Decimal`.
- ✅ `audit_sink` default None ⇒ لا انحدار (محصور بشرط صريح + اختبار مخصّص).
- ✅ لا لمس hot_path (التغييرات في طبقة domain المعزولة فقط).
- ✅ كامل السويت أخضر ≥ baseline (انظر §7).

---

## 7) أدلّة التشغيل (baseline مقابل بعد)
- **baseline (قبل G1.53):** `Ran 739 tests` — `OK`.
- **بعد G1.53 (كامل السويت):** `TESTS_RUN=762 FAILURES=0 ERRORS=0 SKIPPED=0 SUCCESS=True`
  (739 + 23 اختبار G1.53 الجديد). صفر فشل وصفر خطأ ⇒ أخضر ≥ baseline.

---

## 8) الأثر على G1.54 (التالي)
`G1.54` (لوحة ربحية احترافية عرض-فقط في شاشة `08_completed_trades`) يستهلك مباشرةً:
`profitability_by_mode` للأرقام لكل وضع، و`extract_exit_executions` لمقاييس التنفيذ،
و`net_pnl` عند توفّر عمولة بعملة الاقتباس. لا تبعية على أي قرار تنفيذ.

## 9) الأمان
لا أي Live/T16 — محظور قبل اجتياز بوّابة G1 (§10.5). كل التغييرات معزولة وقابلة
للاختبار بالكامل بلا شبكة.
