# -*- coding: utf-8 -*-
"""تحقق نهائي من تحديث البروتوكول (قراءة فقط)."""
import io, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = io.StringIO()
P = lambda *a: print(*a, file=out)
MARK = "11.8 قاعدة التجربة التاريخية الافتراضية"

# PROJECT_STATE.json
with open(os.path.join(ROOT, "PROJECT_STATE.json"), "r", encoding="utf-8") as fh:
    ps = json.load(fh)  # لو فشل التحميل = JSON غير صالح
P("JSON_VALID: True")
P("protocol_version:", ps["protocol_version"])
P("bootstrapped_at :", ps["bootstrapped_at"])
P("last_updated    :", ps.get("last_updated"))
P("11.8_in_system_prompt:", MARK in ps["system_prompt"])
P("system_prompt_len:", len(ps["system_prompt"]))
P("sp_tail:", ps["system_prompt"][-320:])

# prompt.md
with open(os.path.join(ROOT, "prompt.md"), "r", encoding="utf-8") as fh:
    pm = fh.read()
P("\nprompt.md protocol_version lines:")
for ln in pm.splitlines():
    if "protocol_version" in ln:
        P("  ", ln.strip())
P("prompt.md has '= 1.5':", "protocol_version = 1.5" in pm)

# EXECUTOR_PROMPT_AR.md
with open(os.path.join(ROOT, "docs", "EXECUTOR_PROMPT_AR.md"), "r", encoding="utf-8") as fh:
    md = fh.read()
P("\nEXECUTOR 11.8 present:", MARK in md)
P("EXECUTOR '(protocol_version 1.6)' present:", "(protocol_version 1.6)" in md)
P("EXECUTOR 11.7 '(protocol_version 1.5)' still present:", "(protocol_version 1.5)" in md)

# فحص بقايا الإصدار القديم في الوثائق الحيّة (استثناء _archive و docs/archive)
P("\n=== living docs mentioning 'البروتوكول: 1.5' / '** 1.5' (historical sealed reports) ===")
hits = []
for base, dirs, files in os.walk(ROOT):
    if "_archive" in base or os.path.join("docs", "archive") in base or ".git" in base:
        continue
    for f in files:
        if not f.endswith(".md"):
            continue
        p = os.path.join(base, f)
        try:
            t = open(p, "r", encoding="utf-8").read()
        except Exception:
            continue
        if "البروتوكول:** 1.5" in t or "البروتوكول: 1.5" in t or "البروتوكول:1.5" in t:
            hits.append(os.path.relpath(p, ROOT))
for h in hits:
    P("  ", h)
P("living_report_hits_count:", len(hits))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_out.txt"), "w", encoding="utf-8") as fh:
    fh.write(out.getvalue())
print("WROTE verify_out.txt")
