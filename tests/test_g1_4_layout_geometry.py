import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

try:
    from PySide6.QtCore import QRect
except Exception:
    from PyQt6.QtCore import QRect

from ocobot.ui._qt import QApplication, QLabel, QGridLayout
from ocobot.ui.theme import apply_theme
from ocobot.ui.selected_oco import SelectedOcoScreen
from ocobot.ui.monitoring import DynamicMonitoringScreen
from tests.test_ui_monitoring import _sample


def _grect(w):
    return QRect(w.mapToGlobal(w.rect().topLeft()), w.size())


class TestG14LayoutGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_section03_caption_value_no_overlap_when_enlarged(self):
        screen = SelectedOcoScreen()
        screen.set_selected(_sample())
        screen.show()
        # الشبكة QGridLayout مضافة كتخطيط متداخل (addLayout) داخل QVBoxLayout للبطاقة،
        # لذا parentWidget().layout() هو QVBoxLayout الخارجي وليس الشبكة. نبحث بأسلوب متين
        # عن الشبكة التي تحتوي قيمة 'symbol' في العمود 1.
        target_val = screen._fields["symbol"]
        grid = None
        for gl in screen.findChildren(QGridLayout):
            for r in range(gl.rowCount()):
                it = gl.itemAtPosition(r, 1)
                if it is not None and it.widget() is target_val:
                    grid = gl
                    break
            if grid is not None:
                break
        self.assertIsNotNone(
            grid, "لم يُعثر على QGridLayout لبطاقة الهوية في القسم 03"
        )
        for w in (420, 1920):
            screen.resize(w, 800)
            QApplication.processEvents()
            for key in screen._fields:
                val = screen._fields[key]
                if not val.isVisible():
                    continue
                row = None
                for r in range(grid.rowCount()):
                    it = grid.itemAtPosition(r, 1)
                    if it is not None and it.widget() is val:
                        row = r
                        break
                if row is None:
                    continue
                cap_item = grid.itemAtPosition(row, 0)
                cap = cap_item.widget() if cap_item is not None else None
                if cap is None or not cap.isVisible():
                    continue
                self.assertFalse(
                    _grect(cap).intersects(_grect(val)),
                    f"overlap key={key} width={w}",
                )
                self.assertGreater(
                    val.width(), 0, f"zero width key={key} width={w}"
                )

    def test_section04_live_panel_no_overlap_when_enlarged(self):
        screen = DynamicMonitoringScreen()
        screen.set_selected(_sample())
        screen.show()
        for w in (420, 1920):
            screen.resize(w, 800)
            QApplication.processEvents()
            for key in screen._live:
                val = screen._live[key]
                cap = screen.findChild(QLabel, f"MonitoringLiveCaption_{key}")
                if cap is None or not val.isVisible():
                    continue
                self.assertFalse(
                    _grect(cap).intersects(_grect(val)),
                    f"overlap {key} width={w}",
                )
                self.assertGreater(
                    val.width(), 0, f"zero width {key} width={w}"
                )

    def test_section03_edit_rows_have_min_width_for_numbers(self):
        screen = SelectedOcoScreen()
        screen.set_selected(_sample())
        screen.show()
        screen.resize(1920, 800)
        QApplication.processEvents()
        labels = [
            w
            for w in screen.findChildren(QLabel)
            if w.objectName().startswith("SelectedOldValue_")
            or w.objectName().startswith("SelectedNewValue_")
        ]
        self.assertTrue(
            labels,
            "لم يُعثر على خانات التعديل القديمة/الجديدة (SelectedOldValue_/SelectedNewValue_)",
        )
        for lbl in labels:
            # Updated per G1.5 real maximize on 1360x768@125% - 90 is readable and prevents overflow, Expanding handles growth
            self.assertGreaterEqual(
                lbl.minimumWidth(),
                90,
                f"خانة التعديل {lbl.objectName()} بلا حدّ أدنى كافٍ للعرض لإظهار الأرقام",
            )

    def test_section04_live_values_have_min_width(self):
        screen = DynamicMonitoringScreen()
        screen.set_selected(_sample())
        screen.show()
        screen.resize(1920, 800)
        QApplication.processEvents()
        for key in screen._live:
            val = screen._live[key]
            self.assertGreaterEqual(
                val.minimumWidth(),
                120,
                f"قيمة اللوحة الحيّة {key} بلا حدّ أدنى كافٍ للعرض",
            )


if __name__ == "__main__":
    unittest.main()
