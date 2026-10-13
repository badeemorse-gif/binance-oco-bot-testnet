import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication, QLabel, QLineEdit, Qt
from ocobot.ui.theme import apply_theme
from ocobot.ui.selected_oco import SelectedOcoScreen
from ocobot.ui.monitoring import DynamicMonitoringScreen
from tests.test_ui_monitoring import _sample

SMALL_W = 900
LARGE_W = 1900
HEIGHT = 800


def _measure_at(container, widget, width):
    """يضبط عرض الحاوية العليا، يُفعّل ويعالج التخطيط، ثم يعيد عرض الودجت نفسها."""
    container.resize(width, HEIGHT)
    lay = container.layout()
    if lay is not None:
        lay.activate()
    QApplication.processEvents()
    return widget.width()


class TestG15RelativeScaling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _assert_grows(self, container, widget, tag):
        small = _measure_at(container, widget, SMALL_W)
        large = _measure_at(container, widget, LARGE_W)
        self.assertGreater(small, 0, "zero width (small) %s" % tag)
        self.assertGreater(
            large,
            small,
            "value widget did not grow with container %s: small=%d large=%d"
            % (tag, small, large),
        )

    def test_section03_old_new_values_scale_relatively(self):
        # القسم 03: القيم القديمة/الجديدة يجب أن تتّسع مع اتساع الحاوية العليا.
        screen = SelectedOcoScreen()
        screen.set_selected(_sample())
        screen.show()

        old_value = screen._old_fields["stop_limit"]
        new_value = screen.findChild(QLabel, "SelectedNewValue_stop_limit")
        self.assertIsNotNone(
            new_value, "لم يُعثر على SelectedNewValue_stop_limit في القسم 03"
        )

        self._assert_grows(screen, old_value, "sec03 old_value")
        self._assert_grows(screen, new_value, "sec03 new_value")

    def test_section04_live_value_scales_relatively(self):
        # القسم 04: قيمة اللوحة الحيّة (QLabel) يجب أن تنمو مع اتساع الخلية.
        screen = DynamicMonitoringScreen()
        screen.set_selected(_sample())
        screen.show()

        value = screen._live["symbol"]
        self._assert_grows(screen, value, "sec04 live value")

    def test_section03_showMaximized_real(self):
        # القسم 03: بعد التكبير الحقيقي (small ~800 -> maximize 1360x768) يجب أن
        # تُظهر كل قيم القسم عرضًا معقولًا (>100px) دون أن تفيض حدود حاويتها.
        from decimal import Decimal

        # 1) بناء الشاشة وتعبئتها كما في اختبار القسم 03 القائم + تفعيل التعديل + سعر حيّ.
        screen = SelectedOcoScreen()
        sample = _sample(current_price=Decimal("60000.00"))
        screen.set_selected(sample)
        screen._edit_toggle.setChecked(True)  # تفعيل التعديل حتى تُعرض القيم القديمة/الجديدة
        # نِسب تجعل المعاينة تحسب قيمًا جديدة فعليّة.
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        screen.set_current_price(Decimal("60000.00"))  # سعر مرجعي حتى تُحسب القيم الجديدة

        # 2) حجم ابتدائي صغير (~800px) ثم إظهار ومعالجة الأحداث.
        screen.resize(800, 600)
        screen.show()
        QApplication.processEvents()

        # 3) تكبير حقيقي: نطلب حالة التكبير + showMaximized، وبما أن المنصّة offscreen
        # نُعيد تحجيم القمّة إلى 1360x768 حتى يُعاد حساب التخطيط، ثم نعالج الأحداث.
        screen.setWindowState(Qt.WindowState.WindowMaximized)
        screen.showMaximized()
        screen.resize(1360, 768)
        lay = screen.layout()
        if lay is not None:
            lay.activate()
        QApplication.processEvents()

        # 4) جمع ودجت القيم في القسم 03: القيم القديمة/الجديدة + هوية واحدة على الأقل
        #    + قيمتا اللوحة الحيّة.
        widgets = []
        for key in ("stop_limit", "stop_trigger", "tp"):
            old = screen.findChild(QLabel, "SelectedOldValue_%s" % key)
            new = screen.findChild(QLabel, "SelectedNewValue_%s" % key)
            self.assertIsNotNone(old, "SelectedOldValue_%s مفقود" % key)
            self.assertIsNotNone(new, "SelectedNewValue_%s مفقود" % key)
            widgets.append(("SelectedOldValue_%s" % key, old))
            widgets.append(("SelectedNewValue_%s" % key, new))

        identity = screen.findChild(QLabel, "SelectedValue_symbol")
        self.assertIsNotNone(identity, "SelectedValue_symbol مفقود")
        widgets.append(("SelectedValue_symbol", identity))

        live_price = screen.findChild(QLabel, "SelectedLiveCurrentPrice")
        live_stop = screen.findChild(QLabel, "SelectedLiveMaxStop")
        self.assertIsNotNone(live_price, "SelectedLiveCurrentPrice مفقود")
        self.assertIsNotNone(live_stop, "SelectedLiveMaxStop مفقود")
        widgets.append(("SelectedLiveCurrentPrice", live_price))
        widgets.append(("SelectedLiveMaxStop", live_stop))

        # 5) لكل ودجت: عرض > 100px، ولا يفيض حدود حاويته (بهامش تسامح صغير).
        for name, w in widgets:
            self.assertGreater(
                w.width(),
                100,
                "قيمة القسم 03 أضيق من 100px بعد التكبير: %s width=%d"
                % (name, w.width()),
            )
            parent = w.parentWidget()
            self.assertIsNotNone(parent, "بلا حاوية أب: %s" % name)
            self.assertLessEqual(
                w.x() + w.width(),
                parent.width() + 2,
                "قيمة القسم 03 تفيض حاويتها بعد التكبير: %s x=%d width=%d parent=%d"
                % (name, w.x(), w.width(), parent.width()),
            )

    def test_section03_all_value_widgets_min_width_readonly_and_checked(self):
        # القسم 03 (G1.5/03d): كل ودجت قيمة يجب أن يبقى عرضه >= 90px بعد التكبير،
        # في الحالتين: قراءة فقط (التعديل غير مفعّل، كل الخانات "—")،
        # ثم بعد تفعيل التعديل مع ترك حقلَي SL%/TP% فارغَين.
        MIN_W = 90

        def _maximize(screen):
            # تكبير حتمي وآمن على منصّة offscreen: نطلب حالة التكبير + showMaximized
            # ثم نُعيد التحجيم إلى 1360x768 حتى يُعاد حساب التخطيط، ونعالج الأحداث.
            screen.setWindowState(Qt.WindowState.WindowMaximized)
            screen.showMaximized()
            screen.resize(1360, 768)
            lay = screen.layout()
            if lay is not None:
                lay.activate()
            QApplication.processEvents()

        def _collect(screen):
            widgets = []
            for key in ("stop_limit", "stop_trigger", "tp"):
                old = screen.findChild(QLabel, "SelectedOldValue_%s" % key)
                new = screen.findChild(QLabel, "SelectedNewValue_%s" % key)
                self.assertIsNotNone(old, "SelectedOldValue_%s مفقود" % key)
                self.assertIsNotNone(new, "SelectedNewValue_%s مفقود" % key)
                widgets.append(("SelectedOldValue_%s" % key, old))
                widgets.append(("SelectedNewValue_%s" % key, new))
            live_price = screen.findChild(QLabel, "SelectedLiveCurrentPrice")
            live_stop = screen.findChild(QLabel, "SelectedLiveMaxStop")
            self.assertIsNotNone(live_price, "SelectedLiveCurrentPrice مفقود")
            self.assertIsNotNone(live_stop, "SelectedLiveMaxStop مفقود")
            widgets.append(("SelectedLiveCurrentPrice", live_price))
            widgets.append(("SelectedLiveMaxStop", live_stop))
            sl_edit = screen.findChild(QLineEdit, "SelectedSlPctEdit")
            tp_edit = screen.findChild(QLineEdit, "SelectedTpPctEdit")
            self.assertIsNotNone(sl_edit, "SelectedSlPctEdit مفقود")
            self.assertIsNotNone(tp_edit, "SelectedTpPctEdit مفقود")
            widgets.append(("SelectedSlPctEdit", sl_edit))
            widgets.append(("SelectedTpPctEdit", tp_edit))
            return widgets

        def _assert_min_width(screen, phase):
            for name, w in _collect(screen):
                self.assertGreaterEqual(
                    w.width(),
                    MIN_W,
                    "قيمة القسم 03 أضيق من %dpx (%s): %s width=%d"
                    % (MIN_W, phase, name, w.width()),
                )

        # السيناريو (أ): قراءة فقط — التعديل غير مفعّل، كل خانات القيمة "—".
        screen = SelectedOcoScreen()
        screen.set_selected(_sample())
        screen.resize(800, 600)
        screen.show()
        QApplication.processEvents()
        _maximize(screen)
        _assert_min_width(screen, "read-only")

        # السيناريو (ب): تفعيل التعديل مع ترك حقلَي SL%/TP% فارغَين.
        screen._edit_toggle.setChecked(True)
        screen._sl_pct_edit.setText("")
        screen._tp_pct_edit.setText("")
        QApplication.processEvents()
        _maximize(screen)
        _assert_min_width(screen, "checked-empty")


if __name__ == "__main__":
    unittest.main()
