# تشخيص G1.49 — لمس القوس الكاذب وخطر تعليق أمر الخروج

الطور: `G1_MANUAL_TESTING` — Testnet فقط، لا Live. وثيقة تشخيص (chunk_1).

## العَرَضان المُبلَّغ عنهما (تجربة يدوية)
1. القوس كتب «تم ملامسة الحد العلوي» بينما السعر الحيّ لسه ~0.8% **تحت** الحد العلوي.
2. أمر البيع الناتج ظهر ~1% **فوق** السعر الحيّ ⇒ خطر **تعليق** (الأمر يرقد فوق السوق بدل التنفيذ الفوري).
(الصفقة انتهت قبل ~8 ساعات بلا أثر محفوظ في `ocobot_audit.jsonl`؛ فالتشخيص كود-level + اختبار انحدار يحاكي الـwick.)

## المسار الفعلي على القرص
- `ocobot/domain/bracket.py` → `BracketMonitor.check(price)`:
  - يطلق فورًا عند `price >= upper` (علوي) أو `price <= lower` (سفلي).
  - يضبط الـlatch `self._fired = True` **قبل** استدعاء المُنفّذ المحقون.
  - **لا يوجد debounce**: tick لحظي واحد (wick) يكفي للإطلاق.
- `ocobot/ui/bracket_wiring.py` → `tick()`: يقرأ `price = price_getter()` ثم `monitor.check(price)`؛ و`_exit(exit_side, price)` يستدعي `execute_market_exit(reference_price=price, ...)`.
  - أي أن **سعر الإطلاق نفسه هو السعر المرجعي للأمر**.
- `ocobot/ui/app.py` → `_bx_price()` يرجّع `_screen._current_price` ومصدره تغذية `bookTicker` (أفضل BID) من `ocobot/core/market_feed.py`.
- `ocobot/domain/market_exit.py` → `plan_market_exit` للخروج العلوي: `type=LIMIT`, `price = round_to_tick(ref * (1 - slip_pct/100))`، و`DEFAULT_SLIP_PCT = 0.1%` ⇒ `limit = trigger × 0.999`.
- `ocobot/ui/monitoring.py` → رسالة «ملامسة الحد %s» تُبنى في مسار العرض `ORDER_PLACED` (G1.34) من نتيجة النبضة.

## الآلية الجذرية
شمعة/wick لحظية في الـBID تلمس `upper` للحظة ثم ترتدّ:
1. `check()` يطلق فورًا (بلا debounce) ويضبط الـlatch ويبني رسالة «ملامسة الحد العلوي».
2. السعر المرجعي للأمر = سعر الـwick (≈ `upper`) ⇒ `LIMIT = upper × 0.999`.
3. السعر الحيّ المستقر رجع ~0.8% تحت `upper` ⇒ أمر البيع صار ~0.7–1% **فوق** السوق ⇒ **يرقد/يعلّق** بدل التنفيذ.

هذا يفسّر العَرَضين معًا: الإطلاق على wick (رسالة ملامسة مبكرة) + أمر مرساه سعر الـwick (أعلى من السوق المستقر).

## اتجاه الإصلاح (chunks 2–4) — لا يمسّ hot_path
- **chunk_3:** إضافة **wick-debounce** إلى `BracketMonitor` (اشتراط ثبات الاختراق: تِكّتان متتاليتان أو نافذة زمنية صغيرة) + **ترسية الخروج على أفضل BID حيّ لحظة الإطلاق** لا على tick قديم/wick.
- **chunk_2:** سياسة التنفيذ الموحّدة في `market_exit.py` (band محكوم + LIMIT IOC + chase نازل لحد الأرضية + ملاذ (ب) MARKET محمي بالأرضية + telemetry) ⇒ لا تعليق وأقرب نقطة سعرية.
- **chunk_4:** ربط السياسة في كل الوسائل + اختبارات لا-تعارض.

## اختبار الانحدار
`tests/test_g1_49_bracket_wick.py` (منطق خالص، بلا Qt): يحاكي wick علوي ويؤكّد أن الـwick المنفرد **يجب ألّا** يُطلق الخروج (يتطلّب debounce). **أحمر بالتصميم** حتى chunk_3، ثم يصير أخضر بعد الإصلاح.
