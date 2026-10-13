import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication, Qt, QStackedWidget
from ocobot.ui.theme import apply_theme
from ocobot.ui.main_window import MainWindow
from ocobot.ui.sidebar import Sidebar
from ocobot.ui.topbar import Topbar
from ocobot.ui.content import ContentRouter
from ocobot.ui.screens import SCREENS


# Verbatim expectations from docs/ui_mockups (sidebar nav + topbar h1).
EXPECTED_KEYS = [
    "01_dashboard",
    "02_open_orders",
    "03_selected_and_edit",
    "04_dynamic_monitoring",
    "05_safe_execution",
    "06_demo",
    "07_connection",
    "08_completed_trades",
    "09_alerts",
]
EXPECTED_NAV_LABELS = [
    "لوحة التحكم",
    "الأوامر المفتوحة",
    "تفاصيل وتعديل",
    "المراقبة الديناميكية",
    "التنفيذ الآمن",
    "وضع العرض",
    "الاتصال",
    "الصفقات المنتهية",
    "تنبيهات Telegram",
]
EXPECTED_TITLES = {
    "01_dashboard": "لوحة التحكم",
    "02_open_orders": "الأوامر المفتوحة",
    "03_selected_and_edit": "تفاصيل الأمر والتعديل اليدوي",
    "04_dynamic_monitoring": "المراقبة الديناميكية",
    "05_safe_execution": "التنفيذ الآمن",
    "06_demo": "وضع العرض (Demo)",
    "07_connection": "الاتصال بالحساب",
    "08_completed_trades": "الصفقات المنتهية",
    "09_alerts": "تنبيهات Telegram",
}


class UINavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    # --- screen registry (mockup order / wording) ---------------------------

    def test_screen_registry_order_and_labels(self):
        keys = [s["key"] for s in SCREENS]
        labels = [s["nav_label"] for s in SCREENS]
        self.assertEqual(keys, EXPECTED_KEYS)
        self.assertEqual(labels, EXPECTED_NAV_LABELS)

    # --- acceptance_check #2: layout matches the mockup ---------------------

    def test_shell_has_sidebar_topbar_content(self):
        window = MainWindow()
        self.assertIsInstance(window.sidebar, Sidebar)
        self.assertIsInstance(window.topbar, Topbar)
        self.assertIsInstance(window.content, ContentRouter)
        self.assertIsInstance(window.content, QStackedWidget)

    def test_layout_is_rtl_and_sidebar_on_right(self):
        window = MainWindow()
        # Whole shell is RTL.
        self.assertEqual(
            window.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        self.assertEqual(
            window.sidebar.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        self.assertEqual(
            window.content.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        # Under RTL the horizontal root places the first-added widget (the
        # Sidebar) at the trailing/right edge; assert it precedes the main
        # column in layout order so it renders on the right.
        central = window.centralWidget()
        root = central.layout()
        self.assertEqual(root.itemAt(0).widget(), window.sidebar)
        self.assertEqual(root.itemAt(1).widget(), window.main_column)
        # Sidebar is pinned to the mockup rail width (250px).
        self.assertEqual(window.sidebar.width(), 250)

    def test_sidebar_has_all_entries_in_order(self):
        sidebar = Sidebar()
        self.assertEqual(sidebar.keys(), EXPECTED_KEYS)
        for screen in SCREENS:
            button = sidebar.button_for(screen["key"])
            self.assertIsNotNone(button)
            self.assertIn(screen["nav_label"], button.text())

    def test_topbar_has_two_static_pills(self):
        topbar = Topbar(title="لوحة التحكم")
        self.assertEqual(topbar.title_label.text(), "لوحة التحكم")
        # Environment + Connection Pills present as static display widgets.
        self.assertEqual(topbar.env_pill.text(), "Testnet")
        self.assertEqual(topbar.conn_pill.text(), "غير متصل")  # مؤشّر الاتصال يبدأ "غير متصل" حتى نجاح الاتصال/preflight (T10c)

    def test_content_router_has_all_screens(self):
        content = ContentRouter()
        self.assertEqual(content.count(), len(EXPECTED_KEYS))
        self.assertEqual(content.keys(), EXPECTED_KEYS)
        for key in EXPECTED_KEYS:
            self.assertIsNotNone(content.screen_for(key))

    def test_completed_trades_screen_registered_and_reachable(self):
        # AC2 (G1.14): الشاشة 08_completed_trades مسجّلة وقابلة للوصول وعدد
        # الشاشات = 9، مع عنوان Topbar الصحيح عند التنقّل إليها.
        self.assertIn("08_completed_trades", EXPECTED_KEYS)
        self.assertEqual(len(EXPECTED_KEYS), 9)

        content = ContentRouter()
        screen = content.screen_for("08_completed_trades")
        self.assertIsNotNone(screen)
        self.assertEqual(screen.screen_key, "08_completed_trades")
        self.assertTrue(content.show_screen("08_completed_trades"))
        self.assertEqual(content.current_key(), "08_completed_trades")

        window = MainWindow()
        window.navigate_to("08_completed_trades")
        self.assertEqual(
            window.content.current_key(), "08_completed_trades"
        )
        self.assertTrue(
            window.sidebar.button_for("08_completed_trades").isChecked()
        )
        self.assertEqual(
            window.topbar.title_label.text(),
            EXPECTED_TITLES["08_completed_trades"],
        )

    # --- acceptance_check #3: navigation switches the visible Content -------

    def test_router_switches_visible_screen(self):
        content = ContentRouter()
        # Default is the first screen.
        self.assertEqual(content.current_key(), EXPECTED_KEYS[0])
        for key in EXPECTED_KEYS:
            self.assertTrue(content.show_screen(key))
            self.assertEqual(content.current_key(), key)
            self.assertIs(content.currentWidget(), content.screen_for(key))

    def test_sidebar_selection_switches_content_and_title(self):
        window = MainWindow()
        # Default state reflects the first screen.
        self.assertEqual(window.content.current_key(), EXPECTED_KEYS[0])
        self.assertEqual(
            window.topbar.title_label.text(), EXPECTED_TITLES[EXPECTED_KEYS[0]]
        )
        # Activating each sidebar entry switches the visible Content screen
        # and updates the Topbar title (both acceptance checks together).
        for key in EXPECTED_KEYS:
            button = window.sidebar.button_for(key)
            self.assertIsNotNone(button)
            button.click()
            self.assertEqual(window.content.current_key(), key)
            self.assertIs(
                window.content.currentWidget(),
                window.content.screen_for(key),
            )
            self.assertEqual(
                window.topbar.title_label.text(), EXPECTED_TITLES[key]
            )

    def test_programmatic_navigate_to(self):
        window = MainWindow()
        window.navigate_to("04_dynamic_monitoring")
        self.assertEqual(window.content.current_key(), "04_dynamic_monitoring")
        self.assertTrue(
            window.sidebar.button_for("04_dynamic_monitoring").isChecked()
        )
        self.assertEqual(
            window.topbar.title_label.text(),
            EXPECTED_TITLES["04_dynamic_monitoring"],
        )


if __name__ == "__main__":
    unittest.main()
