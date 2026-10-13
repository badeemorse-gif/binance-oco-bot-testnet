import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication, QScrollArea, QGuiApplication
from ocobot.ui.content import ContentRouter
from ocobot.ui.app import build_app, _clamp_window_to_screen


def _ensure_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestG16WindowScrollAndSize(unittest.TestCase):
    """G1.6/G1.9 — المحتوى ملفوف في QScrollArea قابل للتمرير + النافذة مُحتواة داخل availableGeometry عند الإطلاق دون سقف يمنع التكبير."""

    def setUp(self):
        _ensure_app()

    def test_content_wrapped_in_scrollable_scrollarea(self):
        _app, window = build_app()
        # self.content يبقى ContentRouter
        self.assertIsInstance(window.content, ContentRouter)
        # يجب وجود QScrollArea يلفّ المحتوى ليشمل كل الأقسام
        scroll = window.findChild(QScrollArea)
        self.assertIsNotNone(scroll, "لا يوجد QScrollArea يلفّ المحتوى")
        self.assertTrue(scroll.widgetResizable(), "QScrollArea يجب أن يكون setWidgetResizable(True)")
        self.assertIs(scroll.widget(), window.content, "QScrollArea يجب أن يلفّ ContentRouter نفسه")

    def test_clamp_limits_window_to_available_geometry(self):
        _app, window = build_app()
        _clamp_window_to_screen(window)
        screen = QGuiApplication.primaryScreen()
        self.assertIsNotNone(screen)
        avail = screen.availableGeometry()
        # G1.9: أُزيل سقف الحجم (setMaximumSize) كي يعمل زر التكبير؛ لا سقف أصغر من الشاشة
        self.assertGreaterEqual(window.maximumWidth(), avail.width())
        self.assertGreaterEqual(window.maximumHeight(), avail.height())
        self.assertLessEqual(window.width(), avail.width())
        self.assertLessEqual(window.height(), avail.height())


if __name__ == "__main__":
    unittest.main()
