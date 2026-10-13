import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import Qt, QApplication
from ocobot.ui.app import build_app
from ocobot.ui.theme import set_base_font_scale, BASE_FONT_POINT_SIZE


def _ensure_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeAngleDelta:
    def __init__(self, y):
        self._y = y

    def y(self):
        return self._y


class _FakeWheelEvent:
    def __init__(self, y, ctrl=True):
        self._y = y
        self._ctrl = ctrl
        self.accepted = False

    def modifiers(self):
        return Qt.KeyboardModifier.ControlModifier if self._ctrl else Qt.KeyboardModifier.NoModifier

    def angleDelta(self):
        return _FakeAngleDelta(self._y)

    def accept(self):
        self.accepted = True


class _FakeKeyEvent:
    def __init__(self, key, ctrl=True):
        self._key = key
        self._ctrl = ctrl
        self.accepted = False

    def modifiers(self):
        return Qt.KeyboardModifier.ControlModifier if self._ctrl else Qt.KeyboardModifier.NoModifier

    def key(self):
        return self._key

    def accept(self):
        self.accepted = True


class TestG19WindowButtonsAndZoom(unittest.TestCase):
    """G1.9 — أزرار التصغير/التكبير/الإغلاق ظاهرة + تكبير المحتوى بـ Ctrl+wheel مع حدود وإعادة ضبط."""

    def setUp(self):
        _ensure_app()

    def test_window_flags_include_min_max_close(self):
        _app, window = build_app()
        flags = window.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowMinimizeButtonHint)
        self.assertTrue(flags & Qt.WindowType.WindowMaximizeButtonHint)
        self.assertTrue(flags & Qt.WindowType.WindowCloseButtonHint)

    def test_ctrl_wheel_zooms_in_and_out(self):
        _app, window = build_app()
        window._zoom = 1.0
        window.wheelEvent(_FakeWheelEvent(120, ctrl=True))
        self.assertAlmostEqual(window._zoom, 1.1, places=3)
        window.wheelEvent(_FakeWheelEvent(-120, ctrl=True))
        self.assertAlmostEqual(window._zoom, 1.0, places=3)

    def test_ctrl_wheel_respects_bounds(self):
        _app, window = build_app()
        window._zoom = 1.0
        for _ in range(50):
            window.wheelEvent(_FakeWheelEvent(120, ctrl=True))
        self.assertLessEqual(window._zoom, 2.5)
        self.assertAlmostEqual(window._zoom, 2.5, places=3)
        window._zoom = 1.0
        for _ in range(50):
            window.wheelEvent(_FakeWheelEvent(-120, ctrl=True))
        self.assertGreaterEqual(window._zoom, 0.8)
        self.assertAlmostEqual(window._zoom, 0.8, places=3)

    def test_ctrl_zero_resets_zoom(self):
        _app, window = build_app()
        window._zoom = 1.8
        window.keyPressEvent(_FakeKeyEvent(Qt.Key.Key_0, ctrl=True))
        self.assertAlmostEqual(window._zoom, 1.0, places=3)

    def test_set_base_font_scale_clamps_and_scales(self):
        app = _ensure_app()
        self.assertAlmostEqual(set_base_font_scale(app, 5.0), 2.5, places=3)
        self.assertEqual(app.font().pointSize(), round(BASE_FONT_POINT_SIZE * 2.5))
        self.assertAlmostEqual(set_base_font_scale(app, 0.1), 0.8, places=3)
        self.assertEqual(app.font().pointSize(), round(BASE_FONT_POINT_SIZE * 0.8))
        self.assertAlmostEqual(set_base_font_scale(app, 1.0), 1.0, places=3)
        self.assertEqual(app.font().pointSize(), BASE_FONT_POINT_SIZE)


if __name__ == "__main__":
    unittest.main()
