# G1.40 — فهرس الأرشيف `_archive/manifest.json` (البند 11.6)

## ما أُنجز
- **البند 11.6** في `system_prompt`: عند نقل أي ملف إلى `_archive` يُسجَّل قيد في `_archive/manifest.json` بـ `{file, origin_path, task, reason, ts}` — ليبقى الأرشيف قابلًا للاستكشاف والاسترجاع الموجَّه دون إدخاله في مسار القراءة الروتيني. (امتداد للبند 11.3.)
- **دعم في `tools/rotate_state.py`**:
  - `archive_file(path, task, reason)` — ينقل الملف إلى `_archive` ويُسجّله في المانيفست.
  - مُدمَج في `apply` عبر مفتاح `archive` في ops (ضمن خطوة التنظيف الآلية).
  - `backup()` صار يُسجّل نُسخه الاحتياطية في المانيفست أيضًا.
  - أمر CLI جديد: `python tools/rotate_state.py archive <path> <task> <reason>`.
  - `verify` يطبع `manifest_entries`.
- **تزامن** `docs/PORTABLE_PROTOCOL_CLAUSES.md` مع القسم 11 (يشمل 11.6 الآن).

## التحقق
- خُتم G1.40 عبر الأداة نفسها (dogfooding)؛ أُرشِف سكربت المرحلة الأولى وسُجِّل في المانيفست.
- `rotate_state.py verify` ⇒ OK.

## الاسترجاع الموجَّه
للعثور على ملف مؤرشَف: افتح `_archive/manifest.json` وابحث بـ `task` أو `origin_path`، ثم استرجع `file` من `_archive/`.
