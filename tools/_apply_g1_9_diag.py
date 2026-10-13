"""G1.9 step_1_diag — atomic WM update (json round-trip + os.replace).

Records scan_findings, appends a decisions_session entry, marks step_1_diag
done, advances resume_point, bumps updated_at. Diagnosis only — no code/test
files touched, PROJECT_STATE.json untouched.
"""
import io
import json
import os

WM = r"D:\oco\WORKING_MEMORY.json"

with io.open(WM, "r", encoding="utf-8") as fh:
    wm = json.load(fh)

wm["scan_findings"] = {
    "disk_verified": True,
    "symptom1_buttons_root_cause": {
        "file_line": "ocobot/ui/app.py:47",
        "call": "window.setMaximumSize(avail.width(), avail.height())",
        "invoked_from": "ocobot/ui/app.py:76 (main() -> _clamp_window_to_screen(window))",
        "mechanism": (
            "على ويندوز، عندما يكون maximumSize أصغر من دقة الشاشة الكاملة (هنا "
            "availableGeometry التي تستثني شريط المهام)، يستنتج مدير النوافذ أن "
            "النافذة لا يمكن أن تتمدّد لملء الشاشة، فيُعطّل/يُخفت زر التكبير في شريط "
            "العنوان الأصلي. أُضيف هذا الاستدعاء في G1.6. لا يوجد أي setWindowFlags "
            "في MainWindow (main_window.py) يقيّد التلميحات؛ وبالتالي فالسبب الوحيد هو "
            "قيد setMaximumSize. زر التصغير قد يبقى لكن التكبير يُعطّل، وبعض إصدارات "
            "ويندوز/بعض الثيمات تُظهر شريط عنوان مقلّصًا (X فقط بارز)."
        ),
        "no_setwindowflags_in_ui": "لا توجد أي مطابقة لـ setWindowFlags في ocobot/ui/*.py",
    },
    "symptom2_zoom_root_cause": {
        "feature_absent": True,
        "evidence": (
            "لا مطابقة لـ wheelEvent أو ControlModifier أو zoom في ocobot/ui/*.py "
            "ولا في tests/*.py (findstr). لا يوجد أي override لـ wheelEvent ولا "
            "eventFilter في MainWindow. الميزة غير موجودة أصلًا."
        ),
        "chosen_injection_point": (
            "override لـ MainWindow.wheelEvent (main_window.py) يلتقط عجلة الماوس مع "
            "Qt.KeyboardModifier.ControlModifier؛ بديل: eventFilter مثبّت على "
            "self._content_scroll (QScrollArea) وviewport-ه. يُفضّل wheelEvent على "
            "مستوى MainWindow لأنه يغطّي كل الشاشات داخل الـ QScrollArea القائم."
        ),
        "scaling_mechanism": (
            "الاعتماد على مقاربة الزوم عبر الخط: تعديل معامل zoom يُعيد تطبيق حجم "
            "نقطة الخط الأساسي عبر الثيم (theme.apply_theme يضبط app.setFont("
            "QFont('Tajawal', 10)) في theme.py:110). يُضاف base_point_size + "
            "set_zoom(factor) يعيد ضبط app.setFont بالحجم المُقاس، فيعيد المحتوى "
            "التدفّق داخل QScrollArea الموجود دون كسر التخطيط."
        ),
        "bounds_reset": (
            "حدود المعامل 0.8x–2.5x بخطوة ~0.1 لكل درجة عجلة؛ Ctrl+0 لإعادة الضبط "
            "إلى 1.0x. تُثبّت القيمة (clamp) ضمن الحدود."
        ),
    },
    "fix_plan_step2": {
        "target": "ocobot/ui/app.py :: _clamp_window_to_screen + ocobot/ui/main_window.py :: MainWindow.__init__",
        "edits": [
            "إزالة/تعديل السطر ocobot/ui/app.py:47 window.setMaximumSize(avail.width(), avail.height()) "
            "لأنه هو ما يُعطّل زر التكبير على ويندوز.",
            "إبقاء 'الاحتواء داخل الشاشة' عبر resize(min(hint,avail)) + move/moveCenter فقط (بلا سقف حجم "
            "دائم)، والسماح لزر التكبير بالتكبير إلى availableGeometry.",
            "في MainWindow.__init__ ضبط علامات النافذة صراحةً لتشمل التلميحات الثلاثة: "
            "self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinimizeButtonHint | "
            "Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint).",
            "التأكّد من إعادة تصدير Qt (متوفر في _qt.py) — لا حاجة لرمز Qt جديد إذ Qt.WindowType متاح عبر Qt.",
        ],
        "keep_g1_6_constraint": "يبقى المحتوى ملفوفًا في QScrollArea (main_window.py:73-77) والنافذة تُحتوى داخل الشاشة عبر resize+move بدل السقف الصلب.",
    },
    "fix_plan_step3": {
        "target": "ocobot/ui/main_window.py (+ ocobot/ui/theme.py hook)",
        "edits": [
            "إضافة حالة زوم في MainWindow: self._zoom = 1.0 وقاعدة نقطة الخط الأساسية (10 من theme.py).",
            "override MainWindow.wheelEvent(self, event): إذا event.modifiers() & Qt.KeyboardModifier.ControlModifier "
            "استخدم event.angleDelta().y() لزيادة/إنقاص self._zoom بخطوة، ثم استدعِ _apply_zoom() وevent.accept()؛ "
            "وإلا super().wheelEvent(event).",
            "override keyPressEvent أو اختصار: Ctrl+0 يعيد self._zoom=1.0 ثم _apply_zoom().",
            "_apply_zoom(): clamp إلى [0.8, 2.5] ثم QApplication.instance().setFont(QFont('Tajawal', round(10*zoom))) "
            "أو إضافة دالة theme.set_base_font_scale(app, scale) في theme.py تُعيد تطبيق الخط؛ المحتوى يعيد التدفّق داخل QScrollArea.",
            "الحاجة لاستيراد QWheelEvent غير إلزامية (يكفي التوقيع العام)؛ إن لزم إضافة QWheelEvent إلى _qt.py re-exports.",
        ],
        "note": "الاعتماد على الخط يُبقي التخطيط سليمًا ويستفيد من QScrollArea القائم للتمرير عند تجاوز الحجم.",
    },
    "tests_impact": {
        "test_g1_6_window_scroll_and_size": {
            "asserts_max_equals_available": True,
            "lines": [
                "tests/test_g1_6_window_scroll_and_size.py:40 assertEqual(window.maximumWidth(), avail.width())",
                "tests/test_g1_6_window_scroll_and_size.py:41 assertEqual(window.maximumHeight(), avail.height())",
            ],
            "must_update_in_step_4": True,
            "reason": (
                "بما أن step_2 يزيل setMaximumSize، ستفشل هاتان الدعوتان. يجب تحديثهما في step_4 "
                "لتأكيد 'الاحتواء داخل الشاشة' عبر width()/height() <= avail بدل مساواة maximum==avail، "
                "مع الإبقاء على اختبار QScrollArea (السطور 24-31) كما هو."
            ),
        },
        "other_tests_asserting_flags_or_size": "لا توجد اختبارات أخرى تؤكّد setMaximumSize/maximumSize/setWindowFlags/wheelEvent (findstr على tests\\*.py بلا نتائج أخرى).",
    },
}

wm.setdefault("decisions_session", []).append({
    "at": "2026-09-29T01:20:00Z",
    "step": "step_1_diag",
    "decision": (
        "تثبيت جذري العيبين بالأدلة: (1) زر التكبير يُعطّل على ويندوز بسبب "
        "app.py:47 setMaximumSize(availableGeometry) المُضاف في G1.6 — لا "
        "setWindowFlags يقيّد التلميحات في main_window.py. (2) ميزة Ctrl+wheel "
        "zoom غائبة تمامًا (لا wheelEvent/ControlModifier/zoom في ocobot/ui أو "
        "tests). الخطة: step_2 يزيل سقف الحجم ويضبط WindowMinimize/Maximize/Close "
        "ButtonHint مع الاحتواء عبر resize+move؛ step_3 يضيف override لـ "
        "wheelEvent يزوم عبر خط الثيم بحدود 0.8x–2.5x وCtrl+0 لإعادة الضبط. "
        "tests/test_g1_6_window_scroll_and_size.py السطران 40-41 يجب تحديثهما في "
        "step_4. لم يُعدّل أي كود/اختبار، ولم يُمسّ PROJECT_STATE.json."
    ),
})

for s in wm.get("ordered_steps", []):
    if s.get("id") == "step_1_diag":
        s["status"] = "done"

wm["resume_point"] = "step_2_fix_window_buttons"
wm["active"] = True
wm["updated_at"] = "2026-09-29T01:20:00Z"

tmp = WM + ".tmp"
with io.open(tmp, "w", encoding="utf-8") as fh:
    json.dump(wm, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, WM)

# Re-read + verify.
with io.open(WM, "r", encoding="utf-8") as fh:
    v = json.load(fh)

step1 = next((s["status"] for s in v["ordered_steps"] if s["id"] == "step_1_diag"), None)
print("VALID_JSON= True")
print("step_1_diag= " + str(step1))
print("resume_point= " + str(v.get("resume_point")))
print("scan_findings_present= " + str("scan_findings" in v))
print("active= " + str(v.get("active")))
