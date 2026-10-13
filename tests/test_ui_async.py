import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import unittest

from ocobot.ui._qt import QApplication, QEventLoop, QTimer
from ocobot.ui.theme import apply_theme
from ocobot.ui.async_exec import AsyncRunner


def _pump(loop, timeout_ms=5000):
    """Run a nested event loop until quit() or a timeout guard fires.

    The guard is single-shot and started BEFORE ``exec()`` so a missed/lost
    quit can never wedge the loop forever. Callers first drain any already
    queued outcome (via ``processEvents``) and only enter this loop while the
    outcome is still pending, so the fast-callable race can't leave exec()
    blocked on a quit that already fired.
    """
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(timeout_ms)
    loop.exec()
    guard.stop()


class UIAsyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_result_signal_fires_with_value(self):
        runner = AsyncRunner()
        loop = QEventLoop()
        received = {}

        def on_result(value):
            received["value"] = value
            loop.quit()

        runner.submit(lambda: 21 * 2, on_result=on_result)
        QApplication.instance().processEvents()
        if "value" not in received:
            _pump(loop)
        self.assertEqual(received.get("value"), 42)

    def test_no_freeze_submit_returns_immediately_and_runs_off_thread(self):
        runner = AsyncRunner()
        loop = QEventLoop()

        release = threading.Event()
        thread_ids = {}
        finished = {"flag": False}
        results = {}

        ui_thread_id = threading.get_ident()

        def blocking_callable():
            thread_ids["worker"] = threading.get_ident()
            # Block until the UI thread releases us — proves non-blocking submit.
            release.wait(5)
            return "done"

        def on_result(value):
            results["value"] = value

        signals = runner.submit(blocking_callable, on_result=on_result)
        signals.finished.connect(lambda: (finished.__setitem__("flag", True), loop.quit()))

        # submit() returned immediately even though the callable is still blocked.
        self.assertFalse(finished["flag"])
        self.assertNotIn("value", results)

        # Now release the worker and pump the loop to receive queued signals.
        release.set()
        QApplication.instance().processEvents()
        if not finished["flag"]:
            _pump(loop)

        self.assertTrue(finished["flag"])
        self.assertEqual(results.get("value"), "done")
        # Ran on a DIFFERENT thread than the UI thread.
        self.assertIn("worker", thread_ids)
        self.assertNotEqual(thread_ids["worker"], ui_thread_id)

    def test_failing_callable_emits_failed_with_exception(self):
        runner = AsyncRunner()
        loop = QEventLoop()
        captured = {}

        def boom():
            raise ValueError("kaboom")

        def on_error(exc):
            captured["exc"] = exc
            loop.quit()

        runner.submit(boom, on_error=on_error)
        QApplication.instance().processEvents()
        if "exc" not in captured:
            _pump(loop)
        self.assertIsInstance(captured.get("exc"), ValueError)
        self.assertEqual(str(captured["exc"]), "kaboom")


if __name__ == "__main__":
    unittest.main()
