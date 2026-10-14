# تقرير G1.54 — لوحة ربحية احترافية (عرض فقط) في شاشة 08_completed_trades مع drill-down

**المعرّف:** G1.54 · **الخطورة:** major · **البوّابة:** G1 (Testnet) · **human_gate:** false
**يعتمد على:** G1.51 + G1.53 (مختومان) · **الحالة:** implemented → verified → sealed

---

## 1) الهدف
إعادة تنظيم شاشة `08_completed_trades` إلى ثلاث طبقات **عرض-فقط**:
- **أعلى:** ملخّص ربحية احترافي لكل وضع خروج (`exit_source`).
- **أوسط:** قائمة الصفقات، قابلة للفلترة بالوضع، مع التحديد المُصلَّح (G1.51).
- **أسفل:** جدول تفاصيل التموضع القائم.
تُغذّى قراءةً فقط من `profitability_by_mode` (G1.53) و`load_completed_trades`
القائمة. لا شبكة في خيط الواجهة، لا hot_path، لا منطق تنفيذ، لا Live.

---

## 2) النطاق (scope_boundary)
- **داخل:** `ocobot/ui/profitability_panel.py` (جديد)، دمجه في
  `ocobot/ui/completed_trades.py`، ومفاتيح §1.5 في `ocobot/ui/i18n.py`، + `tests/`.
- **خارج (لم يُمَسّ):** أي شبكة في خيط الواجهة، hot_path، أي منطق تنفيذ، أي Live/T16.

---

## 3) التغييرات بالتفصيل

### 3.1 `ocobot/ui/profitability_panel.py` (جديد، عرض فقط)
- **دوال خالصة** (قابلة للاختبار بلا QApplication، نمط `percent_tracker`):
  `fmt_pct`, `fmt_usd`, `fmt_count`, `win_rate_fraction`, `color_for`,
  `order_modes_by_expectancy` (leaderboard، None آخرًا)، `cumulative_pnl`
  (سلسلة تراكمية زمنيًّا، تستبعد live/الغائب)، `win_loss_counts`،
  `polyline_points` (هندسة الرسم)، `mode_label`.
- **ودجات رسم مخصّص** (QPainter معزول الاستيراد binding-agnostic):
  `RingWidget` (حلقة win-rate)، `PnlCurveWidget` (منحنى تراكمي أخضر/أحمر)،
  `WinLossBar` (شريط توزيع)، `ModeCard` (بطاقة وضع قابلة للنقر)،
  `ProfitabilityPanel` (الجامع: بطاقات مرتّبة بالتوقّع + leaderboard + منحنى +
  توزيع + زرّ «كل الأوضاع»). إشارة `modeSelected(str)` للـdrill-down.
- RTL + ألوان `PercentTracker` (أخضر صعود/أحمر هبوط) + كل الحساب `Decimal`.

### 3.2 `ocobot/ui/completed_trades.py` (دمج)
- بناء `ProfitabilityPanel` أعلى الشاشة؛ ربط `modeSelected → _on_mode_filter`.
- `set_trades` قُسّم: تحديث لوحة الملخّص **فقط عند تغيّر مجموعة الصفقات**
  (`_last_all_sig`، تفادي الوميض الدوري) + عرض القائمة عبر `_apply_list`.
- `_apply_list`: فلترة بالوضع (`_mode_filter`) + منطق ثبات التحديد (G1.51) موسَّعًا
  — التوقيع يضمّ الفلتر، والتحديث الدوري المتطابق لا يُعيد البناء ولا يسرق التحديد؛
  `_selected_trade` يفهرس القائمة المرئيّة المفلترة.
- `_load_execs`: قراءة telemetry (`exit_execution`) من سجلّ التدقيق لتغذية
  مقياس «متوسط الانزلاق» — قراءة فقط، متسامح مع الغياب/التلف.
- **drill-down:** نقر بطاقة وضع ⇒ تصفية القائمة ⇒ نقر صفقة ⇒ تفاصيل.

### 3.3 `ocobot/ui/i18n.py` (§1.5)
أُضيفت مفاتيح `AR_TO_EN` لكل نصوص اللوحة الثابتة وتسميات الأوضاع الخمسة؛
`ProfitabilityPanel` و`ModeCard` يُعرّفان `retranslate_i18n` (إعادة رسم من البيانات
المخزّنة) فيلتقطهما `retranslate_widget_tree` القائم.

---

## 4) قرارات التصميم
- **ملخّص عالمي + قائمة مفلترة:** البطاقات/leaderboard/المنحنى/التوزيع تعكس كل
  الصفقات؛ الفلترة بالـdrill-down تمسّ القائمة الوسطى فقط (أبسط وأثبت).
- **فصل الدوال الخالصة عن الرسم:** الهندسة/الترتيب/التنسيق دوالّ نقيّة مُختبَرة؛
  الـQPainter طبقة رفيعة (قابلية اختبار Qt-safe تحت offscreen).
- **عدم كسر G1.51:** الفلتر الافتراضي "" ⇒ المرئيّة = الكل ⇒ سلوك مطابق تمامًا؛
  اختبارات G1.51 تمرّ دون تعديل.
- **i18n في `completed_trades`:** co-located مع المكوّن لإبقاء التطبيق خاليًا من
  التسرّب العربي في EN (أُثبت بـ`test_g1_41_i18n_no_leak`).

---

## 5) الاختبارات (جديدة، Qt-safe تحت offscreen)
- `tests/test_g1_54_profitability_panel.py` — 16 (10 دوال خالصة + 6 ودجت).
- `tests/test_g1_54_completed_trades_integration.py` — 6 (لوحة/فلترة/drill-down/
  ثبات تحديد تحت الفلتر/تفاصيل/وضع فارغ).
- `tests/test_g1_54_i18n.py` — 4 (مفاتيح EN + تسميات الأوضاع + retranslate بلا
  تسرّب + ربط عبر الشاشة).
- **مجموع G1.54:** 26 اختبارًا — خضراء (OK). + انحدار صفري على
  `test_g1_51_selection_stability` و`test_g1_41_i18n_no_leak` و`test_g1_20_language_toggle`.

---

## 6) الفحوص مقابل acceptance_checks
- ✅ اللوحة عرض-فقط تعرض مقاييس كل وضع (بطاقات + leaderboard + منحنى + توزيع).
- ✅ drill-down (وضع→صفقات→تفاصيل) يعمل.
- ✅ التحديد ثابت أثناء التحديث الدوري (G1.51 محفوظ + تحت الفلتر).
- ✅ §1.5 ثنائية اللغة بلا تسرّب عربي في EN بعد retranslate.
- ✅ لا شبكة في خيط الواجهة ولا hot_path (طبقة ui عرض-فقط + domain قراءة فقط).
- ✅ كامل السويت أخضر ≥ baseline (انظر §7).

---

## 7) أدلّة التشغيل (baseline مقابل بعد)
- **baseline (بعد G1.53):** `ran=762`.
- **بعد G1.54 (split-per-file):** `TOTAL ran=788 failures=0 errors=0 files=110 status=OK`
  · PROBLEMS (0) — (762 + 26 اختبار G1.54 الجديد). صفر فشل وصفر خطأ ⇒ أخضر ≥ baseline.
- **طريقة التحقّق:** `tools/_run_suite_per_file.py` (كل ملف اختبار في عملية مستقلة
  تحت `QT_QPA_PLATFORM=offscreen`)، تماشيًا مع اعتماد ختم G1.49–G1.52؛ تشغيل
  `discover` بعملية واحدة غير حتمي هنا بسبب تعليق/انهيار Qt التراكمي (موثّق في
  decisions_log) ولا علاقة له بتغييرات G1.54 (كل اختبارات G1.54 المستهدَفة خضراء).

## 8) الأمان
لا أي Live/T16 — محظور قبل اجتياز بوّابة G1 (§10.5). كل التغييرات عرض-فقط ومعزولة
وقابلة للاختبار بالكامل تحت `QT_QPA_PLATFORM=offscreen` بلا شبكة.
