import json, os

ROOT = r"D:\oco"

# ---------- STEP 0: WRITE-FIRST WORKING_MEMORY.json ----------
wm = os.path.join(ROOT, "WORKING_MEMORY.json")
with open(wm, "r", encoding="utf-8-sig") as f:
    data = json.load(f)

data["updated_at"] = "2026-10-02T02:15:00Z"
data["progress_note"] = (
    "IN PROGRESS (G1.13 substep=convert_cb_wiring): convert path glue. "
    "DoD: app_wiring.build_convert_executor(client) + app_wiring.make_convert_cb(convert_executor, price_provider) "
    "\u062d\u064a\u062b convert_cb(source, tp_pct, sl_pct, reference_price=None, dry_run=False) "
    "\u064a\u062c\u0644\u0628 \u0627\u0644\u0633\u0639\u0631 \u0627\u0644\u062d\u064a\u0651 (D14) \u0639\u0628\u0631 price_provider.set_symbol(source.symbol)+get_price() "
    "\u0639\u0646\u062f \u063a\u064a\u0627\u0628 reference_price \u062b\u0645 \u064a\u0641\u0648\u0651\u0636 \u0625\u0644\u0649 ConvertExecutor.convert\u061b "
    "\u064a\u0631\u0641\u0639 ValueError \u0625\u0646 \u0639\u0627\u062f \u0627\u0644\u0633\u0639\u0631 None. "
    "acceptance: tests/test_convert_cb_g1_13.py \u0623\u062e\u0636\u0631 + \u0643\u0627\u0645\u0644 \u0627\u0644\u0645\u062c\u0645\u0648\u0639\u0629 \u0623\u062e\u0636\u0631. "
    "scope: ocobot/app_wiring.py, tests/test_convert_cb_g1_13.py (\u0645\u0645\u0646\u0648\u0639 \u062a\u0639\u062f\u064a\u0644 ocobot/ui/*). "
    "resume_point \u064a\u0628\u0642\u0649 selection_done \u062d\u062a\u0649 \u0627\u062c\u062a\u064a\u0627\u0632 \u0627\u0644\u062a\u062d\u0642\u0651\u0642."
)

with open(wm, "w", encoding="utf-8", newline="") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

with open(wm, "r", encoding="utf-8") as f:
    chk = json.load(f)

print("WM_RELOAD_OK")
print("updated_at:", chk.get("updated_at"))
print("resume_point:", chk.get("resume_point"))
print("active:", chk.get("active"))
print("task:", chk.get("task"))
print("schema:", chk.get("schema"))

# ---------- Inspect existing app_wiring.py + fakes ----------
aw = os.path.join(ROOT, "ocobot", "app_wiring.py")
print("=== app_wiring exists:", os.path.exists(aw))
if os.path.exists(aw):
    with open(aw, encoding="utf-8") as f:
        print("<<<APP_WIRING_START>>>")
        print(f.read())
        print("<<<APP_WIRING_END>>>")

fm = os.path.join(ROOT, "tests", "_fakes_monitoring.py")
if os.path.exists(fm):
    with open(fm, encoding="utf-8") as f:
        txt = f.read()
    print("<<<FAKES_HEAD_START>>>")
    print("\n".join(txt.splitlines()[:70]))
    print("<<<FAKES_HEAD_END>>>")
