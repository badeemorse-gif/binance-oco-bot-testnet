"""اختبارات G1.30 (chunk_5) — ربط مِحور تسليح الحارس في build_app/MainWindow.

تؤكّد أن:
  - ``build_app(guardian_supervisor=<sup>)`` يمرّر المُشرِف إلى ``MainWindow``
    وأن مؤقّت الحارس يُنشأ ويُشغَّل عند الحقن.
  - بدون حقن ⇒ لا مُشرِف ولا مؤقّت (سلوك التطبيق العادي غير متغيّر).
  - ``build_guardian_supervisor`` مُطفأ افتراضيًّا (بلا OCOBOT_GUARDIAN) ويُفعَّل
    عبر observe/live.
بلا أي شبكة فعلية.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui.app import build_app
from ocobot.ui.guardian_arm import build_guardian_supervisor


class _FakeSupervisor:
    def tick(self):
        return None


class TestGuardianArmWiring(unittest.TestCase):
    def test_build_app_forwards_supervisor_and_starts_timer(self):
        sup = _FakeSupervisor()
        _app, window = build_app(guardian_supervisor=sup)
        try:
            self.assertIs(window._guardian_supervisor, sup)
            self.assertIsNotNone(window._guardian_timer)
        finally:
            window._shutdown_guardian()
            window.close()

    def test_build_app_without_supervisor_has_no_timer(self):
        _app, window = build_app()
        try:
            self.assertIsNone(window._guardian_supervisor)
            self.assertIsNone(window._guardian_timer)
        finally:
            window.close()


class TestGuardianArmGating(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("OCOBOT_GUARDIAN")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("OCOBOT_GUARDIAN", None)
        else:
            os.environ["OCOBOT_GUARDIAN"] = self._saved

    def test_disabled_by_default(self):
        os.environ.pop("OCOBOT_GUARDIAN", None)
        self.assertIsNone(build_guardian_supervisor(lambda: None))

    def test_off_explicit(self):
        os.environ["OCOBOT_GUARDIAN"] = "off"
        self.assertIsNone(build_guardian_supervisor(lambda: None))

    def test_observe_is_dry_run(self):
        os.environ["OCOBOT_GUARDIAN"] = "observe"
        sup = build_guardian_supervisor(lambda: None)
        self.assertIsNotNone(sup)
        self.assertTrue(sup.dry_run)

    def test_live_is_not_dry_run(self):
        os.environ["OCOBOT_GUARDIAN"] = "live"
        sup = build_guardian_supervisor(lambda: None)
        self.assertIsNotNone(sup)
        self.assertFalse(sup.dry_run)


if __name__ == "__main__":
    unittest.main()
