"""يشغّل حزمة الاختبارات كعملية فرعية ويكتب ملخّصًا نظيفًا إلى ملف محدَّد.

يتفادى تذبذب إعادة توجيه stdout في cmd: يلتقط مخرجات ``tools/_run_suite.py``
عبر ``subprocess`` ويكتب الملخّص (stdout) + تذييلًا موجزًا إلى الملف المعطى
مع flush، فيكون الدليل حتميًّا. أداة محلية فقط.
"""
import os
import subprocess
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "_g1_30_suite_result.txt"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

env = dict(os.environ)
env.setdefault("QT_QPA_PLATFORM", "offscreen")

proc = subprocess.run(
    [sys.executable, os.path.join(ROOT, "tools", "_run_suite.py")],
    capture_output=True,
    text=True,
    cwd=ROOT,
    env=env,
)

with open(os.path.join(ROOT, OUT), "w", encoding="utf-8") as fh:
    fh.write(proc.stdout or "")
    fh.write("\n[returncode=%s]\n" % proc.returncode)
    fh.flush()

print(proc.stdout)
print("[returncode=%s]" % proc.returncode)
