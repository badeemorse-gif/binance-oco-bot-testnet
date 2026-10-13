# -*- coding: utf-8 -*-
import json, datetime, io, sys

TS = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PS = r"D:\oco\PROJECT_STATE.json"
WM = r"D:\oco\WORKING_MEMORY.json"

# ---------- PROJECT_STATE.json ----------
with io.open(PS, "r", encoding="utf-8") as f:
    ps = json.load(f)

# A1: append completion seal
ps["completion_seals"].append({
    "task": "T10b",
    "verified": True,
    "evidence_path": "_t10b_run.txt",
    "evidence_count": 184,
    "docs_synced": True,
    "ts": TS,
})

# A2/A3: task_ledger statuses
for t in ps["task_ledger"]:
    if t.get("id") == "T10b":
        t["status"] = "done"
    elif t.get("id") == "T10c":
        t["status"] = "next"

# A4: cursor
ps["cursor"] = {"last_completed": "T10b", "current": "T10c", "next": "T10c"}

# A5: run_log append
ps["run_log"].append({
    "ts": TS,
    "actor": "executor",
    "task": "T10b (done)",
    "note": "أُنجزت T10b (M-UI/0b قوقعة التنقّل): Sidebar يمين RTL + Topbar (عنوان + Pills Environment/Connection ثابتة) + Content عبر QStackedWidget مع توجيه، مدموجة في MainWindow، مطابِقة للموك‑أب بلا منطق أعمال. 184 tests OK → _t10b_run.txt. HANDOFF→T10c. cursor last_completed=T10b, current/next=T10c.",
})

# A6: file_map.ui_layer
ps["file_map"]["ui_layer"] = "ocobot/ui/ (T10a أساس + T10b قوقعة التنقّل Sidebar/Topbar/Content+توجيه منجَزان؛ T10c–T14 قيد البناء حسب docs/ui_mockups)"

with io.open(PS, "w", encoding="utf-8") as f:
    json.dump(ps, f, ensure_ascii=False, indent=2)

# ---------- WORKING_MEMORY.json ----------
wm = {
    "schema": "oco.working_memory.v1",
    "active": False,
    "task_id": None,
    "contract": None,
    "steps": [],
    "last_completed_step": None,
    "current_step": None,
    "resume_point": None,
    "remaining": [],
    "decisions_session": [],
    "evidence_partial": [],
    "updated_at": None,
}
with io.open(WM, "w", encoding="utf-8") as f:
    json.dump(wm, f, ensure_ascii=False, indent=2)

# ---------- RE-READ verify ----------
with io.open(PS, "r", encoding="utf-8") as f:
    ps2 = json.load(f)
with io.open(WM, "r", encoding="utf-8") as f:
    wm2 = json.load(f)

t10b_seal = [s for s in ps2["completion_seals"] if s["task"] == "T10b"]
t10b_status = [t["status"] for t in ps2["task_ledger"] if t.get("id") == "T10b"]
t10c_status = [t["status"] for t in ps2["task_ledger"] if t.get("id") == "T10c"]

out = {
    "T10b_seal": t10b_seal,
    "T10b_status": t10b_status,
    "T10c_status": t10c_status,
    "cursor": ps2["cursor"],
    "run_log_last": ps2["run_log"][-1],
    "file_map_ui_layer": ps2["file_map"]["ui_layer"],
    "working_memory": wm2,
    "PS_valid_json": True,
    "WM_valid_json": True,
}
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"))
sys.stdout.buffer.write(b"\n")
