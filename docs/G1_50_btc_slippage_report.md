# تقرير G1.50 — لوحة تتبّع انزلاق BTC الثالثة بنافذة متحرّكة (عرض فقط)

**الحالة:** sealed · **الخطورة:** major · **البروتوكول:** 1.5 · **الطور:** G1_MANUAL_TESTING
**النطاق:** عرض فقط — لا منطق تداول/تنفيذ/hot_path ولا Live (§10.5).

## الطلب
لوحة ثالثة لتتبّع «انزلاق BTC» بنافذة متحرّكة (rolling window) لا مرساة ثابتة عند بدء المراقبة؛
لأن المرساة الثابتة تُظهر التغيّر التراكمي لا الانزلاق اللحظي. الغرض: رؤية سرعة/مقدار انزلاق BTC
خلال آخر ثوانٍ — نفس ما يُسلّح حارس هبوط BTC.

## الحل
لوحة عرض-فقط في `ocobot/ui` بجوار لوحتَي التتبّع القائمتين (G1.45/G1.48)، تعيد استخدام
`domain.btc_follow._window_drop` (ذروة النافذة مقابل آخر عيّنة) فيطابق المعروضُ ما يُسلّح الحارس.
تعرض: سعر BTC الحيّ · ذروة النافذة · انزلاق النافذة % (أحمر عند الهبوط، صيغة `0.00000%`) · طور الحارس
(خامل/مُسلّح). تُغذَّى لحظيًّا قراءةً فقط من مُشرِف العرض القائم `_btc_display_sup` بلا أي أثر تنفيذي.

## التنفيذ
- **chunk_1:** `ocobot/ui/btc_slippage_tracker.py` — دالة خالصة `window_slippage(samples, now, window_seconds)`
  (غلاف فوق `_window_drop` ⇒ `{drop_pct, peak, current}` أو `None`، fail-safe) + ودجت `BtcSlippageTracker`
  (عرض فقط، RTL، i18n + `retranslate_i18n`). + 7 مفاتيح `AR_TO_EN` في `ocobot/ui/i18n.py` (§1.5).
  اختبارات `tests/test_g1_50_btc_slippage.py` تثبت rolling peak مقابل anchored-at-start.
- **chunk_2:** ربط اللوحة في `ocobot/ui/monitoring.py` (استيراد + تهيئة + بناء داخل `_build_btc_follow_row`
  بجوار لوحة BTC + `_refresh_btc_slip_tracker` قراءةً فقط من `_btc_display_sup` + نداؤها في `_on_live_tick`).
  لا تعديل على `domain/btc_follow.py` أو `btc_follow_supervisor.py` (قراءة فقط).
- **chunk_3:** سويت خضراء كاملة + توثيق + ختم + أرشفة.

## الحدود (scope)
داخل: `ocobot/ui` (الوحدة الجديدة + ربط العرض في `monitoring.py`) + قراءة فقط من
`BtcFollowSupervisor.price_snapshot` / `domain.btc_follow._window_drop` + `ocobot/ui/i18n.py`.
خارج: أي منطق تداول/تنفيذ/hot_path/أوامر فعلية؛ لا تعديل للسوبرفايزر أو حارس BTC؛ لا Live.

## الدليل (acceptance)
تحقّق split-per-file (يتجاوز انهيار إغلاق Qt البيئي): **السويت الكامل أخضر — 0 فشل · 0 خطأ** (≥ baseline).
فحوص القبول مستوفاة: اللوحة عرض-فقط لا تمسّ أي تنفيذ/أمر · الانزلاق محسوب بنافذة متحرّكة
(اختبار rolling vs anchored-at-start) · §1.5 ثنائية اللغة بلا تسرّب عربي في EN بعد retranslate ·
لا كسر للوحتَي التتبّع القائمتين · لا Live.
