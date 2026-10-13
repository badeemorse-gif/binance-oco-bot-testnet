# G1.43 — إغلاق ثغرات حارس ثنائية اللغة (دليل التحقّق)

**الحالة:** sealed — **البروتوكول:** 1.5 — **الطور:** G1_MANUAL_TESTING

## الهدف
إغلاق ثغرات التغطية في حارس منع تسرّب العربية بوضع الإنجليزية (`tests/test_g1_41_i18n_no_leak.py`)
ودالة `ocobot/ui/i18n.py::retranslate_widget_tree`، بحيث تُغطّى الأنواع التي كانت خارج الفحص.

## التغييرات (واجهة/حارس بحت — صفر مساس بـ domain/core أو مسار Live)
1. `ocobot/ui/i18n.py::retranslate_widget_tree` (توسيع):
   - رؤوس `QTableWidget` **العمودية** (كانت الأفقية فقط مُغطّاة).
   - عنوان `QMenu` + نصوص `QAction` عبر `w.actions()`.
   - استيراد `QMenu` عبر `_import_widget` (آمن عند غيابه).
   - **قيد أمان:** خلايا `QTableWidget.item(row,col)` لا تُترجَم (داتا: رموز/أرقام/IDs) — الرؤوس فقط.
2. `tests/test_g1_41_i18n_no_leak.py::_collect_offenders` (توسيع الفحص ليؤكّد خلو وضع en من العربية في):
   - `windowTitle` للنوافذ، رؤوس `QTableWidget` (أفقي+عمودي)، عنوان `QMenu`، نصوص `QAction`.
   - استيراد `QTableWidget`/`QMenu` عبر `_opt`.

## ملاحظات تصميمية
- `translate()` بحثُ قائمة بيضاء `AR_TO_EN.get(text, text)` ⇒ الداتا غير العربية تمرّ بلا تغيير (أمان ثانٍ).
- لا توجد حاليًا قوائم `QMenu`/`QAction` ولا رؤوس عمودية مستخدمة، وعنوان النافذة `"OCOBot"` لاتيني،
  ونوافذ `QMessageBox` مُعرَّبة وقت الإنشاء عبر `translate_for_current` ⇒ التوسيع **دفاعي** (0 offenders حاليًا)
  يمنع أي تسرّب مستقبلي عند إضافة فروع/أنواع ودجت جديدة.

## التحقّق (دليل)
الأمر: `python tools/_run_suite.py` (العدّاء المعتمد عبر unittest discover، المتسامح مع ضجيج Qt على stderr).

```
==== SUITE SUMMARY ====
Ran 558 tests
status=OK failures=0 errors=0 skipped=0
```

- كامل السويت أخضر: **Ran 558 / OK**، صفر failures/errors/skipped — مطابق لخطّ أساس G1.41 (558).
- الحارس الموسَّع أخضر (0 offenders) ⇒ لا تسرّب ولا نصوص جديدة تحتاج تسجيلًا في `AR_TO_EN`.
- `python -m py_compile` على الملفَّين: ناجح.

### ملاحظة بيئة
تشغيل `python -m pytest` في عملية واحدة ينتج عطبًا أصليًّا (Windows access violation) أثناء GC لودجت Qt
عبر الاختبارات — وهو سلوك خاص بعدّاء pytest (سباق GC/teardown)، **ليس فشلًا منطقيًّا ولا متعلّقًا بهذا التغيير**.
العدّاء المعتمد للمشروع هو unittest (`run_tests.cmd` / `tools/_run_suite.py`)، وبه السويت أخضر 558.

## الأثر على معايير الأمان
لا مساس بـ `domain/`/`core/` ولا بمنطق التداول ولا بمسار Live/T16 ولا بثوابت §1. العربية مصدر لا يُمَس؛ الضبط لوضع الإنجليزية فقط.
