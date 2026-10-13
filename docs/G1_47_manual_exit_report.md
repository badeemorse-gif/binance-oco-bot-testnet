# تقرير G1.47 — خروج يدوي فوري بأفضل سعر لحظي بأولوية عُليا

**الحالة:** sealed · **الخطورة:** major · **الطور:** G1_MANUAL_TESTING · **البروتوكول:** 1.5
**القرار الحاكم:** `g1_47_manual_exit_safety` (decisions_log).

## المشكلة
طلب المستخدم خاصيّة داخل المراقبة تمنحه — عند الضغط على زرّ «تنفيذ» — إصدار أمر بيع
بأفضل سعر لحظي عندما يرى ربحًا كبيرًا ويريد الخروج قبل انقلاب السوق، على أن تكون لهذا
الإجراء الأولوية العُليا على الوسائل الأربع (الحارس · btc-follow · إعادة التموضع · البراكِت).

## الحل (داخل scope_boundary فقط)
1. **بوّابة التنفيذ الآمن** — `ocobot/ui/safe_execution.py::manual_exit_safety_gate` (خالصة، بلا
   Qt/شبكة): تطبّق قيد منع البيع المزدوج البنيوي نفسه (`has_resting_protective_sell` +
   `protective_qty = min(free_base_qty, monitored_qty)`).
2. **المنفّذ الأحادي** — `ocobot/ui/manual_exit.py` (`run_manual_market_exit` + `build_manual_exit_fn`):
   يمرّ عبر البوّابة ثم يُعيد استخدام مسار الخروج المُختبَر `ocobot/domain/market_exit.execute_market_exit`
   **حصريًّا** (إلغاء OCO → reconcile → وضع واحد فقط). `dry_run=True` افتراضيًّا (لا أثر).
3. **الواجهة** — زرّ «تنفيذ الخروج الفوري» (`MonitoringManualExitButton`) في
   `ocobot/ui/monitoring.py` داخل قسم المراقبة، مع `set_manual_exit_fn` ومعالِج يُشغّل عبر
   الرَنَر (لا شبكة في طبقة الواجهة). §1.5 ثنائية اللغة في `ocobot/ui/i18n.py`.
4. **الربط وقت التشغيل** — في `ocobot/ui/app.py` (معزول/متسامح، `Testnet`، `dry_run=False`).

## الأولوية البنيوية (لا سباق منفّذات)
بمجرّد تنفيذ الخروج يُغلق المركز (أو يوجد بيع حمائي قائم) فتصبح الوسائل الأربع
idempotent بلا فعل — لأن جميعها مشروط بـ `has_resting_protective_sell` و
`min(free_base_qty, monitored_qty)`. يبقى no-cancel-invariant لمنفّذ الستوب الواقي سليمًا
(الإلغاء هنا جزء من مسار `execute_market_exit` المبدوء بأمر المستخدم).

## الأمان
Testnet فقط ضمن G1؛ لا Live/T16 قبل بوّابة G1 (§10.5). `OCOBOT_ENV` مقفول على Testnet في `main()`.

## الدليل (acceptance_checks)
- اختبارات مخصّصة بمحاكاة عميل بلا شبكة: `tests/test_g1_47_manual_exit.py` (14 اختبارًا) —
  البوّابة + منع البيع المزدوج (bوّابة + reconcile) + قصر الكمية على `min(target, free)` +
  الأولوية على الحارس (`evaluate ⇒ NOOP` بعد الخروج) + §1.5 ثنائية اللغة + `dry_run` بلا أثر.
- كامل السويت أخضر: `Ran 665 tests OK` (failures=0 · errors=0 · skipped=0 ≥ 651).
  المخرجات الكاملة في `_archive/g1_47_results.txt` والملخّص في `_archive/g1_47_summary.txt`.
