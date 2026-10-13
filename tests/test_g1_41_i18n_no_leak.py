# -*- coding: utf-8 -*-
"""G1.41 — حارس يمنع تسرّب العربية في وضع الإنجليزية عبر كل الشاشات.

يبني كل الشاشات الحقيقية عبر ``build_app()`` (ContentRouter يبنيها جميعًا)، ثم
يبدّل اللغة إلى ``en`` ويستدعي ``retranslate_widget_tree`` كما يفعل مسار الزر،
ويتأكّد أن لا نصّ واجهة (تسمية/زر/عنوان/تبويب/عنصر قائمة/عنصر combo) يبقى عربيًا.
كما يفحص المصدر: كل نصّ عربي يُمرَّر لـ translate/translate_for_current له مقابل
إنجليزي. العربية مصدرٌ لا يُمَس؛ الفحص لوضع الإنجليزية فقط.

كل شيء offscreen كي يعمل بلا شاشة، على نمط tests/test_g1_20_language_toggle.py.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ast
import re
import unittest

from ocobot.ui._qt import Qt, QApplication, QWidget, QLabel, QPushButton, QCheckBox
from ocobot.ui.theme import apply_theme
from ocobot.ui.app import build_app
from ocobot.ui import i18n


def _opt(name):
    try:
        import importlib
        shim = importlib.import_module("ocobot.ui._qt")
        return getattr(shim, name, None)
    except Exception:
        return None


QGroupBox = _opt("QGroupBox")
QTabWidget = _opt("QTabWidget")
QListWidget = _opt("QListWidget")
QComboBox = _opt("QComboBox")
QLineEdit = _opt("QLineEdit")
QTableWidget = _opt("QTableWidget")
QMenu = _opt("QMenu")

# نطاق الأحرف العربية (+ أشكال العرض).
_ARABIC = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")

_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ocobot", "ui")


def _has_arabic(text):
    return bool(text) and bool(_ARABIC.search(text))


class G141ArabicLeakGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        i18n.set_language("ar")
        self.app, self.window = build_app()

    def tearDown(self):
        i18n.set_language("ar")

    def _collect_offenders(self):
        offenders = []
        widgets = [self.window] + list(self.window.findChildren(QWidget))
        for w in widgets:
            try:
                # المحتوى القابل للتحرير وقيَم البيانات ليست chrome.
                if QLineEdit is not None and isinstance(w, QLineEdit):
                    continue
                name = w.objectName() if hasattr(w, "objectName") else ""
                if isinstance(name, str) and name.startswith("MonitoringActiveOrder_"):
                    continue

                if QGroupBox is not None and isinstance(w, QGroupBox):
                    if _has_arabic(w.title()):
                        offenders.append((name or "QGroupBox", w.title()))
                if isinstance(w, (QLabel, QPushButton, QCheckBox)):
                    if _has_arabic(w.text()):
                        offenders.append((name or type(w).__name__, w.text()))
                if QTabWidget is not None and isinstance(w, QTabWidget):
                    for i in range(w.count()):
                        if _has_arabic(w.tabText(i)):
                            offenders.append((name or "QTabWidget", w.tabText(i)))
                if QListWidget is not None and isinstance(w, QListWidget):
                    for i in range(w.count()):
                        it = w.item(i)
                        if it is not None and _has_arabic(it.text()):
                            offenders.append((name or "QListWidget", it.text()))
                if QComboBox is not None and isinstance(w, QComboBox):
                    for i in range(w.count()):
                        if _has_arabic(w.itemText(i)):
                            offenders.append((name or "QComboBox", w.itemText(i)))
                if QTableWidget is not None and isinstance(w, QTableWidget):
                    for c in range(w.columnCount()):
                        hit = w.horizontalHeaderItem(c)
                        if hit is not None and _has_arabic(hit.text()):
                            offenders.append((name or "QTableWidget.hheader", hit.text()))
                    for r in range(w.rowCount()):
                        vit = w.verticalHeaderItem(r)
                        if vit is not None and _has_arabic(vit.text()):
                            offenders.append((name or "QTableWidget.vheader", vit.text()))
                if QMenu is not None and isinstance(w, QMenu):
                    if _has_arabic(w.title()):
                        offenders.append((name or "QMenu", w.title()))
                _acts = getattr(w, "actions", None)
                if callable(_acts):
                    for _act in (_acts() or []):
                        if _act is not None and not _act.isSeparator() and _has_arabic(_act.text()):
                            offenders.append((name or "QAction", _act.text()))
                if hasattr(w, "isWindow") and hasattr(w, "windowTitle"):
                    if w.isWindow() and _has_arabic(w.windowTitle()):
                        offenders.append((name or "windowTitle", w.windowTitle()))
            except Exception:
                continue
        return offenders

    def test_english_mode_leaves_no_arabic_chrome(self):
        i18n.set_language("en")
        i18n.retranslate_widget_tree(self.window)
        offenders = self._collect_offenders()
        self.assertEqual(
            offenders, [],
            "تسرّب عربي في وضع الإنجليزية (أول 25): %r" % (offenders[:25],),
        )

    def test_all_translate_literals_map_to_english(self):
        i18n.set_language("en")
        try:
            missing = []
            for fn in sorted(os.listdir(_UI_DIR)):
                if not fn.endswith(".py"):
                    continue
                with open(os.path.join(_UI_DIR, fn), "r", encoding="utf-8") as f:
                    src = f.read()
                try:
                    tree = ast.parse(src)
                except Exception:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        fname = getattr(func, "attr", None) or getattr(func, "id", None)
                        if fname in ("translate", "translate_for_current"):
                            for arg in node.args:
                                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                    lit = arg.value
                                    if _has_arabic(lit) and _has_arabic(i18n.translate(lit)):
                                        missing.append((fn, lit))
            self.assertEqual(
                missing, [],
                "نصوص تُمرَّر لـ translate بلا مقابل إنجليزي (أول 25): %r" % (missing[:25],),
            )
        finally:
            i18n.set_language("ar")

    def test_arabic_mode_unchanged(self):
        i18n.set_language("ar")
        self.assertEqual(i18n.translate("لوحة التحكم"), "لوحة التحكم")
        i18n.set_language("en")
        self.assertEqual(i18n.translate("لوحة التحكم"), "Dashboard")
        i18n.set_language("ar")


if __name__ == "__main__":
    unittest.main()
