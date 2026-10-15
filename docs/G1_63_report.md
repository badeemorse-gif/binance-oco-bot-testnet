# تقرير G1.63 — تنبيه الخروج اليدوي الفوري في كل حالة

## المشكلة (كما أبلغ المستخدم أثناء التجربة اليدوية)
عند الضغط على زرّ «تنفيذ الخروج الفوري» لا يصل أي إشعار Telegram في الحالات الشائعة،
واحتمال عدم وصول إشعار عند إتمام الصفقة بهذه الوسيلة.

## السبب الجذري (بالفحص)
- `domain/market_exit.execute_market_exit` يستدعي `notifier(result)` على **PLACED فقط**
  (بعد بناء نتيجة الوضع). كل مسارات ABORT (ABORT_PROTECTED عند وجود OCO/بيع حمائي قائم،
  ABORT_NO_FREE_QTY، ABORT_GATE، ABORT_NO_SELECTION، ABORT_INVALID_FILTERS، ERROR) تعود
  مبكرًا **دون** استدعاء notifier ⇒ صمت تام عند الضغط. وهذه الحالات شائعة لأن أمر OCO
  القائم يحجز الرصيد الحرّ.
- `manual_exit_record` لا يحمل `placed`، و`build_manual_exit_message` لا يعرض نتيجة/سبب
  عدم التنفيذ.

## الحل (إضافي بحت — لا مساس بأي نجاح)
- **`ocobot/alerts/bridge.py`** (`manual_exit_record`): إضافة `placed`/`reason`/`error`
  إلى `details` (إضافي).
- **`ocobot/alerts/formatting.py`** (`build_manual_exit_message`): فرع جديد عند
  `placed=False` يعرض رسالة واضحة «✋ Manual Exit (not placed)» + `Action` + `Note`
  إنجليزية موجزة بالسبب (§1.5). مسار المنفَّذ (`placed=True`/غير محدَّد) يبقى **كما هو
  تمامًا** (الحقول القياسية Entry/Exit/PnL%).
- **`ocobot/ui/manual_exit.py`** (`build_manual_exit_fn`): إطلاق notifier لكل نتيجة غير
  منفَّذة (بعد المنفّذ، وفي مسارَي «لا تحديد» و«خطأ» المبكِّرَين) حتى لا يبقى الضغط
  صامتًا — مع تفادي الازدواج: المنفَّذ (PLACED) يُطلِقه `execute_market_exit` مرّة واحدة،
  ومسار chase (`bid_getter`) يُطلِق لكل النتائج داخليًا فلا نُكرِّر عند تفعيله.

## الدلالة بعد الإصلاح
- **بعد كل ضغطة** تصل رسالة: المنفَّذ ✋ بتفاصيل الدخول/الخروج/الكمية/PnL% (= تفاصيل
  الصفقة عند الإتمام بهذه الوسيلة)، وغير المنفَّذ ✋ (not placed) بالسبب الواضح.
- **إغلاق الجلسة** 🏁 (`monitor_closed` من G1.62) يبقى عبر كشف الإغلاق العادي.
- رسالة المنفَّذ القياسية والمُطلِقات الأخرى بلا انحدار؛ لا hot_path ولا Live.

## الملفات المتأثّرة
- `ocobot/alerts/bridge.py`
- `ocobot/alerts/formatting.py`
- `ocobot/ui/manual_exit.py`
- `tests/test_g1_63_manual_exit_alert.py` (جديد — 6 اختبارات)

## معايير القبول
- غير المنفَّذ (ABORT_GATE / ABORT_NO_SELECTION) يُشعِر مرّة واحدة برسالة «not placed». ✓
- المنفَّذ (PLACED) يُشعِر مرّة واحدة فقط (بلا ازدواج). ✓
- رسالة المنفَّذ القياسية (Entry/Exit/PnL%) بلا انحدار. ✓
- `manual_exit_record` يحمل `placed`/`reason`. ✓

## الدليل
`python tools/_run_suite_per_file.py` ⇒ `TOTAL ran=995 failures=0 errors=0 files=126 status=OK`
(منها `test_g1_63_manual_exit_alert = 6`). §1.5: رسائل تليجرام إنجليزية — لا نصّ Qt عربي جديد.
