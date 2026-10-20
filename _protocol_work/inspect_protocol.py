# -*- coding: utf-8 -*-
"""فحص بنية البروتوكول قبل التعديل (قراءة فقط)."""
import io, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = io.StringIO()
P = lambda *a: print(*a, file=out)

# --- PROJECT_STATE.json ---
with open(os.path.join(ROOT, "PROJECT_STATE.json"), "r", encoding="utf-8") as fh:
    ps = json.load(fh)

P("=== PROJECT_STATE top-level keys ===")
P(list(ps.keys()))
P("protocol_version:", repr(ps.get("protocol_version")))
P("bootstrapped_at :", repr(ps.get("bootstrapped_at")))
sp = ps.get("system_prompt", "")
P("system_prompt type/len:", type(sp).__name__, len(sp))

for tok in ["11.6", "11.7", "11.8", "القسم 11", "قاعدة الأرشفة", "11.5", "11.4"]:
    P(f"  idx[{tok!r}] =", sp.find(tok))

P("\n=== system_prompt TAIL (last 1500 chars) ===")
P(sp[-1500:])

i117 = sp.find("11.7")
if i117 != -1:
    P("\n=== around '11.7' (sp[i-200 : i+900]) ===")
    P(sp[max(0, i117 - 200): i117 + 900])

# --- decisions_log.json ---
dl_path = os.path.join(ROOT, "state", "decisions_log.json")
P("\n=== decisions_log.json ===")
try:
    with open(dl_path, "r", encoding="utf-8") as fh:
        dl = json.load(fh)
    P("type:", type(dl).__name__, "| len:", len(dl) if hasattr(dl, "__len__") else "n/a")
    if isinstance(dl, list) and dl:
        P("last entry:", json.dumps(dl[-1], ensure_ascii=False))
    elif isinstance(dl, dict):
        P("keys:", list(dl.keys()))
except Exception as e:
    P("ERR:", e)

# --- EXECUTOR_PROMPT_AR.md ---
md_path = os.path.join(ROOT, "docs", "EXECUTOR_PROMPT_AR.md")
with open(md_path, "r", encoding="utf-8") as fh:
    md = fh.readlines()
P("\n=== EXECUTOR_PROMPT_AR.md total lines:", len(md), "===")
for idx, line in enumerate(md, 1):
    if any(t in line for t in ["11.5", "11.6", "11.7", "11.8", "## 11", "القسم 11", "protocol_version"]):
        P(f"L{idx}: {line.rstrip()}")
P("\n=== EXECUTOR last 12 lines ===")
for idx, line in enumerate(md[-12:], len(md) - 11):
    P(f"L{idx}: {line.rstrip()}")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "inspect_out.txt"), "w", encoding="utf-8") as fh:
    fh.write(out.getvalue())
print("WROTE inspect_out.txt")
