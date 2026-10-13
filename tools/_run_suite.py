"""أداة تشغيل مساعدة: تشغّل حزمة unittest بالكامل وتطبع ملخّصًا نظيفًا.

تلتقط النتيجة عبر unittest.TextTestRunner برسالة ملخّص صريحة (Ran N / OK|FAILED)
بصرف النظر عن ضجيج Qt على stderr. تُستعمل محليًّا فقط (أداة، ليست اختبارًا).
"""
import io
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

loader = unittest.TestLoader()
suite = loader.discover(start_dir=os.path.join(ROOT, "tests"), top_level_dir=ROOT)

buf = io.StringIO()
runner = unittest.TextTestRunner(stream=buf, verbosity=1)
result = runner.run(suite)

total = result.testsRun
failures = len(result.failures)
errors = len(result.errors)
skipped = len(result.skipped)
status = "OK" if result.wasSuccessful() else "FAILED"

print("==== SUITE SUMMARY ====")
print(f"Ran {total} tests")
print(f"status={status} failures={failures} errors={errors} skipped={skipped}")
if failures or errors:
    for kind, items in (("FAILURE", result.failures), ("ERROR", result.errors)):
        for test, _tb in items:
            print(f"{kind}: {test}")
sys.exit(0 if result.wasSuccessful() else 1)
