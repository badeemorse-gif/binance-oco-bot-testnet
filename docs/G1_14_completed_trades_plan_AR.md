# خطة G1.14 — فرع عرض الصفقات المنتهية

## المشكلة
لا يوجد فرع يعرض الصفقات التي أنهاها البوت (ستوب أو جني ربح). المطلوب فرع عربي بالكامل (عدا الأرقام ورمز العملة والرمز) مقسوم نصفين: قائمة رأسية بالصفقات المنتهية قابلة للتحديد مع زرّي [مسح الصفقة المحددة] و[تفاصيل الصفقة]، وتفاصيل تموضع جدولية للصفقة المحددة تُظهر سلسلة التنقّل من بدء المراقبة حتى الانتهاء وربح $/% من سعر بدء المراقبة، مع تمرير بعجلة الماوس في النصفين.

## هل تؤثر على المسارات الحالية؟
لا. الإضافة معزولة بالكامل: ملفات جديدة + نقاط تمديد قياسية (SCREENS/ContentRouter) + قراءة-فقط من سجلّ التدقيق. الشاشات الخمس القائمة ومنطق MonitoringEngine/reposition لا تُلمَس.

## المخاطر والاحتواء
- R-A: نوع الإغلاق وسعر البيع الفعلي والاتجاه غير مسجّلة حاليًا. الاحتواء: التقاط سعر البيع عبر خطّاف on_order_event القائم ككتابة تدقيق إضافية append-only (trade_closed_fill) بلا تغيير control-flow؛ الصفقات القديمة تُظهر «غير متاح».
- R-B: اختبارات التنقّل تتحقق من عدد الشاشات (7) وقوائم EXPECTED_* ⇒ تُحدَّث والعدد 7→8.
- R-C: الربح دالة عرض نقية بسيطة من سعر البدء، ليست محرّك تحليلات P&L.
- بوابة G1: human_gate=false، لا ترقية لـG1 ولا مساس بـT16/Live.

## القرارات
- DS1: المسح = إخفاء عبر فهرس dismiss منفصل، لا حذف من سجلّ التدقيق.
- DS2: التقاط سعر البيع إضافي append-only عبر on_order_event عند التجميع.
- DS3: pct=(exit-reference)/reference*100 ، usd=(exit-reference)*quantity.

## خطوات التنفيذ (مقسّمة §9.5)
1. ocobot/domain/completed_trades.py (قراءة-فقط + ربح + dismiss)
2. tests/test_completed_trades_domain.py
3. التقاط سعر البيع عبر on_order_event (إضافي)
4. اختبار الملتقط
5. ocobot/ui/completed_trades.py (نصفان + قائمة + جدول + أزرار + تمرير عجلة)
6. تسجيل الشاشة في SCREENS + ContentRouter
7. تحديث tests/test_ui_navigation.py
8. مزامنة docs/OCOBot_Design_AR.md
9. تشغيل السويت -> tests/_g1_14_run.txt
10. الختم seal + تصفير WORKING_MEMORY

## معايير القبول
AC1 سويت خضراء >=322 · AC2 تسجيل الشاشة وعدد 8 · AC3 إعادة بناء السلسلة · AC4 الربح و«غير متاح» · AC5 المسح لا يحذف التدقيق · AC6 الملتقط append-only.

## تقدّم التنفيذ
- ✅ step_1 الموديول `ocobot/domain/completed_trades.py` (قراءة فقط + ربح + dismiss).
- ✅ step_2 اختبارات `tests/test_completed_trades_domain.py`.
- ✅ step_3 التقاط سعر البيع عبر `on_order_event` (`build_fill_recorder` → `trade_closed_fill` append-only).
- ✅ step_4 اختبار الملتقط `tests/test_completed_trades_capture.py`.
- ✅ step_5 شاشة `ocobot/ui/completed_trades.py` (نصفان: قائمة علوية قابلة للاختيار + زرّا مسح/تفاصيل، وجدول سفلي لسلسلة التموضع + ربح $/%، تمرير بالعجلة، عربية RTL، قراءة فقط).
- ✅ step_6 تسجيل الشاشة `08_completed_trades` في `ocobot/ui/screens.py` + `ocobot/ui/content.py` (`ContentRouter`).
- ✅ step_7 تحديث `tests/test_ui_navigation.py` (EXPECTED_* والعدد 7→8 + اختبار تسجيل/وصول الشاشة).
- ✅ step_8 مزامنة `docs/OCOBot_Design_AR.md` (ملحق تنفيذ G1.14) + هذا الملف.
- ✅ step_9 تشغيل السويت الكاملة -> `tests/_g1_14_run.txt`.
- ⏳ step_10 الختم seal (مؤجَّل حتى تأكيد الاخضرار).
