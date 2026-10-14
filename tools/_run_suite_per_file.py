"""مُشغّل السويت split-per-file (أداة محلية فقط — تنفيذ اختبارات لا تدوير حالة).

يشغّل كل ملف ``tests/test_*.py`` في عملية ``python -m unittest`` مستقلّة تحت
``QT_QPA_PLATFORM=offscreen`` لتفادي تعليق/انهيار Qt التراكمي غير الحتمي الذي
يظهر عند تشغيل كامل السويت في عملية واحدة عبر discover. يجمع عدد الاختبارات
والإخفاقات/الأخطاء لكل ملف، ويكتب ملخّصًا حتميًّا (مع flush تدريجي) إلى الملف
المعطى، وينهي بسطر TOTAL صريح.

الاستعمال:  python tools/_run_suite_per_file.py <out_file> [per_file_timeout_s]
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else "_suite_per_file.out")
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 120

env = dict(os.environ)
env.setdefault("QT_QPA_PLATFORM", "offscreen")

_RAN = re.compile(r"^Ran (\d+) test", re.MULTILINE)
_FAILED = re.compile(r"^FAILED\s*\((.*)\)", re.MULTILINE)

files = sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))

total_ran = 0
total_fail = 0
total_err = 0
problems = []

fh = open(OUT, "w", encoding="utf-8")


def emit(line):
    fh.write(line + "\n")
    fh.flush()
    print(line, flush=True)


emit("==== SPLIT-PER-FILE SUITE ==== files=%d timeout=%ss" % (len(files), TIMEOUT))

for path in files:
    mod = "tests." + os.path.splitext(os.path.basename(path))[0]
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", mod],
            capture_output=True, text=True, cwd=ROOT, env=env, timeout=TIMEOUT,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        m = _RAN.search(out)
        ran = int(m.group(1)) if m else 0
        ok = proc.returncode == 0 and "FAILED" not in out
        fm = _FAILED.search(out)
        fdesc = fm.group(1) if fm else ""
        f_cnt = 0
        e_cnt = 0
        if fdesc:
            fe = re.search(r"failures=(\d+)", fdesc)
            ee = re.search(r"errors=(\d+)", fdesc)
            f_cnt = int(fe.group(1)) if fe else 0
            e_cnt = int(ee.group(1)) if ee else 0
        total_ran += ran
        total_fail += f_cnt
        total_err += e_cnt
        status = "OK" if ok else "FAILED"
        if not ok:
            problems.append("%s -> %s (%s)" % (mod, status, fdesc or ("rc=%s" % proc.returncode)))
        emit("%-55s ran=%-4d %s" % (mod, ran, status))
    except subprocess.TimeoutExpired:
        total_err += 1
        problems.append("%s -> TIMEOUT(%ss)" % (mod, TIMEOUT))
        emit("%-55s TIMEOUT" % mod)

emit("---- PROBLEMS (%d) ----" % len(problems))
for p in problems:
    emit("  " + p)

overall = "OK" if (total_fail == 0 and total_err == 0 and not problems) else "FAILED"
emit("TOTAL ran=%d failures=%d errors=%d files=%d status=%s"
     % (total_ran, total_fail, total_err, len(files), overall))

fh.close()
sys.exit(0 if overall == "OK" else 1)
