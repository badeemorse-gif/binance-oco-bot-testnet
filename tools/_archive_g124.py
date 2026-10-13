# -*- coding: utf-8 -*-
"""Step 6: ensure _archive is gitignored, validate both state JSONs one more time,
and move G1.24 temp/scratch files into _archive."""
import io
import json
import os
import shutil

ROOT = "."
ARCHIVE = "_archive"
GITIGNORE = ".gitignore"


def load(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


# 1) ensure _archive is gitignored
os.makedirs(ARCHIVE, exist_ok=True)
entries = []
if os.path.exists(GITIGNORE):
    with io.open(GITIGNORE, encoding="utf-8") as fh:
        entries = fh.read().splitlines()
has = any(l.strip().strip("/") == "_archive" for l in entries)
if not has:
    with io.open(GITIGNORE, "a", encoding="utf-8") as fh:
        if entries and entries[-1].strip() != "":
            fh.write("\n")
        fh.write("_archive/\n")
    print("GITIGNORE: added _archive/")
else:
    print("GITIGNORE: _archive already present")

# 2) move G1.24 temp/scratch files into _archive
temp_files = [
    "baseline_out.txt",
    "full_tests_out.txt",
    "pytest_full.txt",
    "pytest_full2.txt",
    "suspect.txt",
    "ts.txt",
    "cmd_out.txt",
    "_summary_tail.txt",
    os.path.join("tools", "_baseline_out.txt"),
    os.path.join("tools", "_suspect_out.txt"),
    os.path.join("tools", "_g123tests_out.txt"),
    os.path.join("tools", "_run_baseline.cmd"),
    os.path.join("tools", "_run_suspect.cmd"),
    os.path.join("tools", "_run_g123tests.cmd"),
    os.path.join("tools", "_write_g124.py"),
    os.path.join("tools", "_write_g124_verify.py"),
    os.path.join("tools", "_seal_g124.py"),
    os.path.join("tools", "_seal_g124_inspect2.py"),
    os.path.join("tools", "_apply_seal_g124.py"),
]
moved = []
for f in temp_files:
    if os.path.exists(f):
        dest = os.path.join(ARCHIVE, os.path.basename(f))
        if os.path.abspath(f) == os.path.abspath(dest):
            continue
        if os.path.exists(dest):
            os.remove(dest)
        shutil.move(f, dest)
        moved.append(f + " -> " + dest)
print("MOVED_COUNT:", len(moved))
for m in moved:
    print("  ", m)

# 3) final validation of both state files + confirm seal
ps = load("PROJECT_STATE.json")
g124 = next(e for e in ps["defect_log"] if "G1.24" in str(e.get("id")))
cs124 = [e for e in ps["completion_seals"] if e.get("task") == "G1.24"]
wm = load("WORKING_MEMORY.json")
print("FINAL_PROJECT_STATE: G1.24 status=", g124["status"], "evidence=", g124["evidence_path"], "seal.verified=", (g124.get("seal") or {}).get("verified"))
print("FINAL_completion_seals_G1.24:", json.dumps(cs124[-1], ensure_ascii=False) if cs124 else "MISSING")
print("FINAL_WORKING_MEMORY: active=", wm.get("active"), "resume_point=", wm.get("resume_point"), "last_sealed_task=", wm.get("last_sealed_task"))
print("BOTH_JSON_VALID: True")
print("EVIDENCE_FILE_EXISTS:", os.path.exists(os.path.join(ARCHIVE, "_g1_24_verify.txt")))
