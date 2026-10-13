# -*- coding: utf-8 -*-
"""Write-First registration for defect G1.21 (protocol §10.2).

Atomic JSON edits only: json.load -> modify -> json.dump(ensure_ascii=False,
indent=2) -> temp file -> os.replace. Does NOT touch system_prompt, phase,
cursor, completion_seals, or any other defect entry. Writes no application code.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = os.path.join(ROOT, "PROJECT_STATE.json")
WM = os.path.join(ROOT, "WORKING_MEMORY.json")

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

TITLE = (
    "إعادة ترتيب خانات اللوحة الحيّة في المراقبة الديناميكية لعرض جني الأرباح/وقف "
    "الخسارة (الحالي والتالي) جنبًا إلى جنب دون تغيير الستايل أو المنطق أو انحدار"
)

DESCRIPTION = (
    "خانات اللوحة الحيّة (جني الأرباح الحالي، وقف الخسارة الحالي، جني الأرباح التالي، "
    "وقف الخسارة التالي) معروضة عموديًا تحت بعضها مما يسبب لخبطة بصرية. المطلوب نقلها "
    "جنبًا إلى جنب: صف أول (جني الأرباح الحالي | جني الأرباح التالي) وصف ثانٍ (وقف "
    "الخسارة الحالي | وقف الخسارة التالي)، مع بقاء باقي الحقول أسفلها كما هي، ونفس "
    "الستايل، ونفس كفاءة البوت."
)

PROPOSAL = (
    "توسيع QGridLayout للّوحة الحيّة إلى 4 أعمدة (عنوان|قيمة|عنوان|قيمة): وضع "
    "current_tp و next_tp في صف واحد، و current_sl و next_sl في الصف التالي؛ وإبقاء "
    "بقية الحقول صفوفًا مفردة تمتدّ عبر العرض أسفلهما. الحفاظ على نفس objectNames "
    "والمفاتيح self._live والأحجام الدنيا (قيمة ≥120) وسياسة Expanding والعناوين "
    "QLabel عربية. لا تغيير في _refresh_live_panel ولا في منطق المراقبة/التسعير."
)

CONSTRAINT = (
    "صفر انحدار — كل الاختبارات الخضراء (≥367) تبقى خضراء؛ لا كسر لحرّاس "
    "test_ui_monitoring (حضور/ظهور الـ15 مفتاحًا) ولا test_g1_4_layout_geometry "
    "(لا تداخل عنوان/قيمة عند 420 و1920 + القيم minWidth≥120) ولا test_g1_5 (نمو "
    "القيمة) ولا test_g1_7_ui_arabic (لا إنجليزية في monitoring.py) ولا "
    "test_g1_20_language_toggle."
)

CONTRACT = {
    "task_id": "G1.21",
    "definition_of_done": (
        "في ocobot/ui/monitoring._build_live_panel تُعرض الحقول الأربعة في صفّين: "
        "الصف الأول current_tp | next_tp، والصف الثاني current_sl | next_sl؛ وتبقى "
        "باقي الحقول (sl_limit, tick_size, monitoring_state, last_operation, "
        "connection, environment) أسفلها بنفس الترتيب؛ ونفس QGridLayout/الألوان/"
        "الأحجام الدنيا؛ وكل الـ15 مفتاحًا تبقى في self._live وظاهرة دائمًا؛ وبلا أي "
        "سلسلة إنجليزية في monitoring.py؛ وبلا تغيير في منطق المراقبة/التسعير/"
        "التحويل؛ وكل الاختبارات خضراء (Ran ≥ 368، OK، صفر FAILED)."
    ),
    "acceptance_checks": {
        "AC1": (
            "run_tests.cmd يُظهر Ran ≥ 368 (367 + اختبار G1.21 الجديد)، وسطر OK، "
            "وصفر FAILED (صفر انحدار)."
        ),
        "AC2": (
            "اختبار جديد tests/test_g1_21_live_panel_side_by_side.py: في شبكة اللوحة "
            "الحيّة، current_tp و next_tp في نفس الصف وعمودين مختلفين؛ current_sl و "
            "next_sl في نفس الصف؛ صف TP مباشرةً فوق صف SL؛ وبقية الحقول "
            "(sl_limit..environment) في صفوف أسفلهما."
        ),
        "AC3": (
            "حارس test_ui_monitoring (كل الـ15 مفتاحًا حاضرة وظاهرة) أخضر؛ وحارس "
            "test_g1_4_layout_geometry (لا تداخل caption/value عند 420 و1920 + القيم "
            "minWidth≥120) أخضر؛ وحارس test_g1_5 (نمو قيمة symbol) أخضر."
        ),
        "AC4": (
            "حارس test_g1_7_ui_arabic (لا إنجليزية مقتبسة في monitoring.py) و "
            "test_g1_20_language_toggle يبقيان أخضرين؛ العناوين تبقى QLabel بنصوص "
            "عربية."
        ),
        "AC5_manual": "فحص بصري يدوي على Testnet (اختياري بعد الختم الفني).",
    },
    "ordered_steps": {
        "step_0_contract": "done",
        "step_1_reflow_monitoring": "pending",
        "step_2_test": "pending",
        "step_3_run": "pending",
        "step_4_doc_seal": "pending",
        "step_5_archive": "pending",
    },
    "scope_boundary": {
        "inside": [
            "ocobot/ui/monitoring.py (منطقة _build_live_panel وبنية الشبكة/ترتيب الصفوف فقط)",
            "tests/test_g1_21_live_panel_side_by_side.py (جديد)",
        ],
        "outside": [
            "منطق المراقبة/النبض/التسعير/التحويل",
            "_refresh_live_panel (القيم والمنطق)",
            "طبقة core",
            "ocobot/ui/demo_mode.py وبقية الشاشات",
            "الثوابت العربية ونصوص الحقول (تبقى حرفيًا)",
            "ocobot/ui/i18n.py AR_TO_EN",
            "Live/T16",
        ],
    },
    "expected_evidence": {
        "command": "run_tests.cmd",
        "expected_count": ">=368",
        "evidence_path": "_g1_21_run.txt",
    },
    "checkpoint_plan": (
        "chunk A: إعادة بناء شبكة اللوحة الحيّة في monitoring.py ثم تحقق من القرص؛ "
        "chunk B: إضافة test_g1_21 ثم تشغيل run_tests.cmd — صفر FAILED عند كل نقطة."
    ),
    "dependencies_check": (
        "G1.20 مختوم ومؤرشف (archive_status=done)؛ لا بنود critical/major غير مختومة."
    ),
    "sizing_verdict": (
        "صغير/متوسط §9.5 — ملف تنفيذ واحد + اختبار؛ تجزئة خفيفة (chunk A ثم B) مع "
        "تشغيل اختبارات."
    ),
    "human_gate": False,
    "risks": {
        "R1": (
            "تداخل عنوان/قيمة عند التضييق (420px). تخفيف: إبقاء minWidth≥120 للقيم "
            "وأعمدة شبكة بأدنى عرض؛ QGridLayout لا يُراكِب الخلايا."
        ),
        "R2": (
            "كسر حرّاس الهندسة. تخفيف: إبقاء objectNames "
            "(MonitoringLiveCaption_<key>/MonitoringLiveValue_<key>) وسياسة Expanding "
            "والأحجام الدنيا."
        ),
        "R3": (
            "كسر تبديل اللغة. تخفيف: العناوين تبقى QLabel بنصوص عربية موجودة في "
            "AR_TO_EN؛ لا تغيير للنصوص."
        ),
        "R4": (
            "إدخال سلسلة إنجليزية في monitoring.py. تخفيف: لا literals جديدة؛ العناوين "
            "من LIVE_FIELDS الحالية."
        ),
    },
}

G1_21_ENTRY = {
    "id": "G1.21",
    "title": TITLE,
    "severity": "minor",
    "category": "enhancement",
    "status": "contracted",
    "opened_ts": NOW,
    "description": DESCRIPTION,
    "professional_proposal": PROPOSAL,
    "constraint": CONSTRAINT,
    "contract": CONTRACT,
    "evidence_path": None,
    "seal": None,
}

WM_CONTENT = {
    "active": True,
    "task_id": "G1.21",
    "title": TITLE,
    "status": "in_progress",
    "human_gate": False,
    "contract_ref": "PROJECT_STATE.json.defect_log[G1.21].contract",
    "decisions_session": [
        "D-G1.21-grid4col: توسيع شبكة اللوحة الحيّة إلى 4 أعمدة؛ صفّان مزدوجان current_tp|next_tp ثم current_sl|next_sl؛ بقية الحقول صفوف مفردة تمتدّ أسفلهما.",
        "D-G1.21-preserve: إبقاء objectNames والمفاتيح والأحجام الدنيا والعناوين QLabel العربية؛ _refresh_live_panel مفتاحي فلا يتأثر بإعادة الترتيب.",
        "D-G1.21-shape: اعتُمد شكل G1.20 مع إضافة description و professional_proposal المطلوبين في §10.2 (مجموعة فائقة)؛ opened_ts مفتاح الوقت؛ evidence_count يُضاف عند الختم.",
    ],
    "last_completed_step": "step_0_contract",
    "resume_point": "step_1_reflow_monitoring__pending",
    "remaining": [
        "step_1_reflow_monitoring",
        "step_2_test",
        "step_3_run",
        "step_4_doc_seal",
        "step_5_archive",
    ],
    "expected_evidence": {
        "command": "run_tests.cmd",
        "expected_count": ">=368",
        "evidence_path": "_g1_21_run.txt",
    },
    "note": (
        "G1.21 مُسجَّل (Write-First). التالي step_1 إعادة بناء شبكة اللوحة الحيّة في "
        "monitoring.py (4 أعمدة، صفّان مزدوجان) ثم اختبار ثم تشغيل. لا كود بعد."
    ),
    "updated_at": NOW,
}


def atomic_write(path, obj):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# --- 1 & 2: append G1.21 to defect_log; update root last_updated ---
with open(PS, encoding="utf-8") as f:
    state = json.load(f)

if not isinstance(state.get("defect_log"), list):
    raise SystemExit("defect_log is not a list; aborting to avoid corruption")

existing_ids = [e.get("id") for e in state["defect_log"] if isinstance(e, dict)]
if "G1.21" in existing_ids:
    raise SystemExit("G1.21 already present; aborting to avoid duplicate")

state["defect_log"].append(G1_21_ENTRY)
state["last_updated"] = NOW

atomic_write(PS, state)

# re-parse PROJECT_STATE.json
with open(PS, encoding="utf-8") as f:
    state2 = json.load(f)
appended = [e for e in state2["defect_log"] if isinstance(e, dict) and e.get("id") == "G1.21"]
assert len(appended) == 1, "G1.21 not appended exactly once"
print("PROJECT_STATE.json re-parsed OK; last_updated =", state2.get("last_updated"))
print("defect_log last ids:", [e.get("id") for e in state2["defect_log"] if isinstance(e, dict)][-4:])

# --- 3: overwrite WORKING_MEMORY.json ---
atomic_write(WM, WM_CONTENT)
with open(WM, encoding="utf-8") as f:
    wm2 = json.load(f)
print("WORKING_MEMORY.json re-parsed OK; active =", wm2.get("active"), "task_id =", wm2.get("task_id"))

print("===G1.21_ENTRY_WRITTEN===")
print(json.dumps(appended[0], ensure_ascii=False, indent=2))
print("===WORKING_MEMORY_FULL===")
print(json.dumps(wm2, ensure_ascii=False, indent=2))
print("===BOTH_REPARSE_VALID===")
