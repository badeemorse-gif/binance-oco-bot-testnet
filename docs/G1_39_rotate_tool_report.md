# G1.39 — أداة التدوير الدائمة + قابلية الاستنساخ (بروتوكول 1.4)

## ما أُنجز
- **البند 11.4**: تعريف أداة `tools/rotate_state.py` الدائمة ضمن روتين الختم (تطبيق آلي للبند 11.1).
- **البند 11.5**: قابلية الاستنساخ — بنود القسم 11 بنود حاكمة عامة (project-agnostic) قابلة للنقل لأي مشروع.
- **الأداة** `tools/rotate_state.py`: مكتبة + واجهة سطر أوامر:
  - `verify` — فحص سلامة: مطابقة بصمات `sha256` لكل `defect_log[].ref` ولِـ `*_store` مع ملفات `state/`، ومطابقة الأعداد.
  - `apply <ops.json>` — تطبيق ذرّي لعمليات (defects / decisions / runlog / seals / protocol_append / working_memory) مع نسخة احتياطية في `_archive` ثم `verify`.
- **ملف الاقتطاف** `docs/PORTABLE_PROTOCOL_CLAUSES.md`: مُولَّد من نفس نص القسم 11 (متزامن مع 11.5).
- **تحديث المراجع**: `prompt.md` و `docs/EXECUTOR_PROMPT_AR.md` إلى الإصدار/الأقسام الحالية.

## التحقق
- `python tools/rotate_state.py verify` ⇒ OK (قبل وبعد ختم G1.39).
- خُتم G1.39 عبر الأداة نفسها (dogfooding) لا عبر سكربت لمرة واحدة.

## كيفية الاستنساخ لمشروع آخر
1. تبنَّ اصطلاح ملفات الحالة: `PROJECT_STATE.json`, `WORKING_MEMORY.json`, `state/`, `_archive`, `tools/rotate_state.py`.
2. انسخ `docs/PORTABLE_PROTOCOL_CLAUSES.md` (القسم 11) إلى بروتوكول المشروع الجديد.
3. انسخ `tools/rotate_state.py` كما هي.
