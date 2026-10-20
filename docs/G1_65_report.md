# تقرير G1.65 — تطبيق إنتاجي مُعلَّم لمخرجات G1.64 (increments #1..#5)

> **الحالة:** in_progress (أُنجِز increments #1..#5؛ غير مختوم). **صفر رأس مال حيّ، صفر تغيير سلوك افتراضيًّا.** مسار التجارب **G1.64 يبقى مفتوحًا** (غير مختوم). | **التاريخ:** 2026-10-20

## 0) السياق والأساس
يبني هذا البند على مسار G1.64 بعد اجتياز **بوّابة forward W3** (EXP-024C على نافذة holdout `prevprev90d_full` لم تُرَ وقت المعايرة؛ `forward_w3_launch_gate = MET`، كل G1..G6 PASS). الحافة المُتحقَّقة = التتبّع المتكيّف `wave_adaptive` + رافعة `lock_base` فوق نِسب البطل `k5.0_tf0.15`.

**القرار الاحترافي للتطبيق:** مُعلَّم وقابل للعكس، خلف `feature-flag` مُطفأ افتراضيًّا؛ `lock_base` افتراضي **0.80** (قويّ ومُتحقَّق forward دون تبنّي حافة 0.95)؛ نِسب الدخول العدوانية (البطل) **اختيارية** لأن EXP-010/011 أظهرا مخاطرة ذيل.

## 1) ما نُفِّذ (increment #1)
- **`ocobot/domain/dynamic_exit.py`** (وحدة domain خالصة) تجسّد صيغة `exp_021_run.resim_1m_wave` حرفيًّا: `trail_distance_pct` و`lock_floor_frac` و`next_stop` (ستوب رتيب) و`live_atr_pct`، مع `WADAPT_TIGHT` (lock_base=0.80) و`CHAMPION_RECOMMENDER` و`DynamicExitConfig(enabled=False, ...)` (الافتراضي = السلوك الحالي تمامًا).
- **`ocobot/app_wiring.py`**: `profile=None` متوافق رجعيًا؛ `"champion"` فقط يفعّل بطل المُرشِّح؛ الافتراضي بلا تغيير.
- **`tests/test_g1_65_dynamic_exit.py`**: 19 اختبارًا تُثبّت الصيغة + «الافتراضي = بلا تغيير».

## 1ب) ما نُفِّذ (increment #2) — وصل الخروج المتكيّف خلف الـflag
- **`ocobot/domain/reposition.py`** — `SafeExecutor.build_draft`/`execute` اكتسبا باراميترات **keyword-only اختيارية** (`dynamic_exit`, `peak_price`, `prev_stop`, `live_atr_pct_value`) افتراضها `None`. عند `enabled` وتوفّر المدخلات فقط: يُحسب الستوب عبر `next_stop(...)` ثم يُحوَّل إلى نسبة فعّالة `eff_sl_pct = (1 − next_stop/reference)·100`؛ وإلا `eff_sl_pct = sl_pct` (مطابق تمامًا). كل ما بعد ذلك (`compute_levels`، تقريب tick، فجوة D5، بوّابة D4، المسودّة) بلا مساس.
- **`ocobot/domain/monitoring.py`** — `MonitoringEngine.__init__` اكتسب `dynamic_exit` و`live_atr_pct_provider` اختياريين (افتراض `None`). تتبّع القمّة يحدث **فقط عند التفعيل**؛ ونداء `executor.execute` مُغلَّف `if enabled: (+وسائط التتبّع المتكيّف) else: (النداء الحالي حرفيًّا)` — المسار المُطفأ غير ممسوس.
- **`tests/test_g1_65_increment2_wiring.py`**: 6 اختبارات — تطابق المسودّة عند `None`/`enabled=False` عبر مصفوفة مدخلات، حارس «enabled بلا مدخلات = بلا تغيير»، تطابق `execute`، تطبيق `next_stop` فعليًّا عند التفعيل، وتطابق وسائط `execute` + تمرير مدخلات التتبّع في monitoring.

## 1ج) ما نُفِّذ (increment #3) — وصل مصدر ATR٪ الحيّ الحقيقي خلف المفتاح
- **`ocobot/config.py`** — مفاتيح `dynamic_exit_enabled` (افتراض `False`) و`dynamic_exit_lock_base` (0.80) و`dynamic_exit_profile` (`baseline`) عبر البيئة (`OCOBOT_DYNAMIC_EXIT*`). مُطفأة افتراضيًّا ⇒ صفر تغيير سلوك.
- **`ocobot/app_wiring.py`** — `build_live_atr_pct_provider(klines_service, symbol_fn, …)`: مزوّد بلا وسائط يحسب ATR٪ الحيّ بصيغة `dynamic_exit.live_atr_pct` (≡ `exp_021_run._live_atr_pct`) من شموع 1m عبر `KlinesService`؛ **fail-safe → 0.0** عند نقص البيانات/خطأ (يتراجع لبذرة `dist_min`).
- **`ocobot/cli.py`** — `_dynamic_exit_kwargs(cfg, client, symbol)`: **فارغة عند الإطفاء** (المسار الافتراضي لا يمرّر أي وسائط جديدة ⇒ مطابق بتًّا)؛ عند التفعيل فقط يبني `DynamicExitConfig(enabled=True)` + المزوّد الحيّ ويمرّرهما لموقعَي بناء `MonitoringEngine` (الاستئناف + البدء النظيف).
- **القمّة (peak)** حقيقية أصلًا (تُتتبَّع من ticks حيّة في `MonitoringEngine`)؛ و**fill/prev_stop** مبذوران من السعر المرجعي الحيّ.
- **`tests/test_g1_65_live_atr_provider.py`**: 11 اختبارًا (مطابقة الصيغة + fail-safe + علم مُطفأ=وسائط فارغة + علم مُفعَّل=وصل حيّ + تحليل البيئة).

## 1د) ما نُفِّذ (increment #4) — observability خلف العلم (قراءة-فقط)
- **`ocobot/app_wiring.py`** — `build_live_atr_pct_provider(...)` اكتسب باراميترًا اختياريًّا `observer=None` وعدّادات `provider.stats` (`calls`/`ok`/`failsafe`/`last_value`/`last_reason`/`failsafe_by_reason`) + تسجيل عبر `logging.getLogger("ocobot.dynamic_exit")`: `debug` عند النجاح، و`warning` عند أي سقوط على fail-safe مع **تصنيف السبب** (`no_symbol`/`empty_candles`/`exception`/`zero_value`) و**حفظ الرمز الفاشل**. **صفر تغيير سلوك**: قيم الإرجاع مطابقة تمامًا لكل مسار؛ والـobservability نفسها fail-safe (لا تكسر المراقبة).
- **الفائدة:** تمنع «التدهور الصامت» — أثناء live-forward نُثبت أن الخروج المتكيّف يعمل على ATR٪ حقيقي لا على البذرة (`failsafe==0` بوّابةً).
- **`tests/test_g1_65_atr_observability.py`**: 9 اختبارات (عدّادات المسار السعيد + تصنيف أسباب fail-safe + أحداث observer + حفظ الرمز عند الاستثناء + **صفر تغيير سلوك** + الـobservability نفسها fail-safe).
- **تحقّق حيّ مستقل:** `tools/_verify_atr_live.py` (قراءة-فقط) على بيانات Binance حقيقية ⇒ **ALL PASS**: تطابق ثلاثي (domain == مستقل == provider) على BTCUSDT، و4 رموز سائلة كلها ATR٪ > 0، وحالات فشل مصنّفة صحيحًا.

## 1هـ) ما نُفِّذ (increment #5) — شادو-مود + مصرف observability (قراءة-فقط)
- **`ocobot/config.py`** — علم `dynamic_exit_shadow` (env `OCOBOT_DYNAMIC_EXIT_SHADOW`، افتراض `False`).
- **`ocobot/domain/dynamic_exit.py`** — دالة خالصة `shadow_divergence(...)` تطابق صيغة `build_draft` عند التفعيل (fill=reference): تُعيد الستوب التكيّف وeff_sl_pct والانحراف عن الستوب الحالي.
- **`ocobot/domain/monitoring.py`** — `MonitoringEngine` اكتسب `shadow=False`؛ عند تفعيله (والعلم الرئيسي مُطفأ) يحسب الخروج التكيّف ويسجّله عبر `self._record` (audit): حدثا `dynamic_exit_shadow` و`dynamic_exit_atr` (+لقطة عدّادات المزوّد) — **ونداء `execute` يبقى المسار الحالي حرفيًّا ⇒ صفر تغيير سلوك**. الحساب محصّن بالكامل (لا يكسر المراقبة).
- **`ocobot/cli.py`** — `_dynamic_exit_kwargs` يدعم شادو-فقط (`shadow=True` + `enabled=False`)؛ الكل مُطفأ ⇒ `{}` (مطابق تمامًا).
- **`tests/test_g1_65_shadow.py`**: 10 اختبارات (الدالة الخالصة + تطابق التنفيذ في شادو + تسجيل الحدثين + حصانة فشل المزوّد + config + cli).
- **دليل حيّ:** `tools/_shadow_exit_probe.py` (قراءة-فقط) على BTC/ETH/SOL ⇒ ATR٪ حيّ > 0 للكل، وجدول يُظهر قفل الربح التكيّف (eff SL% يصير فوق المرجع مع ركضة القمّة) مقابل الستوب الثابت −2٪.

## 2) السلامة
- `enabled=False` و`recommender_profile="baseline"` و`dynamic_exit=None` افتراضيًّا ⇒ **صفر تغيير سلوك**. الباراميترات الجديدة كلها keyword-only بقيمة `None`؛ لا موقع نداء قائم يمرّرها.
- وحدات domain خالصة (بلا I/O/شبكة/Qt)، لا hot_path، لا Live/testnet، لا رأس مال.
- حلقة `reposition`/`monitoring` الحيّة مُجهَّزة الآن بالبذرة خلف الـflag؛ والمسار المُطفأ مُثبَت أنّه مطابق بتًّا (اختبار انحدار).

## 3) الأدلة
- اختبارات increment #1 وحدها: **Ran 19 — OK**.
- اختبارات increment #2 وحدها: **Ran 6 — OK** (سجلّ: `_g1_65_inc2_suite.out`).
- كامل السويت: **Ran 1020 tests in 251.693s — OK — failures=0 errors=0** (1014 سابقة + 6 جديدة).
- الأمر: `python -m unittest discover -s tests -t .`.

## 4) المتبقّي
- **قبل أي رأس مال حيّ:** (1) **مرحلة شادو** (`OCOBOT_DYNAMIC_EXIT_SHADOW=1`): المحرّك يحسب الخروج التكيّف ويسجّله (audit) بلا تنفيذ — لجمع أدلّة حيّة والتحقّق من `failsafe==0`؛ ثم (2) live-forward بوقت الساعة (paper/testnet) + طرح مرحلي (maxpos=1) + إدارة ذيل عبر `guardian` + أمر «نفّذ» صريح لتفعيل العلم (`OCOBOT_DYNAMIC_EXIT=1`). **الخطة التفصيلية (تصميم، دون تنفيذ): `docs/G1_65_live_forward_plan.md`**.
- **تحفّظات W3 (سُدَّت تحليليًّا):** تحيّز البقاء = BOUNDED، وبوّابة EXP-021 = RESOLVED — راجع `docs/G1_65_W3_reservations.md`.
- مصدر `ATR٪` الحيّ موصول (increment #3) ومُراقَب (increment #4 — observability) ومُتحقَّق منه حيًّا (`tools/_verify_atr_live.py`)؛ تحسين اختياريّ لاحق: مصدر `fill`/`peak` أدقّ من حالة الصفقة (حاليًّا من ticks/السعر المرجعي)، ومرجع ATR٪ على القمّة بدل آخر إغلاق.

## 5) الانضباط
تطبيق نتائج G1.64 بأمر «نفّذ» (§11.8ج)؛ G1.65 بند جانبي مستقلّ (charter rule 5) وG1.64 تبقى `active:true` غير مختومة. لا Live (T16) قبل بوّابة G1. increment #2 لم يُغيّر أي سلوك افتراضي ولم يُختَم أي بند.
