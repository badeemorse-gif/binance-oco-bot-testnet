# تقرير G1.56 — مُرشِّح نِسب تكيّفي للعملة (TP/SL/Trigger) + ملء تلقائي بوضعين

- **الحالة:** sealed · **severity:** minor · **الطور:** `G1_MANUAL_TESTING`
- **المواصفات:** `docs/G1_55_to_57_plan.md` · **العقد:** `state/defects/G1.56.json`
- **التحقّق:** `tools/_run_suite_per_file.py` ⇒ `TOTAL ran=940 failures=0 errors=0 files=120 status=OK`
  (baseline 823 + 117 اختبارًا جديدًا لـG1.56).

## 1) الهدف
عند اختيار العملة، يقترح المحرّك أفضل `tp_pct`/`sl_pct`/`trigger_pct` من تقلّب العملة
وحركتها بحيث **لا نخرج مبكرًا** ونلتقط أكبر حركة تتبّع ربحية — **عرض/اقتراح فقط**
(لا trading signals ولا قرار شراء/بيع؛ التزام `exclusions`).

## 2) قرار المنفّذ (استشارة المستخدم 2026-10-14)
المستخدم تساءل عن إضافة الزخم/الفوليوم ومؤشرات مثل SuperTrend/RSI وأثرها على السرعة والدقّة.
القرار المعتمد والمنفَّذ:
1. **النواة كما في المواصفات:** `volatility` (ATR%/Yang-Zhang/EWMA) + `excursion`
   (MFE/MAE + عمق الارتداد) + `regime` (ADX/DMI/Choppiness/Hurst/Variance-Ratio) + فريمات هرمية.
2. **إضافة طبقة سيولة/سبريد كحارس قصّ (clamp):** تُوسّع `trigger`/`gap` وتُحجّم `tp` عند
   ضعف السيولة أو اتّساع السبريد، وتتكامل مع فلاتر `tickSize/LOT_SIZE/minNotional` وأرضية
   الفلاش-كراش (G1.33) المُحقَّنة كبارامتر (لا تُختلَق هنا — P4).
3. **استبعاد RSI/Momentum/SuperTrend من المدخلات الأساسية:** تكرار/collinear ورفع لخطر
   الـoverfitting (SuperTrend مشتقّ من ATR الموجود؛ وطبقة `regime` تغطّي الاتجاه/التذبذب).
   تبقى خيارًا **تجريبيًا خلف بوّابة Walk-Forward وفي وضع Observe فقط**، ولا تدخل الإنتاج
   إلا إذا حسّنت مقياس «الخروج المبكر/التقاط MFE» خارج العيّنة.
4. **السرعة مصونة:** كل الحساب في طبقة `async` + قيمة مخزّنة؛ النبضة `on_price_tick` تقرأ
   المخزَّن فقط؛ التطبيق **بين النبضات** لا أثناء `in_flight`؛ لا لمس `hot_path`.

## 3) التنفيذ (8 chunks — دوال domain خالصة + طبقة عرض + CLI)
| chunk | ملف | المحتوى | اختبارات |
|---|---|---|---|
| c1 | `ocobot/domain/volatility.py` | ATR% (Wilder) · Yang-Zhang · Garman-Klass/Parkinson/Rogers-Satchell · EWMA(λ=0.94) · مئينات | `tests/test_g1_56_volatility.py` (24) |
| c2 | `ocobot/domain/excursion.py` | توزيعات MFE/MAE · عمق الارتداد · محاكاة نوافذ أمامية | `tests/test_g1_56_excursion.py` (16) |
| c3 | `ocobot/domain/regime.py` | ADX/DMI · Choppiness · Hurst(R/S) · Variance-Ratio · **قياس سيولة/سبريد** | `tests/test_g1_56_regime.py` (20) |
| c4 | `ocobot/domain/recommender.py` | الربط ⇒ tp/sl/trigger · قصّ الفلاتر · **حارس السيولة** · أرضية ضوضاء هرمية · أرضية فلاش-كراش مُحقَّنة | `tests/test_g1_56_recommender.py` (12) |
| c5 | `ocobot/domain/klines.py` | `KlinesService` (عبر `client.public_request`) + cache TTL + `build_klines_fetcher` للرَنَر | `tests/test_g1_56_klines.py` (9) |
| c6 | `ocobot/ui/rec_panel.py` | لوحة عرض-فقط + زر «ملء مرّة واحدة» + §1.5 (i18n) | `tests/test_g1_56_rec_panel.py` (9) |
| c7 | `ocobot/domain/rec_tracker.py` | وحدة تحكّم Off/Observe/Live + hysteresis + تهدئة + سقف/جلسة + تدقيق | `tests/test_g1_56_rec_tracker.py` (14) |
| c8 | `ocobot/domain/backtest.py` + `ocobot/cli_backtest.py` | Walk-Forward (معايرة تدريب ⇒ قياس خارج العيّنة) + CLI | `tests/test_g1_56_backtest.py` (13) |

### الربط الأساسي (قابل للمعايرة — `RecommenderParams`)
```
sl_pct      ≈ max(k_sl · ATR%,  P80(MAE))        (k_sl=2.0)
trigger_pct ≈ median(pullback) · trigger_f        (trigger_f=0.7)
tp_pct      ≈ P75(MFE) · adx_factor(HTF)
```
ثم قصّ: أرضية الضوضاء (LTF) ⇒ حارس السيولة/السبريد ⇒ أرضية الـticks (فلاتر العملة) ⇒
حدود دنيا/عليا ⇒ تحقّق عدم انهيار المستويات عبر `pricing.compute_levels`. المخرجات نِسب
`Decimal` متوافقة مع `pricing`.

## 4) العزل والسلامة (scope_boundary)
- **لم يُمَسّ** أي من: `on_price_tick`/`MonitoringEngine`/`SafeExecutor`/`reposition`/`create_oco`،
  `domain/bracket.py`، `alerts/*`.
- **لا شبكة في `ocobot/ui/*`**: الحارس `tests/test_ui_no_direct_network.py` أخضر؛ الجلب يتمّ
  عبر `KlinesService` خارج الواجهة ويُسلَّم للّوحة عبر `AsyncRunner.submit`.
- **§1.5 ثنائية اللغة:** أُضيفت مفاتيح EN في `ocobot/ui/i18n.py`؛ حارس `tests/test_g1_41_i18n_no_leak.py`
  أخضر، واختبار اللوحة يثبت عدم تسرّب العربية في وضع الإنجليزية.
- **لا Live قبل G1:** الوضع المتتبّع «حيّ» يُنتج اقتراحًا مُوافَقًا عليه + تدقيقًا فقط؛ لا يلمس
  دورة التموضع (تأثيره — إن وُصِّل لاحقًا — في الدورة التالية فقط).

## 5) خطوة تكامل مؤجّلة (مقصودة)
`RecommendationPanel` ووحدة التتبّع جاهزتان ومُختبَرتان كوحدتين قائمتين بذاتهما، لكن **لم تُركَّب
في `build_app()`** تفاديًا لزعزعة واجهة الاختبار اليدوي الجارية (G1). التركيب خطوة wiring رفيعة
لاحقة (ضمن نطاق مسموح) ولا تؤثّر على صحّة النواة.

## 6) الدليل
- كامل السويت split-per-file: `ran=940 failures=0 errors=0 files=120 status=OK`.
- ثبات الحارسين: `test_ui_no_direct_network` + `test_g1_41_i18n_no_leak` أخضران.
