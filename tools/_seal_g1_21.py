# -*- coding: utf-8 -*-
"""tools/_seal_g1_21.py

Atomically seal defect G1.21 (step_4_doc_seal) in PROJECT_STATE.json,
mirroring EXACTLY how G1.20 was sealed. Also updates WORKING_MEMORY.json.

Pattern: json.load -> modify in memory -> json.dump(ensure_ascii=False,
indent=2) to a temp file in the same dir -> os.replace -> re-parse to verify.

Does NOT touch system_prompt, phase, cursor, or any defect other than G1.21.
Does NOT clear WORKING_MEMORY (archive is the final step and still needs it).
"""
import io
import json
import os
import sys
import tempfile
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = os.path.join(ROOT, "PROJECT_STATE.json")
WM = os.path.join(ROOT, "WORKING_MEMORY.json")

# Single current ISO8601 UTC timestamp reused everywhere this seal needs one.
TS = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

EVIDENCE_PATH = "_g1_21_run.txt"
EVIDENCE_COUNT = 369

# Seal object: mirror G1.20 seal key order/shape exactly (no archive_status yet;
# that key was added to G1.20 only after its archive step completed).
SEAL = {
    "task": "G1.21",
    "verified": True,
    "evidence_path": EVIDENCE_PATH,
    "evidence_count": EVIDENCE_COUNT,
    "docs_synced": True,
    "ts": TS,
}

# completion_seals[] entry: same shape as G1.20's completion_seals entry.
CS_ENTRY = {
    "task": "G1.21",
    "verified": True,
    "evidence_path": EVIDENCE_PATH,
    "evidence_count": EVIDENCE_COUNT,
    "docs_synced": True,
    "ts": TS,
}

# run_log[] entry: keys ts/actor/task/note, note begins "<task> sealed —".
RL_ENTRY = {
    "ts": TS,
    "actor": "executor",
    "task": "G1.21",
    "note": (
        "G1.21 sealed — إعادة ترتيب اللوحة الحيّة: جني الأرباح الحالي|التالي "
        "في صف، ووقف الخسارة الحالي|التالي في صف تحته، وبقية الحقول أسفلها؛ "
        "نفس الستايل والمنطق؛ صفر انحدار؛ الدليل _g1_21_run.txt (Ran 369 OK) "
        "+ اختباران جديدان."
    ),
}


def atomic_write_json(path, data):
    """Write JSON atomically: temp file in same dir, flush+fsync, os.replace."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=d)
    try:
        with io.open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ---------- PROJECT_STATE.json ----------
with io.open(PS, "r", encoding="utf-8") as f:
    ps = json.load(f)

# Locate the G1.21 defect entry (only this one is touched).
g21 = None
for entry in ps["defect_log"]:
    if entry.get("id") == "G1.21":
        g21 = entry
        break
if g21 is None:
    raise SystemExit("G1.21 not found in defect_log")

g21["status"] = "sealed"
g21["evidence_path"] = EVIDENCE_PATH
g21["evidence_count"] = EVIDENCE_COUNT
g21["seal"] = dict(SEAL)
g21["contract"]["ordered_steps"]["step_4_doc_seal"] = "done"
# step_5_archive stays "pending" (not touched).

# Guard: do not duplicate completion_seals / run_log G1.21 entries.
if not any(x.get("task") == "G1.21" for x in ps["completion_seals"]):
    ps["completion_seals"].append(dict(CS_ENTRY))
if not any(
    x.get("task") == "G1.21" and str(x.get("note", "")).startswith("G1.21 sealed")
    for x in ps["run_log"]
):
    ps["run_log"].append(dict(RL_ENTRY))

ps["last_updated"] = TS

atomic_write_json(PS, ps)

# Re-parse to confirm valid JSON.
with io.open(PS, "r", encoding="utf-8") as f:
    ps2 = json.load(f)

# ---------- WORKING_MEMORY.json ----------
with io.open(WM, "r", encoding="utf-8") as f:
    wm = json.load(f)

wm["last_completed_step"] = "step_4_doc_seal"
wm["resume_point"] = "step_5_archive__pending"
wm["remaining"] = ["step_5_archive"]
wm["updated_at"] = TS

atomic_write_json(WM, wm)

with io.open(WM, "r", encoding="utf-8") as f:
    wm2 = json.load(f)

# ---------- Report ----------
g21_out = next(x for x in ps2["defect_log"] if x.get("id") == "G1.21")
cs_out = [x for x in ps2["completion_seals"] if x.get("task") == "G1.21"]
rl_out = [
    x for x in ps2["run_log"]
    if x.get("task") == "G1.21" and str(x.get("note", "")).startswith("G1.21 sealed")
]

out = {
    "ts": TS,
    "project_state_valid_json": True,
    "defect_status": g21_out.get("status"),
    "defect_evidence_path": g21_out.get("evidence_path"),
    "defect_evidence_count": g21_out.get("evidence_count"),
    "ordered_steps": g21_out.get("contract", {}).get("ordered_steps"),
    "seal_object": g21_out.get("seal"),
    "completion_seals_entry": cs_out,
    "run_log_entry": rl_out,
    "last_updated": ps2.get("last_updated"),
    "working_memory": {
        "last_completed_step": wm2.get("last_completed_step"),
        "resume_point": wm2.get("resume_point"),
        "remaining": wm2.get("remaining"),
        "updated_at": wm2.get("updated_at"),
        "active": wm2.get("active"),
        "task_id": wm2.get("task_id"),
    },
}

sys.stdout.buffer.write(
    json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")
)
