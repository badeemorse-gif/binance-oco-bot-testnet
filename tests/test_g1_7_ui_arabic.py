# -*- coding: utf-8 -*-
"""G1.7 — حارس تعريب الواجهة: يمنع عودة أي نص إنجليزي ظاهر للمستخدم في ocobot/ui."""
import os, re, unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ocobot", "ui")
ALLOW = ("OCOBot", "OCO", "Binance", "Testnet", "DEMO", "Demo")

def _residual_latin(s):
    t = s
    for w in ALLOW:
        t = t.replace(w, "")
    t = re.sub(r"[A-Z0-9]{4,}", "", t)
    return re.findall(r"[A-Za-z]", t)

FORBIDDEN = [
    "Order List ID", "Symbol", "Status", "Qty", "Stop Trigger", "Current Price",
    "Reference Price", "Trigger Price", "Current TP", "Current SL", "Next TP",
    "Next SL", "Next Trigger", "SL Limit", "Stop Limit", "Tick Size", "Leg IDs",
    "Monitoring State", "Last Operation + Result", "Last Simulated Operation",
    "Max Available Stop", "Kill Switch", "Reposition Trigger Rise %",
    "TP Distance Above Current %", "SL Distance Below Current %", "Read-only",
    "Connection", "Environment", "Phase", "Start", "Pause", "Resume",
    "TP %", "SL %",
]

SCAN_FILES = [
    "open_orders.py", "dashboard.py", "monitoring.py", "selected_oco.py",
    "demo_mode.py", "topbar.py", "sidebar.py", "main_window.py", "content.py",
    "screens.py", "app.py", "connection.py", "async_exec.py",
]

class G17UiArabicTests(unittest.TestCase):
    def test_column_headers_are_arabic(self):
        from ocobot.ui.open_orders import COLUMN_HEADERS
        for h in COLUMN_HEADERS:
            self.assertFalse(_residual_latin(h), "رأس عمود يحوي لاتينية: %r" % (h,))

    def test_dashboard_field_labels_are_arabic(self):
        from ocobot.ui.dashboard import DASHBOARD_FIELDS
        for entry in DASHBOARD_FIELDS:
            label = entry[0]
            self.assertFalse(_residual_latin(label), "ليبل لوحة يحوي لاتينية: %r" % (label,))

    def test_no_forbidden_english_quoted_literals_in_ui(self):
        offenders = []
        for name in SCAN_FILES:
            path = os.path.join(UI_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            for lit in FORBIDDEN:
                for q in ('"', "'"):
                    if q + lit + q in src:
                        offenders.append("%s: %s%s%s" % (name, q, lit, q))
        self.assertEqual(offenders, [], "نص إنجليزي ظاهر عاد للواجهة: " + "; ".join(offenders))

if __name__ == "__main__":
    unittest.main()
