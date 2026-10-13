import re, json, os, tempfile
path = r"D:\oco\PROJECT_STATE.json"
with open(path, "rb") as f:
    raw = f.read()
text = raw.decode("utf-8")
assert "\r\n" in text, "expected CRLF"

def set_status(t, task_id, new_status):
    m = re.search(r'\{"id":"' + re.escape(task_id) + r'"', t)
    assert m, "task object not found: " + task_id
    start = m.start()
    sm = re.search(r'"status":"[a-z_]+"', t[start:])
    assert sm, "status not found for " + task_id
    s0, s1 = start + sm.start(), start + sm.end()
    return t[:s0] + '"status":"' + new_status + '"' + t[s1:]

# EDIT 1: T5 -> done
text = set_status(text, "T5", "done")
# EDIT 2: T6 -> next
text = set_status(text, "T6", "next")

# EDIT 3: cursor
old_cursor = '{"last_completed":"T4","current":"T5","next":"T5"}'
new_cursor = '{"last_completed":"T5","current":"T6","next":"T6"}'
assert text.count(old_cursor) == 1, "cursor anchor not unique/found"
text = text.replace(old_cursor, new_cursor)

# EDIT 4: open_questions storage-format string
old_oq = "\u0635\u064a\u063a\u0629 \u0627\u0644\u062a\u062e\u0632\u064a\u0646 \u2014 \u062a\u064f\u062d\u0633\u0645 \u062f\u0627\u062e\u0644 T5 (\u0623\u0633\u0627\u0633 \u0627\u0644\u062a\u062e\u0632\u064a\u0646)\u061b \u0627\u0644\u0627\u0641\u062a\u0631\u0627\u0636\u064a \u0627\u0644\u0645\u0642\u062a\u0631\u062d: JSON checkpoint \u0630\u0631\u0651\u064a + JSONL \u0644\u0644\u0640 audit (\u0645\u0643\u062a\u0628\u0629 \u0642\u064a\u0627\u0633\u064a\u0629 \u0641\u0642\u0637)\u060c \u0648SQLite \u0628\u062f\u064a\u0644 \u0645\u0648\u062b\u0651\u0642."
new_oq = "\u0635\u064a\u063a\u0629 \u0627\u0644\u062a\u062e\u0632\u064a\u0646 \u2014 \u062d\u064f\u0633\u0650\u0645\u062a \u0641\u064a T5 (\u0623\u0633\u0627\u0633 \u0627\u0644\u062a\u062e\u0632\u064a\u0646): JSON checkpoint \u0630\u0631\u0651\u064a (temp\u2192rename+fsync) + JSONL \u0644\u0644\u0640 audit (\u0645\u0643\u062a\u0628\u0629 \u0642\u064a\u0627\u0633\u064a\u0629 \u0641\u0642\u0637\u060c \u0628\u0644\u0627 \u0627\u0639\u062a\u0645\u0627\u062f \u062e\u0627\u0631\u062c\u064a)\u061b SQLite \u0628\u062f\u064a\u0644 \u0645\u0648\u062b\u0651\u0642 \u0645\u0624\u062c\u064e\u0651\u0644 (\u0644\u0627 \u064a\u0628\u0631\u0651\u0631\u0647 \u0643\u0627\u062a\u0628 \u0648\u0627\u062d\u062f \u0628\u062a\u0631\u062f\u0651\u062f \u0645\u0646\u062e\u0641\u0636). \u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u0641\u064a ocobot/core/state_store.py \u0628\u0640 SCHEMA_VERSION=1."
assert text.count(old_oq) == 1, "open_question anchor not unique/found"
text = text.replace(old_oq, new_oq)

# EDIT 5: append run_log entry (before run_log's closing ] that precedes "resume_protocol")
run_log_note = "\u0623\u064f\u0646\u062c\u0632\u062a M4a \u2014 \u0623\u0633\u0627\u0633 \u0627\u0644\u062a\u062e\u0632\u064a\u0646 (T5). \u0643\u0648\u062f: ocobot/core/state_store.py (\u0645\u0643\u062a\u0628\u0629 \u0642\u064a\u0627\u0633\u064a\u0629 \u0641\u0642\u0637): \u0643\u062a\u0627\u0628\u0629 \u0630\u0631\u0651\u064a\u0629 (tempfile \u0641\u064a \u0646\u0641\u0633 \u0627\u0644\u0645\u062c\u0644\u062f \u2192 flush \u2192 os.fsync \u2192 os.replace + fsync \u0644\u0644\u0645\u062c\u0644\u062f best-effort + \u062a\u0646\u0638\u064a\u0641 temp \u0639\u0646\u062f \u0627\u0644\u0641\u0634\u0644 \u21d2 \u062a\u0639\u0637\u0651\u0644 \u0645\u0646\u062a\u0635\u0641 \u0627\u0644\u0643\u062a\u0627\u0628\u0629 \u064a\u064f\u0628\u0642\u064a \u0622\u062e\u0631 \u0645\u0644\u0641 \u0633\u0644\u064a\u0645 \u0643\u0645\u0627 \u0647\u0648)\u060c \u0648\u0642\u0631\u0627\u0621\u0629 \u0622\u0645\u0646\u0629 (\u0645\u0641\u0642\u0648\u062f/\u0641\u0627\u0631\u063a/\u0645\u0628\u062a\u0648\u0631/\u0641\u0627\u0633\u062f/\u063a\u064a\u0631 UTF-8 \u21d2 None\u061b StateStoreError \u0641\u064a \u0648\u0636\u0639 strict). \u0633\u0643\u064a\u0645\u0629 dataclasses SCHEMA_VERSION=1: MonitoringCheckpoint (\u0643\u0644 15 \u062d\u0642\u0644 MonitoringState \u0627\u0644\u0644\u0627\u0632\u0645\u0629 \u0644\u0644\u0627\u0633\u062a\u0626\u0646\u0627\u0641: enabled/state/symbol/reference_price/trigger_pct/tp_pct/sl_pct/latched/in_flight/target_order_list_id/tolerance_pct/guard_pct/last_price/last_reposition/cursor) + SelectedOcoContext + SymbolFiltersSchema + LogLocations (\u0645\u0633\u0627\u0631\u0627 checkpoint + audit JSONL) + PersistedState\u060c \u0645\u0639 to_dict/from_dict \u0648\u062d\u0641\u0638 Decimal\u2194str (\u0644\u0627 float \u0644\u0644\u0645\u0627\u0644) \u0648 enum\u2194value\u061b redaction \u0639\u0628\u0631 _strip_secrets \u064a\u064f\u0632\u064a\u0644 \u0623\u064a \u0645\u0641\u062a\u0627\u062d/\u0633\u0631/\u062a\u0648\u0642\u064a\u0639/\u062a\u0648\u0643\u0646 \u0642\u0628\u0644 \u0643\u0644 \u0643\u062a\u0627\u0628\u0629 (\u0644\u0627 \u0623\u0633\u0631\u0627\u0631 \u0641\u064a \u0645\u0644\u0641\u0627\u062a \u0627\u0644\u062d\u0627\u0644\u0629). \u062d\u064f\u0633\u0650\u0645\u062a \u0635\u064a\u063a\u0629 \u0627\u0644\u062a\u062e\u0632\u064a\u0646 (open_question): JSON checkpoint \u0630\u0631\u0651\u064a + JSONL audit (stdlib\u060c \u0645\u0642\u0631\u0648\u0621\u060c \u0643\u0627\u062a\u0628 \u0648\u0627\u062d\u062f\u060c \u062a\u0631\u062f\u0651\u062f \u0645\u0646\u062e\u0641\u0636\u060c \u0628\u0644\u0627 \u0627\u0639\u062a\u0645\u0627\u062f \u062e\u0627\u0631\u062c\u064a)\u061b SQLite \u0628\u062f\u064a\u0644 \u0645\u0648\u062b\u0651\u0642 \u0645\u0624\u062c\u064e\u0651\u0644. \u0627\u062e\u062a\u0628\u0627\u0631\u0627\u062a: 122/122 \u0646\u0627\u062c\u062d\u0629 (+13 \u062c\u062f\u064a\u062f\u0629 \u0641\u064a tests/test_state_store.py\u061b \u0627\u0644\u0623\u0633\u0627\u0633 \u0642\u0628\u0644 T5 = 109) \u062a\u0634\u0645\u0644 round-trip \u0628\u062f\u0642\u0651\u0629 Decimal/enum\u060c crash-mid-write (monkeypatch os.replace) \u064a\u064f\u0628\u0642\u064a \u0627\u0644\u0645\u0644\u0641 \u0627\u0644\u0633\u0644\u064a\u0645 \u0628\u0644\u0627 temp \u0645\u062a\u0628\u0642\u0651\u064d\u060c corrupt/truncated/garbage \u21d2 None\u060c \u0627\u0643\u062a\u0645\u0627\u0644 \u0627\u0644\u0633\u0643\u064a\u0645\u0629 + drift-guard\u060c secret-safety\u060c \u0648stdlib-only \u0639\u0628\u0631 \u0641\u062d\u0635 AST. \u0635\u0641\u0631 \u062a\u0648\u0635\u064a\u0644 \u0628\u0627\u0644\u0645\u062d\u0631\u0651\u0643/\u0627\u0644\u0640CLI (\u0645\u0624\u062c\u064e\u0651\u0644 \u0644\u0640 T8) \u0648\u0635\u0641\u0631 \u062a\u0639\u062f\u064a\u0644 \u062e\u0627\u0631\u062c \u0627\u0644\u0645\u0644\u0641\u064a\u0646 \u0627\u0644\u062c\u062f\u064a\u062f\u064a\u0646 (state_store.py + tests/test_state_store.py). \u0627\u0644\u0645\u0624\u0634\u0651\u0631: next=T6 (M4b \u2014 \u062a\u0648\u0635\u064a\u0644 Audit Log)."

entry = {
  "ts": "2026-09-18",
  "actor": "executor",
  "task": "T5",
  "note": run_log_note
}
new_entry = "    " + json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
m = re.search(r'\]\s*,\s*\r?\n\s*"resume_protocol"', text)
assert m, "run_log close anchor not found"
close_idx = m.start()            # index of the ] that closes run_log
head = text[:close_idx]
brace_idx = head.rstrip().rfind("}")
assert brace_idx != -1, "last run_log element not found"
tail = text[close_idx:]          # from ] onward
text = head[:brace_idx+1] + ",\r\n" + new_entry + "\r\n  " + tail

# VALIDATE then atomic write
obj = json.loads(text)           # raises if invalid -> we do NOT write
tl = {t["id"]: t for t in obj["task_ledger"]}
assert tl["T5"]["status"] == "done"
assert tl["T6"]["status"] == "next"
assert all(tl[i]["status"] == "pending" for i in ["T7","T8","T9","T10","T11","T12","T13","T14","T15"])
assert tl["G1"]["status"] == "blocked" and tl["T16"]["status"] == "blocked"
assert obj["cursor"] == {"last_completed":"T5","current":"T6","next":"T6"}
assert any("\u062d\u064f\u0633\u0650\u0645\u062a \u0641\u064a T5" in q for q in obj["open_questions"])
assert obj["run_log"][-1]["task"] == "T5" and obj["run_log"][-1]["actor"] == "executor"

d = os.path.dirname(path)
fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
with os.fdopen(fd, "wb") as f:
    f.write(text.encode("utf-8"))
    f.flush(); os.fsync(f.fileno())
os.replace(tmp, path)
print("OK: edits applied and validated; run_log len =", len(obj["run_log"]))
